from __future__ import annotations

from ..core.image import AstroImage
from ..core.local_contrast import enhance
from ..history.step import Step

_AMOUNT = {"light": 0.3, "medium": 0.6, "strong": 0.9}


class LocalContrastStep(Step):
    name = "Local Contrast"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        if isinstance(option, str) and option in _AMOUNT:
            amount = _AMOUNT[option]           # legacy recipe (light/medium/strong)
        else:
            amount = float(option) if option not in (None, "") else 0.0
        return enhance(img, amount)
