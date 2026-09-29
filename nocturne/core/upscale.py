from __future__ import annotations

import os
from dataclasses import dataclass
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
_SCALE_CARDS = ("XPIXSZ", "YPIXSZ", "CD1_1", "CD1_2", "CD2_1", "CD2_2")

# The biggest output Upscale will make. MEASURED 2026-09-29 on centre crops of
# his M31 drizzle mosaic (stretched), free splitter, prepare + finish + three
# QImages, one fresh process per size, peak RSS (Apple M-series, 64 GB):
#   output MP   time     peak RSS      output MP   time     peak RSS
#      8         1.1 s    1.39 GB          50        6.2 s     8.03 GB
#     16         2.1 s    2.63 GB          80       10.0 s    12.94 GB
#     20         2.5 s    3.23 GB         120       15.0 s    19.43 GB
#     25         3.1 s    4.03 GB         150       18.6 s    24.34 GB
#     30         3.7 s    4.88 GB
#     33         4.2 s    5.34 GB
# Memory is the limit, not time: about 160 MB per output MP, four float32
# layers plus three QImages. Rule: largest size under 4 GB peak, rounded down
# to 10 -> 20 MP. StarNet2 at 20 MP: 7.5 s, 3.05 GB; at 33 MP: 12.0 s, 4.98 GB.
# The app also holds the project image and its copy, on top of these figures.
UPSCALE_MAX_MP = 20


def output_size(crop_w: int, crop_h: int, scale: int = 2) -> tuple[int, int]:
    return crop_w * scale, crop_h * scale


def megapixels(w: int, h: int) -> float:
    return w * h / 1_000_000


@dataclass
class UpscaleLayers:
    """The slow part, kept: split and both upscales run once per Upscale, so the
    star-tightening slider only re-runs `finish_upscale`."""
    starless_up: AstroImage
    stars_up: AstroImage
    plain_up: AstroImage          # the crop, plain Lanczos 2x — what resizing alone gives
    source_meta: dict
    crop: tuple | None
    scale: int
    engine_prov: dict


def prepare_upscale(img, crop, engine, *, scale=2, rc=None, runner=run_cli) -> UpscaleLayers:
    from ..steps.star_split import resolve_star_split

    data = img.data
    if crop is not None:
        top, bottom, left, right = crop
        data = data[top:bottom, left:right]
    src = AstroImage(np.ascontiguousarray(data, dtype=np.float32),
                     is_linear=img.is_linear, metadata=dict(img.metadata))
    starless, stars = resolve_star_split(src, rc, runner=runner)
    return UpscaleLayers(
        starless_up=engine.upscale(starless, scale),        # may fabricate later (GAN)
        stars_up=LanczosEngine().upscale(stars, scale),     # stars ALWAYS deterministic
        plain_up=LanczosEngine().upscale(src, scale),
        source_meta=dict(img.metadata),
        crop=crop, scale=scale, engine_prov=engine.provenance())


def finish_upscale(layers: UpscaleLayers, tighten: float) -> AstroImage:
    from .star_reduction import reduce_stars

    result = reduce_stars(layers.starless_up, layers.stars_up, tighten)
    meta = dict(layers.source_meta)
    scale = layers.scale
    # A 2x pixel covers half the sky: the optics must say so, as a drizzled
    # master's do (stacker._rescale_optics). Copied unchanged, the upscaled
    # copy's solve hint was twice too wide, and an export wrote it to disk
    # (review 2026-09-29).
    if isinstance(meta.get("pixel_size"), (int, float)):
        meta["pixel_size"] = meta["pixel_size"] / scale
    if meta.get("solve_cards"):
        meta["solve_cards"] = {
            k: (v / scale if k in _SCALE_CARDS and isinstance(v, (int, float)) else v)
            for k, v in meta["solve_cards"].items()}
    meta["upscale"] = {**layers.engine_prov, "scale": scale, "tighten": tighten,
                       "crop": list(layers.crop) if layers.crop else None}
    return AstroImage(result.data, is_linear=result.is_linear, metadata=meta)


def upscale_crop(img, crop, engine, *, scale=2, tighten=TIGHTEN_DEFAULT, rc=None, runner=run_cli):
    """Layered 2× upscale of a crop: split → upscale starless + stars → tighten
    stars + screen-recombine. Non-destructive; returns a new AstroImage. A
    degenerate split (no stars) reduces to a plain full-frame upscale."""
    return finish_upscale(prepare_upscale(img, crop, engine, scale=scale, rc=rc,
                                          runner=runner), tighten)


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
