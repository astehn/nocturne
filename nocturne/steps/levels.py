from __future__ import annotations

from ..core.image import AstroImage
from ..core.levels import AUTO, apply_levels, auto_levels
from ..history.step import Step


class LevelsStep(Step):
    name = "Levels"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        if option == AUTO:
            # Derive from the image in front of us, not from whatever image the
            # recipe's author had. `auto_levels` is deterministic — median and
            # MAD, no randomness — so a saved PROJECT, which replays this step
            # on the same pixels, still reproduces exactly.
            black, gamma, white = auto_levels(img.data)
        else:
            black, gamma, white = option if option else (0.0, 1.0, 1.0)
        return apply_levels(img, black, gamma, white)
