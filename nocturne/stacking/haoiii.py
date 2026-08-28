from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from astropy.io import fits

from ..core.export import save_fits
from ..core.fits_io import _bayer_pattern, solve_cards_from_header
from ..core.image import AstroImage
from .coverage import full_coverage_bounds
from .integrate import average_integrate, sigma_clip_integrate
from .parallel import ordered_results, plan_workers
from .register import RegistrationError, find_transform, warp_with_validity


def load_cfa(path: str) -> tuple:
    """Load a raw 2D CFA sub: (cfa float32, pattern, exptime). Raises ValueError
    for a 3D/already-debayered file."""
    with fits.open(path) as hdul:
        data = np.asarray(hdul[0].data)
        header = hdul[0].header
    if data.ndim != 2:
        raise ValueError("Ha/OIII extraction needs raw (un-debayered) subs")
    exp = float(header.get("EXPTIME", 0.0) or 0.0)
    return data.astype(np.float32), _bayer_pattern(header), exp


def _site_offsets(pattern: str) -> dict:
    """Map each colour to its (row, col) offsets within the 2x2 CFA tile."""
    offsets: dict = {"R": [], "G": [], "B": []}
    for i, ch in enumerate(pattern.upper()):
        offsets[ch].append((i // 2, i % 2))
    return offsets


def _lerp_axis(a: np.ndarray, off: int, n: int, axis: int) -> np.ndarray:
    """Bilinear resample along one axis onto n samples at source coord (i-off)/2,
    clamping at the edges. Separable because the scale is exactly 2 and the
    offsets are whole pixels, which makes this bit-identical to a 2D
    map_coordinates call (asserted in the tests) and 2.8x faster than one.
    """
    idx = (np.arange(n, dtype=np.float32) - off) / 2.0
    i0 = np.floor(idx).astype(np.intp)
    w = (idx - i0).astype(np.float32)
    lim = a.shape[axis] - 1
    lo = a.take(np.clip(i0, 0, lim), axis=axis)
    hi = a.take(np.clip(i0 + 1, 0, lim), axis=axis)
    return lo * (1.0 - w.reshape((-1, 1) if axis == 0 else (1, -1))) + \
        hi * w.reshape((-1, 1) if axis == 0 else (1, -1))


def _upsample_site(cfa: np.ndarray, r: int, c: int, shape: tuple) -> np.ndarray:
    """Bilinearly interpolate ONE CFA sub-plane onto the full grid, honouring
    where its samples actually sit.

    Sub-plane element [i, j] is full-frame pixel (2i + r, 2j + c), so full-frame
    row R reads sub-plane row (R - r)/2. Decimating and then resizing every
    colour identically — which is what this replaced — throws that offset away:
    red lives at (0,1) in a GRBG tile and blue at (1,0), so Ha and OIII came out
    about a pixel apart from each other (predicted (0.75, 0.75) from the tile,
    measured (0.84, 1.02) on real M16 masters).
    """
    sub = cfa[r::2, c::2]
    return _lerp_axis(_lerp_axis(sub, r, shape[0], 0), c, shape[1], 1).astype(np.float32)


def _plane(cfa: np.ndarray, sites: list, shape: tuple) -> np.ndarray:
    """Full-res mean of the sub-planes at the given (row, col) site offsets.

    Each is interpolated to full res BEFORE averaging. Averaging first, as this
    used to, silently blurs: a GRBG tile's two greens sit at (0,0) and (1,1), so
    adding the raw sub-planes averages pixels a diagonal step apart.
    """
    return np.mean([_upsample_site(cfa, r, c, shape) for r, c in sites],
                   axis=0).astype(np.float32)


def extract_cfa_planes(cfa: np.ndarray, pattern: str) -> tuple:
    """(ha, oiii) full-res float32. Ha = red sites; OIII = (green + blue)/2,
    each interpolated from where the sensor actually sampled it."""
    if cfa.ndim != 2:
        raise ValueError("extract_cfa_planes needs a 2D CFA frame")
    off = _site_offsets(pattern)
    shape = cfa.shape
    ha = _plane(cfa, off["R"], shape)
    oiii = ((_plane(cfa, off["G"], shape) + _plane(cfa, off["B"], shape)) / 2.0)
    return ha, oiii.astype(np.float32)


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


@dataclass
class HaOIIIResult:
    image: AstroImage
    used: list
    rejected: list
    frame_count: int
    integration_seconds: float
    output_path: str


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
        candidate = remaining.pop(0)
        try:
            cfa, pat, exp = load_cfa(candidate)
        except Exception as exc:  # noqa: BLE001
            rejected.append((candidate, f"unreadable or not raw CFA: {exc}"))
            continue
        ref_path, ref_ha = candidate, extract_cfa_planes(cfa, pat)[0]
        ref_shape, ref_exp = cfa.shape, exp
        ref_header = fits.getheader(candidate)   # for the master's astrometry cards
        break
    if ref_path is None:
        raise ValueError("no raw (un-debayered) CFA subs found to use as a reference")

    transforms = {ref_path: np.eye(3)}
    exposures = {ref_path: ref_exp}
    used = [ref_path]

    # Phase A: register each remaining sub on its Ha plane.
    for i, path in enumerate(remaining, start=1):
        try:
            cfa, pat, exp = load_cfa(path)
        except Exception as exc:  # noqa: BLE001
            rejected.append((path, f"unreadable or not raw CFA: {exc}"))
            continue
        if cfa.shape != ref_shape:
            rejected.append((path, "dimension mismatch"))
            continue
        try:
            ha, _ = extract_cfa_planes(cfa, pat)
            matrix = find_transform(ha, ref_ha)
        except RegistrationError as exc:
            rejected.append((path, f"registration failed: {exc}"))
            continue
        transforms[path] = matrix
        exposures[path] = exp
        used.append(path)
        if on_progress is not None:
            on_progress(i, n, "registering")

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
    # Phase A above stays serial on purpose; it is astroalign, GIL-bound, and
    # only 13% of the run, where threads measured 1.22x against 3.98x for
    # processes. Not worth a second process pool for a fraction of a fraction.
    plan = plan_workers()
    pass_no = {"n": 0}

    def _prepare(path):
        cfa, pat, _ = load_cfa(path)
        ha, oiii = extract_cfa_planes(cfa, pat)
        return warp_with_validity(np.stack([ha, oiii], axis=2), transforms[path])

    def frames():
        pass_no["n"] += 1
        label = f"stacking Ha + OIII (pass {pass_no['n']})"
        for i, out in enumerate(
                ordered_results(used, _prepare, workers=plan.count), start=1):
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
    oiii_master = apply_oiii_fit(oiii_master, fit)
    if opts.autocrop:
        ha_master = ha_master[core]
        oiii_master = oiii_master[core]

    rgb = np.stack([ha_master, oiii_master, oiii_master], axis=2).astype(np.float32)
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
    header = {"NSUBS": len(used), "STACKCNT": len(used), "EXPTIME": integ}
    header.update(solve_cards_from_header(ref_header))       # pointing + scale, for solving
    if ref_header.get("OBJECT"):
        header["OBJECT"] = ref_header["OBJECT"]
    save_fits(image, opts.output_path, header=header)
    return HaOIIIResult(image, used, rejected, len(used), integ, opts.output_path)
