from __future__ import annotations

import os

from .fits_io import resolve_integration, format_integration

ASPECTS: list[tuple[str, float | None]] = [
    ("Original", None), ("1:1", 1.0), ("4:5", 4 / 5),
    ("9:16", 9 / 16), ("3:2", 3 / 2), ("16:9", 16 / 9),
]


def caption_line(metadata: dict, handle: str) -> str:
    """One-line caption: target · integration · frames×sub · date · @handle.
    Any field with no data is omitted; a blank handle drops the @ segment."""
    segs: list[str] = []
    target = str(metadata.get("target") or "").strip()
    if target:
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


def share_filename(source_label: str | None, aspect_label: str) -> str:
    stem = os.path.splitext(source_label or "share")[0] or "share"
    tag = aspect_label.replace(":", "x")
    return f"{stem}_{tag}.jpg"
