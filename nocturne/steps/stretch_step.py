from __future__ import annotations

from ..core.image import AstroImage
from ..core.stretch import apply_stretch
from ..history.step import Step


# DERIVED from the display target, not copied beside it. It lived here as a
# separate 0.5 while the panel said 0.43 and then 0.30 — two numbers for one
# fact, which is how they drift, and on 2026-09-14 they did: the default moved
# and the linear preview's target did not follow, so arriving at Stretch
# darkened the canvas 18% before the user touched anything.
from ..core.autostretch import DEFAULT_TARGET_BG
from ..core.stretch import target_to_amount

_DEFAULT = target_to_amount(DEFAULT_TARGET_BG)


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


def parse_stretch_linked(option) -> bool:
    """A SIBLING of `parse_stretch_option` rather than a change to its return
    type, which would break its three callers.

    Defaults True in every shape: an option written before 2026-09-14 predates
    the choice, and a linked stretch is what it produced.
    """
    if isinstance(option, dict):
        return bool(option.get("linked", True))
    return True


def parse_stretch_version(option) -> int:
    """The linked stretch's version an option was made with. Absent means 1:
    every option written before 2026-10-11 predates version 2, and must replay
    as what it produced. See autostretch.STRETCH_VERSION."""
    from ..core.autostretch import STRETCH_V1
    if isinstance(option, dict):
        try:
            return int(option.get("version", STRETCH_V1))
        except (TypeError, ValueError):
            return STRETCH_V1
    return STRETCH_V1


def new_stretch_option(amount: float, linked: bool = True) -> dict:
    """The option for a stretch made NOW: it records the current version, so a
    later change of version (or of the switch) cannot alter it on replay.
    Every place that creates a stretch goes through here."""
    from ..core.autostretch import STRETCH_VERSION
    return {"amount": float(amount), "linked": bool(linked),
            "version": STRETCH_VERSION}


class StretchStep(Step):
    name = "Stretch"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        return apply_stretch(img, parse_stretch_option(option),
                             linked=parse_stretch_linked(option),
                             version=parse_stretch_version(option))
