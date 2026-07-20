from __future__ import annotations

from ..core.color import remove_green_fringe
from ..core.image import AstroImage
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro


class GreenFringeStep(Step):
    name = "Remove Green Fringe"

    def __init__(self, rcastro: RCAstro) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        starless, stars = self._rc.remove_stars(img, runner=self._runner)
        strength = float(option) if option not in (None, "") else 0.0
        return remove_green_fringe(starless, stars, strength)
