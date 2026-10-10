from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .image import AstroImage

# The shapes a frame can be locked to — ONE list for Crop, Trim, Share and
# Upscale Crop. Crop/Trim and Share/Upscale each kept their own (5 and 6 names,
# different orders, 4:5 in one and 9:16 only in the other); a beginner met two
# vocabularies for one idea. Landscape only: Portrait turns any of them
# (`shape_name`), so 4:5 and 9:16 are 5:4 and 16:9 turned, not entries.
# Width / height.
RATIO_SHAPES: list[tuple[str, float]] = [
    ("1:1", 1.0), ("5:4", 5 / 4), ("4:3", 4 / 3), ("3:2", 3 / 2), ("16:9", 16 / 9),
]

# Stored names (recipes, project bundles, the history option). A stored name is
# the shape the user made, turned: a portrait 3:2 is stored and logged as "2:3".
FREE = "Free"          # no ratio lock: drag any rectangle
PICTURE = "Picture"    # locked to the picture's own proportions ("Original" on the button)
# Before 2026-10-10 Crop's and Trim's free choice was called "Original", and
# recipes hold that word. It must keep meaning FREE — the locked "Original" is
# new and is therefore stored under a new name, PICTURE.
LEGACY_FREE = "Original"


def turned(name: str) -> str:
    """"3:2" -> "2:3"."""
    a, b = name.split(":")
    return f"{b}:{a}"


def shape_name(base: str, portrait: bool) -> str:
    """The stored (and shown) name of `base` in an orientation. Free, Picture and
    1:1 have none."""
    if portrait and base in dict(RATIO_SHAPES) and base != "1:1":
        return turned(base)
    return base


def split_shape(name: str) -> tuple[str, bool]:
    """(base, portrait) for a stored name: "9:16" -> ("16:9", True). Anything
    that is not a ratio we offer reads as Free, the lock-nothing choice."""
    if name == PICTURE:
        return PICTURE, False
    bases = dict(RATIO_SHAPES)
    if name in bases:
        return name, False
    if ":" in name and turned(name) in bases:
        return turned(name), True
    return FREE, False


def shape_label(name: str) -> str:
    """The stored name as the user knows it — the word on the button. The log
    and the provenance report say this, never the internal "Picture"."""
    if name == PICTURE:
        return "Original"
    if name == LEGACY_FREE or split_shape(name) == (FREE, False):
        return FREE
    return name


def shape_ratio(name: str, picture_ratio: float | None = None) -> float | None:
    """Width / height for a stored name; None is no lock. `picture_ratio` is the
    picture's own, which PICTURE takes. "Original" (LEGACY_FREE) is None."""
    if name == PICTURE:
        return picture_ratio
    try:
        a, b = (float(x) for x in name.split(":"))
    except (ValueError, AttributeError):
        return None                       # Free, legacy "Original", unknown
    return a / b if a > 0 and b > 0 else None


# Composition guides, label -> what ImageView.set_guides expects.
GUIDE_KINDS = {"None": "none", "Thirds": "thirds", "Centre": "center"}
GUIDES = list(GUIDE_KINDS)


@dataclass
class CropParams:
    bounds: tuple[int, int, int, int] | None = None  # (top, bottom, left, right), input coords
    aspect: str = FREE        # a stored shape name (see shape_ratio)
    rotate: int = 0  # clockwise degrees: 0, 90, 180, 270
    flip_h: bool = False
    flip_v: bool = False


def _center_crop_to_ratio(data: np.ndarray, ratio: float) -> np.ndarray:
    h, w = data.shape[:2]
    if w / h > ratio:  # too wide -> trim width
        new_w = max(1, round(h * ratio))
        x0 = (w - new_w) // 2
        return data[:, x0:x0 + new_w]
    new_h = max(1, round(w / ratio))  # too tall -> trim height
    y0 = (h - new_h) // 2
    return data[y0:y0 + new_h, :]


def apply_crop_params(img: AstroImage, params: CropParams | None) -> AstroImage:
    params = params or CropParams()
    data = img.data
    if params.bounds is not None:
        t, b, l, r = params.bounds
        data = data[t:b, l:r]
    k = (params.rotate // 90) % 4
    h0, w0 = img.data.shape[:2]
    # The picture's own proportions, as it will be shown: turned with it.
    picture = (h0 / w0) if k % 2 else (w0 / h0)
    if k:
        data = np.rot90(data, -k)  # clockwise
    if params.flip_h:
        data = data[:, ::-1]
    if params.flip_v:
        data = data[::-1, :]
    ratio = shape_ratio(params.aspect, picture)
    if ratio is not None:
        data = _center_crop_to_ratio(data, ratio)
    return AstroImage(
        np.ascontiguousarray(data.astype(np.float32)),
        is_linear=img.is_linear,
        metadata=dict(img.metadata),
    )


def detect_content_bounds(img: AstroImage, threshold: float = 0.002) -> tuple[int, int, int, int]:
    """Find (top, bottom, left, right) of the non-black content rectangle left
    after stacking/dithering (rows/cols whose mean exceeds `threshold`)."""
    data = img.data
    gray = data.mean(axis=2) if data.ndim == 3 else data
    rows = np.where(gray.mean(axis=1) > threshold)[0]
    cols = np.where(gray.mean(axis=0) > threshold)[0]
    if rows.size == 0 or cols.size == 0:
        return 0, gray.shape[0], 0, gray.shape[1]
    return int(rows[0]), int(rows[-1] + 1), int(cols[0]), int(cols[-1] + 1)


def auto_crop(img: AstroImage, margin: float = 0.0) -> AstroImage:
    """Crop to the detected content rectangle, then trim an extra `margin`
    fraction off each side."""
    top, bottom, left, right = detect_content_bounds(img)
    data = img.data[top:bottom, left:right]
    if margin > 0:
        h, w = data.shape[:2]
        dh, dw = int(h * margin), int(w * margin)
        data = data[dh:h - dh, dw:w - dw]
    return AstroImage(
        np.ascontiguousarray(data.astype(np.float32)),
        is_linear=img.is_linear,
        metadata=dict(img.metadata),
    )


def uncovered_fraction(img: AstroImage) -> float:
    """How much of the frame is not data at all — the black wedges an uncropped
    mosaic or a rotated stack leaves behind.

    Exactly zero across every channel, not "dark": real sky is faint but never
    identically zero, while an uncovered pixel was never written to. A threshold
    generous enough to catch dark sky would warn on every well-exposed linear
    image, which would train the user to ignore the warning.

    The number matters because background extraction fits a model over the WHOLE
    frame. GraXpert has no way to know a black corner is not sky, so it fits the
    gradient to it and the result is unusable — which is what a user meets if
    they leave the crop until the end of the pipeline.
    """
    data = np.asarray(img.data)
    empty = (data == 0.0).all(axis=2) if data.ndim == 3 else (data == 0.0)
    return float(empty.mean())
