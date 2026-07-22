from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from astropy.io import fits
from skimage.transform import resize

from ..core.export import save_fits
from ..core.fits_io import _bayer_pattern, solve_cards_from_header
from ..core.image import AstroImage
from .coverage import coverage_map, full_coverage_bounds
from .integrate import average_integrate, sigma_clip_integrate
from .register import RegistrationError, find_transform, warp_to


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


def _plane(cfa: np.ndarray, sites: list) -> np.ndarray:
    """Mean of the half-res sub-planes at the given (row, col) site offsets."""
    parts = [cfa[r::2, c::2] for r, c in sites]
    return np.mean(parts, axis=0).astype(np.float32)


def extract_cfa_planes(cfa: np.ndarray, pattern: str) -> tuple:
    """(ha, oiii) full-res float32. Ha = red sites; OIII = (green + blue)/2.
    Half-res planes are bilinearly upscaled to the CFA's full (H, W)."""
    if cfa.ndim != 2:
        raise ValueError("extract_cfa_planes needs a 2D CFA frame")
    off = _site_offsets(pattern)
    red = _plane(cfa, off["R"])
    green = _plane(cfa, off["G"])
    blue = _plane(cfa, off["B"])
    oiii_half = (green + blue) / 2.0
    shape = cfa.shape
    ha = resize(red, shape, order=1, preserve_range=True, anti_aliasing=False).astype(np.float32)
    oiii = resize(oiii_half, shape, order=1, preserve_range=True,
                  anti_aliasing=False).astype(np.float32)
    return ha, oiii


def _mad(x: np.ndarray) -> float:
    return float(np.median(np.abs(x - np.median(x))))


def renorm_oiii(ha: np.ndarray, oiii: np.ndarray) -> np.ndarray:
    """Linear-fit OIII to Ha (Siril ExtractHaOIII): match median and MAD."""
    mad_o = _mad(oiii)
    a = (_mad(ha) / mad_o) if mad_o > 1e-9 else 1.0
    out = a * (oiii - np.median(oiii)) + np.median(ha)
    return np.clip(out, 0.0, None).astype(np.float32)


@dataclass
class HaOIIIOptions:
    method: str          # "sigma_clip" | "average"
    kappa: float
    include: list        # sub paths, best-first; include[0] is the reference
    output_path: str


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

    def _channel_frames(which: str, label: str):
        def gen():
            for i, path in enumerate(used, start=1):
                cfa, pat, _ = load_cfa(path)
                ha, oiii = extract_cfa_planes(cfa, pat)
                plane = ha if which == "ha" else oiii
                if on_progress is not None:
                    on_progress(i, total, label)
                yield warp_to(plane, transforms[path])
        return gen

    ha_frames = _channel_frames("ha", "stacking Ha")
    oiii_frames = _channel_frames("oiii", "stacking OIII")
    if opts.method == "sigma_clip":
        ha_master = sigma_clip_integrate(ha_frames, opts.kappa)
        oiii_master = sigma_clip_integrate(oiii_frames, opts.kappa)
    else:
        ha_master = average_integrate(ha_frames())
        oiii_master = average_integrate(oiii_frames())

    # Coverage crop (Ha transforms), then renorm OIII to Ha and pack RGB.
    coverage = coverage_map([transforms[p] for p in used], ref_shape)
    top, bottom, left, right = full_coverage_bounds(coverage, len(used))
    ha_master = ha_master[top:bottom, left:right]
    oiii_master = oiii_master[top:bottom, left:right]
    oiii_master = renorm_oiii(ha_master, oiii_master)

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
