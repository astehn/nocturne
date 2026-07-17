import pytest

from nocturne.stacking.grade import grade_frame, grade_frames
from tests.stacking.synthetic import make_star_field, write_color_fits


def test_grade_frame_counts_stars(tmp_path):
    p = tmp_path / "s.fit"
    write_color_fits(p, make_star_field(n_stars=25, seed=3))
    stats = grade_frame(str(p))
    assert stats.star_count >= 10
    assert stats.background < 0.2


def test_grade_frames_flags_cloudy_outlier(tmp_path):
    paths = []
    for i in range(5):
        p = tmp_path / f"good{i}.fit"
        write_color_fits(p, make_star_field(n_stars=30, seed=i, bg=0.02))
        paths.append(str(p))
    cloudy = tmp_path / "cloudy.fit"
    # high background, few stars -> should be flagged not-included
    write_color_fits(cloudy, make_star_field(n_stars=3, seed=99, bg=0.6))
    paths.append(str(cloudy))

    graded = grade_frames(paths)
    by_path = {s.path: s for s in graded}
    assert by_path[str(cloudy)].included is False
    # sorted worst -> best: the cloudy frame is first
    assert graded[0].path == str(cloudy)


from nocturne.stacking.grade import (
    REASON_CLOUDS, REASON_MEASURE, REASON_SOFT, WARN_SKY,
    FrameStats, judge, upper_gate,
)


def _fs(path="f.fit", stars=800, fwhm=2.5, bg=1200.0, included=True):
    return FrameStats(path, stars, fwhm, bg, 0.5, included)


def test_upper_gate_simple_median_plus_k_sd():
    # No values above the gate -> single pass: median 2.5, SD of [2,2.5,3]
    vals = [2.0, 2.5, 3.0]
    import numpy as np
    expected = 2.5 + 3.0 * float(np.asarray(vals).std())
    assert upper_gate(vals, 3.0) == pytest.approx(expected)


def test_upper_gate_iterates_until_stable():
    # One catastrophic outlier inflates SD; after it is clipped the gate
    # tightens and must be recomputed from the surviving values.
    vals = [2.0] * 20 + [2.1] * 20 + [50.0]
    gate = upper_gate(vals, 3.0)
    assert gate < 10.0          # outlier no longer poisons the statistics
    assert gate > 2.1           # but normal frames stay under the gate


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
