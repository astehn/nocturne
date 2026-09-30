"""An unlinked stretch discards a photometric calibration completely (measured
0.0004 of a level left). The picker says so, but only while it is open; Apply
Stretch committed without a word (found by Andreas, 2026-09-29).
"""
from nocturne.core.color import ColorSettings

from tests.ui.test_main_window import _make_fits, _window


def _calibrated_at_stretch(qtbot, tmp_path, monkeypatch, method="photometric"):
    """Colour committed with `method`, then on Stretch. The step is stubbed:
    the real photometric path needs ASTAP and the network."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))

    class _Colour:
        name = "Color"; last_message = ""
        def apply(self, img, option):
            return img
    real = win._step_for
    monkeypatch.setattr(win, "_step_for",
                        lambda sid: _Colour() if sid == "color" else real(sid))
    win._go_to_id("color")
    win.apply_current(ColorSettings(method=method)); qtbot.wait(50)
    assert win.project.entries()[-1][1].method == method, "fixture"
    win._go_to_id("stretch")
    return win


def _note(win):
    return win._panel.spcc_note


def test_no_note_while_the_stretch_is_linked(qtbot, tmp_path, monkeypatch):
    win = _calibrated_at_stretch(qtbot, tmp_path, monkeypatch)
    assert win._panel.stretch_linked is True, "fixture"
    assert not _note(win).isVisibleTo(win._panel)


def test_choosing_unlinked_after_spcc_shows_the_note(qtbot, tmp_path, monkeypatch):
    win = _calibrated_at_stretch(qtbot, tmp_path, monkeypatch)
    win._apply_picked_stretch({"amount": 0.24, "linked": False})
    note = _note(win)
    assert note.isVisibleTo(win._panel)
    assert "photometric" in note.text().lower()
    assert "Linked" in note.text(), "it must say how to keep the calibration"


def test_choosing_linked_again_hides_it(qtbot, tmp_path, monkeypatch):
    win = _calibrated_at_stretch(qtbot, tmp_path, monkeypatch)
    win._apply_picked_stretch({"amount": 0.24, "linked": False})
    win._apply_picked_stretch({"amount": 0.24, "linked": True})
    assert not _note(win).isVisibleTo(win._panel)


def test_no_note_after_sky_balance(qtbot, tmp_path, monkeypatch):
    """Most people never run SPCC; warning them would be crying wolf."""
    win = _calibrated_at_stretch(qtbot, tmp_path, monkeypatch, method="sky")
    win._apply_picked_stretch({"amount": 0.24, "linked": False})
    assert not _note(win).isVisibleTo(win._panel)


def test_committing_unlinked_after_spcc_is_logged(qtbot, tmp_path, monkeypatch):
    win = _calibrated_at_stretch(qtbot, tmp_path, monkeypatch)
    win._apply_picked_stretch({"amount": 0.24, "linked": False})
    before = win.activity.text()
    win._panel.apply_btn.click(); qtbot.wait(50)
    assert win.project.entries()[-1][1] == {"amount": 0.24, "linked": False}, "fixture"
    added = win.activity.text()[len(before):].lower()
    assert "photometric" in added and "discarded" in added


def test_committing_linked_after_spcc_logs_nothing_about_it(qtbot, tmp_path, monkeypatch):
    win = _calibrated_at_stretch(qtbot, tmp_path, monkeypatch)
    before = win.activity.text()
    win._panel.apply_btn.click(); qtbot.wait(50)
    assert win.project.entries()[-1][1]["linked"] is True, "fixture"
    assert "discarded" not in win.activity.text()[len(before):].lower()


def test_once_committed_the_note_does_not_still_say_will(qtbot, tmp_path, monkeypatch):
    """After Apply the calibration is already gone; the log says so. A note
    still promising it 'will' be discarded would be false."""
    win = _calibrated_at_stretch(qtbot, tmp_path, monkeypatch)
    win._apply_picked_stretch({"amount": 0.24, "linked": False})
    win._panel.apply_btn.click(); qtbot.wait(50)
    assert not _note(win).isVisibleTo(win._panel)
