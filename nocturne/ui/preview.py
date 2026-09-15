from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage

from ..core.autostretch import autostretch  # noqa: F401 - re-exported
from ..core.export import display_data
from ..core.image import AstroImage, finite_or_zero


# Long edge of a live preview. Big enough to judge colour and structure,
# small enough that a slider tick recomputes in milliseconds.
PREVIEW_MAX = 640


def downscale(img: AstroImage, max_edge: int = PREVIEW_MAX) -> AstroImage:
    """Shrink for the live preview by AVERAGING each block, not by sampling one
    pixel in every N.

    Striding is cheaper and destroys a star field: measured on 300 synthetic 3x3
    stars decimated 8x, 253 vanished entirely and the 47 survivors were drawn at
    full amplitude, which is the hard single-pixel look. Averaging keeps every
    star and conserves flux exactly, for a few hundred milliseconds once — after
    a star split that already takes seconds.
    """
    from skimage.transform import downscale_local_mean
    h, w = img.data.shape[:2]
    step = max(1, max(h, w) // max_edge)
    if step == 1:
        return img
    blocks = (step, step, 1) if img.data.ndim == 3 else (step, step)
    small = downscale_local_mean(img.data, blocks).astype(np.float32)
    return AstroImage(np.ascontiguousarray(small),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def rgb_to_qimage(rgb: np.ndarray) -> QImage:
    """Wrap a uint8 H×W×3 RGB array in a detached QImage."""
    rgb = np.ascontiguousarray(rgb)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def qimage_to_rgb8(qi) -> np.ndarray:
    """The inverse of rgb_to_qimage: an H×W×3 uint8 copy of a QImage.

    Qt pads every scanline to a 4-byte boundary, so bytesPerLine() is NOT
    width*3 in general — for a 3285-wide RGB888 image it is 9856, not 9855. The
    old inline version divided bytesPerLine() by 3 and reshaped, which is only
    correct when the width is a multiple of 4 (3w is divisible by 4 exactly when
    w is). Seestar frames are 1080 wide so it always worked; a cropped or
    drizzled master failed three times in four with "cannot reshape array of
    size ... into shape ...".

    Reshape by BYTES, then take the valid part of each row.
    """
    from PySide6.QtGui import QImage

    if qi.format() != QImage.Format.Format_RGB888:
        qi = qi.convertToFormat(QImage.Format.Format_RGB888)
    w, h = qi.width(), qi.height()
    buf = np.frombuffer(qi.constBits(), np.uint8, count=qi.sizeInBytes())
    return buf.reshape(h, qi.bytesPerLine())[:, :w * 3].reshape(h, w, 3).copy()


def to_rgb8(img: AstroImage, *, linked: bool = True) -> np.ndarray:
    """The uint8 H×W×3 array the canvas displays. Linear images are autostretched
    for display only — the underlying data is untouched, which is why the hover
    readout reports data values and labels them 'linear'.

    Non-finite values are replaced with 0.0 before the uint8 cast (see
    image.finite_or_zero), matching histogram._counts_256 and export._to_uint,
    so the canvas, the histogram and the exported file agree and no
    RuntimeWarning is emitted. This guard is the last line, not the only one:
    it can only paint a NaN pixel black, and until _stretch_params was made
    NaN-aware it faithfully painted a whole autostretch-poisoned channel black
    instead."""
    # The SAME function the picture exporters use, so the canvas and the file
    # cannot drift apart — see core.export.display_data.
    data = display_data(img, linked=linked)
    if data.ndim == 2:
        data = np.repeat(data[:, :, None], 3, axis=2)
    return (finite_or_zero(data) * 255 + 0.5).astype(np.uint8)


def to_qimage(img: AstroImage, *, linked: bool = True) -> QImage:
    # Carries `linked` because the stretch picker renders through it — without
    # it the picker could not show the choice it is asking the user to make.
    return rgb_to_qimage(to_rgb8(img, linked=linked))
