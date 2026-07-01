from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.export import save_fits
from ..core.image import AstroImage
from .coverage import coverage_map, full_coverage_bounds
from .frames import load_sub, luminance
from .integrate import average_integrate, sigma_clip_integrate
from .register import RegistrationError, find_transform, warp_to


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

    # Phase A: register each remaining sub against the reference.
    for i, path in enumerate(paths[1:], start=1):
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
            on_progress(i, n, "registering")

    if len(used) < 3:
        raise ValueError(
            "not enough frames could be registered — the reference may be too "
            "star-sparse to align (need at least 3)"
        )

    # Phase B: integrate (streaming — reload + warp per frame, low memory).
    # Emit per-frame progress so the (longest) integration step isn't a frozen
    # bar. sigma-clip walks every frame twice, so label the passes.
    total = len(used)
    passes = 2 if opts.method == "sigma_clip" else 1
    pass_no = {"n": 0}

    def frames():
        pass_no["n"] += 1
        label = "integrating" if passes == 1 else f"integrating (pass {pass_no['n']}/{passes})"
        for i, path in enumerate(used, start=1):
            if on_progress is not None:
                on_progress(i, total, label)
            yield warp_to(load_sub(path, normalize=False).data, transforms[path])

    if opts.method == "sigma_clip":
        master = sigma_clip_integrate(frames, opts.kappa)
    else:
        master = average_integrate(frames())

    integ = sum(exposures[p] for p in used)

    # Auto-crop to the region covered by (nearly) all frames. Field rotation
    # (alt-az) and drift leave slanted, low-coverage edges; keep only the fully
    # stacked interior so the master is a clean rectangle of good pixels.
    if autocrop:
        coverage = coverage_map([transforms[p] for p in used], ref_shape)
        top, bottom, left, right = full_coverage_bounds(coverage, len(used))
        master = master[top:bottom, left:right]

    ch, cw = master.shape[:2]
    peak = float(master.max())
    if peak > 0:
        master = master / peak
    image = AstroImage(
        np.clip(master, 0.0, 1.0).astype(np.float32),
        is_linear=True,
        metadata={
            "target": ref_img.metadata.get("target"),
            "frames": len(used),
            "exposure": integ,
            "width": cw,
            "height": ch,
        },
    )
    save_fits(image, opts.output_path,
              header={"NSUBS": len(used), "STACKCNT": len(used), "EXPTIME": integ})
    return StackResult(image, used, rejected, len(used), integ, opts.output_path)
