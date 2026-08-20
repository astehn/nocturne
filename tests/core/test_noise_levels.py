"""The three engines' strength maps. Calibrated 2026-08-20; see noise_sharpen.py."""
from nocturne.steps.noise_sharpen import _GX_LEVELS, _NXT_LEVELS, _TV_LEVELS


def test_every_engine_gets_stronger_with_each_level():
    """light < medium < strong, in every engine.

    GraXpert's map was never calibrated and its 'strong' (0.9) was weaker than
    NoiseXTerminator's 'light' — the ordering within each engine still held, but
    nothing checked it, and nothing checks a map that is silently mistyped.
    """
    for name, levels in (("nxt", _NXT_LEVELS), ("graxpert", _GX_LEVELS), ("tv", _TV_LEVELS)):
        assert levels["light"] < levels["medium"] < levels["strong"], name
        assert all(0.0 <= v <= 1.0 for v in levels.values()), name


def test_graxpert_medium_is_meaningfully_stronger_than_it_was():
    """Pins the calibration's INTENT, not just its numbers.

    The old medium (0.7) measured 0.0265 background noise against the free TV
    fallback's 0.0273 — 137x the runtime for a 3% gain, which is what a user
    meant by "not really that good". Anything at or below 0.8 puts it back
    within noise of the free path.
    """
    assert _GX_LEVELS["medium"] >= 0.85
