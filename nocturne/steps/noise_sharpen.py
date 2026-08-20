from __future__ import annotations

from ..core.image import AstroImage
from ..core.noise import reduce_noise
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.graxpert import GraXpert
from ..tools.rcastro import RCAstro

_NXT_LEVELS = {"light": 0.75, "medium": 0.90, "strong": 0.95}  # RC-Astro NoiseXTerminator

# CALIBRATED 2026-08-20 against a real M 45 master, after a user reported that
# GraXpert-only denoising "is not really that good". It carried a `# calibrate`
# comment from the day it was written and never had been, so the paid path was
# tuned against data and the free one by guess. Background noise / chroma
# (green-magenta) / median star radius, same frame throughout:
#
#     no denoise            lumN 0.0446   chroma 0.1037   starR 7.776
#     nxt   0.75  (light)   lumN 0.0217   chroma 0.0292   starR 7.800
#     nxt   0.90  (medium)  lumN 0.0195   chroma 0.0172   starR 7.803
#     gx    0.5   was light lumN 0.0311   chroma 0.0617   starR 7.772
#     gx    0.7   was medium lumN 0.0265  chroma 0.0450   starR 7.771
#     gx    0.9             lumN 0.0229   chroma 0.0290   starR 7.770
#     gx    1.0             lumN 0.0217   chroma 0.0220   starR 7.767
#
# Two things follow. GraXpert's old "medium" was barely better than the FREE TV
# fallback (0.0265 vs 0.0273 lumN, 0.0450 vs 0.0484 chroma) while taking 274 s
# against 2 s — 137x the wait for almost nothing. And GraXpert at MAXIMUM only
# reaches NoiseXTerminator's LIGHT setting (both 0.0217), so the ceiling here is
# real: no mapping makes the free engine match NXT's medium.
#
# Star radius is flat to 0.05% across every GraXpert strength, so pushing to 1.0
# costs no detail. Raising medium 0.7 -> 0.9 cuts luminance noise 14% and chroma
# noise 36% on the same image, for the same runtime.
_GX_LEVELS = {"light": 0.7, "medium": 0.9, "strong": 1.0}      # GraXpert AI denoise

_TV_LEVELS = {"light": 0.4, "medium": 0.7, "strong": 0.9}      # free TV fallback


def parse_noise_option(option) -> tuple[str | None, str]:
    """Return (engine, level). option is {"engine","level"} (engine in
    {"rcastro","graxpert"}) or a legacy bare level string (engine None)."""
    if isinstance(option, dict):
        lvl = option.get("level", "medium")
        return option.get("engine"), (lvl if lvl in _TV_LEVELS else "medium")
    return None, (option if option in _TV_LEVELS else "medium")


class NoiseSharpenStep(Step):
    """Post-stretch denoise. Engine = chosen (RC-Astro NoiseXTerminator or
    GraXpert AI); falls back to the other installed engine, then to free TV."""

    name = "Noise Reduction"

    def __init__(self, rcastro: RCAstro | None = None,
                 graxpert: GraXpert | None = None) -> None:
        self._rc = rcastro
        self._gx = graxpert
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["light", "medium", "strong"]

    def default_option(self) -> str:
        return "medium"

    def apply(self, img: AstroImage, option) -> AstroImage:
        engine, level = parse_noise_option(option)
        order = ["graxpert", "rcastro"] if engine == "graxpert" else ["rcastro", "graxpert"]
        for e in order:
            if e == "rcastro" and self._rc is not None:
                return self._rc.denoise(img, _NXT_LEVELS[level], runner=self._runner)
            if e == "graxpert" and self._gx is not None:
                return self._gx.denoise(img, _GX_LEVELS[level], runner=self._runner)
        return reduce_noise(img, _TV_LEVELS[level])
