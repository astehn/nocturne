from __future__ import annotations

from ..core.image import AstroImage
from ..core.levels import apply_levels, resolve_levels
from ..history.step import Step


class LevelsStep(Step):
    name = "Levels"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        # Auto derives from the image in front of us, not from whatever image
        # the recipe's author had, in the version the option records ("auto"
        # alone is version 1 — see core.levels.parse_levels_option). Both
        # versions are deterministic, so a saved PROJECT, which replays this
        # step on the same pixels, still reproduces exactly.
        # Kept for the caller's log line: what Auto decided, and whether it
        # stopped at the clipping limit.
        self.last_resolved = r = resolve_levels(img, option)
        return self.apply_resolved(img, r)

    def apply_resolved(self, img: AstroImage, r) -> AstroImage:
        """The step with its numbers already resolved — MainWindow reuses
        Auto's cached search for the input the preview showed."""
        return apply_levels(img, r.black, r.gamma, r.white, r.offsets)
