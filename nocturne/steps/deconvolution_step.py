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
        # NOT a star split — this step has no splitter at all. Recorded because
        # a fast Deconvolution is exactly what Andreas read as proof that the
        # SEPARATION had fallen back (2026-09-22). The free path is an unsharp
        # mask and finishes in milliseconds; that is correct and now says so.
        # "BlurX", not "StarX": RC-Astro is three tools and naming the wrong
        # one in a log line is worse than naming none.
        self.last_engine = "BlurX" if self._rc is not None else "free"
        if self._rc is not None:
            return self._rc.deconvolve(
                img, sharpen_stars=ss, sharpen_nonstellar=sn, runner=self._runner)
        return sharpen(img, sn)
