"""The Colour step's method is a pair of buttons, like Export's choices — his ask,
2026-10-14: dropdowns have gone almost everywhere else in the app."""
from PySide6.QtWidgets import QComboBox, QPushButton

from tests.ui.test_step_commit_model import _win


def _buttons(win):
    return [b for b in win._panel.method_box.findChildren(QPushButton)]


def test_the_method_is_two_buttons_not_a_dropdown(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    assert not isinstance(win._panel.method_box, QComboBox)
    assert [b.text() for b in _buttons(win)] == ["Sky balance", "Photometric (SPCC)"]
    assert win._panel.method_box.currentText() == "Sky balance", "the default is unchanged"


def test_clicking_spcc_selects_it_and_makes_the_step_pending(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    assert win._has_pending() is False, "fixture: nothing touched yet"
    _buttons(win)[1].click()
    assert win._panel.method_box.currentText() == "Photometric (SPCC)"
    assert win._has_pending() is True
    assert win._panel.commit_option().method == "photometric"


def test_the_two_buttons_are_one_exclusive_choice(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    sky, spcc = _buttons(win)
    spcc.click()
    sky.click()
    assert sky.isChecked() and not spcc.isChecked()
    assert win._panel.commit_option().method == "sky"
