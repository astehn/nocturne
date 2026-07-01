from seestar_processor.stacking.grade import grade_frame, grade_frames
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
