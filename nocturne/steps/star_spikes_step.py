from __future__ import annotations

from ..core.image import AstroImage
from ..core.star_spikes import add_spikes, detect_stars
from ..history.step import Step

_KEYS = ("length", "count", "angle", "intensity", "variation", "colour")


class StarSpikesStep(Step):
    """Star Spikes from its six recorded sliders. Stars are found on the picture
    in front of it, as the dialog does on open; `count` takes the brightest N
    that exist, so a preset from a starrier frame still draws."""
    name = "Star Spikes"

    def options(self): return []
    def default_option(self): return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        if not isinstance(option, dict) or any(k not in option for k in _KEYS):
            raise ValueError("Star Spikes was saved without its settings")
        o = option
        return add_spikes(img, detect_stars(img.data), float(o["length"]), int(o["count"]),
                          float(o["angle"]), float(o["intensity"]),
                          float(o["variation"]), float(o["colour"]))
