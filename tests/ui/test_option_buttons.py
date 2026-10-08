"""Levels as joined buttons instead of a dropdown (Andreas, 2026-10-08)."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QComboBox

from nocturne.ui import theme
from nocturne.ui.option_buttons import OptionButtons


def _buttons(qtbot, values=("off", "light", "strong")):
    w = OptionButtons()
    qtbot.addWidget(w)
    w.addItems(list(values))
    return w


def test_every_level_is_a_visible_button_named_for_people(qtbot):
    w = _buttons(qtbot)
    assert [b.text() for b in w.buttons()] == ["Off", "Light", "Strong"]
    assert [w.itemText(i) for i in range(w.count())] == ["off", "light", "strong"], \
        "the stored option strings are unchanged, so history and recipes still match"


def test_one_level_is_chosen_at_a_time(qtbot):
    w = _buttons(qtbot)
    assert w.currentText() == "off"
    w.buttons()[2].click()
    assert w.currentText() == "strong" and w.currentIndex() == 2
    assert [b.isChecked() for b in w.buttons()] == [False, False, True]


def test_choosing_reports_once_and_an_unknown_level_changes_nothing(qtbot):
    w = _buttons(qtbot)
    got = []
    w.currentTextChanged.connect(got.append)
    w.setCurrentText("light")
    w.setCurrentText("light")
    assert got == ["light"]
    w.setCurrentText("medium")
    assert w.currentText() == "light" and got == ["light"]


def test_the_ends_are_rounded_and_the_joints_square(qtbot):
    w = _buttons(qtbot)
    assert [b.property("seg") for b in w.buttons()] == ["first", "mid", "last"]


def test_the_chosen_level_does_not_wear_the_accent():
    """Blue is Next and "interactive"; a chosen level must not compete with it."""
    css = theme.build_stylesheet()
    rule = css.split("QPushButton#level:checked {", 1)[1].split("}", 1)[0]
    assert theme.ACCENT.lower() not in rule.lower()


@pytest.mark.parametrize("stage_id,levels", [
    ("background", ["off", "light", "strong"]),
    ("deconvolution", ["light", "medium", "strong"]),
    ("noise_sharpen", ["light", "medium", "strong"]),
])
def test_the_level_steps_show_buttons_not_a_dropdown(qtbot, tmp_path, stage_id, levels):
    from tests.ui.test_main_window import _window, _make_fits
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id(stage_id)
    box = win._panel.option_box
    assert isinstance(box, OptionButtons)
    assert [box.itemText(i) for i in range(box.count())] == levels
    assert not [c for c in win._panel.findChildren(QComboBox)
                if c.count() and c.itemText(0) in levels], "no dropdown of the same levels left"


def test_the_buttons_dim_while_the_step_works_and_keep_the_choice(qtbot, tmp_path):
    from tests.ui.test_main_window import _window, _make_fits
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("deconvolution")
    box = win._panel.option_box
    box.setCurrentText("strong")
    before = box.currentText()
    win._set_busy(True)
    try:
        assert all(not b.isEnabled() for b in box.buttons())
    finally:
        win._set_busy(False)
    assert all(b.isEnabled() for b in box.buttons())
    assert box.currentText() == before
