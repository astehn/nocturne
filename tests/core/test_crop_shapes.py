"""The one shape list Crop, Trim, Share and Upscale Crop share, and the promise
that every recipe saved before it replays exactly as it did."""
import numpy as np
import pytest

from nocturne.core.crop import (
    FREE, LEGACY_FREE, PICTURE, RATIO_SHAPES, CropParams, apply_crop_params,
    shape_name, shape_ratio, split_shape,
)
from nocturne.core.image import AstroImage

# What core/crop.py held before 2026-10-10, frozen here on purpose: the guard
# compares against THIS, not against whatever the module now says.
_OLD_RATIOS = {"Original": None, "1:1": 1.0, "16:9": 16 / 9, "4:5": 4 / 5, "3:2": 3 / 2}


def _old_apply(data, aspect):
    ratio = _OLD_RATIOS[aspect]
    if ratio is None:
        return data
    h, w = data.shape[:2]
    if w / h > ratio:
        new_w = max(1, round(h * ratio))
        x0 = (w - new_w) // 2
        return data[:, x0:x0 + new_w]
    new_h = max(1, round(w / ratio))
    y0 = (h - new_h) // 2
    return data[y0:y0 + new_h, :]


def _frame(h=37, w=61):
    rng = np.random.default_rng(7)
    return rng.random((h, w, 3)).astype(np.float32)


def test_the_shape_order_is_the_approved_one():
    assert [n for n, _ in RATIO_SHAPES] == ["1:1", "5:4", "4:3", "3:2", "16:9"]
    assert all(r >= 1.0 for _, r in RATIO_SHAPES), "the list is landscape; Portrait turns it"


@pytest.mark.parametrize("base, portrait, name", [
    ("3:2", True, "2:3"), ("16:9", True, "9:16"), ("5:4", True, "4:5"),
    ("4:3", True, "3:4"), ("3:2", False, "3:2"), ("1:1", True, "1:1"),
    (FREE, True, FREE), (PICTURE, True, PICTURE),
])
def test_portrait_turns_the_name_except_where_there_is_nothing_to_turn(base, portrait, name):
    assert shape_name(base, portrait) == name


@pytest.mark.parametrize("name, split", [
    ("2:3", ("3:2", True)), ("9:16", ("16:9", True)), ("4:5", ("5:4", True)),
    ("16:9", ("16:9", False)), (PICTURE, (PICTURE, False)), (FREE, (FREE, False)),
    (LEGACY_FREE, (FREE, False)), ("nonsense", (FREE, False)),
])
def test_a_stored_name_reads_back_to_the_button_and_orientation(name, split):
    assert split_shape(name) == split


def test_ratios_are_width_over_height():
    assert shape_ratio("2:3") == pytest.approx(2 / 3)
    assert shape_ratio("9:16") == pytest.approx(9 / 16)
    assert shape_ratio(FREE) is None
    assert shape_ratio(LEGACY_FREE) is None
    assert shape_ratio(PICTURE, 1.5) == 1.5


@pytest.mark.parametrize("aspect", list(_OLD_RATIOS))
def test_every_name_stored_before_the_change_crops_identically(aspect):
    # With bounds, so the region cropped has proportions of its own that are
    # NOT the picture's: an old "Original" read as the new locked Original
    # would then cut it, where on the bare frame it would be a no-op either way.
    data = _frame()
    out = apply_crop_params(AstroImage(data), CropParams(bounds=(2, 30, 3, 50),
                                                         aspect=aspect)).data
    want = _old_apply(data[2:30, 3:50], aspect)
    assert out.shape == want.shape
    assert np.array_equal(out, want)


@pytest.mark.parametrize("aspect", list(_OLD_RATIOS))
def test_every_old_recipe_replays_identically_through_batch(aspect):
    """The path a saved recipe actually takes: JSON -> deserialize -> batch."""
    from nocturne.batch import apply_recipe
    from nocturne.core.crop import detect_content_bounds
    from nocturne.recipe import Recipe
    from nocturne.settings import Settings
    data = np.zeros((48, 80, 3), np.float32)
    data[3:45, 5:77] = _frame(42, 72)
    img = AstroImage(data, is_linear=True)
    step = {"stage": "crop", "option": {"aspect": aspect, "rotate": 0,
                                        "flip_h": False, "flip_v": False}}
    out = apply_recipe(img, Recipe(steps=[step]), Settings()).data
    t, b, l, r = detect_content_bounds(img)
    want = _old_apply(data[t:b, l:r], aspect)
    assert np.array_equal(out, want)


def test_an_old_original_is_free_not_the_new_locked_original():
    data = _frame(40, 60)                      # a 3:2 picture
    free = apply_crop_params(AstroImage(data),
                             CropParams(bounds=(0, 40, 0, 30), aspect=LEGACY_FREE)).data
    assert free.shape[:2] == (40, 30)          # a 3:4 region, left alone
    assert np.array_equal(free, data[:, :30])


def test_picture_keeps_the_pictures_own_proportions_after_a_trim():
    data = _frame(40, 60)                      # 3:2 picture
    out = apply_crop_params(AstroImage(data),
                            CropParams(bounds=(0, 40, 0, 40), aspect=PICTURE)).data
    h, w = out.shape[:2]
    assert (w, h) == (40, round(40 / 1.5))


@pytest.mark.parametrize("name, wh", [("2:3", (40, 60)), ("9:16", (27, 48)), ("4:5", (40, 50))])
def test_a_portrait_name_crops_to_a_tall_frame(name, wh):
    data = _frame(60, 90) if name != "9:16" else _frame(48, 90)
    out = apply_crop_params(AstroImage(data), CropParams(aspect=name)).data
    h, w = out.shape[:2]
    assert h > w
    assert (w, h) == (round(h * shape_ratio(name)), h)


def test_a_new_recipe_states_the_turned_name():
    from nocturne.recipe import deserialize_option, serialize_option
    stored = serialize_option("crop", CropParams(aspect="2:3"))
    assert stored["aspect"] == "2:3"
    assert deserialize_option("crop", stored).aspect == "2:3"
    assert serialize_option("crop", CropParams())["aspect"] == FREE
