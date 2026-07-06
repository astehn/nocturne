from __future__ import annotations

from ..core.deconvolution import sharpen
from ..core.image import AstroImage
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro

# option -> (sharpen_stars, sharpen_nonstellar)
_LEVELS = {"light": (0.3, 0.3), "medium": (0.5, 0.5), "strong": (0.7, 0.7)}


class DeconvolutionStep(Step):
    """Linear deconvolution (BlurXTerminator): tightens stars and recovers fine
    detail, run before the stretch. Free unsharp-mask fallback without RC-Astro."""

    name = "Deconvolution"

    def __init__(self, rcastro: RCAstro | None = None) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["light", "medium", "strong"]

    def default_option(self) -> str:
        return "medium"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        ss, sn = _LEVELS[option]
        if self._rc is not None:
            return self._rc.deconvolve(
                img, sharpen_stars=ss, sharpen_nonstellar=sn, runner=self._runner)
        return sharpen(img, sn)
