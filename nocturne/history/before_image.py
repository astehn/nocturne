"""The before frame of the Share video: the opened image with only the recorded
geometry applied, so before and after frame the same picture."""
from __future__ import annotations

import numpy as np

from ..core.autostretch import linked_stretch
from ..core.crop import CropParams, apply_crop_params
from ..core.image import AstroImage
from ..core.share import to_rgb8
from ..ui.pipeline import GEOMETRY_NAMES  # pure module, no Qt

_LINEAR_TARGET = 0.205


def _bounds(option):
    """(t, b, l, r) from a live CropParams or a reloaded bundle's dict, else None."""
    b = option.bounds if isinstance(option, CropParams) else (
        option.get("bounds") if isinstance(option, dict) else None)
    return tuple(int(v) for v in b) if b is not None else None


def before_image(project) -> AstroImage:
    entries = project.entries()
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
        img = apply_crop_params(img, params)
    if replayed and tuple(img.data.shape[:2]) == tuple(project.shape_at(project.position)[:2]):
        return img
    return project.state_at(geo[-1] + 1)


def before_rgb8(project) -> np.ndarray:
    img = before_image(project)
    data = linked_stretch(img.data, _LINEAR_TARGET) if img.is_linear else img.data
    return to_rgb8(data)
