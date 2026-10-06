from __future__ import annotations

from ..core.hdr import recover_core
from ..core.image import AstroImage
from ..history.step import Step


class RecoverCoreStep(Step):
    name = "Recover Core"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    @staticmethod
    def amount(option) -> float:
        """The option as the effect reads it — one parse, shared with the
        window's Apply, which reuses the preview's prepared blur."""
        return float(option) if option not in (None, "") else 0.0

    def apply(self, img: AstroImage, option) -> AstroImage:
        return recover_core(img, self.amount(option))
