from __future__ import annotations

from ..core.color import remove_green_fringe, remove_green_fringe_masked
from ..core.image import AstroImage
from ..core.starless import star_mask
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro

# Green fringe lives in the halo AROUND stars, so the free-path mask is widened
# past the star core to cover it (only used by the no-RC-Astro masked de-green).
FRINGE_MASK_SCALE = 2.5


class GreenFringeStep(Step):
    name = "Remove Green Fringe"

    def __init__(self, rcastro: RCAstro | None = None) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        strength = float(option) if option not in (None, "") else 0.0
        if self._rc is not None:                              # StarX: clean stars layer
            starless, stars = self._rc.remove_stars(img, runner=self._runner)
            return remove_green_fringe(starless, stars, strength)
        # Free path: the split can't isolate a broad chromatic halo, so de-green
        # the image in place inside a widened star-neighbourhood mask instead.
        return remove_green_fringe_masked(img, star_mask(img, FRINGE_MASK_SCALE), strength)
