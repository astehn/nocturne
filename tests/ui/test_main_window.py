import shutil

import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from seestar_processor.ui.main_window import MainWindow  # noqa: E402


def _fake_bg_runner(args):
    """Stand in for the GraXpert CLI: copy the input FITS to the output path."""
    import os
    in_fits = next(a for a in args if a.endswith(".fits") and os.path.exists(a))
    out_path = args[args.index("-output") + 1]
    shutil.copy(in_fits, out_path)


def _make_fits(tmp_path):
    arr = (np.random.rand(3, 24, 24) * 1000).astype(np.uint16)
    p = tmp_path / "stack.fits"
    fits.PrimaryHDU(arr).writeto(str(p))
    return str(p)


def _window(qtbot, tmp_path):
    win = MainWindow(settings_path=str(tmp_path / "settings.json"))
    qtbot.addWidget(win)
    return win


def test_open_fits_loads_and_advances_to_crop(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win.project is not None
    assert win.project.current().is_linear is True
    assert win.current_stage_id() == "crop"


def test_next_walks_enabled_stages_and_skips_stars(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))           # at "crop"
    expected = ["background", "color", "deconvolution", "noise",
                "stretch", "final_fixes", "export"]
    for stage_id in expected:
        win.go_next()
        assert win.current_stage_id() == stage_id
    win.go_next()                                  # clamp at end (stars skipped)
    assert win.current_stage_id() == "export"


def test_back_skips_disabled_stages(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("export")
    win.go_back()                                  # final_fixes (skips stars)
    assert win.current_stage_id() == "final_fixes"
    win.go_back()                                  # stretch
    assert win.current_stage_id() == "stretch"
    win.go_back()                                  # noise
    assert win.current_stage_id() == "noise"


def test_apply_crop_changes_dimensions_and_advances(qtbot, tmp_path):
    from seestar_processor.core.crop import CropSettings
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))           # at crop, image 24x24
    win.apply_current(CropSettings(aspect="16:9"))
    h, w, _ = win.project.current().data.shape
    assert (h, w) != (24, 24)
    assert win.current_stage_id() == "background"  # advanced past crop


def test_apply_stretch_marks_nonlinear_and_advances(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current("Medium")
    assert win.project.current().is_linear is False
    assert win.current_stage_id() == "final_fixes"


def test_reapply_stretch_does_not_duplicate_history(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current("Small")
    win._go_to_id("stretch")                       # navigate back to stretch
    win.apply_current("Large")
    names = [n for n, _ in win.project.entries()]
    assert names.count("Stretch") == 1


def test_panel_matches_current_stage(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win._panel.panel_kind == "crop"        # crop
    win.go_next()
    assert win._panel.panel_kind == "process"     # background
    win.go_next()
    assert win._panel.panel_kind == "color"       # color
    win.go_next()
    assert win._panel.panel_kind == "process"     # deconvolution
    win.go_next()
    assert win._panel.panel_kind == "process"     # noise
    win.go_next()
    assert win._panel.panel_kind == "stretch"
    win.go_next()
    assert win._panel.panel_kind == "final_fixes"


def test_navigation_never_crashes_after_undo(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._bg_runner = _fake_bg_runner               # no real GraXpert binary
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("background")
    win.apply_current("Small")                     # background -> color
    win._go_to_id("stretch")
    win.apply_current("Medium")                    # stretch -> export
    assert [n for n, _ in win.project.entries()] == ["Background", "Stretch"]
    win._undo()
    for sid in ("load", "crop", "background", "color", "deconvolution",
                "noise", "stretch", "final_fixes", "export"):
        win._go_to_id(sid)
    assert win.project is not None
