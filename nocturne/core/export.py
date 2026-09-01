from __future__ import annotations

import numpy as np
import tifffile
from astropy.io import fits
from PIL import Image

from .image import AstroImage, finite_or_zero


def _to_uint(data: np.ndarray, bits: int) -> np.ndarray:
    # finite_or_zero BEFORE the clip: np.clip leaves NaN as NaN, and casting NaN
    # to an unsigned integer is undefined -- it produced whatever that platform's
    # float->uint conversion happened to yield, while the canvas (which does
    # guard) showed black. The preview must equal the export.
    maxval = (2 ** bits) - 1
    clipped = np.clip(finite_or_zero(data), 0.0, 1.0)
    dtype = np.uint16 if bits == 16 else np.uint8
    return (clipped * maxval + 0.5).astype(dtype)


# ICC profile tag. Photoshop and every other reader assigns its OWN working
# space to an untagged file — which is why a correct M 16 export rendered dark
# in Photoshop: sRGB data read as ProPhoto. This module stays ignorant of colour
# SPACES (core/ is Qt-free and the bytes come from Qt); it embeds what it is
# given. See nocturne/colour_profiles.py.
_ICC_TAG = 34675


def display_data(img: AstroImage) -> np.ndarray:
    """What a PICTURE format should contain: exactly what the canvas shows.

    A linear image is autostretched here for the same reason preview.to_rgb8
    autostretches it — because that is what the user is looking at. Without it,
    reaching Export without having run Stretch wrote a file about 10x darker
    than the canvas (measured on a faint linear frame: canvas mean 61.7 of 255,
    file mean 6.4). It looks like a black picture and nothing says why.

    CLAUDE.md: "The preview at any step must equal what export would produce.
    'Probably the same' is a bug." This is that rule, in the one place both
    sides can share, so they cannot drift.

    NOT used by save_fits, deliberately. FITS carries DATA, and linear data
    should stay linear in it; a picture format is the only place the question
    arises.
    """
    from .autostretch import autostretch
    return autostretch(img) if img.is_linear else np.clip(img.data, 0.0, 1.0)


def save_tiff(img: AstroImage, path: str, icc: bytes | None = None) -> None:
    # 16-bit TIFF for both mono and color (preserves dynamic range for further
    # editing). Pillow cannot write 16-bit RGB reliably, so use tifffile.
    extratags = [(_ICC_TAG, 1, len(icc), icc, True)] if icc else None
    tifffile.imwrite(path, _to_uint(display_data(img), 16), extratags=extratags)


def save_jpeg(img: AstroImage, path: str, quality: int = 95,
              icc: bytes | None = None) -> None:
    arr = _to_uint(display_data(img), 8)
    mode = "L" if arr.ndim == 2 else "RGB"
    extra = {"icc_profile": icc} if icc else {}
    Image.fromarray(arr, mode=mode).save(path, format="JPEG", quality=quality,
                                         **extra)


def save_png(img: AstroImage, path: str, icc: bytes | None = None) -> None:
    arr = _to_uint(display_data(img), 8)
    mode = "L" if arr.ndim == 2 else "RGB"
    extra = {"icc_profile": icc} if icc else {}
    Image.fromarray(arr, mode=mode).save(path, format="PNG", **extra)


def save_fits(img: AstroImage, path: str, header: dict | None = None) -> None:
    # 32-bit float FITS; color stored channels-first (3, H, W).
    data = img.data.astype(np.float32)
    if data.ndim == 3:
        data = np.transpose(data, (2, 0, 1))
    hdu = fits.PrimaryHDU(data)
    if header:
        for key, value in header.items():
            hdu.header[key] = value
    hdu.writeto(path, overwrite=True)
