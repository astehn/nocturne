from __future__ import annotations

import os
import re
from dataclasses import dataclass

import numpy as np
import tifffile
from astropy.io import fits


def _import_demosaicing():
    """Import colour_demosaicing without letting it shell out to git.

    Its __init__ runs `git describe` at import time to decorate a version
    string, and wraps it in a bare except — so on a developer's machine it
    fails silently and nobody notices. On a Mac WITHOUT the Xcode command line
    tools, /usr/bin/git is a stub whose entire job is to pop the system
    "install the developer tools?" dialog. The exception is still caught; the
    dialog has already appeared.

    So a downloaded copy of Nocturne asked its user to install a compiler
    before it would open a photograph (reported on 0.11.1, 2026-08-05). Denying
    the call before it can spawn a process is the whole fix: their own except
    swallows the FileNotFoundError and falls back to the packaged version
    string, which is the value we want anyway.
    """
    import subprocess
    real = subprocess.check_output

    def no_git(cmd, *args, **kwargs):
        first = cmd[0] if isinstance(cmd, (list, tuple)) and cmd else cmd
        if isinstance(first, str) and first.rsplit("/", 1)[-1] == "git":
            raise FileNotFoundError("git lookup suppressed: a packaged app must "
                                    "not trigger the Xcode tools installer")
        return real(cmd, *args, **kwargs)

    subprocess.check_output = no_git
    try:
        from colour_demosaicing import demosaicing_CFA_Bayer_bilinear
    finally:
        subprocess.check_output = real
    return demosaicing_CFA_Bayer_bilinear


# BILINEAR ON PURPOSE. Do not "upgrade" this to a gradient-corrected demosaic.
#
# Malvar2004 was tried and reverted on 2026-08-18. It IS sharper — 21.7% on a
# real sub over a common 417-star subset — but it puts a four-fold coloured cross
# around every star, aligned with the 2x2 Bayer grid. Gradient-corrected
# demosaics infer red and blue from the green gradient, which assumes
# neighbouring colours correlate; at a Seestar star spanning ~2.6 px that
# assumption fails and the correction rings along the CFA axes. Andreas saw it
# immediately on a real stack: "artifacts on basically every single star where
# they were clean before".
#
# The obvious remedy does not work. Median-filtering the (R-G) and (B-G) planes
# was measured at sizes 3 to 9: even at 9 the cross was still plainly visible,
# while per-star colour spread had collapsed to 0.0032 against Siril's 0.0201 —
# the filter bleaches real star colour before it removes the artefact.
#
# The sharpness is worth having, so this is unfinished rather than settled, but
# the route is a CFA-aware one (a demosaic designed for point sources, e.g. RCD,
# or stacking in the CFA domain) — not another interpolation kernel. See TODO.
_demosaic = _import_demosaicing()

from .image import AstroImage, finite_or_zero
from .instrument import DEFAULT_INSTRUMENT, SEESTAR_S30_PRO, identify


def _normalize(arr: np.ndarray) -> np.ndarray:
    """Scale to [0, 1] by the peak, with non-finite samples zeroed FIRST.

    NaN arrives from real files: a registration that rotates for alt-az field
    rotation leaves no-data corners, and stacking software commonly writes NaN
    there rather than zero.

    The order matters, and the old guard got it wrong in a way that failed
    silently twice over. It read `peak = float(arr.max()); if peak > 0` — with
    one NaN present `max()` returns NaN and `NaN > 0` is False, so the array was
    returned COMPLETELY UNSCALED: a 16-bit frame kept values up to 65535 while
    every later step assumes [0, 1]. The surviving NaN then blanked an entire
    channel in the display autostretch, because a single NaN poisons the median
    that derives the stretch parameters.

    Zeroing before the peak fixes both: the peak is measured over real data, and
    nothing downstream has to cope with a value that has no meaning.
    """
    arr = finite_or_zero(arr.astype(np.float32))
    peak = float(arr.max())
    if peak > 0:
        arr = arr / peak
    return arr


_VALID_CFA = ("RGGB", "BGGR", "GRBG", "GBRG")


def _bayer_pattern(header) -> str:
    """CFA pattern from the file's own BAYERPAT header (authoritative), falling
    back to the instrument default only when it is missing/invalid. A wrong
    pattern demosaics one phase off -> green maze + false colour."""
    pattern = str(header.get("BAYERPAT", "") or "").strip().upper()
    return pattern if pattern in _VALID_CFA else SEESTAR_S30_PRO.bayer_pattern


def _parse_metadata(header, height: int, width: int) -> dict:
    meta: dict = {"width": width, "height": height}
    mapping = {
        "exposure": ("EXPTIME",),
        "gain": ("GAIN",),
        "target": ("OBJECT",),
        "frames": ("STACKCNT", "NFRAMES", "NCOMBINE"),
        "bitpix": ("BITPIX",),
        "temp": ("CCD-TEMP", "CCD_TEMP"),
        "date": ("DATE-OBS", "DATE"),
        "livetime": ("LIVETIME",),
        "creator": ("CREATOR",),        # 'ZWO Seestar S50' — names the camera outright
        "instrument": ("INSTRUME",),    # 'imx585' or 'Seestar S50'; inconsistent, so secondary
        "focal_length": ("FOCALLEN",),
        "pixel_size": ("XPIXSZ", "YPIXSZ"),
        "ra": ("OBJCTRA", "RA"),
        "dec": ("OBJCTDEC", "DEC"),
        "filter": ("FILTER",),
    }
    for key, candidates in mapping.items():
        for card in candidates:
            if card in header:
                meta[key] = header[card]
                break
    solve = solve_cards_from_header(header)
    if solve:
        meta["solve_cards"] = solve
    return meta


# Raw header cards ASTAP reads to seed a plate-solve: pointing (OBJCTRA/OBJCTDEC/
# RA/DEC) + scale (FOCALLEN/XPIXSZ…) + any existing WCS. Handed to the solver so a
# processed/re-saved image gets the same hints ASTAP has when it opens the
# original file — without them a headerless image won't solve.
SOLVE_CARDS = ("OBJCTRA", "OBJCTDEC", "RA", "DEC", "FOCALLEN", "FOCALLEN2",
               "XPIXSZ", "YPIXSZ", "FOCRATIO", "CD1_1", "CD1_2", "CD2_1", "CD2_2")


def solve_cards_from_header(header) -> dict:
    """The plate-solve hint cards (pointing + scale) present in a FITS header,
    as a plain {card: value} dict. Empty if none are present."""
    return {card: header[card] for card in SOLVE_CARDS if card in header}


@dataclass
class Integration:
    total_s: float | None
    per_sub_s: float | None
    frames: int | None


def _plausible_sub(x: float) -> bool:
    return 0.5 <= x <= 600.0


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def resolve_integration(meta: dict) -> "Integration | None":
    """Resolve total integration + per-sub exposure across the differing header
    conventions. `EXPTIME` is per-sub in native ZWO/Siril files but the *total*
    in Nocturne's own masters; native files carry the standard `LIVETIME` total.
    Rule-2's ratio test only sees Nocturne `EXPTIME=total` masters, because
    native files carry LIVETIME and are handled by rule 1."""
    live = _num(meta.get("livetime"))
    exp = _num(meta.get("exposure"))
    frames = meta.get("frames")
    try:
        frames = int(frames) if frames is not None else None
    except (TypeError, ValueError):
        frames = None

    if live and live > 0:
        per = exp if (exp and _plausible_sub(exp)) else (
            live / frames if frames else None)
        return Integration(live, per, frames)
    if exp and frames:
        cand = exp / frames
        if _plausible_sub(cand):
            return Integration(exp, cand, frames)       # EXPTIME already total
        return Integration(exp * frames, exp, frames)   # EXPTIME per-sub
    if exp:
        return Integration(None, exp, frames)
    return None


def format_integration(seconds: float) -> str:
    """Human total integration: 2900 -> '48m 20s', 8100 -> '2h 15m', 20 -> '20s'."""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def _summary_section(title: str, pairs: list[tuple[str, str]]) -> str:
    rows = "".join(
        f"<tr><td style='color:#8a9099'>{k}</td><td>&nbsp;&nbsp;{v}</td></tr>"
        for k, v in pairs
    )
    return f"<b>{title}</b><table cellspacing='0'>{rows}</table>"


def _target_from_filename(filename: str | None) -> str | None:
    """Best-effort target name from a source filename: strip the extension and
    a trailing capture suffix, e.g. 'NGC7000_182x20s_61min.fits' -> 'NGC7000'."""
    if not filename:
        return None
    stem = os.path.splitext(os.path.basename(filename))[0]
    match = re.search(r"_\d+x?\d*", stem)
    if match:
        stem = stem[: match.start()]
    return stem or None


def import_summary(meta: dict, instrument=None,
                    filename: str | None = None) -> str:
    """Grouped rich-HTML readout: 'Your stack' (header, present fields only) +
    'Camera & scope' (per-file where available, else instrument profile).

    `instrument` defaults to whichever camera the file names, so an S50 stack
    is not labelled with the S30 Pro's sensor. Callers may still pass one
    explicitly; None means "work it out"."""
    if instrument is None:
        instrument = identify(meta) or DEFAULT_INSTRUMENT
    stack: list[tuple[str, str]] = []
    target = meta.get("target") or _target_from_filename(filename)
    if target:
        stack.append(("Target", str(target)))
    solved = meta.get("target_solved")
    if solved:
        stack.append(("Target (solved)", str(solved)))

    integration = resolve_integration(meta)
    if integration is not None:
        if integration.total_s is not None:
            value = format_integration(integration.total_s)
            if integration.frames is not None and integration.per_sub_s is not None:
                value += f" ({integration.frames} × {integration.per_sub_s:g}s)"
            stack.append(("Total integration", value))
        elif integration.per_sub_s is not None:
            stack.append(("Exposure", f"{integration.per_sub_s:g}s"))

    frames = meta.get("frames")
    if frames is not None:
        stack.append(("Frames", f"{frames}"))
    if meta.get("gain") is not None:
        try:
            stack.append(("Gain", f"{float(meta['gain']):g}"))
        except (TypeError, ValueError):
            pass
    if meta.get("temp") is not None:
        try:
            stack.append(("Sensor temp", f"{float(meta['temp']):.1f} °C"))
        except (TypeError, ValueError):
            pass
    if meta.get("date"):
        stack.append(("Captured", str(meta["date"]).split("T")[0]))
    if meta.get("width") and meta.get("height"):
        stack.append(("Dimensions", f"{meta['width']} × {meta['height']}"))

    if not stack:
        stack.append(("", "Couldn't read capture details from this file's header."))

    focal = meta.get("focal_length") or instrument.focal_length_mm
    pix = meta.get("pixel_size") or instrument.pixel_size_um
    scale = 206.265 * float(pix) / float(focal)
    scope = [
        ("Sensor", f"{instrument.sensor} (colour)"),
        ("Pixel size", f"{float(pix):g} µm"),
        ("Focal length", f"{float(focal):g} mm · f/{instrument.f_ratio:g}"),
        ("Image scale", f"~{scale:.1f}″ / pixel"),
    ]

    html = _summary_section("Your stack", stack)
    html += _summary_section("Camera &amp; scope", scope)
    return html


def load_fits(path: str, normalize: bool = True) -> AstroImage:
    with fits.open(path) as hdul:
        raw = np.asarray(hdul[0].data)
        header = hdul[0].header
    if raw.ndim == 3:
        # FITS color cubes are typically (channels, H, W); some are already (H, W, 3).
        if raw.shape[0] == 3:
            raw = np.transpose(raw, (1, 2, 0))
        elif raw.shape[2] != 3:
            raise ValueError(
                f"unsupported 3D FITS shape {raw.shape}; expected (3, H, W) or (H, W, 3)"
            )
        data = _normalize(raw) if normalize else raw.astype(np.float32)
        if normalize:
            data = np.clip(data, 0.0, 1.0)
        h, w = data.shape[:2]
        return AstroImage(data.astype(np.float32), is_linear=True,
                          metadata=_parse_metadata(header, h, w))
    # 2D mono-Bayer -> debayer. The CFA pattern MUST come from the file's own
    # header (Seestar subs are 'GRBG', not 'RGGB'); a wrong pattern demosaics one
    # phase off and produces a green maze + false colour.
    base = _normalize(raw) if normalize else raw.astype(np.float32)
    rgb = _demosaic(base, _bayer_pattern(header))
    if normalize:
        rgb = np.clip(rgb, 0.0, 1.0)
    h, w = rgb.shape[:2]
    return AstroImage(rgb.astype(np.float32), is_linear=True,
                      metadata=_parse_metadata(header, h, w))


def is_stacked_master(path: str) -> bool:
    """True if `path` is something already stacked rather than a raw sub.

    Checked from the header only, before any debayer: load_fits demosaics 2D
    Bayer data into a 3-channel array too, so AstroImage.data.ndim is 3 for both
    a master AND a debayered raw sub — only the on-disk header distinguishes
    them.

    A colour master is NAXIS=3, which used to be the whole test. That is not
    enough now the extractor can write single-gas Ha and OIII masters: those are
    MONO, so NAXIS=2, and a mono master is shaped exactly like a raw CFA sub.
    Left undetected one would be graded as a sub, and since a stacked frame is
    full of sharp stars it could grade best and become the registration
    reference — then _bayer_pattern would fall back to the instrument default
    and Bayer-split a finished image into nonsense, silently.

    STACKCNT is the discriminator: every master Nocturne writes carries it (see
    master_header) and no raw sub does — verified against real Seestar subs,
    whose headers have no such card.
    """
    with fits.open(path) as hdul:
        header = hdul[0].header
        return int(header.get("NAXIS", 0)) == 3 or "STACKCNT" in header


def load_master(path: str) -> AstroImage:
    """Load a processed master back to a linear AstroImage. Supports the formats
    the app writes: FITS (via load_fits) and 16-bit TIFF (via tifffile)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".fits", ".fit", ".fts"):
        # A colour master is a 3-channel cube (NAXIS=3). A 2D FITS is a mono or
        # raw-CFA frame, which load_fits would debayer into fake colour — reject
        # it instead so the caller gets an honest error, not garbage.
        with fits.open(path) as hdul:
            if int(hdul[0].header.get("NAXIS", 0)) != 3:
                raise ValueError("expected a colour (RGB) master, not a mono image")
        return load_fits(path)
    if ext in (".tif", ".tiff"):
        # _normalize, not a second hand-rolled copy: this branch carried the same
        # `peak > 0` guard and therefore the same NaN hole (a float TIFF can hold
        # NaN even though a 16-bit one cannot).
        arr = _normalize(np.asarray(tifffile.imread(path)))
        h, w = arr.shape[:2]
        return AstroImage(np.clip(arr, 0.0, 1.0), is_linear=True,
                          metadata={"width": w, "height": h})
    raise ValueError(f"unsupported input format: {ext}")
