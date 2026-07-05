from __future__ import annotations

from ..core.image import AstroImage
from ..core.noise import reduce_noise
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro

_LEVELS = {"light": 0.4, "medium": 0.7, "strong": 0.9}   # denoise strengths


class NoiseSharpenStep(Step):
    """Post-stretch denoise (NoiseXTerminator; free reduce_noise fallback).
    Sharpening/deconvolution is the separate Deconvolution step."""

    name = "Noise Reduction"

    def __init__(self, rcastro: RCAstro | None = None) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["light", "medium", "strong"]

    def default_option(self) -> str:
        return "medium"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        dn = _LEVELS[option]
        if self._rc is not None:
            return self._rc.denoise(img, dn, runner=self._runner)
        return reduce_noise(img, dn)
