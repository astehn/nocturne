"""Is there a Share title plate burned into this JPEG?

Spec §2.3. Sets `submissions.has_plate` at seed time, and lets Andreas re-check
an image after he re-exports it without the plate. A plated row renders no
`<figcaption>` (its facts are already in the pixels) and can never be a planner
representative (a burned title is wrong for every target but one).

HOW, and why not OCR. A title plate is the only thing on an astrophoto with
HORIZONTAL STRUCTURE: bright glyphs separated by dark gaps, repeated over a run
of rows near the bottom. Sky and nebulosity vary smoothly; stars are isolated
points that do not fill a row. So a run of high per-row variance low in the
frame is the signal, and OCR would be a dependency and a model for a yes/no
question that pixel statistics answer.

WHY A SLIDING WINDOW rather than whole rows. Share places the plate left,
centre or right. Measured 2026-09-21: M 31's plate is bottom-RIGHT aligned, and
on a 1100x608 mosaic it occupies so little of each full row that whole-row
variance read 1073 against a 900 threshold -- one JPEG re-encode from being
called clean. Scanning windows across the width is placement-agnostic and took
the same image to 2488.

MEASURED, 2026-09-21, peak windowed row variance and rows over threshold:

    ngc7635   13493 / 67      m17       10795 / 74      m8         9648 / 71
    ngc6888   13350 / 65      ic1396a   10712 / 82      ngc7000    8165 / 156
    ngc6992   11223 / 66      ngc281     9874 / 78      m16        6370 / 40
    m31        2488 / 28   <- the weakest real plate
    synthetic clean starfield        429 / 0   <- the negative case

The threshold sits between two populations that are far apart, not beside
either. If a real submission ever trips it, tighten to the plate's band
geometry -- do NOT raise the threshold until it passes, which would blind the
detector to the exact case it exists for.
"""
from __future__ import annotations

import pathlib

# plate_text() writes low in the frame; start above it so a tall plate is not
# clipped by the band edge.
_BAND_TOP = 0.66
# A third of the width: wide enough to hold a line of the plate, narrow enough
# that a right-aligned one is not diluted by empty sky on the left.
_WINDOW = 0.34
_STEP = 0.08
# Between 429 (clean) and 2488 (the weakest real plate).
_ROW_VARIANCE = 900.0
# One bright row could be a satellite trail. A plate is several rows of text;
# the weakest real one had 28.
_MIN_ROWS = 3


def plate_rows(path: "pathlib.Path | str") -> int:
    """How many rows look like plate text. Exposed so a test can assert a
    MARGIN rather than a boolean: M 31's right-aligned plate clears whole-row
    variance by exactly one row, which is the near-miss the sliding window
    exists to fix, and a boolean assertion cannot tell the two apart."""
    import numpy as np
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(path) as im:
        a = np.asarray(im.convert("L"), dtype=float)
    h, w = a.shape
    band = a[int(h * _BAND_TOP):, :]
    if band.size == 0 or w < 8:
        return 0

    best = np.zeros(band.shape[0])
    off = 0.0
    while off + _WINDOW <= 1.0001:
        x0, x1 = int(w * off), int(w * (off + _WINDOW))
        if x1 > x0:
            best = np.maximum(best, band[:, x0:x1].var(axis=1))
        off += _STEP
    return int((best > _ROW_VARIANCE).sum())


def has_plate(path: "pathlib.Path | str") -> bool:
    """True if a Share title plate appears to be burned into the image."""
    return plate_rows(path) >= _MIN_ROWS
