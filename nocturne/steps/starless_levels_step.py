from __future__ import annotations

from ..core.enhance import starless_levels_layers
from ..core.image import AstroImage
from ..history.step import Step
from ..tools.base import run_cli
from .star_split import resolve_star_split, splitter_name


class StarlessLevelsStep(Step):
    name = "Starless Levels"

    def __init__(self, splitter=None) -> None:
        self._splitter = splitter
        self._runner = run_cli

    def options(self): return []
    def default_option(self): return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        black, white = (float(v) for v in option)
        starless, stars = resolve_star_split(img, self._splitter, self._runner)
        self.last_engine = splitter_name(self._splitter)
        return starless_levels_layers(starless, stars, black, white)
