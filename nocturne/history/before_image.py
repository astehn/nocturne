"""The before frame of the Share video: the opened image with only the recorded
geometry applied, so before and after frame the same picture."""
from __future__ import annotations

import numpy as np

from ..core.autostretch import apply_linked_stretch, linked_stretch_params
from ..core.crop import CropParams, apply_crop_params
from ..core.image import AstroImage
from ..core.share import to_rgb8
from ..ui.pipeline import GEOMETRY_NAMES  # pure module, no Qt

_LINEAR_TARGET = 0.205


def _bounds(option):
    """(t, b, l, r) from a live CropParams or a reloaded bundle's dict, else None.

    A bundle comes off disk, so anything malformed means "cannot replay" and
    the caller falls back — never a crash in the middle of Save video."""
    b = option.bounds if isinstance(option, CropParams) else (
        option.get("bounds") if isinstance(option, dict) else None)
    try:
        out = tuple(int(v) for v in b)
    except (TypeError, ValueError):
        return None
    return out if len(out) == 4 else None


def has_processing(project, position: int) -> bool:
    """Whether anything but geometry made state `position`. Without it the
    video would wipe from the finished picture to itself — an Upscale Crop copy
    or a finished TIFF opened and shared untouched."""
    return any(name not in GEOMETRY_NAMES
               for name, _ in project.entries_through(position))


def before_image(project, position: int | None = None, token=None) -> AstroImage:
    """`position` pins the history state the after came from: Share snapshots
    it on open, so a step landing meanwhile cannot change the before."""
    check = token.check if token is not None else (lambda: None)
    if position is None:
        position = project.position
    entries = project.entries_through(position)
    geo = [i for i, (name, _) in enumerate(entries) if name in GEOMETRY_NAMES]
    if not geo:
        return project.state_at(0)
    img = project.state_at(0)
    replayed = True
    for i in geo:
        name, option = entries[i]
        if name in ("Crop", "Trim"):
            b = _bounds(option)
            if b is None:
                replayed = False
                break
            params = CropParams(bounds=b)  # never aspect: it is recorded, not applied
        elif name == "Rotate":
            params = CropParams(rotate=90)
        elif name == "Flip H":
            params = CropParams(flip_h=True)
        else:
            params = CropParams(flip_v=True)
        check()
        img = apply_crop_params(img, params)
    if replayed and tuple(img.data.shape[:2]) == tuple(project.shape_at(position)[:2]):
        return img
    return project.state_at(geo[-1] + 1)


def before_rgb8(project, position: int | None = None, box=None, token=None) -> np.ndarray:
    """`box` (t, b, l, r) crops before the stretch and the 8-bit conversion, so a
    133 MP mosaic never holds a full-frame stretched copy. The stretch is still
    derived from the WHOLE frame: the look must not depend on the framing."""
    check = token.check if token is not None else (lambda: None)
    img = before_image(project, position, token)
    check()
    data = img.data
    params = linked_stretch_params(data, _LINEAR_TARGET) if img.is_linear else None
    if box is not None:
        t, b, l, r = box
        data = data[t:b, l:r]
    del img
    check()
    if params is not None:
        data = apply_linked_stretch(data, params)
        check()
    return to_rgb8(data)
