from __future__ import annotations

from ..core.color import remove_green_fringe
from ..core.image import AstroImage
from ..history.step import Step


class GreenFringeStep(Step):
    name = "Remove Green Fringe"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        strength = float(option) if option not in (None, "") else 0.0
        return remove_green_fringe(img, strength)
