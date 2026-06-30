import shutil

import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from seestar_processor.ui.main_window import MainWindow  # noqa: E402


def _fake_bg_runner(args):
    """Stand in for the GraXpert CLI: copy the input FITS to the output path."""
    in_fits = args[3]
    out_stem = args[args.index("-output") + 1]
    shutil.copy(in_fits, out_stem + ".fits")


def _make_fits(tmp_path):
    arr = (np.random.rand(3, 24, 24) * 1000).astype(np.uint16)
    p = tmp_path / "stack.fits"
    fits.PrimaryHDU(arr).writeto(str(p))
    return str(p)


def _window(qtbot, tmp_path):
    win = MainWindow(settings_path=str(tmp_path / "settings.json"))
    qtbot.addWidget(win)
    return win


def test_open_fits_loads_and_advances_to_background(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win.project is not None
    assert win.project.current().is_linear is True
    assert win.current_stage_id() == "background"


def test_next_skips_disabled_stages(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))           # at "background"
    win.go_next()                                  # skips color/decon/noise
    assert win.current_stage_id() == "stretch"
    win.go_next()
    assert win.current_stage_id() == "export"
    win.go_next()                                  # clamp at end
    assert win.current_stage_id() == "export"


def test_back_skips_disabled_stages(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.go_next()                                  # stretch
    win.go_back()                                  # background
    assert win.current_stage_id() == "background"
    win.go_back()                                  # load
    assert win.current_stage_id() == "load"


def test_apply_stretch_marks_nonlinear_and_advances(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.go_next()                                  # stretch stage
    win.apply_current("Medium")
    assert win.project.current().is_linear is False
    assert win.current_stage_id() == "export"


def test_reapply_stretch_does_not_duplicate_history(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.go_next()                                  # stretch
    win.apply_current("Small")
    win._go_to_id("stretch")                       # navigate back to stretch
    win.apply_current("Large")
    names = [n for n, _ in win.project.entries()]
    assert names.count("Stretch") == 1


def test_panel_matches_current_stage(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win._panel.panel_kind == "process"     # background
    win.go_next()
    assert win._panel.panel_kind == "stretch"


def test_navigation_never_crashes_after_undo(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._bg_runner = _fake_bg_runner               # no real GraXpert binary
    win.open_fits(_make_fits(tmp_path))
    win.apply_current("Small")                     # background -> stretch
    win.apply_current("Medium")                    # stretch -> export
    assert [n for n, _ in win.project.entries()] == ["Background", "Stretch"]
    win._undo()
    for sid in ("load", "background", "stretch", "export"):
        win._go_to_id(sid)
    assert win.project is not None
