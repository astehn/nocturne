from __future__ import annotations

from ..core.crop import CropSettings, apply_crop
from ..core.image import AstroImage
from ..history.step import Step


class CropStep(Step):
    name = "Crop"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option: CropSettings) -> AstroImage:
        return apply_crop(img, option)
