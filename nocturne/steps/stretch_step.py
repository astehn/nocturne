from __future__ import annotations

from ..core.image import AstroImage
from ..core.stretch import apply_stretch
from ..history.step import Step


# The panel's default, so pressing Apply without touching anything produces what
# the slider already showed. This lived here as a separate 0.5 while the panel
# said 0.43 and then 0.30 — two numbers for one fact, which is how they drift.
_DEFAULT = 0.30


def parse_stretch_option(option) -> float:
    """`{"amount": x}`, or a legacy bare float/string.

    Same shape as `parse_noise_option` (steps/noise_sharpen.py), whose option is
    already `{"engine","level"}` or a legacy bare string — an established
    pattern here rather than a new one.

    The dict exists so the visual stretch picker can add `{"linked": False}`
    later without changing the stored format a second time. See
    docs/superpowers/specs/2026-09-14-visual-stretch-picker-design.md.
    """
    if isinstance(option, dict):
        option = option.get("amount")
    if option in (None, ""):
        return _DEFAULT
    try:
        return float(option)
    except (TypeError, ValueError):
        return _DEFAULT


class StretchStep(Step):
    name = "Stretch"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        return apply_stretch(img, parse_stretch_option(option))
