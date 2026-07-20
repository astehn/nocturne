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
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        starless, stars = self._rc.remove_stars(img, runner=self._runner)
        if isinstance(option, str) and option in _AMOUNT:
            amount = _AMOUNT[option]           # legacy recipe (light/medium/strong)
        else:
            amount = float(option) if option not in (None, "") else 0.0
        return reduce_stars(starless, stars, amount)
