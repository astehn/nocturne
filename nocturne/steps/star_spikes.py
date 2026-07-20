from __future__ import annotations

from ..core.image import AstroImage
from ..core.star_spikes import add_spikes, detect_stars
from ..history.step import Step


class StarSpikesStep(Step):
    name = "Star Spikes"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        if not option:
            return AstroImage(img.data.copy(),
                              is_linear=img.is_linear, metadata=dict(img.metadata))
        length, count, angle = option
        return add_spikes(img, detect_stars(img.data), length, count, angle)
