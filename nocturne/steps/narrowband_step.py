from __future__ import annotations

import numpy as np

from ..core.image import AstroImage
from ..core.narrowband import NarrowbandParams, render, screen
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro


def parse_narrowband_option(option) -> NarrowbandParams:
    """Accept a NarrowbandParams (live), a plain dict (recipe), or None (default)."""
    if isinstance(option, NarrowbandParams):
        return option
    if isinstance(option, dict):
        import dataclasses
        fields = {f.name for f in dataclasses.fields(NarrowbandParams)}
        return NarrowbandParams(**{k: v for k, v in option.items() if k in fields})
    return NarrowbandParams()


class NarrowbandStep(Step):
    name = "Narrowband"

    def __init__(self, rcastro: RCAstro | None) -> None:
        self._rc = rcastro                       # None -> whole-image (no StarX)
        self._runner = run_cli

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        if not img.is_color:
            raise ValueError("Narrowband needs a colour image")
        params = parse_narrowband_option(option)
        if self._rc is not None:
            starless, stars = self._rc.remove_stars(img, runner=self._runner)
        else:
            starless, stars = img, None
        nebula = render(starless, params)
        if stars is None:
            return nebula
        out = screen(nebula.data, np.clip(stars.data, 0.0, 1.0))
        return AstroImage(out, is_linear=False, metadata=dict(starless.metadata))
