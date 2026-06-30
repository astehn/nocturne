from __future__ import annotations

from ..core.color import ColorSettings, apply_color
from ..core.image import AstroImage
from ..history.step import Step


class ColorStep(Step):
    name = "Color"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option: ColorSettings) -> AstroImage:
        return apply_color(img, option)
