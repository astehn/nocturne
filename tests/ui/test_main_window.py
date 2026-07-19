import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from nocturne.ui.main_window import MainWindow  # noqa: E402
from nocturne.core.image import AstroImage  # noqa: E402


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
    assert "24 × 24" in win._panel.meta_label.text()
    assert "Sony IMX585" in win._panel.meta_label.text()


def test_default_in_app_path_navigation(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    seq = ["crop", "background", "color", "deconvolution", "stretch", "levels",
           "saturation", "noise_sharpen", "local_contrast", "star_reduction",
           "enhancements", "export"]
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


def _bordered_window(qtbot, tmp_path):
    """A window on a bordered image so detect_content_bounds is a sub-rectangle."""
    win = _window(qtbot, tmp_path)
    arr = np.zeros((3, 30, 30), dtype=np.uint16)
    arr[:, 5:25, 6:24] = 2000
    p = tmp_path / "b.fits"
    fits.PrimaryHDU(arr).writeto(str(p))
    win.open_fits(str(p))
    return win


def test_entering_crop_leaves_box_hidden(qtbot, tmp_path):
    win = _bordered_window(qtbot, tmp_path)
    win._go_to_id("crop")
    # crop mode is on but the box is not drawn until the image is clicked
    assert win.image_view.crop_box_visible() is False
    assert win._panel.apply_btn.isEnabled() is False   # Apply disabled until box shown


def test_showing_crop_box_uses_content_bounds_and_enables_apply(qtbot, tmp_path):
    win = _bordered_window(qtbot, tmp_path)
    win._go_to_id("crop")
    win.image_view.show_crop_box()
    assert win.image_view.crop_box_visible() is True
    assert win.image_view.crop_bounds() == (5, 25, 6, 24)  # detected content edges
    assert win._panel.apply_btn.isEnabled() is True        # cropBoxShown -> Apply on


def test_apply_crop_hides_box_and_disables_apply(qtbot, tmp_path):
    win = _bordered_window(qtbot, tmp_path)
    win._go_to_id("crop")
    win.image_view.show_crop_box()
    win._apply_crop()
    assert win.project.entries()[-1][0] == "Crop"          # crop committed
    assert win.image_view.crop_box_visible() is False      # box hidden after apply
    assert win._panel.apply_btn.isEnabled() is False       # Apply disabled again


def test_crop_size_readout_updates_and_resets(qtbot, tmp_path):
    win = _bordered_window(qtbot, tmp_path)
    win._go_to_id("crop")
    assert win._panel.crop_size_label.text() == "—"   # reset by _setup_crop_overlay
    win.image_view.show_crop_box()
    win._update_crop_readout(0, 100, 0, 200)
    assert win._panel.crop_size_label.text() == "200 × 100 px"


def test_apply_color_with_none_option(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("color")
    win.apply_current(None)  # auto panel emits None
    assert win.project.entries()[-1][0] == "Color"


def test_apply_geometry_crop_changes_dimensions(qtbot, tmp_path):
    from nocturne.core.crop import CropParams
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
    from nocturne.core.crop import CropParams
    win._apply_geometry("Crop", CropParams(bounds=(0, 24, 4, 20)))  # 24x16
    before = win.project.current().data.shape[:2]
    win._rotate()
    after = win.project.current().data.shape[:2]
    assert after == (before[1], before[0])       # 90° swaps H/W
    assert win.project.entries()[-1][0] == "Rotate"


def test_flip_after_crop_does_not_recrop(qtbot, tmp_path):
    from nocturne.core.crop import CropParams
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("crop")
    win._apply_geometry("Crop", CropParams(bounds=(4, 20, 4, 20)))  # -> 16x16
    dims_after_crop = win.project.current().data.shape[:2]
    win._flip_h()
    assert win.project.current().data.shape[:2] == dims_after_crop  # flip didn't re-crop
    assert win.project.entries()[-1][0] == "Flip H"


def test_processing_preserves_geometry(qtbot, tmp_path):
    from nocturne.core.crop import CropParams
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
    from nocturne.core.crop import CropParams
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("crop")
    win._apply_geometry("Crop", CropParams(bounds=(4, 20, 4, 20)))
    win._rotate()
    win.project.undo()
    assert win.project.entries()[-1][0] == "Crop"                   # rotate undone, crop remains


def test_step_for_types(qtbot, tmp_path):
    from nocturne.steps.crop import CropStep
    from nocturne.steps.saturation_step import SaturationStep
    from nocturne.steps.noise_sharpen import NoiseSharpenStep
    from nocturne.steps.levels import LevelsStep
    from nocturne.steps.local_contrast import LocalContrastStep
    from nocturne.steps.star_reduction import StarReductionStep
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
    win._go_to_id("stretch")
    win.apply_current(0.5)          # Levels operates on the stretched image
    win._go_to_id("levels")
    win.apply_current((0.2, 1.0, 1.0))
    assert win.current_stage_id() == "levels"
    assert win.project.entries()[-1][0] == "Levels"
    assert "Levels" in win.log_panel.text()


def test_levels_refused_on_linear_image(qtbot, tmp_path):
    # Belt-and-suspenders: navigation auto-stretches, but undoing that leaves us
    # on Levels with a linear image. Applying Levels then would clip the tiny
    # linear values (~0.003) to black; the guard must refuse with a hint instead.
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("levels")                         # auto-stretches, lands on Levels
    win._undo()                                     # undo the auto-stretch -> linear again
    assert win.current_stage_id() == "levels"
    assert win.project.current().is_linear
    names_before = [n for n, _ in win.project.entries()]
    win.apply_current((0.01, 1.0, 1.0))             # a tiny black-point nudge
    assert [n for n, _ in win.project.entries()] == names_before   # nothing applied
    assert win.project.current().is_linear          # image untouched, not blacked out
    assert "Stretch" in win._status.text()


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
    from nocturne import APP_NAME
    win = _window(qtbot, tmp_path)
    assert win.windowTitle() == APP_NAME


def test_help_menu_actions_exist(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert win._help_act is not None and win._about_act is not None


def test_save_recipe_writes_loadable_file(qtbot, tmp_path, monkeypatch):
    from nocturne.recipe import load_recipe
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


def test_export_single_routes_through_run_busy(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    out = tmp_path / "pic.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    calls = []
    monkeypatch.setattr(win, "_run_busy",
                        lambda work, on_result, label, err_prefix: calls.append(label))
    win.export_final("PNG")
    assert calls == ["Exporting…"]     # export now goes through the busy helper


def test_export_failure_is_surfaced(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    import nocturne.ui.main_window as mw
    win = _window(qtbot, tmp_path)  # _async_enabled = False -> inline
    win.open_fits(_make_fits(tmp_path))
    out = tmp_path / "pic.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(mw, "save_png",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    win.export_final("PNG")
    assert "Export failed: disk full" in win._status.text()
    assert win._busy is False


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
    from nocturne.settings import Settings
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
    from nocturne.core.image import AstroImage
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
    import nocturne.ui.main_window as mw
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
    from nocturne.core.image import AstroImage
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
    from nocturne.ui.about_dialog import AboutDialog
    win = _window(qtbot, tmp_path)
    dlg = win._make_about_dialog()
    qtbot.addWidget(dlg)
    assert isinstance(dlg, AboutDialog)
    assert "Photon Donors" in dlg.body.text()


def test_export_final_split_writes_two_tiffs(qtbot, tmp_path, monkeypatch):
    import numpy as np
    from PySide6.QtWidgets import QFileDialog
    from nocturne.settings import Settings
    from nocturne.core.image import AstroImage
    import nocturne.ui.main_window as mw

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


def test_export_clears_stale_error_on_success(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._status.setText("Export failed: disk full")   # stale error from a prior attempt
    out = tmp_path / "pic.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    win.export_final("PNG")
    assert out.exists()
    assert win._status.text() == ""   # stale error cleared on the successful export


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

    monkeypatch.setattr("nocturne.ui.palette_dialog.PaletteDialog", _FakeDialog)
    win._open_advanced_palette()
    assert [n for n, _ in win.project.entries()] == before   # nothing lost on cancel


def test_advanced_apply_records_colourise(qtbot, tmp_path, monkeypatch):
    from nocturne.core.image import AstroImage
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    result = AstroImage(np.zeros((12, 12, 3), np.float32), is_linear=False)

    class _FakeDialog:                              # Apply: invokes the on_apply callback
        def __init__(self, *a, **k):
            self._cb = k.get("on_apply")
        def exec(self):
            self._cb(result)
            return 1

    monkeypatch.setattr("nocturne.ui.palette_dialog.PaletteDialog", _FakeDialog)
    win._open_advanced_palette()
    assert [n for n, _ in win.project.entries()][-1] == "Colourise"


def test_open_advanced_palette_guarded_when_busy(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._busy = True
    win._open_advanced_palette()                    # guarded: no crash, no history change
    assert win.project.entries() == []


def test_colourise_starx_extracts_stars_from_stretched(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
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
    from nocturne.core.crop import CropParams
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


def test_deconvolution_applied_and_preserved_after_stretch(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)                 # _async_enabled False
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("deconvolution")
    win.apply_current("medium")                    # free unsharp fallback (no RC-Astro in tests)
    assert win.project.entries()[-1][0] == "Deconvolution"
    win._go_to_id("stretch")
    win.apply_current(0.5)
    names = [n for n, _ in win.project.entries()]
    assert "Deconvolution" in names and "Stretch" in names
    assert names.index("Deconvolution") < names.index("Stretch")   # preserved before the reveal


def test_enhance_appends_undoable_steps(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)                    # _async_enabled False
    win.open_fits(_make_fits(tmp_path))
    before = win.project.current().data.copy()
    win._enhance("Boost Red")
    assert win.project.entries()[-1][0] == "Boost Red"
    assert not np.allclose(win.project.current().data, before)   # image changed
    win._enhance("Darken Sky")                        # taps stack
    names = [n for n, _ in win.project.entries()]
    assert names[-2:] == ["Boost Red", "Darken Sky"]
    win.project.undo()                                # Undo peels one off
    assert win.project.entries()[-1][0] == "Boost Red"
    assert "enhancements" in win._done_ids()


def test_enhance_truncated_by_earlier_step(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._enhance("Boost Blue")
    win._go_to_id("saturation")
    win.apply_current(0.6)                             # earlier processing step
    names = [n for n, _ in win.project.entries()]
    assert "Boost Blue" not in names                  # trailing enhancement truncated


def test_run_busy_clears_busy_when_on_result_raises(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)  # _async_enabled = False -> inline
    win.open_fits(_make_fits(tmp_path))

    def boom(_result):
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError):
        win._run_busy(lambda: 1, boom, "Working…", "Failed")
    assert win._busy is False  # finally cleared it despite the throw


def test_run_busy_reports_error_prefix(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))

    def work():
        raise ValueError("disk full")

    win._run_busy(work, lambda r: None, "Working…", "Export failed")
    assert win._busy is False
    assert "Export failed: disk full" in win._status.text()


def test_set_busy_gates_immediately_but_delays_visuals(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._set_busy(True, "Applying Stretch…")
    assert win._busy is True
    assert win._back_btn.isEnabled() is False          # gate is immediate
    assert win._busy_shown is False                    # visuals delayed by the timer
    assert win._busy_timer.isActive() is True
    win._set_busy(False)
    assert win._busy is False
    assert win._busy_timer.isActive() is False
    assert win._back_btn.isEnabled() is True


def test_show_and_hide_busy_visuals_balance_cursor(qtbot, tmp_path):
    from PySide6.QtWidgets import QApplication
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._busy_label_text = "Colourising…"
    win._show_busy_visuals()
    assert win._busy_shown is True
    assert win._busy_bar.isHidden() is False
    assert "Colourising…" in win._busy_label.text()
    assert win._cursor_active is True
    win._hide_busy_visuals()
    assert win._busy_shown is False
    assert win._busy_bar.isHidden() is True
    assert win._busy_label.text() == ""
    assert win._cursor_active is False
    assert QApplication.overrideCursor() is None       # balanced, no leftover override


def test_navigating_to_levels_auto_stretches(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win.project.current().is_linear
    win._go_to_id("levels")
    names = [n for n, _ in win.project.entries()]
    assert "Stretch" in names
    assert not win.project.current().is_linear
    assert "Stretch (auto)" in win.log_panel.text()
    win.apply_current((0.2, 1.0, 1.0))
    assert win.project.entries()[-1][0] == "Levels"


def test_navigating_to_pre_stretch_step_does_not_auto_stretch(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("background")
    assert "Stretch" not in [n for n, _ in win.project.entries()]


def test_navigating_to_export_does_not_auto_stretch(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("export")
    assert "Stretch" not in [n for n, _ in win.project.entries()]
    assert win.project.current().is_linear


def test_already_stretched_is_not_double_stretched(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("saturation")
    names = [n for n, _ in win.project.entries()]
    assert names.count("Stretch") == 1


def test_auto_stretch_is_undoable(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("levels")
    assert not win.project.current().is_linear
    win._undo()
    assert win.project.current().is_linear


def test_explainer_shows_current_step_help(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("background")
    from nocturne.ui import help_content as hc
    assert hc.TOPICS["background"].summary in win._explainer.text()


def test_open_help_shows_requested_topic(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    dlg = win._open_help("stretch")
    qtbot.addWidget(dlg)
    from nocturne.ui import help_content as hc
    assert hc.TOPICS["stretch"].title in dlg.viewer.toPlainText()
    dlg.close()


def test_save_recipe_warns_and_cancels_on_uncaptured(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from nocturne.history.project import Project
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    # apply a real Stretch, then an append-only Enhancement (uncaptured)
    win._go_to_id("stretch"); win.apply_current(0.5)
    win._go_to_id("enhancements"); win._enhance("Boost Red")
    calls = {"dialog": 0}
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: (calls.__setitem__("dialog", calls["dialog"] + 1)
                                                      or QMessageBox.StandardButton.Cancel)))
    saved = {"n": 0}
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (saved.__setitem__("n", saved["n"] + 1), ("", ""))[1]))
    win._save_recipe()
    assert calls["dialog"] == 1            # warned about the uncaptured step
    assert saved["n"] == 0                  # cancel -> never reached the file dialog


def test_save_recipe_warns_then_saves_when_confirmed(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from nocturne.recipe import load_recipe
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch"); win.apply_current(0.5)
    win._go_to_id("enhancements"); win._enhance("Boost Red")
    out = str(tmp_path / "r.json")
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Save))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._save_recipe()
    # Saved the captured subset (Stretch), dropped the uncaptured Boost Red.
    stages = [s["stage"] for s in load_recipe(out).steps]
    assert "stretch" in stages


def test_closeevent_no_edits_accepts(qtbot, tmp_path):
    from PySide6.QtGui import QCloseEvent
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))          # loaded, no steps applied
    assert not win.project.entries()
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert ev.isAccepted()                       # no prompt, quits cleanly


def test_closeevent_with_edits_prompts_and_respects_choice(qtbot, tmp_path, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._rotate()                                # applies a Rotate step -> has edits
    assert win.project.entries()
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Cancel)
    ev = QCloseEvent(); win.closeEvent(ev)
    assert not ev.isAccepted()                   # Cancel -> stays open
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Discard)
    ev2 = QCloseEvent(); win.closeEvent(ev2)
    assert ev2.isAccepted()                      # Discard -> quits


def test_unlink_toggle_sets_flag_and_survives_rebuild(qtbot, tmp_path):
    win = MainWindow(settings_path=str(tmp_path / "settings.json"))
    qtbot.addWidget(win)
    assert win._display_unlinked is False
    win._on_unlink_toggle(True)
    assert win._display_unlinked is True
    win._go_to_id("crop")
    win._rebuild_panel()
    assert win._panel.unlink_check.isChecked() is True


def test_unlink_only_effective_on_crop_stage(qtbot, tmp_path):
    win = MainWindow(settings_path=str(tmp_path / "settings.json"))
    qtbot.addWidget(win)

    def idx(sid):
        return next(i for i, s in enumerate(win._stages) if s.id == sid)

    win._display_unlinked = True
    win._stage = idx("crop")
    assert win._effective_unlinked() is True
    # Stretch is still linear, but its preview must predict the linked commit.
    win._stage = idx("stretch")
    assert win._effective_unlinked() is False
    win._stage = idx("color")
    assert win._effective_unlinked() is False
    # Off means off everywhere, including Crop.
    win._display_unlinked = False
    win._stage = idx("crop")
    assert win._effective_unlinked() is False
