from __future__ import annotations

from ..core.image import AstroImage
from ..core.stretch import STRETCH_PRESETS, apply_stretch
from ..history.step import Step


class StretchStep(Step):
    name = "Stretch"

    def options(self) -> list[str]:
        return list(STRETCH_PRESETS)

    def default_option(self) -> str:
        return "Medium"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        return apply_stretch(img, option)
