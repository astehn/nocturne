from __future__ import annotations

from ..core.crop import auto_crop
from ..core.image import AstroImage
from ..history.step import Step


class CropAutoStep(Step):
    name = "Crop"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        margin = float(option) if option else 0.0
        return auto_crop(img, margin)
