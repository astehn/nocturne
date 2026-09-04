from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from ..core.export import save_fits
from ..core.image import AstroImage
from ..core.tasks import current
from .coverage import full_coverage_bounds
from .drizzle_stack import DRIZZLE_SCALE, PIXFRAC, drizzle_clipped
from .frames import load_sub, luminance
from .integrate import average_integrate, sigma_clip_integrate
from .normalize import frame_stats, normalize_to
from .parallel import ordered_results, plan_workers
from .register_pool import register_frames
from .register import RegistrationError, find_transform, warp_with_validity


def _check_cancel() -> None:
    tok = current()
    if tok is not None:
        tok.check()      # raises Cancelled if the user cancelled


def _rescale_optics(cards: dict, scale: int) -> dict:
    """Halve the pixel size (and any WCS scale) for a drizzled master.

    A 2x master's pixel covers HALF the sky its subs' pixels did, so the
    reference frame's XPIXSZ no longer describes it. Copying it verbatim tells
    the solver the field is twice as wide as it is: measured 2026-08-31 on a
    real 314-frame M 16 drizzle, ASTAP searched a "4.27 deg square search
    window" for a field of about half that and reported "No solution found",
    which cost SPCC its photometric calibration and the annotation everything.
    """
    if scale <= 1:
        return cards
    out = dict(cards)
    for key in ("XPIXSZ", "YPIXSZ"):
        if isinstance(out.get(key), (int, float)):
            out[key] = out[key] / scale
    for key in ("CD1_1", "CD1_2", "CD2_1", "CD2_2"):
        if isinstance(out.get(key), (int, float)):
            out[key] = out[key] / scale
    return out


def capture_span(paths) -> tuple[str, str]:
    """(earliest, latest) DATE-OBS across `paths`, as ("", "") when unknown.

    Header-only reads: 0.24 ms a file measured on real subs, so ~0.3 s for a
    1233-frame stack. Failures are skipped rather than raised — a master must
    not fail to be written because one sub has a malformed card.
    """
    from astropy.io import fits

    stamps = []
    for path in paths or ():
        try:
            value = fits.getheader(path, 0).get("DATE-OBS")
        except Exception:      # noqa: BLE001 — a bad card must not lose the stack
            continue
        if value:
            stamps.append(str(value))
    if not stamps:
        return ("", "")
    return (min(stamps), max(stamps))


def master_header(ref_meta: dict, count: int, integ: float,
                  trimmed: bool | None = None, scale: int = 1) -> dict:
    """FITS header for a written master: stack counts + the reference sub's
    astrometry cards (pointing + scale) and target, so the master plate-solves
    like an original Seestar file instead of failing as a headerless image.

    `trimmed` records the framing choice. Two masters of the same subs differ in
    size by ~45% on a 56-minute alt-az run depending on that one checkbox, and
    with nothing written down the only way to tell them apart is to remember —
    which cost an afternoon on 2026-08-28.
    """
    header = {"NSUBS": count, "STACKCNT": count, "EXPTIME": integ}
    if trimmed is not None:
        header["TRIMMED"] = bool(trimmed)
    header.update(_rescale_optics(ref_meta.get("solve_cards") or {}, scale))
    target = ref_meta.get("target")
    if target:
        header["OBJECT"] = target
    filt = ref_meta.get("filter")
    if filt:
        header["FILTER"] = filt
    # Name the camera that took the data. Without it a reloaded master is
    # identified only by its focal length, which works today but is a guess the
    # moment two Seestars share one. INSTRUME rather than CREATOR: the data came
    # from the camera, but the FILE was created by Nocturne, and CREATOR
    # conventionally means the latter.
    camera = ref_meta.get("instrument") or ref_meta.get("creator")
    if camera:
        header["INSTRUME"] = camera
    # When the data was taken, and at what gain. Neither was written before
    # 2026-09-02: master_metadata copied both into the IN-MEMORY dict, so the
    # session that made the stack showed "Captured 2026-08-26" and "Gain 200"
    # while the FILE had no DATE card at all — re-open it tomorrow and both are
    # gone. DATE-END as well as DATE-OBS because a real run crosses midnight
    # (NGC 281: 20:06 to 03:24, 924 frames on one date and 590 on the other),
    # and one timestamp cannot say that.
    for key, card in (("date", "DATE-OBS"), ("date_end", "DATE-END"),
                      ("gain", "GAIN")):
        value = ref_meta.get(key)
        if value is not None:
            header[card] = value
    return header


def master_metadata(ref_meta: dict, count: int, integ: float, w: int, h: int,
                    scale: int = 1) -> dict:
    """In-memory metadata for a master, mirroring what master_header writes to
    the file. The optics cards are the point: fov_hint reads focal_length and
    pixel_size, and without them it falls back to the SEESTAR_S30_PRO profile.

    The master used to be built from a bare dict of target/frames/exposure/
    dimensions, so the FILE carried the optics (via solve_cards) while the
    in-memory image handed straight to open_image did not. Nothing caught it on
    an S30 Pro, where the fallback profile happens to be the right camera. On a
    Seestar S50 (250 mm vs 160 mm) the assumed scale is 3.74"/px against a real
    2.39"/px, so the FOV hint comes out 56% too large — enough to make a solve
    fail, which silently costs SPCC its photometric calibration.
    """
    meta = {
        "target": ref_meta.get("target"),
        "frames": count,
        "exposure": integ,
        "width": w,
        "height": h,
    }
    # Pointing and scale survive stacking: registration is a rigid transform to
    # the reference frame, so the reference's own optics still describe the master.
    for key in ("focal_length", "pixel_size", "ra", "dec", "filter", "gain",
                "date", "date_end", "solve_cards", "creator", "instrument"):
        if (value := ref_meta.get(key)) is not None:
            meta[key] = value
    # ... EXCEPT the scale, when the master is on a finer grid than its subs.
    # The comment above says "pointing and scale survive stacking", which is
    # true of a rigid registration and false of drizzle.
    if scale > 1:
        if isinstance(meta.get("pixel_size"), (int, float)):
            meta["pixel_size"] = meta["pixel_size"] / scale
        if meta.get("solve_cards"):
            meta["solve_cards"] = _rescale_optics(meta["solve_cards"], scale)
    return meta


def master_filename(target: str, count: int, exposure_s: float, total_s: float,
                    mosaic: bool = False, drizzle: bool = False) -> str:
    """Descriptive default filename for a master, e.g. NGC7000_177x20s_59min.fits,
    or M31_mosaic_302x10s_50min.fits. Degrades gracefully as header info is
    missing; worst case master.fits.

    A mosaic says so in its name: it is the one property that distinguishes it
    from every other master in the same folder, and a frame count alone does
    not hint at it. A drizzle master says so for the same reason, and a stronger
    one — it is four times the size of its neighbour and otherwise looks
    identical in a file listing."""
    obj = re.sub(r"[^A-Za-z0-9-]+", "", target or "") or "master"
    if mosaic:
        obj += "_mosaic"
    if drizzle:
        obj += "_drizzle"
    if exposure_s > 0:
        frames = f"{count}x{exposure_s:g}s"
    elif count > 0:
        frames = f"{count}frames"
    else:
        return f"{obj}.fits"
    minutes = f"{max(1, round(total_s / 60))}min" if total_s > 0 else ""
    parts = [obj, frames] + ([minutes] if minutes else [])
    return "_".join(parts) + ".fits"


@dataclass
class StackOptions:
    method: str          # "average" | "sigma_clip" | "drizzle"
    kappa: float
    include: list         # paths, ordered best-first; include[0] is the reference
    output_path: str
    # Trim to the region nearly every frame covered. A user choice rather than a
    # test hook: with coverage-aware integration and normalization the uncovered
    # fringe is correctly exposed, just built from fewer frames, so keeping it is
    # a legitimate preference — and on a 2 MP sensor the pixels are worth having.
    autocrop: bool = True
    pixfrac: float = PIXFRAC     # drizzle only; see drizzle_stack.PIXFRAC


@dataclass
class StackResult:
    image: AstroImage
    used: list
    rejected: list        # (path, reason)
    frame_count: int
    integration_seconds: float
    output_path: str
    # What the master was divided by. A mosaic averages several masters, each
    # normalised by its OWN peak, so two panels whose brightest star differs sit
    # on different scales — undoing that is the difference between a seam and a
    # smooth join. Defaulted so existing positional construction is unaffected.
    peak: float = 0.0


def run_stack(opts: StackOptions, *, on_progress=None) -> StackResult:
    paths = list(opts.include)
    if len(paths) < 3:
        raise ValueError("need at least 3 frames to stack")

    ref_path = paths[0]
    ref_img = load_sub(ref_path, normalize=False)
    ref_lum = luminance(ref_img.data)
    ref_shape = ref_img.data.shape[:2]

    transforms = {ref_path: np.eye(3)}
    exposures = {ref_path: float(ref_img.metadata.get("exposure", 0.0) or 0.0)}
    # Sky level is measured here, while Phase A has each frame open anyway, and
    # applied at integration. Without it, which frames a pixel happened to
    # average changes its background, so every coverage boundary shows as a step
    # — see normalize.py.
    ref_stats = frame_stats(ref_img.data)
    norm_stats = {ref_path: ref_stats}
    used = [ref_path]
    rejected: list = []
    n = len(paths)

    # A stack refills the progress bar several times — once registering, then
    # once per integration pass — and a bar that reaches 100% and restarts with
    # no explanation reads as a hang or a crash. Number the phases so the
    # restart is expected. The count lives HERE because only run_stack knows
    # that sigma-clip walks the frames twice; asking the dialog to know that
    # would be a second copy of the same fact.
    # Drizzle walks them twice as well — it measures for rejection, then
    # drizzles — and adding that pass without updating this count is how a real
    # 2,037-frame run spent hours announcing "Step 3 of 2".
    steps = 1 + (2 if opts.method in ("sigma_clip", "drizzle") else 1)

    def step_label(step: int, what: str) -> str:
        return f"Step {step} of {steps} — {what}"

    # Derived per stack, never hardcoded: a count tuned to a 14-core desktop
    # would swap a MacBook Air, and one safe for the Air would waste the
    # desktop. See parallel.plan_workers for the measurements behind it.
    plan = plan_workers()

    # Phase A: register each remaining sub against the reference, across
    # PROCESSES. astroalign is GIL-bound, so threads gave 1.22x here against
    # 3.98x for processes; and a worker returns only a 3x3 matrix plus two short
    # arrays, so there is almost nothing to pickle. Results come back in path
    # order, so `used` is identical to the serial implementation's.
    def _phase_a_progress(i):
        if on_progress is not None:
            on_progress(i, n, step_label(1, "aligning frames"))

    for res in register_frames(paths[1:], ref_path, workers=plan.count,
                               on_progress=_phase_a_progress,
                               check_cancel=_check_cancel):
        if res.reason is not None:
            rejected.append((res.path, res.reason))
            continue
        transforms[res.path] = res.matrix
        exposures[res.path] = res.exposure
        norm_stats[res.path] = res.stats
        used.append(res.path)

    if len(used) < 3:
        raise ValueError(
            "not enough frames could be registered — the reference may be too "
            "star-sparse to align (need at least 3)"
        )

    # Phase B: integrate (streaming — reload + warp per frame, low memory).
    # Emit per-frame progress so the (longest) integration step isn't a frozen
    # bar. sigma-clip walks every frame twice, hence a step number per pass.
    total = len(used)
    pass_no = {"n": 0}

    def _prepare(path):
        """The per-frame work, run on a worker thread.

        Nearly all of it — FITS read, demosaic, normalise, warp — is C that
        releases the GIL, which is why threads give 6.8x here where they give
        1.2x in Phase A. Deliberately contains NO cancel check: core.tasks keeps
        the ambient token in a threading.local, so `current()` is None on a
        worker and the check would silently do nothing. Cancellation is handled
        by the consuming loop below, which owns the token.
        """
        # Normalize BEFORE warping: warp's out-of-frame fill stays a clean
        # zero and the validity mask keeps it out of the average, whereas
        # correcting afterwards would shift that fill to a plausible-looking
        # sky value.
        data = normalize_to(load_sub(path, normalize=False).data,
                            norm_stats[path], ref_stats)
        return warp_with_validity(data, transforms[path])

    def frames():
        pass_no["n"] += 1
        label = step_label(1 + pass_no["n"], "combining frames")
        # ordered_results keeps the ORDER. Measured: the current integrators are
        # order-INSENSITIVE at realistic scales, so this is not fixing a live
        # bug. It is reproducibility by construction, for free — see
        # parallel.ordered_results for the measurement and why it stays.
        for i, out in enumerate(
                ordered_results(used, _prepare, workers=plan.count,
                                window=plan.window), start=1):
            _check_cancel()
            if on_progress is not None:
                on_progress(i, total, label)
            yield out

    def drizzle_items():
        """Frames NORMALISED but NOT warped, plus their transforms.

        Drizzle does its own resampling — that is the entire point, and handing
        it an already-warped frame would interpolate the data twice and throw
        away the resolution drizzle exists to recover. So it cannot reuse
        `frames()`.

        It IS normalised, and that matters more than it looks. The 2026-07
        branch fed raw frames, because per-frame sky normalisation did not exist
        yet — it landed in d1d842e on 2026-08-04, eleven days AFTER drizzle was
        shelved for drawing a background "patchwork". Unnormalised sky is
        exactly what turns every coverage boundary into a step in background
        level; full_coverage_bounds documents the same effect drawing "visible
        curved BANDS" on real M31 data. Ordinary stacking hides it behind
        interpolation, drizzle interpolates nothing and draws it. Re-measured
        2026-08-31 with normalisation in place: the structure drizzle adds is
        0.05% of background, against a 0.03% noise floor.
        """
        def prep(path):
            data = normalize_to(load_sub(path, normalize=False).data,
                                norm_stats[path], ref_stats)
            return data, transforms[path]

        # drizzle_clipped walks the frames TWICE — once to measure, once to
        # reject and accumulate — so this generator is called twice and the
        # progress bar legitimately runs to the end and starts again. Label the
        # passes differently or it reads as one job restarting, which is how
        # Andreas read it on the first real run (2026-08-31). The second pass is
        # the slow one: it gathers pass-1 statistics at every input pixel, per
        # channel, before it can drizzle anything.
        drizzle_items.pass_no = getattr(drizzle_items, "pass_no", 0) + 1
        what = ("measuring frames for rejection" if drizzle_items.pass_no == 1
                else "drizzling frames")
        for i, out in enumerate(ordered_results(used, prep, workers=plan.count,
                                                window=plan.window), start=1):
            _check_cancel()
            if on_progress is not None:
                on_progress(i, total, step_label(1 + drizzle_items.pass_no, what))
            yield out

    if opts.method == "drizzle":
        channels = ref_img.data.shape[2] if ref_img.data.ndim == 3 else 1
        master, coverage = drizzle_clipped(
            drizzle_items, ref_shape, channels,
            kappa=opts.kappa, pixfrac=opts.pixfrac)
    elif opts.method == "sigma_clip":
        master, coverage = sigma_clip_integrate(frames, opts.kappa)
    else:
        master, coverage = average_integrate(frames())

    out_scale = DRIZZLE_SCALE if opts.method == "drizzle" else 1
    integ = sum(exposures[p] for p in used)

    # Auto-crop to the region covered by (nearly) all frames. Field rotation
    # (alt-az) and drift leave slanted, low-coverage edges; keep only the fully
    # stacked interior so the master is a clean rectangle of good pixels.
    # The coverage comes from integration itself — it used to be recomputed here
    # by warping a mask per transform, a second answer to a question integration
    # had already answered.
    if opts.autocrop:
        top, bottom, left, right = full_coverage_bounds(coverage, len(used))
        master = master[top:bottom, left:right]

    # The reference frame is one sub, so its DATE-OBS is one moment in a run
    # that may have gone on for seven hours. Read the span off the frames that
    # actually made it into the master. Header-only, and measured at 0.24 ms a
    # file — 0.3 s across 1233 subs, against a stack that runs for minutes.
    span = capture_span(used)
    ref_meta_for_master = dict(ref_img.metadata)
    if span[0]:
        ref_meta_for_master["date"] = span[0]
    if span[1]:
        ref_meta_for_master["date_end"] = span[1]

    ch, cw = master.shape[:2]
    peak = float(master.max())
    if peak > 0:
        master = master / peak
    image = AstroImage(
        np.clip(master, 0.0, 1.0).astype(np.float32),
        is_linear=True,
        metadata=master_metadata(ref_meta_for_master, len(used), integ, cw, ch,
                                 scale=out_scale),
    )
    save_fits(image, opts.output_path,
              header=master_header(ref_meta_for_master, len(used), integ,
                                   trimmed=opts.autocrop, scale=out_scale))
    return StackResult(image, used, rejected, len(used), integ, opts.output_path,
                       peak)
