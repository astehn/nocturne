from __future__ import annotations

from ..core.curves import apply_curves
from ..core.image import AstroImage
from ..history.step import Step


class CurvesStep(Step):
    name = "Curves"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        """`option` is either a MATRIX of curves keyed "channel/target", or a
        bare list of points from before 2026-09-05. `apply_curves` accepts both
        — a bare list means the RGB curve over all colours, which is what it
        has always meant — so old projects and recipes keep reproducing."""
        return apply_curves(img, option)
