import numpy as np
import pytest
from nocturne.core.image import AstroImage
from nocturne.settings import Settings
from nocturne.steps.factory import make_step


def _stretched(h=64, w=96, seed=1):
    rng = np.random.default_rng(seed)
    data = (rng.random((h, w, 3)) * 0.2 + 0.1).astype(np.float32)
    for y, x in ((10, 20), (40, 70), (30, 50)):            # a few bright stars
        data[y-1:y+2, x-1:x+2] = [0.95, 0.9, 0.85]
    return AstroImage(data, is_linear=False, metadata={})


@pytest.mark.parametrize("op", ["Vibrance", "Boost Gold", "Soft Glow", "Darken Sky"])
def test_a_plain_tap_equals_the_in_app_tap(op):
    from nocturne.core.enhance import ENHANCE_OPS
    img = _stretched()
    step = make_step("enhance", Settings())
    out = step.apply(img, op)
    np.testing.assert_array_equal(out.data, ENHANCE_OPS[op](img).data)
    assert step.display_name(op) == op
    assert step.recorded_option(op) == ""          # what _enhance records by hand


@pytest.mark.parametrize("op,fn", [("Star Colour", "star_colour_layers"),
                                   ("Sharpen Nebulosity", "sharpen_nebulosity_layers")])
def test_a_split_tap_uses_the_split_layers(op, fn):
    import nocturne.core.enhance as enh
    from nocturne.core.starless import split_stars
    img = _stretched()
    sl, st = split_stars(img)                      # Settings() has no splitter: the free path
    want = getattr(enh, fn)(sl, st)
    got = make_step("enhance", Settings()).apply(img, op)
    np.testing.assert_array_equal(got.data, want.data)


def test_an_unknown_tap_raises_by_name():
    with pytest.raises(ValueError, match="Nonsense"):
        make_step("enhance", Settings()).apply(_stretched(), "Nonsense")


def _spikes_opt(**kw):
    o = {"length": 0.35, "count": 3, "angle": 45.0, "intensity": 0.8,
         "variation": 0.0, "colour": 0.5}
    o.update(kw)
    return o


def test_star_spikes_replays_exactly_what_the_dialog_draws():
    from nocturne.ui.star_spikes_dialog import _render    # the dialog's own render
    from nocturne.core.star_spikes import detect_stars
    # Big enough that the arms are long enough for the angle to move a pixel:
    # at 64x96 they are ~2 px and a +1 degree mutation passed. Variation is
    # non-zero because 0.0 is add_spikes' default, so dropping it would pass.
    img = _stretched(256, 384)
    o = _spikes_opt(variation=0.2)
    params = (o["length"], o["count"], o["angle"], o["intensity"], o["variation"], o["colour"])
    want, _rgb = _render(img, detect_stars(img.data), params)
    got = make_step("star_spikes", Settings()).apply(img, o)
    np.testing.assert_array_equal(got.data, want.data)


def test_star_spikes_count_beyond_the_stars_found_draws_what_there_is():
    img = _stretched()
    out = make_step("star_spikes", Settings()).apply(img, _spikes_opt(count=500))
    assert out.data.shape == img.data.shape
    assert not np.array_equal(out.data, np.clip(img.data, 0, 1))   # it drew something


def test_star_spikes_without_settings_refuses():
    with pytest.raises(ValueError, match="without its settings"):
        make_step("star_spikes", Settings()).apply(_stretched(), "")


def test_starless_levels_replays_the_dialog_compose():
    from nocturne.core.enhance import starless_levels_layers
    from nocturne.core.starless import split_stars
    img = _stretched()
    sl, st = split_stars(img)
    want = starless_levels_layers(sl, st, 0.12, 0.8)
    step = make_step("starless_levels", Settings())
    got = step.apply(img, (0.12, 0.8))
    np.testing.assert_array_equal(got.data, want.data)
    assert step.last_engine == "free"


def test_every_other_step_names_itself():
    step = make_step("stretch", Settings())
    assert step.display_name({"amount": 0.3}) == "Stretch"
