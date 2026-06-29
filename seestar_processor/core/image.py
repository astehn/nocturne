from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


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
