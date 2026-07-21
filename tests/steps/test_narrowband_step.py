import numpy as np
import pytest
from nocturne.core.image import AstroImage
from nocturne.core.narrowband import NarrowbandParams, render
from nocturne.steps.narrowband_step import NarrowbandStep, parse_narrowband_option
from nocturne.recipe import serialize_option, deserialize_option, _NAME_TO_STAGE, uncaptured_step_names


def _img():
    ha = np.full((16, 16), 0.5, np.float32)
    oiii = np.full((16, 16), 0.2, np.float32)
    return AstroImage(np.stack([ha, oiii, oiii], axis=2), is_linear=False)


def test_parse_option_passthrough_dict_and_default():
    p = NarrowbandParams(palette="Pseudo-SHO", oiii_boost=1.4)
    assert parse_narrowband_option(p) is p
    d = parse_narrowband_option({"palette": "HOO", "oiii_boost": 1.2})
    assert d.palette == "HOO" and d.oiii_boost == 1.2
    assert parse_narrowband_option(None).palette == "HOO"


def test_step_without_rcastro_recolours_whole_image():
    out = NarrowbandStep(None).apply(_img(), NarrowbandParams(palette="HOO"))
    assert out.data.shape == (16, 16, 3)
    assert not np.allclose(out.data, _img().data)      # colour changed


def test_step_mono_raises():
    with pytest.raises(ValueError):
        NarrowbandStep(None).apply(AstroImage(np.zeros((8, 8), np.float32), is_linear=False),
                                   NarrowbandParams())


def test_step_with_rcastro_screens_stars_back():
    img = _img()
    starless = AstroImage(img.data * 0.5, is_linear=False)
    stars = AstroImage(np.zeros_like(img.data), is_linear=False)
    stars.data[4, 4] = [0.9, 0.9, 0.9]

    class FakeRC:
        def remove_stars(self, image, runner=None):
            return starless, stars

    out = NarrowbandStep(FakeRC()).apply(img, NarrowbandParams(palette="HOO"))
    # the star pixel is screened back -> brighter than the recoloured nebula there
    assert out.data[4, 4].max() > 0.5


def test_recipe_round_trip_matches_live(monkeypatch):
    # serialize -> deserialize -> apply must equal a direct apply of the same params
    params = NarrowbandParams(palette="Pseudo-SHO", oiii_boost=1.3, protect_background=0.2)
    live = NarrowbandStep(None).apply(_img(), params).data
    ser = serialize_option("narrowband", params)
    assert isinstance(ser, dict) and ser["palette"] == "Pseudo-SHO"
    back = deserialize_option("narrowband", ser)
    replay = NarrowbandStep(None).apply(_img(), back).data
    assert np.allclose(live, replay)


def test_narrowband_is_recipe_captured_not_uncaptured():
    assert _NAME_TO_STAGE["Narrowband"] == "narrowband"
    assert uncaptured_step_names([("Narrowband", NarrowbandParams())]) == []
