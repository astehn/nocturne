"""Replay a Colour Balance adjustment from a recipe.

The dialog was the only thing that could apply this: the live app commits its
result as a precomputed image, so nothing ever needed a Step. But the stage IS
registered as recipe-capturable and fully (de)serialised — the serialiser even
carries a comment defending how it stores the band — so `preflight` reported
"this step will run as saved" and `apply_recipe` then raised
`ValueError: color_balance`, which `run_batch` turned into a failure for every
file in the folder. This is the missing half.

The arithmetic is deliberately NOT re-derived here. It calls the same
`apply_balance` / `range_mask` / `screen` the dialog calls, in the same order, so
a batch cannot drift from what the user saw when they saved the recipe.
"""
from __future__ import annotations

import numpy as np

from ..core.color_balance import TONES, Balance, apply_balance
from ..core.image import AstroImage
from ..core.mask import range_mask
from ..core.narrowband import screen
from ..history.step import Step
from .star_split import resolve_star_split, splitter_name
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro


def parse_color_balance_option(option) -> dict:
    """Accept a plain dict (recipe or live) or None (a neutral no-op)."""
    return dict(option) if isinstance(option, dict) else {}


def _triple(o: dict, key: str) -> tuple:
    v = o.get(key) or (0.0, 0.0, 0.0)
    return (float(v[0]), float(v[1]), float(v[2]))


class ColorBalanceStep(Step):
    name = "Colour Balance"

    def __init__(self, rcastro: RCAstro | None) -> None:
        self._rc = rcastro                       # None -> whole image, no split
        self._runner = run_cli

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        o = parse_color_balance_option(option)
        balance = Balance(
            **{t: _triple(o, t) for t in TONES},
            preserve_lum=bool(o.get("preserve_lum", True)),
            strength=float(o.get("strength", 1.0)),
        )
        # Stars are held aside and screened back untouched, exactly as the dialog
        # does it — the whole point of the tool is that a colour shift aimed at
        # nebulosity does not tint the stars. Through the SHARED resolver, so
        # that without RC-Astro this falls back to the free SEP split like the
        # other four star steps, rather than skipping the split and tinting the
        # stars on any machine that has not configured StarX.
        self.last_engine = splitter_name(self._rc)
        starless, stars = resolve_star_split(img, self._rc, runner=self._runner)

        data = starless.data
        lum = data.mean(axis=2) if data.ndim == 3 else data
        m = range_mask(lum, float(o.get("lo", 0.0)), float(o.get("hi", 1.0)),
                       feather=float(o.get("feather", 0.08)))
        if bool(o.get("invert", False)):
            m = (1.0 - m).astype(np.float32)

        adjusted = apply_balance(starless, balance, m)
        if stars is None:
            return adjusted
        out = screen(adjusted.data, np.clip(stars.data, 0.0, 1.0))
        return AstroImage(out, is_linear=starless.is_linear,
                          metadata=dict(starless.metadata))
