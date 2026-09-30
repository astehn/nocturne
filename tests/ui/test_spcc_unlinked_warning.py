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


def test_after_a_linked_commit_the_note_points_at_import(qtbot, tmp_path, monkeypatch):
    """Linked committed, then Import switched to Unlinked: Apply would discard
    SPCC, but Visual stretch is disabled on a stretched image, so the note must
    not send people there (review 2026-09-30)."""
    win = _calibrated_at_stretch(qtbot, tmp_path, monkeypatch)
    win._panel.apply_btn.click(); qtbot.wait(50)
    assert win.project.entries()[-1][1]["linked"] is True, "fixture"
    win._set_view_linked(False)
    win._go_to_id("stretch"); qtbot.wait(20)
    assert win._panel.stretch_linked is False, "fixture"
    assert not win._panel.visual_btn.isEnabled(), "fixture"
    note = _note(win)
    assert note.isVisibleTo(win._panel)
    assert "Import" in note.text() and "Visual stretch" not in note.text()


def test_the_note_hides_when_it_no_longer_applies(qtbot, tmp_path, monkeypatch):
    """Toothless without the setVisible(True) first: the panel builds it hidden."""
    win = _calibrated_at_stretch(qtbot, tmp_path, monkeypatch)
    _note(win).setVisible(True)
    win._sync_step_controls()
    assert not _note(win).isVisibleTo(win._panel)


def test_recommitting_unlinked_does_not_log_the_discard_again(qtbot, tmp_path, monkeypatch):
    win = _calibrated_at_stretch(qtbot, tmp_path, monkeypatch)
    win._apply_picked_stretch({"amount": 0.24, "linked": False})
    win._panel.apply_btn.click(); qtbot.wait(50)
    before = win.activity.text()
    win._panel.stretch_slider.setValue(30)
    win._panel.apply_btn.click(); qtbot.wait(50)
    assert win.project.entries()[-1][1] == {"amount": 0.30, "linked": False}, "fixture"
    assert "discarded" not in win.activity.text()[len(before):].lower()


def test_the_note_sits_at_the_bottom_directly_above_apply(qtbot, tmp_path, monkeypatch):
    """Andreas, 2026-09-30: under Visual stretch it was out of the eye's path
    to Apply. It is the card's last item, after the stretch that fills it."""
    win = _calibrated_at_stretch(qtbot, tmp_path, monkeypatch)
    lay = win._panel.layout()
    last = lay.itemAt(lay.count() - 1).widget()
    assert last is _note(win)
    assert lay.itemAt(lay.count() - 2).spacerItem() is not None, \
        "a stretch above it pushes it to the bottom edge"


def test_the_discard_is_an_amber_notice_not_only_a_log_line(qtbot, tmp_path, monkeypatch):
    win = _calibrated_at_stretch(qtbot, tmp_path, monkeypatch)
    win._apply_picked_stretch({"amount": 0.24, "linked": False})
    win._panel.apply_btn.click(); qtbot.wait(50)
    assert "discarded" in win._warning.text().lower()
