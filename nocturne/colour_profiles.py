"""ICC profile bytes for the colour spaces Nocturne can export.

Sourced from Qt's QColorSpace rather than from the filesystem. Three reasons:
redistributing Adobe's and Apple's profiles carries their licences, reading
/System/Library/ColorSync/Profiles is macOS-only, and Qt gives one source of
truth for the bytes that both the numpy and the QImage export paths can share.

Verified to work with NO QApplication, which matters because batch export runs
headless.

This module lives OUTSIDE nocturne/core deliberately: core is Qt-free by rule
(see CLAUDE.md), and these bytes come from Qt. The conversion maths, which needs
no Qt, stays in core/colour.py.
"""
from __future__ import annotations

from .core.colour import SPACES

_QT_NAME = {
    "sRGB": "SRgb",
    "Display P3": "DisplayP3",
    "Adobe RGB": "AdobeRgb",
    "ProPhoto RGB": "ProPhotoRgb",
}


def qt_colour_space(space: str):
    """The QColorSpace for `space`, for callers that save through QImage."""
    if space not in _QT_NAME:
        raise ValueError(f"unknown colour space {space!r}")
    from PySide6.QtGui import QColorSpace
    return QColorSpace(getattr(QColorSpace.NamedColorSpace, _QT_NAME[space]))


def icc_bytes(space: str) -> bytes:
    """ICC profile bytes for `space`, for callers that write files themselves."""
    cs = qt_colour_space(space)
    if not cs.isValid():
        raise ValueError(f"Qt has no usable profile for {space!r}")
    return bytes(cs.iccProfile())


def prepare_for_export(img, space: str, *, linked: bool = True):
    """Convert into `space` and return (image, profile bytes) — for the single
    Export and for Batch, which wrote untagged files until 2026-10-16.

    Conversion first, THEN the tag — the two must agree. Tagging without
    converting would mis-declare the file, which is worse than an untagged
    export: a reader would faithfully render the wrong thing instead of
    guessing.
    """
    from .core.colour import convert
    if space == "sRGB":
        return img, icc_bytes("sRGB")     # no conversion, but still declared
    from .core.image import AstroImage, finite_or_zero
    if img.data.ndim == 2:
        # The panel greys these out for mono; this is the backstop. A grey
        # TIFF cannot carry an RGB working space, and the conversion itself
        # throws on a 2-D array — say why instead of a matmul error.
        raise ValueError(f"A mono picture exports in sRGB only, not {space}.")
    if img.is_linear:
        # STRETCH, THEN CONVERT. The canvas shows display_data; converting
        # the linear data and letting save_tiff stretch it afterwards wrote
        # a file up to 0.22 off the canvas (synthetic star field, ProPhoto,
        # unlinked) — and off the Starless + Stars pair, which stretched
        # first all along.
        from .core.export import display_data
        img = AstroImage(finite_or_zero(display_data(img, linked=linked)),
                         is_linear=False, metadata=dict(img.metadata))
    moved = convert(img.data, space)
    return (AstroImage(moved, is_linear=img.is_linear, metadata=dict(img.metadata)),
            icc_bytes(space))


__all__ = ["SPACES", "icc_bytes", "prepare_for_export", "qt_colour_space"]
