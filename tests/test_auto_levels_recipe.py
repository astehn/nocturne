"""Auto Levels in a recipe stores the DECISION, not one image's measurement.

A recipe stored `levels` as three literal floats. If they came from Auto, the
black point is `median - 3.5*MAD` of THAT image's noise floor, and replaying it
applies one frame's noise floor to another frame's data. Nearly every other
stage already stores a decision and re-derives per image — `background` stores
"strong", `color` stores `method: photometric` and re-queries Gaia per frame,
`stretch` stores an amount whose target is computed per image. Levels was the
odd one out.
"""
import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.core.levels import apply_levels, auto_levels
from nocturne.recipe import deserialize_option, serialize_option
from nocturne.steps.levels import LevelsStep

# Imported, not re-declared: a third copy with nothing asserting it equals
# the others is a rename that fails silently in two places.
from nocturne.core.levels import AUTO


def _img(mean, seed=0):
    rng = np.random.default_rng(seed)
    return AstroImage(np.clip(rng.normal(mean, 0.05, (64, 64, 3)), 0, 1).astype(np.float32),
                      is_linear=False, metadata={})


def test_auto_round_trips_through_a_recipe():
    assert serialize_option("levels", AUTO) == AUTO
    assert deserialize_option("levels", AUTO) == AUTO


def test_a_saved_recipe_from_before_this_change_still_replays_its_numbers():
    """The backward-compatibility guarantee: a list still means chosen numbers.
    Type alone distinguishes the two forms, so no migration and no refusal."""
    assert serialize_option("levels", (0.031, 1.0, 1.0)) == [0.031, 1.0, 1.0]
    assert deserialize_option("levels", [0.031, 1.0, 1.0]) == (0.031, 1.0, 1.0)


def test_replaying_auto_derives_from_the_image_in_front_of_it():
    img = _img(0.30)
    out = LevelsStep().apply(img, AUTO)
    b, g, w = auto_levels(img.data)
    assert np.allclose(out.data, apply_levels(img, b, g, w).data, atol=1e-6)


def test_two_images_with_different_noise_floors_get_different_black_points():
    """The whole point: each image is levelled against its OWN floor.

    Asserted POSITIVELY. The first version of this test only checked that each
    output was unlike the other image's levelling — and a mutation that ignored
    "auto" entirely and returned `(0.0, 1.0, 1.0)` PASSED it, because "untouched
    dark" is trivially unlike "dark levelled with bright's floor". Two negatives
    do not add up to the positive claim.
    """
    dark, bright = _img(0.15, seed=1), _img(0.55, seed=2)
    b_dark, b_bright = auto_levels(dark.data)[0], auto_levels(bright.data)[0]
    assert b_dark != b_bright, "the fixture cannot tell the two floors apart"

    assert np.allclose(LevelsStep().apply(dark, AUTO).data,
                       apply_levels(dark, *auto_levels(dark.data)).data, atol=1e-6)
    assert np.allclose(LevelsStep().apply(bright, AUTO).data,
                       apply_levels(bright, *auto_levels(bright.data)).data, atol=1e-6)
    # and NOT the identity, which is what the mutation returned
    assert not np.allclose(LevelsStep().apply(bright, AUTO).data, bright.data, atol=1e-6)


def test_auto_is_deterministic_so_saved_projects_stay_pixel_exact():
    """`levels` is in _REPRODUCIBLE_STAGES, so a project replays the step rather
    than caching pixels. Re-deriving on the SAME image must give the same answer."""
    img = _img(0.30)
    a = LevelsStep().apply(img, AUTO)
    b = LevelsStep().apply(img, AUTO)
    assert np.array_equal(a.data, b.data)


def test_a_plain_tuple_still_applies_those_exact_numbers():
    img = _img(0.30)
    out = LevelsStep().apply(img, (0.02, 1.0, 0.9))
    assert np.allclose(out.data, apply_levels(img, 0.02, 1.0, 0.9).data, atol=1e-6)


def test_auto_enhance_records_the_decision_too():
    """Auto Enhance derives the black point the same way the Auto button does,
    so a recipe saved after one tap carried exactly the defect this change
    fixes — a frozen `[0.23, 1.0, 1.0]` measured off one frame — and nothing in
    the UI could correct it, because the user never pressed Auto."""
    import inspect

    from nocturne.core import auto_enhance
    src = inspect.getsource(auto_enhance)
    assert "option = auto_levels(img.data)" not in src, (
        "Auto Enhance still freezes the derived black point into the recipe")
