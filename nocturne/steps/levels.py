from __future__ import annotations

from ..core.image import AstroImage
from ..core.levels import apply_levels
from ..history.step import Step


class LevelsStep(Step):
    name = "Levels"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        black, gamma, white = option if option else (0.0, 1.0, 1.0)
        return apply_levels(img, black, gamma, white)
