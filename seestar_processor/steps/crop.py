from __future__ import annotations

from ..core.crop import CropParams, apply_crop_params
from ..core.image import AstroImage
from ..history.step import Step


class CropStep(Step):
    name = "Crop"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        params = option if isinstance(option, CropParams) else CropParams()
        return apply_crop_params(img, params)
