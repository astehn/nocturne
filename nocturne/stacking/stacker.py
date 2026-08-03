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


def master_filename(target: str, count: int, exposure_s: float, total_s: float) -> str:
    """Descriptive default filename for a master, e.g. NGC7000_177x20s_59min.fits.
    Degrades gracefully as header info is missing; worst case master.fits."""
    obj = re.sub(r"[^A-Za-z0-9-]+", "", target or "") or "master"
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


@dataclass
class StackResult:
    image: AstroImage
    used: list
    rejected: list        # (path, reason)
    frame_count: int
    integration_seconds: float
    output_path: str


def run_stack(opts: StackOptions, *, on_progress=None, autocrop: bool = True) -> StackResult:
    paths = list(opts.include)
    if len(paths) < 3:
        raise ValueError("need at least 3 frames to stack")

    ref_path = paths[0]
    ref_img = load_sub(ref_path, normalize=False)
    ref_lum = luminance(ref_img.data)
    ref_shape = ref_img.data.shape[:2]

    transforms = {ref_path: np.eye(3)}
    exposures = {ref_path: float(ref_img.metadata.get("exposure", 0.0) or 0.0)}
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

    def frames():
        pass_no["n"] += 1
        label = step_label(1 + pass_no["n"], "combining frames")
        for i, path in enumerate(used, start=1):
            _check_cancel()
            if on_progress is not None:
                on_progress(i, total, label)
            yield warp_with_validity(load_sub(path, normalize=False).data,
                                     transforms[path])

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
    if autocrop:
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
    return StackResult(image, used, rejected, len(used), integ, opts.output_path)
