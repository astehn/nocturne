import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from seestar_processor.ui.main_window import MainWindow  # noqa: E402


def _make_fits(tmp_path):
    arr = (np.random.rand(3, 24, 24) * 1000).astype(np.uint16)
    p = tmp_path / "stack.fits"
    fits.PrimaryHDU(arr).writeto(str(p))
    return str(p)


def _window(qtbot, tmp_path):
    win = MainWindow(settings_path=str(tmp_path / "settings.json"))
    win._async_enabled = False  # run step processing synchronously in tests
    qtbot.addWidget(win)
    return win


def test_open_fits_stays_on_import_with_metadata(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win.project is not None
    assert win.current_stage_id() == "load"
    assert win._panel.panel_kind == "import"
    assert "24x24" in win._panel.meta_label.text()


def test_default_in_app_path_navigation(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    seq = ["destination", "crop", "background", "color", "stretch", "levels",
           "saturation", "noise_sharpen", "local_contrast", "star_reduction", "export"]
    for sid in seq:
        win.go_next()
        assert win.current_stage_id() == sid
    win.go_next()  # clamp
    assert win.current_stage_id() == "export"


def test_external_destination_changes_tail(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("destination")
    win.set_destination("external")
    ids = [s.id for s in win._stages]
    assert ids[-1] == "export_external"
    assert "saturation" not in ids
    win.go_next()
    assert win.current_stage_id() == "crop"


def test_apply_stretch_sets_nonlinear(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.6)  # slider amount
    assert win.project.current().is_linear is False
    assert win.project.entries()[-1][0] == "Stretch"


def test_apply_does_not_auto_advance(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert win.current_stage_id() == "stretch"  # stays put for before/after


def test_apply_ignored_while_busy(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win._busy = True
    win.apply_current(0.6)
    assert win.project.entries() == []  # nothing applied while busy


def test_entering_crop_enables_overlay(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    # bordered image so detect_content_bounds is a sub-rectangle
    arr = np.zeros((3, 30, 30), dtype=np.uint16)
    arr[:, 5:25, 6:24] = 2000
    p = tmp_path / "b.fits"
    fits.PrimaryHDU(arr).writeto(str(p))
    win.open_fits(str(p))
    win._go_to_id("crop")
    assert win.image_view._body is not None  # overlay active
    assert win.image_view.crop_bounds() == (5, 25, 6, 24)


def test_apply_color_with_none_option(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("color")
    win.apply_current(None)  # auto panel emits None
    assert win.project.entries()[-1][0] == "Color"


def test_apply_crop_with_params_changes_dimensions(qtbot, tmp_path):
    from seestar_processor.core.crop import CropParams
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("crop")
    win.apply_current(CropParams(bounds=(4, 20, 4, 20)))
    h, w, _ = win.project.current().data.shape
    assert (h, w) == (16, 16)


def test_step_for_types(qtbot, tmp_path):
    from seestar_processor.steps.crop import CropStep
    from seestar_processor.steps.saturation_step import SaturationStep
    from seestar_processor.steps.noise_sharpen import NoiseSharpenStep
    from seestar_processor.steps.levels import LevelsStep
    from seestar_processor.steps.local_contrast import LocalContrastStep
    from seestar_processor.steps.star_reduction import StarReductionStep
    win = _window(qtbot, tmp_path)
    assert isinstance(win._step_for("crop"), CropStep)
    assert isinstance(win._step_for("saturation"), SaturationStep)
    assert isinstance(win._step_for("noise_sharpen"), NoiseSharpenStep)
    assert isinstance(win._step_for("levels"), LevelsStep)
    assert isinstance(win._step_for("local_contrast"), LocalContrastStep)
    assert isinstance(win._step_for("star_reduction"), StarReductionStep)


def test_apply_levels_stays_on_step_and_logs(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("levels")
    win.apply_current((0.2, 1.0, 1.0))
    assert win.current_stage_id() == "levels"
    assert win.project.entries()[-1][0] == "Levels"
    assert "Levels" in win.log_panel.text()


def test_histogram_updates_on_open(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win.histogram_view._hist is not None


def test_before_after_toggle_enables_compare(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._ba_act.setChecked(True)
    win._toggle_before_after()
    assert win.image_view.compare_active() is True
    win._ba_act.setChecked(False)
    win._toggle_before_after()
    assert win.image_view.compare_active() is False


def test_window_title_is_app_name(qtbot, tmp_path):
    from seestar_processor import APP_NAME
    win = _window(qtbot, tmp_path)
    assert win.windowTitle() == APP_NAME


def test_help_menu_actions_exist(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert win._help_act is not None and win._about_act is not None


def test_save_recipe_writes_loadable_file(qtbot, tmp_path, monkeypatch):
    from seestar_processor.recipe import load_recipe
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    out = str(tmp_path / "r.json")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._save_recipe()
    assert [s["stage"] for s in load_recipe(out).steps] == ["stretch"]


def test_open_bad_file_does_not_crash(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    bad = tmp_path / "bad.fits"
    bad.write_text("not a fits file")
    win.open_fits(str(bad))  # must not raise
    assert win.project is None
    assert "open" in win._status.text().lower()


def test_export_failure_is_surfaced(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    ok = win._guarded(lambda: (_ for _ in ()).throw(OSError("disk full")))
    assert ok is False
    assert "disk full" in win._status.text()


def test_background_off_records_no_history(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("background")
    win.apply_current("off")
    assert "Background" not in [n for n, _ in win.project.entries()]
    assert win.current_stage_id() == "background"  # stays put


def test_status_cleared_on_navigation(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._status.setText("some error")
    win._go_to_id("destination")
    assert win._status.text() == ""


def test_tools_label_reflects_configured_paths(qtbot, tmp_path):
    from seestar_processor.settings import Settings
    gx = tmp_path / "graxpert"
    gx.write_text("#!/bin/sh\n")
    win = _window(qtbot, tmp_path)
    win.settings = Settings(graxpert_path=str(gx))  # rc-astro left empty
    win._update_tools_label()
    text = win._tools_label.text()
    assert "GraXpert ✓" in text          # configured → green check
    assert "RC-Astro ✗" in text          # not set → red cross
    assert "#3fb950" in text and "#f85149" in text  # green + red colors present


def test_log_records_applied_step(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.6)
    log = win.log_panel.text()
    assert "Stretch" in log and "Δ" in log


def test_log_records_open(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert "Opened" in win.log_panel.text()


def test_log_toggle_hides_panel(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._log_act.setChecked(False)
    win._toggle_log()
    assert win.log_panel.isHidden() is True


def test_export_external_panel_split_gated(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("destination")
    win.set_destination("external")
    win._go_to_id("export_external")
    # no RC-Astro configured -> split (item 1) disabled
    assert win._panel.fmt_box.model().item(1).isEnabled() is False


def test_open_image_loads_astroimage(qtbot, tmp_path):
    import numpy as np
    from seestar_processor.core.image import AstroImage
    win = _window(qtbot, tmp_path)
    win.open_image(AstroImage(np.zeros((12, 14, 3), np.float32), is_linear=True),
                   "stacked master")
    assert win.project is not None
    assert win.current_stage_id() == "load"
    assert "stacked master" in win.log_panel.text()
