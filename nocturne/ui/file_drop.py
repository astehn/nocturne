"""What a file dragged onto the window would open, if anything.

Andreas, 2026-10-06: "i have myself on several occasions actually tried to
drag at least images into nocturne with no luck". One local file of a kind the
Open menus already accept; anything else is refused before it is dropped, so
the cursor says "no" instead of the drop silently doing nothing.
"""
from __future__ import annotations

import os

IMAGE_EXTS = (".fit", ".fits", ".fts", ".tif", ".tiff")   # as Open Image's picker
PROJECT_EXT = ".nocturne"


def dropped_file(mime) -> tuple[str, str] | None:
    """("project" | "image", path) for exactly one local file Nocturne opens,
    else None. Several files are refused rather than guessed between."""
    if mime is None or not mime.hasUrls():
        return None
    urls = mime.urls()
    if len(urls) != 1 or not urls[0].isLocalFile():
        return None
    path = urls[0].toLocalFile()
    if not os.path.isfile(path):
        return None                     # a folder, or a file that has gone
    low = path.lower()
    if low.endswith(PROJECT_EXT):
        return ("project", path)
    if low.endswith(IMAGE_EXTS):
        return ("image", path)
    return None
