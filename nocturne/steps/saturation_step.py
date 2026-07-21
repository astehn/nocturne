from __future__ import annotations

from ..core.image import AstroImage
from ..core.saturation import nebula_saturate, saturate
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro


def parse_saturation_option(option) -> tuple[float, float]:
    """Return (amount, nebula) from the step option: a 2-tuple/2-list
    (amount, nebula), a legacy bare float amount (nebula 0), or empty (native).
    A falsy amount (0/0.0/None/"") means "no change" (native 0.5), NOT greyscale —
    preserving the step's long-standing behaviour."""
    if isinstance(option, (tuple, list)):
        amount, nebula = option
    else:
        amount, nebula = option, 0.0
    return (float(amount) if amount else 0.5, float(nebula) if nebula else 0.0)


class SaturationStep(Step):
    name = "Saturation"

    def __init__(self, rcastro: RCAstro) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        amount, nebula = parse_saturation_option(option)
        if nebula > 0.0:
            starless, stars = self._rc.remove_stars(img, runner=self._runner)
            img = nebula_saturate(starless, stars, nebula)
        return saturate(img, amount)
