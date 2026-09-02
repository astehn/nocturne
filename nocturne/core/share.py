from __future__ import annotations

import os

from .fits_io import resolve_integration, format_integration

ASPECTS: list[tuple[str, float | None]] = [
    ("Original", None), ("1:1", 1.0), ("4:5", 4 / 5),
    ("9:16", 9 / 16), ("3:2", 3 / 2), ("16:9", 16 / 9),
]

# Longest-edge presets. 2048 was the hardcoded value and stays the default; the
# rest exist because a tool whose whole purpose is producing a file for
# somewhere else should let you say how big that file is. "Full" keeps the
# cropped resolution — compose_share only ever downscales, never upscales.
SIZES: list[tuple[str, int | None]] = [
    ("1080 px", 1080), ("2048 px", 2048), ("4096 px", 4096), ("Full size", None),
]
DEFAULT_SIZE = 2048

# JPEG for posting, PNG when lossless matters (annotation labels and the caption
# band have hard edges that JPEG smears at low quality).
FORMATS: list[tuple[str, str]] = [("JPEG", "jpg"), ("PNG", "png")]

# Caption sizes are FRACTIONS of the composited height, never pixel sizes. The
# band scales with the output, so an absolute "18 px" means something different
# at 1080 than at 4096 — pick one, export both, and one of them is unreadable.
# A fraction stays correct at every size.
CAPTION_SIZES: list[tuple[str, float]] = [
    ("Small", 0.022), ("Medium", 0.028), ("Large", 0.038),
]
DEFAULT_CAPTION_SIZE = 0.028        # the value that was hardcoded as FONT_FRAC

# "on"    — translucent band over the bottom of the picture (the original, and
#           what you want for a full-bleed post).
# "below" — the canvas is extended and the caption sits underneath, so it never
#           covers any of the image.
PLACEMENTS: list[tuple[str, str]] = [("On image", "on"), ("Below image", "below")]
DEFAULT_PLACEMENT = "on"
DEFAULT_CAPTION_COLOUR = "#ffffff"

ALIGNMENTS: list[tuple[str, str]] = [
    ("Left", "left"), ("Centre", "centre"), ("Right", "right"),
]
DEFAULT_ALIGNMENT = "left"

# Alpha of the band painted over the picture, 0–1. 0.59 is 150/255, the value
# that was hardcoded. Applies to the "on image" placement only: a "below" strip
# sits on canvas that did not exist before, so there is nothing to see through.
DEFAULT_BAND_OPACITY = 0.59


def caption_line(metadata: dict, handle: str, *, include_target: bool = True) -> str:
    """One-line caption: target · integration · frames×sub · date · @handle.
    Any field with no data is omitted; a blank handle drops the @ segment.

    `include_target=False` is for the title plate, where the object already has
    two slots of its own and repeating it here would print the name twice. The
    default is unchanged so the Share dialog's Data preset stays byte-identical.
    """
    segs: list[str] = []
    # `target_solved` too, matching the info strip (main_window), the provenance
    # report and the FITS export — every one of which reads the pair. Share was
    # the only surface that did not, so a stacked master with no OBJECT header
    # that you plate-solved to NGC 7000 showed "NGC 7000" everywhere in the app
    # and published with no target in the caption at all.
    target = str(metadata.get("target") or metadata.get("target_solved") or "").strip()
    if target and include_target:
        segs.append(target)
    integ = resolve_integration(metadata)
    if integ is not None:
        if integ.total_s:
            segs.append(format_integration(integ.total_s))
        if integ.frames and integ.per_sub_s:
            segs.append(f"{integ.frames} × {round(integ.per_sub_s)}s")
    date = str(metadata.get("date") or "").strip()
    if len(date) >= 10:
        segs.append(date[:10])           # ISO 'YYYY-MM-DDT..' → 'YYYY-MM-DD'
    handle = handle.strip()
    if handle:
        segs.append(handle if handle.startswith("@") else "@" + handle)
    return " · ".join(segs)


def centered_crop(w: int, h: int, aspect: float | None) -> tuple[int, int, int, int]:
    """(top, bottom, left, right) for a centered max-fit box of `aspect`
    (width/height). Full frame when aspect is None."""
    if aspect is None:
        return (0, h, 0, w)
    if w / h > aspect:                   # image wider than target → limit by height
        ch = h
        cw = round(h * aspect)
    else:                                # taller/narrower → limit by width
        cw = w
        ch = round(w / aspect)
    left = (w - cw) // 2
    top = (h - ch) // 2
    return (top, top + ch, left, left + cw)


def share_filename(source_label: str | None, aspect_label: str, ext: str = "jpg") -> str:
    stem = os.path.splitext(source_label or "share")[0] or "share"
    tag = aspect_label.replace(":", "x")
    return f"{stem}_{tag}.{ext.lstrip('.')}"
