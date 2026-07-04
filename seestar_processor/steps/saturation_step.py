from __future__ import annotations

from ..core.image import AstroImage
from ..core.saturation import saturate
from ..history.step import Step


class SaturationStep(Step):
    name = "Saturation"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        # 0.5 is native (no-op) under the re-centred saturation model; a falsy
        # option means "no change", NOT greyscale (which is 0.0).
        return saturate(img, float(option) if option else 0.5)
