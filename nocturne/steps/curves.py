from __future__ import annotations

from ..core.curves import apply_curve
from ..core.image import AstroImage
from ..history.step import Step

_IDENTITY = [(0.0, 0.0), (1.0, 1.0)]


class CurvesStep(Step):
    name = "Curves"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        points = option if option else _IDENTITY
        return apply_curve(img, points)
