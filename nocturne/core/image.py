from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def finite_or_zero(arr: np.ndarray) -> np.ndarray:
    """Non-finite samples replaced by 0.0 — the app's one definition of what a
    NaN/Inf pixel means: no data, i.e. black.

    Four surfaces need this and each had grown its own copy (or, in export's
    case, forgotten to): import normalisation, the display cast, the histogram
    and the export cast. Divergence between them is a WYSIWYG bug by
    construction — the canvas showed black where export wrote whatever the
    undefined float→uint cast happened to produce on that platform.

    Deliberately NOT enforced in `AstroImage.__post_init__`: that runs on every
    step and every copy, and silently rewriting data on construction would mask
    the arrival of NaN rather than expose it. The invariant is established once
    at the import boundary and re-asserted only where pixels leave for a screen
    or a file.
    """
    return np.where(np.isfinite(arr), arr, 0.0).astype(arr.dtype, copy=False)


@dataclass
class AstroImage:
    data: np.ndarray
    is_linear: bool = True
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        arr = np.asarray(self.data, dtype=np.float32)
        if arr.ndim not in (2, 3):
            raise ValueError(f"data must be 2D or 3D, got {arr.ndim}D")
        if arr.ndim == 3 and arr.shape[2] != 3:
            raise ValueError("3D data must have 3 channels (H, W, 3)")
        self.data = arr

    @property
    def is_color(self) -> bool:
        return self.data.ndim == 3

    def copy(self) -> "AstroImage":
        return AstroImage(self.data.copy(), self.is_linear, dict(self.metadata))
