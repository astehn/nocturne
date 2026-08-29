from __future__ import annotations

import os

from dataclasses import dataclass

import numpy as np
from astropy.io import fits

from ..core.export import save_fits
from ..core.tasks import current
from ..core.fits_io import _bayer_pattern, _parse_metadata
from ..core.image import AstroImage
from .cfa import (_OIII_GREEN_WEIGHT, _lerp_axis, _plane, _site_offsets,
                  _upsample_site, extract_cfa_planes, load_cfa)
from .coverage import full_coverage_bounds
from .integrate import average_integrate, sigma_clip_integrate
from .normalize import frame_stats, normalize_to
from .parallel import ordered_results, plan_workers
from .register import RegistrationError, find_transform, warp_with_validity
from .register_pool import register_frames
from .stacker import master_header


def _mad(x: np.ndarray) -> float:
    return float(np.median(np.abs(x - np.median(x))))


def oiii_fit(ha: np.ndarray, oiii: np.ndarray) -> tuple:
    """(scale, oiii median, ha median) for the linear match. Measured apart from
    where it is applied, so a master the user chose not to trim can still be fitted
    on its fully-covered core — median and MAD are the whole fit, and the ragged
    fringe is built from fewer frames, so letting it in drags the pedestal off."""
    mad_o = _mad(oiii)
    a = (_mad(ha) / mad_o) if mad_o > 1e-9 else 1.0
    return a, float(np.median(oiii)), float(np.median(ha))


def apply_oiii_fit(oiii: np.ndarray, fit: tuple) -> np.ndarray:
    a, med_o, med_ha = fit
    return np.clip(a * (oiii - med_o) + med_ha, 0.0, None).astype(np.float32)


def renorm_oiii(ha: np.ndarray, oiii: np.ndarray) -> np.ndarray:
    """Linear-fit OIII to Ha (Siril ExtractHaOIII): match median and MAD."""
    return apply_oiii_fit(oiii, oiii_fit(ha, oiii))


@dataclass
class HaOIIIOptions:
    method: str          # "sigma_clip" | "average"
    kappa: float
    include: list        # sub paths, best-first; include[0] is the reference
    output_path: str
    autocrop: bool = True
    write_channels: bool = False


@dataclass
class HaOIIIResult:
    image: AstroImage
    used: list
    rejected: list
    frame_count: int
    integration_seconds: float
    output_path: str


def _check_cancel() -> None:
    """Raise if the user has asked to stop. A 1116-frame extract runs for a long
    time and had no way out — the token was ambient the whole time and this
    module simply never looked at it."""
    tok = current()
    if tok is not None:
        tok.check()      # raises Cancelled if the user cancelled


def channel_paths(output_path: str) -> tuple:
    """(<stem>_Ha.fits, <stem>_OIII.fits) beside the master."""
    stem = os.path.splitext(output_path)[0]
    return f"{stem}_Ha.fits", f"{stem}_OIII.fits"


def _write_channel_files(ha, oiii, header: dict, output_path: str) -> None:
    """Write each gas as its own mono master, UN-EQUALISED.

    The point of separate files is to recombine them yourself, so they hold what
    was actually measured: OIII really is fainter than Ha here, as it is on the
    sky, and renorm_oiii's lift is a decision the recombiner should get to make.
    Both are divided by the SAME peak, so the Ha:OIII ratio — the one thing you
    cannot recover once it is gone — survives the trip to [0, 1].

    They carry STACKCNT like any master, which is what stops the grader reading
    them back as raw subs (see is_stacked_master).
    """
    peak = float(max(ha.max(), oiii.max())) or 1.0
    ha_path, oiii_path = channel_paths(output_path)
    for path, plane, gas in ((ha_path, ha, "Ha"), (oiii_path, oiii, "OIII")):
        cards = dict(header)
        cards["GAS"] = gas          # which line this plane holds
        save_fits(AstroImage((plane / peak).astype(np.float32), is_linear=True),
                  path, header=cards)


def run_haoiii_extract(opts: HaOIIIOptions, *, on_progress=None) -> HaOIIIResult:
    paths = list(opts.include)
    if len(paths) < 3:
        raise ValueError("need at least 3 frames to extract")

    rejected: list = []
    n = len(paths)

    # Choose the reference: the best-graded sub that is actually a raw CFA frame.
    # The output master is written back into the graded folder, so a stray
    # debayered FITS (e.g. a prior run's RGB master) can grade highest — reject
    # such frames and promote the next best rather than aborting the whole run.
    ref_path = ref_ha = ref_shape = ref_header = None
    ref_exp = 0.0
    remaining = list(paths)
    while remaining:
        _check_cancel()
        candidate = remaining.pop(0)
        try:
            cfa, pat, exp = load_cfa(candidate)
        except Exception as exc:  # noqa: BLE001
            rejected.append((candidate, f"unreadable or not raw CFA: {exc}"))
            continue
        ref_ha, ref_oiii = extract_cfa_planes(cfa, pat)
        ref_path = candidate
        ref_shape, ref_exp = cfa.shape, exp
        ref_header = fits.getheader(candidate)   # for the master's astrometry cards
        break
    if ref_path is None:
        raise ValueError("no raw (un-debayered) CFA subs found to use as a reference")

    transforms = {ref_path: np.eye(3)}
    exposures = {ref_path: ref_exp}
    # Every frame is brought to the reference's sky level before it is warped.
    # Without this, which frames a pixel happened to average sets its background,
    # so every coverage boundary is a step and the rotation envelope is drawn
    # onto the picture as bands — see normalize.py, which measured 262% of sky
    # variation across one real session. The extractor never did this; the crop
    # hid it, because a near-fully-covered pixel has nearly the same frames
    # behind it as its neighbour. Turning Trim off exposed it immediately, on a
    # 1116-frame NGC 281 stack (2026-08-29).
    ref_stats = frame_stats(np.stack([ref_ha, ref_oiii], axis=2))
    norm_stats = {ref_path: ref_stats}
    used = [ref_path]

    # Phase A: register each remaining sub on its Ha plane, across processes.
    #
    # This was a plain serial loop — the extractor never got the parallel
    # rebuild the normal stacker had in v0.16.0, which is a large part of why a
    # 1116-frame run took what it took. Processes, not threads: astroalign does
    # its triangle matching in Python, so Phase A is GIL-bound and threads
    # bought 1.22x where processes buy far more (see register_pool).
    plan = plan_workers()
    for res in register_frames(remaining, ref_path, plan.count, gas=True,
                               check_cancel=_check_cancel,
                               on_progress=(lambda i: on_progress(i, n, "registering"))
                               if on_progress is not None else None):
        if res.reason is not None:
            rejected.append((res.path, res.reason))
            continue
        transforms[res.path] = res.matrix
        exposures[res.path] = res.exposure
        norm_stats[res.path] = res.stats
        used.append(res.path)

    if len(used) < 3:
        raise ValueError("not enough frames could be registered (need at least 3)")

    total = len(used)

    # Both channels in ONE pass, across threads.
    #
    # Ha and OIII were integrated as two independent passes over the same
    # frames, so every sub was Bayer-split five times and warped four. Profiled
    # on 12 real subs: extraction 41.6% of the run, warping 34.2%, and reading
    # the files off disk 2.4% — the repetition was the cost, not the I/O. Both
    # planes come out of one read, so they travel together as a 2-channel frame:
    # extraction drops to 3 calls per sub and warping to 2, which is the same
    # streaming shape the main stacker uses (reload per sigma-clip pass, low
    # memory) rather than caching everything.
    #
    # Threads, not processes: this is FITS reading, a Bayer split, a resize and
    # a warp — C that releases the GIL, which is where stacker.py measured 6.8x.
    #
    # This used to add that Phase A "stays serial on purpose ... only 13% of the
    # run". That was wrong, and measuring it is what showed how wrong. On 80 real
    # NGC 281 subs, serial registration was 84.8% of the whole run — 40.6s of
    # 48.0s. Giving it the process pool took the run to 15.4s, 3.1x overall.
    plan = plan_workers()
    pass_no = {"n": 0}

    def _prepare(path):
        cfa, pat, _ = load_cfa(path)
        ha, oiii = extract_cfa_planes(cfa, pat)
        # Normalise BEFORE warping, as run_stack does: warp's out-of-frame fill
        # then stays a clean zero that the validity mask keeps out of the
        # average, where correcting afterwards would turn it into a plausible
        # sky value.
        both = normalize_to(np.stack([ha, oiii], axis=2),
                            norm_stats[path], ref_stats)
        return warp_with_validity(both, transforms[path])

    def frames():
        pass_no["n"] += 1
        label = f"stacking Ha + OIII (pass {pass_no['n']})"
        for i, out in enumerate(
                ordered_results(used, _prepare, workers=plan.count), start=1):
            _check_cancel()
            if on_progress is not None:
                on_progress(i, total, label)
            yield out

    if opts.method == "sigma_clip":
        both, coverage = sigma_clip_integrate(frames, opts.kappa)
    else:
        both, coverage = average_integrate(frames())
    ha_master, oiii_master = both[..., 0], both[..., 1]

    # Coverage crop (from the Ha integration — both channels share the same
    # transforms, so one coverage map describes both), then renorm and pack RGB.
    top, bottom, left, right = full_coverage_bounds(coverage, len(used))
    core = (slice(top, bottom), slice(left, right))
    fit = oiii_fit(ha_master[core], oiii_master[core])
    oiii_matched = apply_oiii_fit(oiii_master, fit)
    if opts.autocrop:
        ha_master = ha_master[core]
        oiii_master = oiii_master[core]
        oiii_matched = oiii_matched[core]

    rgb = np.stack([ha_master, oiii_matched, oiii_matched], axis=2).astype(np.float32)
    peak = float(rgb.max())
    if peak > 0:
        rgb = rgb / peak
    integ = sum(exposures[p] for p in used)
    ch, cw = rgb.shape[:2]
    image = AstroImage(
        np.clip(rgb, 0.0, 1.0).astype(np.float32),
        is_linear=True,
        metadata={"frames": len(used), "exposure": integ, "width": cw, "height": ch},
    )
    # Same helper the normal stacker uses, so the two masters carry the same
    # provenance by construction. Hand-rolling it here dropped FILTER and
    # INSTRUME, which left a reloaded Ha/OIII master unable to name its own
    # camera or filter while a normal stack of the same subs could.
    ref_meta = _parse_metadata(ref_header, *ref_shape)
    header = master_header(ref_meta, len(used), integ, trimmed=opts.autocrop)
    save_fits(image, opts.output_path, header=header)
    if opts.write_channels:
        _write_channel_files(ha_master, oiii_master, header, opts.output_path)
    return HaOIIIResult(image, used, rejected, len(used), integ, opts.output_path)
