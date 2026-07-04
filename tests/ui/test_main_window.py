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
    seq = ["crop", "background", "color", "stretch", "levels",
           "saturation", "noise_sharpen", "local_contrast", "star_reduction", "export"]
    for sid in seq:
        win.go_next()
        assert win.current_stage_id() == sid
    win.go_next()  # clamp
    assert win.current_stage_id() == "export"


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


def test_apply_geometry_crop_changes_dimensions(qtbot, tmp_path):
    from seestar_processor.core.crop import CropParams
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("crop")
    win._apply_geometry("Crop", CropParams(bounds=(4, 20, 4, 20)))
    h, w, _ = win.project.current().data.shape
    assert (h, w) == (16, 16)


def test_rotate_adds_step_and_swaps_dims(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))          # _make_fits is 24x24; use a non-square below
    win._go_to_id("crop")
    from seestar_processor.core.crop import CropParams
    win._apply_geometry("Crop", CropParams(bounds=(0, 24, 4, 20)))  # 24x16
    before = win.project.current().data.shape[:2]
    win._rotate()
    after = win.project.current().data.shape[:2]
    assert after == (before[1], before[0])       # 90° swaps H/W
    assert win.project.entries()[-1][0] == "Rotate"


def test_flip_after_crop_does_not_recrop(qtbot, tmp_path):
    from seestar_processor.core.crop import CropParams
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("crop")
    win._apply_geometry("Crop", CropParams(bounds=(4, 20, 4, 20)))  # -> 16x16
    dims_after_crop = win.project.current().data.shape[:2]
    win._flip_h()
    assert win.project.current().data.shape[:2] == dims_after_crop  # flip didn't re-crop
    assert win.project.entries()[-1][0] == "Flip H"


def test_processing_preserves_geometry(qtbot, tmp_path):
    from seestar_processor.core.crop import CropParams
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("crop")
    win._apply_geometry("Crop", CropParams(bounds=(4, 20, 4, 20)))  # -> 16x16
    win._go_to_id("stretch")
    win.apply_current(0.5)
    names = [n for n, _ in win.project.entries()]
    assert "Crop" in names and "Stretch" in names
    assert win.project.current().data.shape[:2] == (16, 16)         # crop preserved


def test_undo_reverses_one_geometry_op(qtbot, tmp_path):
    from seestar_processor.core.crop import CropParams
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("crop")
    win._apply_geometry("Crop", CropParams(bounds=(4, 20, 4, 20)))
    win._rotate()
    win.project.undo()
    assert win.project.entries()[-1][0] == "Crop"                   # rotate undone, crop remains


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
    win._go_to_id("crop")
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


def test_open_image_loads_astroimage(qtbot, tmp_path):
    import numpy as np
    from seestar_processor.core.image import AstroImage
    win = _window(qtbot, tmp_path)
    win.open_image(AstroImage(np.zeros((12, 14, 3), np.float32), is_linear=True),
                   "stacked master")
    assert win.project is not None
    assert win.current_stage_id() == "load"
    assert "stacked master" in win.log_panel.text()


def test_open_palette_requires_image(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)          # no image loaded
    win._open_palette()
    assert "open" in win._status.text().lower()


def test_record_palette_adds_history_step(qtbot, tmp_path):
    import numpy as np
    from seestar_processor.core.image import AstroImage
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._record_palette(AstroImage(np.zeros((12, 12, 3), np.float32), is_linear=False))
    assert win.project.entries()[-1][0] == "Palette"


def test_toolbar_actions_have_icons(qtbot, tmp_path):
    from PySide6.QtWidgets import QToolBar
    win = _window(qtbot, tmp_path)
    main = next(b for b in win.findChildren(QToolBar) if b.windowTitle() == "Main")
    labelled = [a for a in main.actions() if a.text()]
    assert labelled, "toolbar has labelled actions"
    assert all(not a.icon().isNull() for a in labelled), "every labelled action has an icon"


def test_chrome_hidden_until_image_loaded(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert win.stepper.isHidden() is True          # full-bleed welcome
    assert win._right_panel.isHidden() is True
    win.open_fits(_make_fits(tmp_path))
    assert win.stepper.isHidden() is False         # chrome revealed on load
    assert win._right_panel.isHidden() is False


def test_center_stack_switches_on_open(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    # welcome page shown before any image is loaded
    assert win._center_stack.currentIndex() == 0
    win.open_fits(_make_fits(tmp_path))
    # image page shown after loading
    assert win._center_stack.currentIndex() == 1
    assert win._center_stack.currentWidget() is win.image_view


def test_toolbar_has_about_button(qtbot, tmp_path):
    from PySide6.QtWidgets import QToolBar
    win = _window(qtbot, tmp_path)
    main = next(b for b in win.findChildren(QToolBar) if b.windowTitle() == "Main")
    about = [a for a in main.actions() if a.text() == "About"]
    assert about and not about[0].icon().isNull()


def test_show_about_opens_dialog(qtbot, tmp_path):
    from seestar_processor.ui.about_dialog import AboutDialog
    win = _window(qtbot, tmp_path)
    dlg = win._make_about_dialog()
    qtbot.addWidget(dlg)
    assert isinstance(dlg, AboutDialog)
    assert "Photon Donors" in dlg.body.text()


def test_export_final_split_writes_two_tiffs(qtbot, tmp_path, monkeypatch):
    import numpy as np
    from PySide6.QtWidgets import QFileDialog
    from seestar_processor.settings import Settings
    from seestar_processor.core.image import AstroImage
    import seestar_processor.ui.main_window as mw

    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    # RC-Astro "configured" so the split path is allowed
    rc_bin = tmp_path / "rc"; rc_bin.write_text("#!/bin/sh\n")
    win.settings = Settings(rcastro_path=str(rc_bin))

    out = tmp_path / "splitout"; out.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(out)))

    class _FakeRC:
        def __init__(self, *a, **k):
            pass
        def remove_stars(self, img, runner=None):
            base = AstroImage(np.zeros((8, 8, 3), np.float32))
            return base, base

    monkeypatch.setattr(mw, "RCAstro", _FakeRC)
    win.export_final("Starless + Stars (two TIFFs)")
    assert (out / "starless.tif").exists()
    assert (out / "stars.tif").exists()


def test_export_final_single_file(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    out = tmp_path / "pic.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    win.export_final("PNG")
    assert out.exists()


def test_next_from_load_is_crop(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("load")
    win.go_next()
    assert win.current_stage_id() == "crop"
