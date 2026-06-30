from __future__ import annotations

from ..core.image import AstroImage
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.graxpert import GraXpert

_STRENGTH = {"Small": 0.2, "Medium": 0.5, "Large": 0.8}


class BackgroundStep(Step):
    name = "Background"

    def __init__(self, graxpert: GraXpert) -> None:
        self._gx = graxpert
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["Small", "Medium", "Large"]

    def default_option(self) -> str:
        return "Medium"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        return self._gx.background_extraction(
            img, _STRENGTH[option], runner=self._runner
        )
