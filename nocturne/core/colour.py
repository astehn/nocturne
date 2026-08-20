"""Convert the finished image into the colour space it will be declared to be in.

Astro data has NO SOURCE COLOUR SPACE. A FITS file is photon counts; unlike a
camera raw there is no original space to preserve. The colour in a Nocturne
image is created by the pipeline — demosaic, white balance, stretch — and
finally judged by eye on a calibrated display fed an sRGB signal. So sRGB is
what the numbers already mean, and it is where every conversion here starts.

Converting to a wider space does NOT add gamut. The colours stay where they
are; only the encoding changes. What it buys is that the file opens in the
user's working space without conversion, and that later edits — saturation
especially — have headroom before clipping.

No Qt: `core/` is Qt-free by rule, and the ICC profile BYTES (which do come from
Qt) live in nocturne/colour_profiles.py instead.
"""
from __future__ import annotations

import numpy as np

# What the UI offers, mapped to the names the `colour` library uses. All three
# share a D65 whitepoint, so chromatic adaptation between them is a no-op and
# cannot introduce a cast of its own.
_COLOUR_LIB_NAME = {
    "sRGB": "sRGB",
    "Display P3": "Display P3",
    "Adobe RGB": "Adobe RGB (1998)",
}

SPACES = tuple(_COLOUR_LIB_NAME)

# Wide gamut spreads the same 256 levels over a larger volume, so an 8-bit file
# in one has visibly coarser gradients — and astro images are mostly smooth
# gradients, the worst case for banding. PNG and JPEG are the share-and-publish
# formats, where sRGB is what every viewer expects anyway.
EIGHT_BIT_SPACES = ("sRGB",)


def convert(data: np.ndarray, to: str, frm: str = "sRGB") -> np.ndarray:
    """Re-encode `data` from `frm` into `to`. Both default sensibly to sRGB.

    Returns float32 in [0, 1]. Out-of-gamut results are clipped rather than
    allowed to wrap: casting a negative float to uint16 is undefined, and it
    produced garbage pixels here once already.
    """
    for name in (to, frm):
        if name not in _COLOUR_LIB_NAME:
            raise ValueError(f"unknown colour space {name!r}")
    arr = np.asarray(data, dtype=np.float32)
    if to == frm:
        return arr                      # a true no-op, not an almost-identity
    from colour import RGB_to_RGB
    from colour.models import RGB_COLOURSPACES

    # Decode and matrix, but stop BEFORE the target's transfer function so the
    # gamut clip happens in linear light. Doing it the other way round produces
    # NaN: an out-of-gamut colour goes negative after the matrix, and raising a
    # negative to a fractional exponent is not a number. np.clip does NOT remove
    # NaN, so it would reach the file — pure red is enough to trigger it.
    linear = RGB_to_RGB(arr.astype(np.float64),
                        _COLOUR_LIB_NAME[frm], _COLOUR_LIB_NAME[to],
                        apply_cctf_decoding=True, apply_cctf_encoding=False)
    linear = np.clip(np.asarray(linear), 0.0, 1.0)
    encode = RGB_COLOURSPACES[_COLOUR_LIB_NAME[to]].cctf_encoding
    out = np.clip(np.asarray(encode(linear)), 0.0, 1.0)
    return np.nan_to_num(out, nan=0.0).astype(np.float32)
