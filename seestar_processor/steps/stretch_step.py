from __future__ import annotations

from ..core.image import AstroImage
from ..core.stretch import apply_stretch
from ..history.step import Step


class StretchStep(Step):
    name = "Stretch"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        amount = float(option) if option not in (None, "") else 0.5
        return apply_stretch(img, amount)
