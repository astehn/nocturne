import pytest

pytest.importorskip("PySide6")
from nocturne.ui.zoom_pill import ZoomPill  # noqa: E402


def test_buttons_invoke_callbacks(qtbot):
    calls = []
    pill = ZoomPill(lambda: calls.append("out"),
                    lambda: calls.append("fit"),
                    lambda: calls.append("in"))
    qtbot.addWidget(pill)
    pill.out_btn.click()
    pill.fit_btn.click()
    pill.in_btn.click()
    assert calls == ["out", "fit", "in"]
