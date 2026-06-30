from __future__ import annotations

from ..core.final_fixes import FinalFixesSettings, apply_final_fixes
from ..core.image import AstroImage
from ..history.step import Step


class FinalFixesStep(Step):
    name = "Final Fixes"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option: FinalFixesSettings) -> AstroImage:
        return apply_final_fixes(img, option)
