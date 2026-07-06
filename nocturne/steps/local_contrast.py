from __future__ import annotations

from ..core.image import AstroImage
from ..core.local_contrast import enhance
from ..history.step import Step

_AMOUNT = {"light": 0.3, "medium": 0.6, "strong": 0.9}


class LocalContrastStep(Step):
    name = "Local Contrast"

    def options(self) -> list[str]:
        return ["light", "medium", "strong"]

    def default_option(self) -> str:
        return "medium"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        return enhance(img, _AMOUNT[option])
