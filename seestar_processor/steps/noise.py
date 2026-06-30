from __future__ import annotations

from ..core.image import AstroImage
from ..core.noise import reduce_noise
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro

# option -> (nxt denoise strength, fallback TV strength)
_NOISE = {"Small": (0.5, 0.3), "Medium": (0.8, 0.5), "Large": (0.95, 0.8)}


class NoiseStep(Step):
    name = "Noise"

    def __init__(self, rcastro: RCAstro | None = None) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["Small", "Medium", "Large"]

    def default_option(self) -> str:
        return "Medium"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        nxt_strength, fallback = _NOISE[option]
        if self._rc is not None:
            return self._rc.denoise(img, nxt_strength, runner=self._runner)
        return reduce_noise(img, fallback)
