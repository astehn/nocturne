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


__all__ = ["SPACES", "icc_bytes", "qt_colour_space"]
