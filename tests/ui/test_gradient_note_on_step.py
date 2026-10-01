"""'Show what was removed' changes nothing, so it writes nothing to the log
(Andreas, 2026-10-01: a view toggle sat in the record of edits between
Background and Deconvolution). Its one new fact — how much was removed — is
shown on the step, under the checkbox, while the view is on."""
import numpy as np

from nocturne.core.image import AstroImage

from tests.ui.test_main_window import _make_fits, _window


def _with_background(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("background")
    before = win.project.current()
    data = before.data.astype(np.float32)          # (h, w) or (h, w, 3)
    h, w = data.shape[:2]
    ramp = np.tile(np.linspace(0.0, 0.2, w, dtype=np.float32), (h, 1))
    if data.ndim == 3:
        ramp = ramp[..., None]
    after = AstroImage(np.clip(data - ramp, 0, None), is_linear=True)
    monkeypatch.setattr(win, "_background_states", lambda: (before, after))
    return win


def test_ticking_it_shows_the_size_on_the_step_not_in_the_log(qtbot, tmp_path, monkeypatch):
    win = _with_background(qtbot, tmp_path, monkeypatch)
    before = win.activity.text()
    win._panel.show_model_check.setChecked(True)
    note = win._panel.show_model_note
    assert note.isVisibleTo(win._panel)
    assert "%" in note.text() and "removed" in note.text().lower()
    assert "removed gradient" not in win.activity.text()[len(before):].lower()


def test_unticking_hides_it(qtbot, tmp_path, monkeypatch):
    win = _with_background(qtbot, tmp_path, monkeypatch)
    win._panel.show_model_check.setChecked(True)
    win._panel.show_model_check.setChecked(False)
    assert not win._panel.show_model_note.isVisibleTo(win._panel)
