from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from ..core.export import save_fits
from ..core.image import AstroImage
from ..core.tasks import current
from .coverage import full_coverage_bounds
from .frames import load_sub, luminance
from .integrate import average_integrate, sigma_clip_integrate
from .normalize import frame_stats, normalize_to
from .parallel import ordered_results, plan_workers
from .register import RegistrationError, find_transform, warp_with_validity


def _check_cancel() -> None:
    tok = current()
    if tok is not None:
        tok.check()      # raises Cancelled if the user cancelled


def master_header(ref_meta: dict, count: int, integ: float) -> dict:
    """FITS header for a written master: stack counts + the reference sub's
    astrometry cards (pointing + scale) and target, so the master plate-solves
    like an original Seestar file instead of failing as a headerless image."""
    header = {"NSUBS": count, "STACKCNT": count, "EXPTIME": integ}
    header.update(ref_meta.get("solve_cards") or {})
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
    return header


def master_metadata(ref_meta: dict, count: int, integ: float, w: int, h: int) -> dict:
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
                "date", "solve_cards", "creator", "instrument"):
        if (value := ref_meta.get(key)) is not None:
            meta[key] = value
    return meta


def master_filename(target: str, count: int, exposure_s: float, total_s: float,
                    mosaic: bool = False) -> str:
    """Descriptive default filename for a master, e.g. NGC7000_177x20s_59min.fits,
    or M31_mosaic_302x10s_50min.fits. Degrades gracefully as header info is
    missing; worst case master.fits.

    A mosaic says so in its name: it is the one property that distinguishes it
    from every other master in the same folder, and a frame count alone does
    not hint at it."""
    obj = re.sub(r"[^A-Za-z0-9-]+", "", target or "") or "master"
    if mosaic:
        obj += "_mosaic"
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
    method: str          # "average" | "sigma_clip"
    kappa: float
    include: list         # paths, ordered best-first; include[0] is the reference
    output_path: str
    # Trim to the region nearly every frame covered. A user choice rather than a
    # test hook: with coverage-aware integration and normalization the uncovered
    # fringe is correctly exposed, just built from fewer frames, so keeping it is
    # a legitimate preference — and on a 2 MP sensor the pixels are worth having.
    autocrop: bool = True


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
    steps = 1 + (2 if opts.method == "sigma_clip" else 1)

    def step_label(step: int, what: str) -> str:
        return f"Step {step} of {steps} — {what}"

    # Phase A: register each remaining sub against the reference.
    for i, path in enumerate(paths[1:], start=1):
        _check_cancel()
        try:
            sub = load_sub(path, normalize=False)
        except Exception as exc:
            rejected.append((path, f"unreadable: {exc}"))
            continue
        if sub.data.shape[:2] != ref_shape:
            rejected.append((path, "dimension mismatch"))
            continue
        try:
            matrix = find_transform(luminance(sub.data), ref_lum)
        except RegistrationError as exc:
            rejected.append((path, f"registration failed: {exc}"))
            continue
        transforms[path] = matrix
        exposures[path] = float(sub.metadata.get("exposure", 0.0) or 0.0)
        norm_stats[path] = frame_stats(sub.data)
        used.append(path)
        if on_progress is not None:
            on_progress(i, n, step_label(1, "aligning frames"))

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

    # Derived per stack, never hardcoded: a count tuned to a 14-core desktop
    # would swap a MacBook Air, and one safe for the Air would waste the
    # desktop. See parallel.plan_workers for the measurements behind it.
    plan = plan_workers()

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
                ordered_results(used, _prepare, workers=plan.count), start=1):
            _check_cancel()
            if on_progress is not None:
                on_progress(i, total, label)
            yield out

    if opts.method == "sigma_clip":
        master, coverage = sigma_clip_integrate(frames, opts.kappa)
    else:
        master, coverage = average_integrate(frames())

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

    ch, cw = master.shape[:2]
    peak = float(master.max())
    if peak > 0:
        master = master / peak
    image = AstroImage(
        np.clip(master, 0.0, 1.0).astype(np.float32),
        is_linear=True,
        metadata=master_metadata(ref_img.metadata, len(used), integ, cw, ch),
    )
    save_fits(image, opts.output_path,
              header=master_header(ref_img.metadata, len(used), integ))
    return StackResult(image, used, rejected, len(used), integ, opts.output_path,
                       peak)
