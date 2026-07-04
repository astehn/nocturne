from PySide6.QtCore import Qt

from seestar_processor.ui.reset_slider import ResetSlider


def test_resets_to_default_on_double_click(qtbot):
    s = ResetSlider(50)
    qtbot.addWidget(s)
    assert s.value() == 50
    s.setValue(30)
    qtbot.mouseDClick(s, Qt.MouseButton.LeftButton)
    assert s.value() == 50


def test_range_set_before_value_avoids_clamp(qtbot):
    s = ResetSlider(100, minimum=10, maximum=300)
    qtbot.addWidget(s)
    assert s.value() == 100          # not clamped to a default 0-99 range
    assert s._default == 100
    s.setValue(250)
    qtbot.mouseDClick(s, Qt.MouseButton.LeftButton)
    assert s.value() == 100


def test_has_reset_tooltip(qtbot):
    s = ResetSlider(0)
    qtbot.addWidget(s)
    assert "reset" in s.toolTip().lower()


def test_reset_emits_value_changed(qtbot):
    s = ResetSlider(50)
    qtbot.addWidget(s)
    s.setValue(20)
    seen = []
    s.valueChanged.connect(seen.append)
    qtbot.mouseDClick(s, Qt.MouseButton.LeftButton)
    assert 50 in seen
