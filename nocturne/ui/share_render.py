"""Qt rendering and file IO for Share — the half of the old core/share.py that
was never pure.

`nocturne/core/share.py` was the ONLY module under core/ importing PySide6,
against the project's own rule that core holds no Qt. It also declared its Qt
imports mid-file, at line 57, which is how it went unnoticed. The genuinely pure
parts (ASPECTS, SIZES, FORMATS, caption_line, centered_crop, share_filename)
stayed behind; everything that paints or writes lives here.

This also retires a verbatim duplicate: _qimage_from_rgb8 existed identically in
both core/share.py and ui/share_dialog.py.
"""
from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter

from ..core.share import DEFAULT_SIZE

BAND_FRAC = 0.07     # caption band height as a fraction of composited height
FONT_FRAC = 0.028    # caption font size as a fraction of composited height (kept light, not heavy)
PAD_FRAC = 0.03


def qimage_from_rgb8(rgb8: np.ndarray) -> QImage:
    if rgb8.ndim == 2:
        rgb8 = np.stack([rgb8] * 3, axis=2)
    rgb8 = np.ascontiguousarray(rgb8.astype(np.uint8))
    h, w = rgb8.shape[:2]
    return QImage(rgb8.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def compose_share(rgb8: np.ndarray, crop, caption: str,
                  longest_edge: int | None = DEFAULT_SIZE) -> QImage:
    """`longest_edge=None` keeps the cropped resolution. Downscale only — a share
    is never upscaled, which would add pixels without adding detail."""
    top, bottom, left, right = crop
    if rgb8.ndim == 2:
        rgb8 = np.stack([rgb8] * 3, axis=2)
    cropped = rgb8[top:bottom, left:right]
    image = qimage_from_rgb8(cropped)
    w, h = image.width(), image.height()
    longest = max(w, h)
    if longest_edge and longest > longest_edge:      # downscale only, keep aspect
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
    """Kept for callers that specifically want JPEG. save_share picks by extension."""
    image.save(path, "JPEG", quality)


def save_share(image: QImage, path: str, quality: int = 92) -> None:
    """Write by extension: PNG is lossless (quality ignored), anything else JPEG.
    PNG matters here because annotation labels and the caption band have hard
    edges, which is exactly what JPEG smears."""
    if os.path.splitext(path)[1].lower() == ".png":
        image.save(path, "PNG")
    else:
        image.save(path, "JPEG", quality)


def to_clipboard(image: QImage) -> None:
    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().setImage(image)
