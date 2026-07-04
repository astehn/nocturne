from __future__ import annotations

from ..core.color import remove_green
from ..core.image import AstroImage
from ..history.step import Step


class RemoveGreenStep(Step):
    name = "Remove Green"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option=None) -> AstroImage:
        # SCNR green removal; option is unused (no parameters).
        return remove_green(img)
