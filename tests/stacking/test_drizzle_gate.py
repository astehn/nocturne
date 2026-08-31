import numpy as np

from nocturne.stacking.drizzle_gate import drizzle_advice


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
