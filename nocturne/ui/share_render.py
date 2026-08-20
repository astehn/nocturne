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

from ..core.share import (
    DEFAULT_ALIGNMENT, DEFAULT_BAND_OPACITY, DEFAULT_CAPTION_COLOUR,
    DEFAULT_CAPTION_SIZE, DEFAULT_PLACEMENT, DEFAULT_SIZE,
)

_ALIGN_FLAGS = {
    "left": Qt.AlignmentFlag.AlignLeft,
    "centre": Qt.AlignmentFlag.AlignHCenter,
    "right": Qt.AlignmentFlag.AlignRight,
}

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
                  longest_edge: int | None = DEFAULT_SIZE,
                  *, size_frac: float = DEFAULT_CAPTION_SIZE,
                  colour: str = DEFAULT_CAPTION_COLOUR,
                  placement: str = DEFAULT_PLACEMENT,
                  align: str = DEFAULT_ALIGNMENT,
                  band_opacity: float = DEFAULT_BAND_OPACITY) -> QImage:
    """`longest_edge=None` keeps the cropped resolution. Downscale only — a share
    is never upscaled, which would add pixels without adding detail.

    Caption styling is applied AFTER the downscale, so the band and text are
    sized against the pixels actually being written. Doing it before would make
    the caption shrink with the image and land at the wrong size."""
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
        image = _burn_caption(image, caption, size_frac=size_frac, colour=colour,
                              placement=placement, align=align,
                              band_opacity=band_opacity)
    return image


def _burn_caption(image: QImage, caption: str, *,
                  size_frac: float = DEFAULT_CAPTION_SIZE,
                  colour: str = DEFAULT_CAPTION_COLOUR,
                  placement: str = DEFAULT_PLACEMENT,
                  align: str = DEFAULT_ALIGNMENT,
                  band_opacity: float = DEFAULT_BAND_OPACITY) -> QImage:
    """Draw the caption on, or below, the picture.

    "below" extends the canvas rather than painting over it, so nothing you
    photographed is ever covered — the band height is derived from the IMAGE
    height so the strip is the same proportion either way.

    Band height follows the font, not a fixed fraction: at Large the old fixed
    7% band clipped the glyphs' descenders.
    """
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    w, h = image.width(), image.height()
    px = max(8, round(h * size_frac))
    band = max(px * 2, round(h * BAND_FRAC))
    pad = max(1, round(h * PAD_FRAC))

    if placement == "below":
        # The slider means the same thing in both modes: how DARK the band is.
        # It used to be alpha-over-the-picture only, which left it inert here and
        # so it was disabled — a control that visibly does nothing reads as
        # broken. 1.0 is black, 0.0 is white.
        level = max(0, min(255, round((1.0 - band_opacity) * 255)))
        out = QImage(w, h + band, QImage.Format.Format_RGB888)
        out.fill(QColor(level, level, level))
        p = QPainter(out)
        p.drawImage(0, 0, image)
        band_top = h
    else:
        out = image
        p = QPainter(out)
        band_top = h - band

    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if placement != "below":
        alpha = max(0, min(255, round(band_opacity * 255)))
        p.fillRect(0, band_top, w, band, QColor(0, 0, 0, alpha))
    font = QFont()
    font.setPixelSize(px)
    p.setFont(font)
    p.setPen(QColor(colour))
    text = QFontMetrics(font).elidedText(caption, Qt.TextElideMode.ElideRight, w - 2 * pad)
    flag = _ALIGN_FLAGS.get(align, Qt.AlignmentFlag.AlignLeft)
    p.drawText(pad, band_top, w - 2 * pad, band,
               int(Qt.AlignmentFlag.AlignVCenter | flag), text)
    p.end()
    return out


def _tag_srgb(image: QImage) -> QImage:
    """Declare the image sRGB before writing it.

    QImage.save() embeds whatever colour space the image carries, and an
    untagged file leaves the reader to guess — which is exactly how a correct
    export came to render dark in Photoshop. sRGB SPECIFICALLY, not the user's
    chosen export space: a shared image is destined for the web, where every
    browser assumes sRGB, and tagging it anything else would make it render
    wrongly in the one place it is meant to be seen.
    """
    from ..colour_profiles import qt_colour_space
    out = QImage(image)                 # detach; never retag the caller's image
    out.setColorSpace(qt_colour_space("sRGB"))
    return out


def save_share_jpeg(image: QImage, path: str, quality: int = 92) -> None:
    """Kept for callers that specifically want JPEG. save_share picks by extension."""
    _tag_srgb(image).save(path, "JPEG", quality)


def save_share(image: QImage, path: str, quality: int = 92) -> None:
    """Write by extension: PNG is lossless (quality ignored), anything else JPEG.
    PNG matters here because annotation labels and the caption band have hard
    edges, which is exactly what JPEG smears."""
    tagged = _tag_srgb(image)
    if os.path.splitext(path)[1].lower() == ".png":
        tagged.save(path, "PNG")
    else:
        tagged.save(path, "JPEG", quality)


def to_clipboard(image: QImage) -> None:
    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().setImage(image)
