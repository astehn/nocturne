from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import Image

from .image import AstroImage
from .tasks import current


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

# The biggest output Upscale will make follows THIS computer's memory, not one
# number for every machine: a fixed 20 MP stopped his own full frame (33 MP out)
# on a 64 GB Mac, and a fixed 35 MP would push an 8 GB laptop — common among
# Seestar owners — deep into swap (his call, 2026-09-29).
#
# MEASURED 2026-09-29, centre crops of his stretched M31 drizzle mosaic, free
# splitter, prepare + finish + the dialog's three QImages, one fresh process per
# size, peak RSS (Apple M-series):
#   output MP     8      20      33      50      100
#   peak GB     1.33    3.09    5.07    7.75    15.41
#   seconds      0.9     2.1     3.5     5.2     10.4
# About 155 MB per output megapixel, steady from 8 to 100 MP. The peak is the
# transient float32 copies inside the split, Lanczos and reduce_stars, not the
# kept layers (float16 layers were tried the same day and bought nothing).
MB_PER_OUTPUT_MP = 160          # 155 measured, rounded up for margin
RAM_SHARE = 0.4                 # the rest is macOS/Linux, Nocturne's own image, other apps
MAX_OUTPUT_MP = 100             # even on a big machine: ~10 s and ~15 GB there
FALLBACK_MAX_MP = 20            # memory unreadable: assume a small machine


def physical_memory() -> int | None:
    """Installed RAM in bytes, or None where the OS won't say."""
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        return None


def upscale_limit_mp(ram_bytes: int | None = None) -> int:
    """The largest output, in megapixels, this computer should be asked for."""
    ram = physical_memory() if ram_bytes is None else ram_bytes
    if not ram:
        return FALLBACK_MAX_MP
    return int(min(MAX_OUTPUT_MP, RAM_SHARE * ram / (MB_PER_OUTPUT_MP * 1e6)))


def memory_gb(ram_bytes: int | None = None) -> int | None:
    """Installed RAM as the whole number of GB a person knows their machine by."""
    ram = physical_memory() if ram_bytes is None else ram_bytes
    return round(ram / 2**30) if ram else None


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
    # The free splitter and Lanczos never look at the token, so Cancel would
    # otherwise only land when the whole run had finished (review 2026-09-29).
    _check_cancel()
    starless_up = engine.upscale(starless, scale)          # may fabricate later (GAN)
    _check_cancel()
    stars_up = LanczosEngine().upscale(stars, scale)       # stars ALWAYS deterministic
    return UpscaleLayers(
        starless_up=starless_up, stars_up=stars_up,
        source_meta=dict(img.metadata),
        crop=crop, scale=scale, engine_prov=engine.provenance())


def _check_cancel() -> None:
    tok = current()
    if tok is not None:
        tok.check()


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
    if up.get("tighten") is not None:
        lines.append(f"Star tightening: {up['tighten']}")
    if up.get("fabricates"):
        lines.append("Contains AI-synthesized detail — NOT for measurement or source discovery.")
    else:
        lines.append(f"{scale}× presentation derivative — enlarged, no synthesized detail.")
    return "\n".join(lines)
