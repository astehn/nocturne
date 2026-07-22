from __future__ import annotations

from ..core.image import AstroImage
from ..core.saturation import nebula_saturate, saturate
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro


def parse_saturation_option(option) -> tuple[float, float]:
    """Return (amount, nebula) from the step option: a 2-tuple/2-list
    (amount, nebula), a legacy bare float amount (nebula 0), or an UNSET option
    (None / "") which means native (0.5, no change). An EXPLICIT amount of 0.0 is
    greyscale (the slider's left endpoint) — so the live commit and a recipe
    replay of the same option agree, and the slider is continuous."""
    if option is None or option == "":
        return (0.5, 0.0)
    if isinstance(option, (tuple, list)):
        amount, nebula = option
        return (float(amount), float(nebula))
    return (float(option), 0.0)


class SaturationStep(Step):
    name = "Saturation"

    def __init__(self, rcastro: RCAstro | None = None) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        amount, nebula = parse_saturation_option(option)
        if nebula > 0.0:
            from .star_split import resolve_star_split
            starless, stars = resolve_star_split(img, self._rc, runner=self._runner)
            img = nebula_saturate(starless, stars, nebula)
        return saturate(img, amount)
