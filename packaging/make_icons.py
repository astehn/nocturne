"""Regenerate the macOS .icns app icon from nocturne/assets/nocturne_icon.svg.

Run from the repo root:  .venv/bin/python packaging/make_icons.py
Requires macOS `iconutil` (bundled with Xcode command line tools).
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG = os.path.join(ROOT, "nocturne", "assets", "nocturne_icon.svg")
OUT = os.path.join(ROOT, "packaging", "nocturne.icns")

# (filename, pixel size) for a macOS .iconset
_SPECS = [
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
]


def _render(size: int, path: str) -> None:
    r = QSvgRenderer(SVG)
    if not r.isValid():
        raise SystemExit(f"invalid SVG: {SVG}")
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(0)  # transparent outside the circular badge
    p = QPainter(img)
    r.render(p)
    p.end()
    img.save(path)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "nocturne.iconset")
        os.makedirs(iconset)
        for name, size in _SPECS:
            _render(size, os.path.join(iconset, name))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", OUT], check=True)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
