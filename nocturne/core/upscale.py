from __future__ import annotations

import os
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


from ..tools.base import run_cli

TIGHTEN_DEFAULT = 0.35


def upscale_crop(img, crop, engine, *, scale=2, tighten=TIGHTEN_DEFAULT, rc=None, runner=run_cli):
    """Layered 2× upscale of a crop: split → upscale starless + stars → tighten
    stars + screen-recombine. Non-destructive; returns a new AstroImage. A
    degenerate split (no stars) reduces to a plain full-frame upscale."""
    from ..steps.star_split import resolve_star_split
    from .star_reduction import reduce_stars

    data = img.data
    if crop is not None:
        top, bottom, left, right = crop
        data = data[top:bottom, left:right]
    src = AstroImage(np.ascontiguousarray(data, dtype=np.float32),
                     is_linear=img.is_linear, metadata=dict(img.metadata))

    starless, stars = resolve_star_split(src, rc, runner=runner)
    starless_up = engine.upscale(starless, scale)      # chosen engine (may fabricate later, e.g. GAN)
    stars_up = LanczosEngine().upscale(stars, scale)   # stars ALWAYS deterministic — no engine ever fabricates a star
    result = reduce_stars(starless_up, stars_up, tighten)

    meta = dict(result.metadata)
    meta["upscale"] = {**engine.provenance(), "scale": scale, "tighten": tighten,
                       "crop": list(crop) if crop else None}
    return AstroImage(result.data, is_linear=result.is_linear, metadata=meta)


def upscale_filename(source_label, scale: int) -> str:
    stem = os.path.splitext(source_label or "upscale")[0] or "upscale"
    return f"{stem}_{scale}x.jpg"


def upscale_provenance_text(metadata: dict) -> str:
    up = metadata.get("upscale") or {}
    engine = up.get("engine", "?")
    scale = up.get("scale", "?")
    lines = [
        f"Upscale derivative — {scale}× ({engine})",
        f"Source: {metadata.get('source_label', 'unknown')}",
    ]
    if metadata.get("target"):
        lines.append(f"Target: {metadata['target']}")
    if up.get("crop"):
        lines.append(f"Crop (t,b,l,r): {up['crop']}")
    if up.get("fabricates"):
        lines.append("Contains AI-synthesized detail — NOT for measurement or source discovery.")
    else:
        lines.append(f"{scale}× presentation derivative — enlarged, no synthesized detail.")
    return "\n".join(lines)
