import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.theme import apply_dark_theme, ACCENT  # noqa: E402


def test_apply_dark_theme_sets_stylesheet(qapp):
    apply_dark_theme(qapp)
    qss = qapp.styleSheet()
    assert isinstance(qss, str) and len(qss) > 0
    assert ACCENT in qss
    # dark base color present (image stays the focal point)
    assert "#1e1f22" in qss
