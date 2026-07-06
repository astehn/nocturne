from nocturne.ui import theme


def test_tokens_defined():
    for name in ("BG_0", "BG_1", "BG_2", "BG_3", "ACCENT", "SUCCESS",
                 "WARNING", "DANGER", "TEXT", "TEXT_DIM", "TEXT_FAINT"):
        val = getattr(theme, name)
        assert isinstance(val, str) and val.startswith("#")


def test_build_stylesheet_uses_tokens():
    qss = theme.build_stylesheet()
    assert isinstance(qss, str) and len(qss) > 500
    # semantic colours flow into the stylesheet
    assert theme.ACCENT in qss
    assert theme.BG_1 in qss
    # slider + progressbar polish present
    assert "QSlider" in qss and "QProgressBar" in qss
    assert "::sub-page" in qss  # accent-filled slider track
