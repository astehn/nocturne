import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from seestar_processor.ui.main_window import MainWindow  # noqa: E402
from seestar_processor.core.image import AstroImage  # noqa: E402


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
    seq = ["crop", "background", "color", "deconvolution", "stretch", "levels",
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
    assert "GraXpert" in text and "RC-Astro" in text     # names present
    # Only the mark is coloured, not the label text.
    assert 'color:#3fb950">✓</span>' in text             # works → green check
    assert 'color:#f85149">✗</span>' in text             # not set → red cross
    assert '#3fb950">GraXpert' not in text               # label itself is not coloured
    assert '#f85149">RC-Astro' not in text


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


def test_colourise_records_and_is_stretched(qtbot, tmp_path):
    win = _window(qtbot, tmp_path); win._async_enabled = False
    win.open_fits(_make_fits(tmp_path))
    win._colourise()                                   # no RC-Astro -> whole-image colour
    names = [n for n, _ in win.project.entries()]
    assert names[-1] == "Colourise"
    assert win.project.current().is_linear is False


def test_colourise_preserved_after_later_step(qtbot, tmp_path):
    win = _window(qtbot, tmp_path); win._async_enabled = False
    win.open_fits(_make_fits(tmp_path))
    win._colourise()
    win._go_to_id("saturation")
    win.apply_current(0.6)
    names = [n for n, _ in win.project.entries()]
    assert "Colourise" in names and "Saturation" in names
    assert names.index("Colourise") < names.index("Saturation")


def test_colourise_marks_stretch_done(qtbot, tmp_path):
    win = _window(qtbot, tmp_path); win._async_enabled = False
    win.open_fits(_make_fits(tmp_path))
    win._colourise()
    assert "stretch" in win._done_ids()


def test_colourise_caches_star_removal(qtbot, tmp_path, monkeypatch):
    import seestar_processor.ui.main_window as mw
    win = _window(qtbot, tmp_path); win._async_enabled = False
    win.open_fits(_make_fits(tmp_path))
    monkeypatch.setattr(mw, "rcastro_valid", lambda s: True)
    calls = []
    def fake_remove(img):
        calls.append(1)
        half = AstroImage(img.data * 0.5, is_linear=True)
        return half, half
    win._remove_stars = fake_remove
    win._colourise()
    win._colourise()                                   # same base -> cache hit
    assert len(calls) == 2                             # two passes on first call, zero on cache hit
    assert [n for n, _ in win.project.entries()][-1] == "Colourise"


def test_open_image_invalidates_colourise_cache(qtbot, tmp_path):
    from seestar_processor.core.image import AstroImage
    win = _window(qtbot, tmp_path)
    win.open_image(AstroImage(np.zeros((8, 8, 3), np.float32), is_linear=True), "a")
    win._colourise_layers = ("stale-sig", object(), object())
    win.open_image(AstroImage(np.ones((8, 8, 3), np.float32), is_linear=True), "b")
    assert win._colourise_layers is None         # loading a new image clears the cache


def test_open_advanced_palette_requires_image(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._open_advanced_palette()                       # no project -> guarded, no crash
    assert win._status.text() == ""                    # new behavior: silently returns


def test_record_colourise_adds_history_step(qtbot, tmp_path):
    win = _window(qtbot, tmp_path); win._async_enabled = False
    win.open_fits(_make_fits(tmp_path))
    win._record_colourise(AstroImage(np.zeros((12, 12, 3), np.float32), is_linear=False))
    assert [n for n, _ in win.project.entries()][-1] == "Colourise"


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


def test_remove_green_records_undoable_entry_and_reduces_green(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("color")
    before = win.project.current()
    green_before = float(before.data[..., 1].mean()) if before.data.ndim == 3 else 0.0
    win._remove_green()
    names = [n for n, _ in win.project.entries()]
    assert names[-1] == "Remove Green"
    after = win.project.current()
    if after.data.ndim == 3:
        assert float(after.data[..., 1].mean()) <= green_before + 1e-6
    win.project.undo()
    assert "Remove Green" not in [n for n, _ in win.project.entries()]


def test_remove_green_preserved_after_later_step(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("color")
    win._remove_green()
    win._go_to_id("stretch")
    win.apply_current(0.5)
    names = [n for n, _ in win.project.entries()]
    assert "Remove Green" in names and "Stretch" in names
    assert names.index("Remove Green") < names.index("Stretch")


def test_reset_action_disabled_until_loaded(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert win._reset_act.isEnabled() is False
    win.open_fits(_make_fits(tmp_path))
    assert win._reset_act.isEnabled() is True
    assert win._source_base is not None and win._source_label


def test_reset_confirmed_clears_history(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    import numpy as np
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    base = win.project.current().data.copy()
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert win.project.entries()                      # has edits
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    win._reset_image()
    assert win.project.entries() == []                # history cleared
    assert win._stages[win._stage].id == "load"       # back on Import
    assert np.array_equal(win.project.current().data, base)


def test_reset_declined_keeps_edits(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.No)
    win._reset_image()
    assert any(n == "Stretch" for n, _ in win.project.entries())   # edit survived


def test_advanced_open_then_cancel_preserves_history(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._colourise()
    before = [n for n, _ in win.project.entries()]

    class _FakeDialog:                              # Cancel: opens, never calls on_apply
        def __init__(self, *a, **k):
            pass
        def exec(self):
            return 0

    monkeypatch.setattr("seestar_processor.ui.palette_dialog.PaletteDialog", _FakeDialog)
    win._open_advanced_palette()
    assert [n for n, _ in win.project.entries()] == before   # nothing lost on cancel


def test_advanced_apply_records_colourise(qtbot, tmp_path, monkeypatch):
    from seestar_processor.core.image import AstroImage
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    result = AstroImage(np.zeros((12, 12, 3), np.float32), is_linear=False)

    class _FakeDialog:                              # Apply: invokes the on_apply callback
        def __init__(self, *a, **k):
            self._cb = k.get("on_apply")
        def exec(self):
            self._cb(result)
            return 1

    monkeypatch.setattr("seestar_processor.ui.palette_dialog.PaletteDialog", _FakeDialog)
    win._open_advanced_palette()
    assert [n for n, _ in win.project.entries()][-1] == "Colourise"


def test_open_advanced_palette_guarded_when_busy(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._busy = True
    win._open_advanced_palette()                    # guarded: no crash, no history change
    assert win.project.entries() == []


def test_colourise_starx_extracts_stars_from_stretched(qtbot, tmp_path, monkeypatch):
    import seestar_processor.ui.main_window as mw
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    monkeypatch.setattr(mw, "rcastro_valid", lambda s: True)
    seen_linear = []
    def fake_remove(img):
        seen_linear.append(img.is_linear)
        half = AstroImage(img.data * 0.5, is_linear=img.is_linear)
        return half, half
    win._remove_stars = fake_remove
    base = win.project.current()
    starless, stars = win._colourise_starx(base)
    # StarX was run on BOTH a linear image (for the starless) and a stretched one (for stars)
    assert True in seen_linear and False in seen_linear
    assert stars is not None


def test_geometry_after_processing_reapply_no_corruption(qtbot, tmp_path):
    from seestar_processor.core.crop import CropParams
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("crop")
    win._apply_geometry("Crop", CropParams(bounds=(4, 20, 4, 20)))  # -> 16x16
    win._go_to_id("stretch")
    win.apply_current(0.5)                       # Crop, Stretch
    win._go_to_id("crop")
    win._flip_h()                                # geometry after processing
    win._go_to_id("stretch")
    win.apply_current(0.5)                        # re-apply Stretch
    names = [n for n, _ in win.project.entries()]
    assert names.count("Stretch") == 1           # NOT double-applied
    assert "Flip H" in names and "Crop" in names # geometry preserved
    assert win.project.current().data.shape[:2] == (16, 16)
