"""Colour Balance in a recipe.

It was registered as recipe-capturable and fully (de)serialised — the serialiser
even carries a comment defending how it stores the band — but `make_step` had no
case for it. So `preflight` reported

    StepPlan(step='Colour Balance', outcome='run', ...)

i.e. "this step will run as saved", and `apply_recipe` then raised
`ValueError: color_balance`, which `run_batch`'s per-file `except Exception`
turned into a failure for EVERY file in the folder, with a raw stage id as the
message the user sees.
"""
import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.recipe import Recipe, deserialize_option, preflight, serialize_option
from nocturne.settings import Settings
from nocturne.steps.factory import make_step


def _img(h=48, w=48):
    rng = np.random.default_rng(0)
    data = np.clip(rng.normal(0.35, 0.1, (h, w, 3)), 0, 1).astype(np.float32)
    data[10:20, 10:20] = (0.7, 0.3, 0.3)        # a bright, red-dominant patch
    return AstroImage(data, is_linear=False, metadata={})


def _opts(**over):
    o = {"shadows": [0.0, 0.0, 0.0], "midtones": [0.2, 0.0, -0.2],
         "highlights": [0.0, 0.0, 0.0], "preserve_lum": True, "strength": 1.0,
         "lo": 0.0, "hi": 1.0, "feather": 0.08, "invert": False}
    o.update(over)
    return o


def test_make_step_can_build_colour_balance():
    """The missing case. Without it a saved recipe kills a whole batch."""
    step = make_step("color_balance", Settings())
    assert step is not None


def test_preflight_and_replay_agree():
    """Preflight promised 'run'; replay must actually run."""
    r = Recipe(steps=[{"stage": "color_balance",
                       "option": serialize_option("color_balance", _opts())}])
    plans = preflight(r, Settings())
    # "run" with StarX configured, "substitute" without it — the receipt names
    # the free SEP split as the fallback, which is exactly the warning a batch
    # user wants. What must never happen again is "fail", or a promise to run
    # that `apply_recipe` then breaks.
    assert plans[0].outcome in ("run", "substitute"), plans[0]
    step = make_step("color_balance", Settings())
    out = step.apply(_img(), deserialize_option("color_balance", r.steps[0]["option"]))
    assert out.data.shape == (48, 48, 3)
    assert np.isfinite(out.data).all()


def test_replay_actually_shifts_colour():
    """A step that returns its input unchanged would pass the two tests above."""
    img = _img()
    step = make_step("color_balance", Settings())
    out = step.apply(img, deserialize_option(
        "color_balance", serialize_option("color_balance", _opts())))
    before = img.data.mean(axis=(0, 1))
    after = out.data.mean(axis=(0, 1))
    assert not np.allclose(before, after, atol=1e-4), "replay did nothing"
    # midtones pushed red up and blue down, so that is the direction expected
    assert (after[0] - before[0]) > 0, "red should rise"
    assert (after[2] - before[2]) < 0, "blue should fall"


def test_a_zero_balance_is_a_no_op():
    """The identity case must be exact, or a recipe carrying a neutral Colour
    Balance would quietly alter every frame it touched."""
    img = _img()
    step = make_step("color_balance", Settings())
    neutral = _opts(midtones=[0.0, 0.0, 0.0])
    out = step.apply(img, deserialize_option(
        "color_balance", serialize_option("color_balance", neutral)))
    assert np.allclose(out.data, img.data, atol=1e-6)
