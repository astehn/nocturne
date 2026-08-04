import pytest

from nocturne.stacking.grade import (
    REASON_CLOUDS, REASON_MEASURE, REASON_SOFT, WARN_SKY,
    FrameStats, grade_frame, grade_frames, judge, upper_gate,
)
from tests.stacking.synthetic import make_star_field, write_cfa_fits, write_color_fits


def test_grade_frame_counts_stars(tmp_path):
    p = tmp_path / "s.fit"
    write_cfa_fits(p, make_star_field(n_stars=25, seed=3))
    stats = grade_frame(str(p))
    assert stats.star_count >= 10
    # write_cfa_fits stores raw ADU-scale counts (base * 1000, uint16), not
    # normalized 0..1 floats, so the background sits well under the ~1000-scale
    # star peaks rather than under 0.2.
    assert stats.background < 20.0


def test_grade_frames_flags_cloudy_outlier(tmp_path):
    paths = []
    for i in range(5):
        p = tmp_path / f"good{i}.fit"
        write_cfa_fits(p, make_star_field(n_stars=30, seed=i, bg=0.02))
        paths.append(str(p))
    cloudy = tmp_path / "cloudy.fit"
    # high background, few stars -> should be flagged not-included
    write_cfa_fits(cloudy, make_star_field(n_stars=3, seed=99, bg=0.6))
    paths.append(str(cloudy))

    graded = grade_frames(paths)
    by_path = {s.path: s for s in graded}
    assert by_path[str(cloudy)].included is False
    # sorted worst -> best: the cloudy frame is first
    assert graded[0].path == str(cloudy)


def _fs(path="f.fit", stars=800, fwhm=2.5, bg=1200.0, included=True, elongation=1.05):
    return FrameStats(path, stars, fwhm, bg, 0.5, included, elongation=elongation)


def test_upper_gate_is_median_plus_k_robust_sigma():
    import numpy as np
    vals = [2.0, 2.5, 3.0]
    med = 2.5
    mad = float(np.median(np.abs(np.asarray(vals) - med))) * 1.4826
    assert upper_gate(vals, 3.0) == pytest.approx(med + 3.0 * mad)


def test_upper_gate_is_not_poisoned_by_one_catastrophic_value():
    """The original purpose, preserved: a single wild frame must not widen the
    gate so far that everything passes. The MAD ignores it outright, where the
    old code needed an iterative clip to remove it."""
    vals = [2.0] * 20 + [2.1] * 20 + [50.0]
    gate = upper_gate(vals, 3.0)
    assert gate < 10.0          # the outlier does not set the scale
    assert gate > 2.1           # normal frames stay under it


def test_upper_gate_never_falls_below_the_median():
    """The bug the MAD replaced. Iteratively clipping the tail shrank the SD
    each pass and walked the gate downward, until on real data it sat BELOW the
    median — condemning most typical frames. Measured on 60 M31 subs at k=2.0:
    the elongation gate reached 1.132 against a median of 1.158 (37/60 rejected)
    and the background gate 6684 against a median near 15000 (41/60).

    A gate under the median cannot be an outlier test, whatever the inputs."""
    import numpy as np
    rng = np.random.default_rng(3)
    for skew in (1.0, 3.0, 10.0):
        # tight core, long upper tail — the shape that broke the old gate
        vals = list(rng.normal(1.15, 0.02, 50)) + list(1.15 + rng.exponential(0.1 * skew, 10))
        med = float(np.median(vals))
        for k in (2.0, 3.0, 4.0):
            assert upper_gate(vals, k) >= med, \
                f"gate fell below the median at k={k}, skew={skew}"


def test_upper_gate_is_monotonic_in_strictness():
    """Stricter must never keep MORE. The iterative version could invert,
    because a lower k clipped harder and shrank the SD faster."""
    import numpy as np
    rng = np.random.default_rng(7)
    vals = list(rng.normal(1.15, 0.03, 60)) + [1.5, 1.7, 1.8]
    assert upper_gate(vals, 2.0) <= upper_gate(vals, 3.0) <= upper_gate(vals, 4.0)


def test_judge_tight_distribution_rejects_nothing():
    # The property the old 3xMAD code failed: uniformly good, tightly
    # clustered sessions must keep every frame.
    stats = [_fs(path=f"f{i}.fit", stars=800 + i, fwhm=2.4 + 0.01 * i,
                 bg=1200.0 + i) for i in range(50)]
    judge(stats)
    assert all(s.included for s in stats)
    assert all(s.reason == "" for s in stats)


def test_judge_rejects_star_collapse_as_clouds():
    stats = [_fs(path=f"f{i}.fit") for i in range(20)]
    stats.append(_fs(path="cloudy.fit", stars=300))   # < 50% of median 800
    judge(stats)
    bad = stats[-1]
    assert bad.included is False
    assert bad.reason_code == "clouds"
    assert bad.reason.startswith(REASON_CLOUDS)


def test_judge_rejects_soft_fwhm_with_detail():
    stats = [_fs(path=f"f{i}.fit", fwhm=2.4 + 0.001 * i) for i in range(30)]
    stats.append(_fs(path="soft.fit", fwhm=6.0))
    judge(stats)
    bad = stats[-1]
    assert bad.included is False
    assert bad.reason_code == "soft_stars"
    assert bad.reason.startswith(REASON_SOFT)
    assert "6.0" in bad.reason        # measured value visible to the user


def test_judge_bright_sky_warns_but_keeps():
    stats = [_fs(path=f"f{i}.fit", bg=1200.0 + i) for i in range(30)]
    stats.append(_fs(path="twilight.fit", bg=2400.0))
    judge(stats)
    bright = stats[-1]
    assert bright.included is True
    assert bright.warning == WARN_SKY
    assert bright.reason == ""


def test_judge_strictness_relaxed_keeps_more_than_strict():
    stats = [_fs(path=f"f{i}.fit", fwhm=2.4) for i in range(30)]
    stats.append(_fs(path="edge.fit", fwhm=2.9))
    judge(stats, strictness="strict")
    strict_included = stats[-1].included
    judge(stats, strictness="relaxed")
    relaxed_included = stats[-1].included
    assert (not strict_included) or relaxed_included  # relaxed never harsher


def test_judge_zero_star_frames_dont_poison_fwhm_gate():
    # Zero-star frames carry a sentinel fwhm=0.0 (not a measurement). Mixed into
    # the FWHM gate's median/SD, they widen the gate enough to let a genuinely
    # soft (tracking-error) frame slip through. The FWHM gate must be computed
    # only from frames that actually have stars.
    stats = [_fs(path=f"f{i}.fit", stars=800, fwhm=2.4 + 0.1 * i / 29)
             for i in range(30)]
    stats += [_fs(path=f"cloud{i}.fit", stars=0, fwhm=0.0) for i in range(3)]
    stats.append(_fs(path="soft.fit", stars=800, fwhm=3.5))
    judge(stats, strictness="normal")
    by_path = {s.path: s for s in stats}

    soft = by_path["soft.fit"]
    assert soft.included is False
    assert soft.reason_code == "soft_stars"

    for i in range(3):
        cloud = by_path[f"cloud{i}.fit"]
        assert cloud.included is False
        assert cloud.reason_code == "clouds"


def test_judge_under_five_frames_keeps_all():
    stats = [_fs(path=f"f{i}.fit", stars=100 * (i + 1)) for i in range(4)]
    judge(stats)
    assert all(s.included for s in stats)


def test_judge_skips_error_frames_and_leaves_them_excluded():
    stats = [_fs(path=f"f{i}.fit") for i in range(10)]
    broken = FrameStats("bad.fit", 0, 0.0, 0.0, 0.0, False,
                        reason_code="measure_failed", reason=REASON_MEASURE,
                        error=True)
    stats.append(broken)
    judge(stats)
    assert broken.included is False
    assert broken.reason == REASON_MEASURE
    # its zero FWHM/bg must not have polluted the gates:
    assert all(s.included for s in stats[:-1])


def test_grade_frame_captures_exposure_and_target(tmp_path):
    p = tmp_path / "s.fit"
    write_cfa_fits(p, make_star_field(n_stars=25, seed=3))  # exptime=10.0
    stats = grade_frame(str(p))
    assert stats.exposure == pytest.approx(10.0)
    assert stats.error is False


def test_grade_frame_excludes_already_stacked_master(tmp_path):
    # A previously written master is a 3-plane RGB cube, the same shape
    # save_fits writes (H, W, 3) -> (3, H, W) on disk. It must never be
    # graded/measured like a raw sub, or it gets silently stacked into the
    # new run and its EXPTIME (the whole prior session) pollutes stats.
    p = tmp_path / "master.fit"
    write_color_fits(p, make_star_field(n_stars=25, seed=3))
    stats = grade_frame(str(p))
    assert stats.error is True
    assert stats.included is False
    assert stats.reason_code == "not_raw"
    assert "Already-stacked" in stats.reason


def test_grade_frame_unreadable_returns_error_verdict(tmp_path):
    p = tmp_path / "garbage.fit"
    p.write_bytes(b"this is not a FITS file")
    stats = grade_frame(str(p))
    assert stats.error is True
    assert stats.included is False
    assert stats.reason == REASON_MEASURE
    assert stats.reason_code == "measure_failed"


def test_grade_frames_strictness_kwarg(tmp_path):
    paths = []
    for i in range(6):
        p = tmp_path / f"g{i}.fit"
        write_cfa_fits(p, make_star_field(n_stars=30, seed=i, bg=0.02))
        paths.append(str(p))
    graded = grade_frames(paths, strictness="relaxed")
    assert all(s.included for s in graded)


def test_grade_frames_cancels_via_ambient_token(tmp_path):
    from nocturne.core.tasks import CancelToken, Cancelled, set_ambient, clear_ambient
    paths = []
    for i in range(3):
        p = tmp_path / f"g{i}.fit"
        write_cfa_fits(p, make_star_field(n_stars=25, seed=i))
        paths.append(str(p))
    tok = CancelToken()
    tok.cancel()
    set_ambient(tok)
    try:
        with pytest.raises(Cancelled):
            grade_frames(paths)
    finally:
        clear_ambient()


def test_grade_frame_bad_exptime_header_degrades_not_crashes(tmp_path):
    from astropy.io import fits as pyfits
    p = tmp_path / "badexp.fit"
    write_cfa_fits(p, make_star_field(n_stars=25, seed=3))
    with pyfits.open(str(p), mode="update") as hdul:
        hdul[0].header["EXPTIME"] = "bogus"
    stats = grade_frame(str(p))
    assert stats.error is True
    assert stats.included is False
    assert stats.reason_code == "measure_failed"


# --- roundness -----------------------------------------------------------------
# Trailing was invisible to grading BY CONSTRUCTION. FWHM is measured as
# 2.3548 * sqrt(a*b), the geometric mean of the two axes, which is unchanged when
# a star is stretched along one axis and squeezed along the other — and even for
# a pure stretch it moves far less than the elongation does. Measured on real
# M31 subs 2026-08-03: frame #15 had stars 70% longer than wide (a/b = 1.70) and
# sailed through every existing gate as a good frame.

def test_frame_stats_carries_elongation():
    from nocturne.stacking.grade import FrameStats
    s = FrameStats("f.fit", 800, 2.5, 1200.0, 0.5, True)
    assert s.elongation == pytest.approx(1.0), "round is the sane default"


def test_judge_rejects_a_trailed_frame():
    from nocturne.stacking.grade import REASON_TRAILED
    stats = [_fs(path=f"f{i}.fit", elongation=1.10 + 0.001 * i) for i in range(30)]
    stats.append(_fs(path="trailed.fit", elongation=1.70))
    judge(stats)
    bad = stats[-1]
    assert bad.included is False
    assert bad.reason_code == "trailed"
    assert bad.reason.startswith(REASON_TRAILED)
    assert "1.7" in bad.reason          # the measured value, visible to the user


def test_a_trailed_frame_is_not_caught_by_the_fwhm_gate():
    """The whole reason this metric exists. Stretching a star along one axis
    while squeezing the other leaves sqrt(a*b) — and therefore FWHM — untouched,
    so no FWHM threshold can ever see it."""
    stats = [_fs(path=f"f{i}.fit", fwhm=2.50, elongation=1.10) for i in range(30)]
    stats.append(_fs(path="trailed.fit", fwhm=2.50, elongation=1.90))
    judge(stats)
    assert stats[-1].included is False
    assert stats[-1].reason_code == "trailed", \
        "an identical FWHM means only the roundness test can reject this"


def test_round_frames_are_never_rejected_for_roundness():
    stats = [_fs(path=f"f{i}.fit", elongation=1.02 + 0.002 * i) for i in range(40)]
    judge(stats)
    assert all(s.included for s in stats)


def test_roundness_gate_follows_strictness():
    def run(strictness):
        stats = [_fs(path=f"f{i}.fit", elongation=1.10 + 0.01 * i) for i in range(20)]
        stats.append(_fs(path="edge.fit", elongation=1.45))
        judge(stats, strictness)
        return sum(1 for s in stats if s.included)
    assert run("strict") <= run("normal") <= run("relaxed")


def test_a_uniformly_trailed_session_is_not_all_rejected():
    """Same relative-to-the-session rule as the other gates: if every frame is
    equally elongated there is no outlier, and throwing the whole session away
    would leave the user with nothing. Documented behaviour, not an oversight."""
    stats = [_fs(path=f"f{i}.fit", elongation=1.60 + 0.001 * i) for i in range(30)]
    judge(stats)
    assert all(s.included for s in stats)


def test_measure_reports_elongation_from_the_pixels(tmp_path):
    """Exercises _measure itself. The judging tests above build FrameStats by
    hand, so they never proved the number is computed — or computed the right
    way up. Inverting it to b/a passed every one of them."""
    for stretch, expect in ((1.0, 1.0), (2.0, 2.0), (3.0, 3.0)):
        p = tmp_path / f"e{stretch}.fit"
        write_cfa_fits(p, make_star_field(shape=(160, 160), n_stars=60, seed=2,
                                          stretch=stretch))
        s = grade_frame(str(p))
        assert s.elongation == pytest.approx(expect, rel=0.35), \
            f"stretch {stretch} measured as elongation {s.elongation:.2f}"
        assert s.elongation >= 0.99, "elongation is a/b and must never be < 1"


def test_a_trailed_frame_measures_the_same_fwhm_as_a_round_one(tmp_path):
    """The justification for the whole metric, proved on pixels rather than
    asserted in a docstring: stretching one axis while squeezing the other
    leaves the geometric mean — and therefore FWHM — essentially unchanged."""
    p_round = tmp_path / "round.fit"
    p_trail = tmp_path / "trail.fit"
    write_cfa_fits(p_round, make_star_field(shape=(160, 160), n_stars=60, seed=4,
                                            stretch=1.0))
    write_cfa_fits(p_trail, make_star_field(shape=(160, 160), n_stars=60, seed=4,
                                            stretch=2.5))
    a, b = grade_frame(str(p_round)), grade_frame(str(p_trail))
    assert b.fwhm == pytest.approx(a.fwhm, rel=0.25), \
        "if FWHM could see trailing, roundness would be redundant"
    assert b.elongation > a.elongation * 1.8, "roundness must see what FWHM cannot"


def test_a_trailed_frame_scores_worse_so_it_is_not_chosen_as_reference(tmp_path):
    """include[0] is the frame every other frame is registered against. A
    trailed reference degrades the whole stack, so elongation belongs in the
    score and not only in the gate."""
    p_round = tmp_path / "r.fit"
    p_trail = tmp_path / "t.fit"
    write_cfa_fits(p_round, make_star_field(shape=(160, 160), n_stars=60, seed=6,
                                            stretch=1.0))
    write_cfa_fits(p_trail, make_star_field(shape=(160, 160), n_stars=60, seed=6,
                                            stretch=2.5))
    assert grade_frame(str(p_trail)).score < grade_frame(str(p_round)).score


def test_score_prefers_the_rounder_of_two_otherwise_identical_frames():
    """The score picks the reference every other frame is registered against, so
    elongation has to count here as well as at the gate. Tested directly because
    two real frames never differ in only one measurement — comparing measured
    frames let the elongation term be deleted with every test still passing."""
    from nocturne.stacking.grade import _score
    round_frame = _score(star_count=800, fwhm=2.4, background=0.02, elongation=1.05)
    trailed = _score(star_count=800, fwhm=2.4, background=0.02, elongation=1.80)
    assert trailed < round_frame, "elongation is not affecting the score"
    assert trailed == pytest.approx(round_frame * (1.05 / 1.80), rel=1e-6)
