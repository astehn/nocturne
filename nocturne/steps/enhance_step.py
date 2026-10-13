from __future__ import annotations

from ..core.enhance import ENHANCE_OPS, sharpen_nebulosity_layers, star_colour_layers
from ..core.image import AstroImage
from ..history.step import Step
from ..tools.base import run_cli
from .star_split import resolve_star_split, splitter_name

_LAYERED = {"Star Colour": star_colour_layers,
            "Sharpen Nebulosity": sharpen_nebulosity_layers}


class EnhanceTapStep(Step):
    """One Enhancements tap, replayable by a runner. The two split taps take the
    preferred splitter, as the in-app tap does (_enhance_with_star_split), not
    batch's always-free split, so a preset's tap matches a hand tap here."""
    name = "Enhancements"

    def __init__(self, splitter=None) -> None:
        self._splitter = splitter
        self._runner = run_cli

    def options(self): return []
    def default_option(self): return ""
    def display_name(self, option) -> str: return str(option)
    def recorded_option(self, option): return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        op = str(option)
        if op in _LAYERED:
            starless, stars = resolve_star_split(img, self._splitter, self._runner)
            self.last_engine = splitter_name(self._splitter)
            return _LAYERED[op](starless, stars)
        if op not in ENHANCE_OPS:
            raise ValueError(f"unknown enhancement {op!r}")
        self.last_engine = None
        return ENHANCE_OPS[op](img)
