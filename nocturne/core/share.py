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


import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter

BAND_FRAC = 0.07     # caption band height as a fraction of composited height
FONT_FRAC = 0.028    # caption font size as a fraction of composited height (kept light, not heavy)
PAD_FRAC = 0.03


def _qimage_from_rgb8(rgb8: np.ndarray) -> QImage:
    if rgb8.ndim == 2:
        rgb8 = np.stack([rgb8] * 3, axis=2)
    rgb8 = np.ascontiguousarray(rgb8.astype(np.uint8))
    h, w = rgb8.shape[:2]
    return QImage(rgb8.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def compose_share(rgb8: np.ndarray, crop, caption: str, longest_edge: int = 2048) -> QImage:
    top, bottom, left, right = crop
    if rgb8.ndim == 2:
        rgb8 = np.stack([rgb8] * 3, axis=2)
    cropped = rgb8[top:bottom, left:right]
    image = _qimage_from_rgb8(cropped)
    w, h = image.width(), image.height()
    longest = max(w, h)
    if longest > longest_edge:                       # downscale only, keep aspect
        image = image.scaled(
            round(w * longest_edge / longest), round(h * longest_edge / longest),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    if caption:
        image = _burn_caption(image, caption)
    return image


def _burn_caption(image: QImage, caption: str) -> QImage:
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    w, h = image.width(), image.height()
    band = max(1, round(h * BAND_FRAC))
    pad = max(1, round(h * PAD_FRAC))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillRect(0, h - band, w, band, QColor(0, 0, 0, 150))     # translucent band
    font = QFont()
    font.setPixelSize(max(8, round(h * FONT_FRAC)))
    p.setFont(font)
    p.setPen(QColor(255, 255, 255))
    text = QFontMetrics(font).elidedText(caption, Qt.TextElideMode.ElideRight, w - 2 * pad)
    p.drawText(pad, h - band, w - 2 * pad, band,
               int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
    p.end()
    return image


def save_share_jpeg(image: QImage, path: str, quality: int = 92) -> None:
    image.save(path, "JPEG", quality)


def to_clipboard(image: QImage) -> None:
    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().setImage(image)
