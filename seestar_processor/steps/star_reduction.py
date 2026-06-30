from __future__ import annotations

from ..core.image import AstroImage
from ..core.star_reduction import reduce_stars
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro

_AMOUNT = {"light": 0.3, "medium": 0.6, "strong": 0.9}


class StarReductionStep(Step):
    name = "Star Reduction"

    def __init__(self, rcastro: RCAstro) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["light", "medium", "strong"]

    def default_option(self) -> str:
        return "medium"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        starless, stars = self._rc.remove_stars(img, runner=self._runner)
        return reduce_stars(starless, stars, _AMOUNT[option])
