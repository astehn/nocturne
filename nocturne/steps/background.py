from __future__ import annotations

from ..core.image import AstroImage
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.graxpert import GraXpert

_STRENGTH = {"light": 0.3, "strong": 0.7}


class BackgroundStep(Step):
    name = "Background"

    def __init__(self, graxpert: GraXpert) -> None:
        self._gx = graxpert
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["off", "light", "strong"]

    def default_option(self) -> str:
        return "light"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        if option == "off":
            return img.copy()
        return self._gx.background_extraction(
            img, _STRENGTH[option], runner=self._runner
        )
