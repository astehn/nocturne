import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from seestar_processor.ui.main_window import MainWindow  # noqa: E402


def test_open_and_stretch_updates_preview(qtbot, tmp_path):
    # synthetic Seestar-like color FITS
    arr = (np.random.rand(3, 32, 32) * 1000).astype(np.uint16)
    fpath = tmp_path / "stack.fits"
    fits.PrimaryHDU(arr).writeto(str(fpath))

    win = MainWindow(settings_path=str(tmp_path / "settings.json"))
    qtbot.addWidget(win)
    win.open_fits(str(fpath))
    assert win.project is not None
    assert win.project.current().is_linear is True

    win.apply_step(win.stretch_step, "Medium")
    assert win.project.current().is_linear is False
    assert win.preview_label.pixmap() is not None


def _open_with_two_steps(qtbot, tmp_path):
    arr = (np.random.rand(3, 16, 16) * 1000).astype(np.uint16)
    fpath = tmp_path / "stack.fits"
    fits.PrimaryHDU(arr).writeto(str(fpath))
    win = MainWindow(settings_path=str(tmp_path / "settings.json"))
    qtbot.addWidget(win)
    win.open_fits(str(fpath))
    win.apply_step(win.stretch_step, "Small")
    win.apply_step(win.stretch_step, "Medium")
    return win


def test_undo_keeps_step_list_in_sync(qtbot, tmp_path):
    win = _open_with_two_steps(qtbot, tmp_path)
    # Load + 2 steps -> 3 rows
    assert win.step_list.count() == 3
    win._undo()
    # after undo, list must shrink to Load + 1 entry (no stale rows)
    assert win.step_list.count() == 1 + len(win.project.entries())
    assert win.step_list.count() == 2


def test_clicking_step_row_does_not_crash_after_undo(qtbot, tmp_path):
    win = _open_with_two_steps(qtbot, tmp_path)
    win._undo()
    # clicking the last currently-valid row must not raise (regression: stale
    # row -> jump_back IndexError). Iterate every visible row to be safe.
    for row in range(win.step_list.count()):
        win._on_step_clicked(win.step_list.item(row))
    assert win.project is not None
