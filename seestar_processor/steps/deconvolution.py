from __future__ import annotations

from ..core.deconvolution import sharpen
from ..core.image import AstroImage
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro

# option -> (bxt sharpen_stars, bxt sharpen_nonstellar, fallback sharpen strength)
_DECON = {
    "Small": (0.0, 0.50, 0.3),
    "Medium": (0.1, 0.75, 0.5),
    "Large": (0.2, 0.90, 0.8),
}


class DeconvolutionStep(Step):
    name = "Deconvolution"

    def __init__(self, rcastro: RCAstro | None = None) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["Small", "Medium", "Large"]

    def default_option(self) -> str:
        return "Medium"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        ss, sn, fallback = _DECON[option]
        if self._rc is not None:
            return self._rc.deconvolve(
                img, sharpen_stars=ss, sharpen_nonstellar=sn, runner=self._runner
            )
        return sharpen(img, fallback)
