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

    def apply(self, img: AstroImage, option) -> AstroImage:
        amount = float(option) if option not in (None, "") else 0.0
        return recover_core(img, amount)
