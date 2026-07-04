import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.welcome import WelcomeScreen  # noqa: E402


def test_welcome_buttons_invoke_callbacks(qtbot):
    calls = []
    w = WelcomeScreen(lambda: calls.append("open"), lambda: calls.append("stack"))
    qtbot.addWidget(w)
    w.open_btn.click()
    w.stack_btn.click()
    assert calls == ["open", "stack"]
