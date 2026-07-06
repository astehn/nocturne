import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QWidget  # noqa: E402
from seestar_processor.ui.busy_bar import BusyBar, BUSY_BAR_HEIGHT  # noqa: E402


def test_busy_bar_show_over_and_hide(qtbot):
    parent = QWidget()
    parent.resize(200, 100)
    qtbot.addWidget(parent)
    bar = BusyBar()
    bar.show_over(parent)
    assert bar.parent() is parent
    assert bar.isHidden() is False
    assert bar._timer.isActive() is True
    assert bar.height() == BUSY_BAR_HEIGHT
    assert bar.width() == parent.width()
    bar.hide_bar()
    assert bar._timer.isActive() is False
    assert bar.isHidden() is True


def test_busy_bar_follows_target_resize(qtbot):
    parent = QWidget()
    parent.resize(200, 100)
    qtbot.addWidget(parent)
    parent.show()                 # hidden widgets don't get Resize events delivered
    bar = BusyBar()
    bar.show_over(parent)
    qtbot.waitUntil(lambda: bar.width() == 200, timeout=1000)
    parent.resize(400, 120)
    # the bar tracks the target via its eventFilter on the target's Resize event
    qtbot.waitUntil(lambda: bar.width() == 400, timeout=1000)


def test_busy_bar_is_mouse_transparent(qtbot):
    bar = BusyBar()
    qtbot.addWidget(bar)
    assert bar.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is True
