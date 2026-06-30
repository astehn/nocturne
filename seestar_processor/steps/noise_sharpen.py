from __future__ import annotations

from ..core.deconvolution import sharpen
from ..core.image import AstroImage
from ..core.noise import reduce_noise
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro

# option -> (denoise strength, sharpen amount)
_LEVELS = {"light": (0.4, 0.3), "medium": (0.7, 0.5), "strong": (0.9, 0.7)}


class NoiseSharpenStep(Step):
    """Post-stretch cosmetic clean-up: denoise then sharpen, in one step."""

    name = "Noise & Sharpen"

    def __init__(self, rcastro: RCAstro | None = None) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["light", "medium", "strong"]

    def default_option(self) -> str:
        return "medium"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        dn, sh = _LEVELS[option]
        if self._rc is not None:
            denoised = self._rc.denoise(img, dn, runner=self._runner)
            return self._rc.deconvolve(
                denoised, sharpen_stars=0.0, sharpen_nonstellar=sh, runner=self._runner
            )
        return sharpen(reduce_noise(img, dn), sh)
