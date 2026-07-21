from __future__ import annotations

from ..core.image import AstroImage
from ..core.noise import reduce_noise
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.graxpert import GraXpert
from ..tools.rcastro import RCAstro

_NXT_LEVELS = {"light": 0.75, "medium": 0.90, "strong": 0.95}  # RC-Astro NoiseXTerminator
_GX_LEVELS = {"light": 0.5, "medium": 0.7, "strong": 0.9}      # GraXpert AI denoise (calibrate)
_TV_LEVELS = {"light": 0.4, "medium": 0.7, "strong": 0.9}      # free TV fallback


def parse_noise_option(option) -> tuple[str | None, str]:
    """Return (engine, level). option is {"engine","level"} (engine in
    {"rcastro","graxpert"}) or a legacy bare level string (engine None)."""
    if isinstance(option, dict):
        return option.get("engine"), option.get("level", "medium")
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
