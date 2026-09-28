import numpy as np
import pytest

from nocturne.stacking.drizzle_gate import (PLAIN_OK, SUITS_SUMMARY, drizzle_advice,
                                            plain_advice)


class _S:  # minimal stand-in for FrameStats
    def __init__(self, fwhm, included=True):
        self.fwhm = fwhm
        self.included = included


def _dithered(n):  # transforms with well-scattered sub-pixel translations
    rng = np.random.default_rng(0)
    return [np.array([[1, 0, rng.uniform(-1, 1)], [0, 1, rng.uniform(-1, 1)], [0, 0, 1]])
            for _ in range(n)]


def test_undersampled_dithered_many_is_recommended():
    adv = drizzle_advice([_S(1.6) for _ in range(40)], _dithered(40))
    assert adv.level == "recommended"


def test_soft_stars_not_recommended():
    adv = drizzle_advice([_S(3.2) for _ in range(40)], _dithered(40))
    assert adv.level == "not_recommended" and "soft" in adv.reason.lower()


def test_too_few_frames_marginal_or_not():
    adv = drizzle_advice([_S(1.6) for _ in range(6)], _dithered(6))
    assert adv.level in ("marginal", "not_recommended")


def test_advice_without_transforms_uses_fwhm_and_count():
    # Undersampled + plenty of frames, no transforms yet (grade time) ->
    # recommended on FWHM + count alone, dither path skipped.
    adv = drizzle_advice([_S(1.6) for _ in range(40)])
    assert adv.level == "recommended"
    assert "dither" not in adv.reason.lower() or "not yet assessed" in adv.reason.lower()

    # Soft stars, no transforms -> still not_recommended regardless of dither.
    adv_soft = drizzle_advice([_S(3.2) for _ in range(40)], transforms=None)
    assert adv_soft.level == "not_recommended"


def test_typical_s30_pro_data_is_not_warned_off():
    """The gate shipped with FWHM_MAX = 2.0 while the S30 Pro sits at about
    2.5 px (~3.7"/px), so it told the user their own camera was unsuitable.
    Measured 2026-08-31 on 100 IC 1396A frames, 2.5 px data gains 22% tighter
    stars and 64% more of them — the gate was simply wrong."""
    adv = drizzle_advice([_S(2.5) for _ in range(120)], _dithered(120))
    assert adv.level != "not_recommended", adv.reason


def test_genuinely_soft_data_is_still_discouraged():
    """The gate must still mean something. Badly out of focus, or a focal
    length that oversamples — drizzle has nothing to recover there."""
    adv = drizzle_advice([_S(6.0) for _ in range(120)], _dithered(120))
    assert adv.level == "not_recommended", adv.reason


# --- plain words (spec 2026-09-28 §5): yes or no, and one plain reason -------

def _still(n):  # transforms with no sub-pixel scatter at all
    return [np.array([[1, 0, 3.0], [0, 1, -2.0], [0, 0, 1]]) for _ in range(n)]


@pytest.mark.parametrize("stats, transforms, suits, text", [
    ([_S(2.5)] * 120, None, True, PLAIN_OK),
    ([_S(2.5)] * 25, None, True, PLAIN_OK),          # the gate's "marginal", enough frames
    ([_S(2.5)] * 20, None, True, PLAIN_OK),          # MIN_FRAMES is inclusive
    ([_S(2.5)] * 19, None, False,
     "Not suitable for Drizzle: too few frames (19; it needs at least 20)."),
    ([_S(2.5)] * 6, None, False,
     "Not suitable for Drizzle: too few frames (6; it needs at least 20)."),
    ([_S(3.2)] * 40, None, False,
     "Not suitable for Drizzle: your stars are too soft for it to add detail."),
    ([_S(2.5, included=False)] * 30, None, False,
     "Not suitable for Drizzle: no frames are ticked."),
    ([_S(2.5)] * 40, _still(40), False,
     "Not suitable for Drizzle: the frames barely moved between exposures, so there "
     "is nothing to fill the finer grid."),
    ([_S(2.5)] * 40, _dithered(40), True, PLAIN_OK),
])
def test_every_reason_reads_in_plain_words(stats, transforms, suits, text):
    plain = plain_advice(drizzle_advice(stats, transforms))
    assert plain.suits is suits
    assert plain.text == text
    assert "px" not in plain.text and "FWHM" not in plain.text, "a number crept in"


def test_the_numbers_go_to_the_tooltip():
    plain = plain_advice(drizzle_advice([_S(2.5)] * 120))
    assert plain.numbers == (
        "Median star size FWHM 2.5 px — Drizzle helps below 3.0 px. 120 frames "
        "ticked — it needs at least 20, and 40 or more is where it pays off.")
    assert plain_advice(drizzle_advice([_S(2.5, included=False)] * 3)).numbers == (
        "No frames are ticked.")
    assert SUITS_SUMMARY == "Drizzle suits this stack"


def test_the_gates_own_reason_is_unchanged():
    """reason is still the engineer's sentence; only the dialog changed words."""
    adv = drizzle_advice([_S(2.5)] * 120)
    assert adv.reason == ("Undersampled stars (FWHM 2.5px) and enough frames (120) — "
                          "recommended based on sharpness and frame count")
    assert (adv.code, adv.fwhm, adv.frames) == ("ok", 2.5, 120)
