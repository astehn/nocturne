from __future__ import annotations

from typing import Protocol

import numpy as np
from PIL import Image

from .image import AstroImage


class UpscaleEngine(Protocol):
    name: str

    def available(self) -> bool: ...
    def upscale(self, img: AstroImage, scale: int) -> AstroImage: ...
    def provenance(self) -> dict: ...


def _resample_channel_lanczos(chan: np.ndarray, scale: int) -> np.ndarray:
    """16-bit Lanczos resample of one float32 [0,1] channel."""
    h, w = chan.shape
    u16 = np.clip(chan, 0.0, 1.0)
    u16 = (u16 * 65535.0 + 0.5).astype(np.uint16)
    # Let Pillow infer mode "I;16" from the uint16 array. Passing mode="I;16"
    # explicitly triggers a DeprecationWarning in Pillow >= 12 ("'mode'
    # parameter for changing data types is deprecated"); omitting it avoids
    # the warning while still yielding true 16-bit Lanczos resampling.
    im = Image.fromarray(u16)
    im = im.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
    return np.asarray(im, dtype=np.float32) / 65535.0


class LanczosEngine:
    name = "Lanczos"

    def available(self) -> bool:
        return True

    def upscale(self, img: AstroImage, scale: int) -> AstroImage:
        data = np.ascontiguousarray(img.data, dtype=np.float32)
        if data.ndim == 2:
            up = _resample_channel_lanczos(data, scale)
        else:
            up = np.stack(
                [_resample_channel_lanczos(data[..., c], scale) for c in range(data.shape[2])],
                axis=2,
            )
        return AstroImage(
            np.clip(up, 0.0, 1.0).astype(np.float32),
            is_linear=img.is_linear,
            metadata=dict(img.metadata),
        )

    def provenance(self) -> dict:
        return {"engine": self.name, "kind": "deterministic-lanczos", "fabricates": False}
