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

    @staticmethod
    def amount(option) -> float:
        """The option as the effect reads it — one parse, shared with the
        window's Apply, which reuses the preview's prepared CLAHE."""
        if isinstance(option, str) and option in _AMOUNT:
            return _AMOUNT[option]             # legacy recipe (light/medium/strong)
        return float(option) if option not in (None, "") else 0.0

    def apply(self, img: AstroImage, option) -> AstroImage:
        return enhance(img, self.amount(option))
