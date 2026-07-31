import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from nocturne.ui.main_window import MainWindow  # noqa: E402
from nocturne.core.image import AstroImage  # noqa: E402


class _Stub:
    def exec(self):
        return 0


def _make_fits(tmp_path, filter_card="L"):
    arr = (np.random.rand(3, 24, 24) * 1000).astype(np.uint16)
    p = tmp_path / "stack.fits"
    hdu = fits.PrimaryHDU(arr)
    if filter_card is not None:
        hdu.header["FILTER"] = filter_card
    hdu.writeto(str(p))
    return str(p)


def _window(qtbot, tmp_path):
    win = MainWindow(settings_path=str(tmp_path / "settings.json"), check_updates=False)
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
    seq = ["crop", "background", "color", "deconvolution", "stretch", "recover_core",
           "levels", "curves", "saturation", "green_fringe", "noise_sharpen", "local_contrast",
           "star_reduction", "enhancements", "export"]
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


def test_crop_dismiss_unmodified_hides_without_dialog(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    win = _bordered_window(qtbot, tmp_path)
    win._go_to_id("crop")
    win.image_view.show_crop_box()
    called = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: called.append(True))
    win._on_crop_dismiss()
    assert win.image_view.crop_box_visible() is False
    assert called == []                               # no confirm for a fresh box
    assert win._panel.apply_btn.isEnabled() is False
    assert win._panel.crop_size_label.text() == "—"


def test_crop_dismiss_modified_confirms(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    win = _bordered_window(qtbot, tmp_path)
    win._go_to_id("crop")
    win.image_view.show_crop_box()
    win.image_view._geometry_changed()                # mark modified

    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Cancel)
    win._on_crop_dismiss()
    assert win.image_view.crop_box_visible() is True   # Cancel keeps the box

    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Discard)
    win._on_crop_dismiss()
    assert win.image_view.crop_box_visible() is False  # Discard hides it


def test_apply_color_with_none_option(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("color")
    win.apply_current(None)  # auto panel emits None
    assert win.project.entries()[-1][0] == "Color"


def test_color_photometric_fallback_message_shown(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    from nocturne.core.color import ColorSettings
    # Force _step_for to return a stub Color step that reports a fallback.
    class _Stub:
        name = "Color"; last_message = "Couldn't reach Gaia — used sky balance."
        def apply(self, img, option):
            return img
    monkeypatch.setattr(win, "_step_for", lambda sid: _Stub())
    win._go_to_id("color")
    win.apply_current(ColorSettings(method="photometric"))
    assert "sky balance" in win.output_panel.toPlainText().lower()


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


def test_undo_redo_jumps_to_affected_step(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.6)                          # step 1, stage "stretch"
    win._go_to_id("levels")
    win.apply_current((0.2, 1.0, 1.0))              # step 2, stage "levels"
    names = [n for n, _ in win.project.entries()]
    assert names == ["Stretch", "Levels"]

    win._go_to_id("load")                            # navigate somewhere unrelated

    win._undo()                                       # reverts Levels
    assert win.current_stage_id() == "levels"

    win._redo()                                        # re-applies Levels
    assert win.current_stage_id() == "levels"

    win._undo()                                        # reverts Levels again
    win._undo()                                         # reverts Stretch
    assert win.current_stage_id() == "stretch"


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


def test_noise_busy_label_warns_for_graxpert(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    win = _window(qtbot, tmp_path)
    monkeypatch.setattr(mw, "graxpert_valid", lambda s: True)
    warn = win._busy_label_for("noise_sharpen", {"engine": "graxpert", "level": "medium"})
    assert "GraXpert" in warn and "minute" in warn
    # non-GraXpert (and other steps) use the plain label
    assert win._busy_label_for("noise_sharpen", {"engine": "rcastro", "level": "medium"}) \
        == "Applying Noise Reduction…"
    assert win._busy_label_for("levels", (0.0, 1.0, 1.0)) == "Applying Levels…"


def test_noise_records_engine_dict_option(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.6)
    win._go_to_id("noise_sharpen")
    win.apply_current({"engine": "graxpert", "level": "medium"})   # simulate panel option
    names = [n for n, _ in win.project.entries()]
    assert "Noise Reduction" in names
    # the recorded option is the dict, so a recipe captures the engine
    from nocturne.recipe import recipe_from_entries
    steps = recipe_from_entries(win.project.entries())
    ns = [s for s in steps.steps if s["stage"] == "noise_sharpen"]
    assert ns and ns[0]["option"] == {"engine": "graxpert", "level": "medium"}


def test_levels_refused_on_linear_image(qtbot, tmp_path):
    # Belt-and-suspenders: _undo() now navigates to the stage of the reverted
    # step (Stretch), so it no longer leaves the stepper on Levels. Reach the
    # same linear-image-on-Levels corner case via project.undo() directly (as
    # test_undo_reverses_one_geometry_op does) to keep exercising the
    # apply_current guard: applying Levels then would clip the tiny linear
    # values (~0.003) to black; the guard must refuse with a hint instead.
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("levels")                         # auto-stretches, lands on Levels
    win.project.undo()                              # undo the auto-stretch -> linear again
    assert win.current_stage_id() == "levels"
    assert win.project.current().is_linear
    names_before = [n for n, _ in win.project.entries()]
    win.apply_current((0.01, 1.0, 1.0))             # a tiny black-point nudge
    assert [n for n, _ in win.project.entries()] == names_before   # nothing applied
    assert win.project.current().is_linear          # image untouched, not blacked out
    assert "Stretch" in win._warning.text()


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
    assert "open" in win._warning.text().lower()


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


def test_export_dialog_opens_on_chosen_format(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    seen = {}

    def fake(parent, title, initial, filters, selected):
        seen["initial"] = initial
        seen["selected"] = selected
        return (str(tmp_path / "out.fits"), "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake))
    monkeypatch.setattr(win, "_run_busy",
                        lambda work, on_result, label, err_prefix: None)
    win.export_final("FITS")
    assert seen["selected"] == "FITS (*.fits)"     # dialog respects the app choice
    assert seen["initial"].endswith(".fits")       # suggested name matches format


def test_stretch_live_preview_renders(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win._on_stretch_change(0.7)
    win._render_stretch_preview()          # non-committing preview, must render
    assert not win.image_view._item.pixmap().isNull()
    assert win.project.current().is_linear  # preview did NOT commit the stretch


def test_slider_preview_updates_histogram(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    seen = []
    monkeypatch.setattr(win.histogram_view, "set_image", lambda img: seen.append(img))
    win._on_stretch_change(0.6)
    win._render_stretch_preview()
    assert seen  # the shared _show_preview fed the previewed data to the histogram


def test_recover_core_live_preview_renders(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("recover_core")                # recover_core is a POST_STRETCH_IDS
                                                   # stage, so this auto-stretches
    entries_before = [n for n, _ in win.project.entries()]
    win._on_recover_change(0.7)
    win._render_recover_preview()               # non-committing preview
    assert not win.image_view._item.pixmap().isNull()
    assert [n for n, _ in win.project.entries()] == entries_before  # preview did NOT commit


def test_recover_core_preview_updates_histogram(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("recover_core")
    seen = []
    monkeypatch.setattr(win.histogram_view, "set_image", lambda img: seen.append(img))
    win._on_recover_change(0.5)
    win._render_recover_preview()
    assert seen                                 # shared _show_preview fed the histogram


def test_curve_live_preview_renders_without_commit(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("curves")
    entries_before = [name for name, _ in win.project.entries()]
    win._on_curve_change([(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
    win._render_curve_preview()
    assert not win.image_view._item.pixmap().isNull()
    assert [name for name, _ in win.project.entries()] == entries_before  # no commit


def test_curve_preview_updates_histogram(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("curves")
    seen = []
    monkeypatch.setattr(win.histogram_view, "set_image", lambda img: seen.append(img))
    win._on_curve_change([(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
    win._render_curve_preview()
    assert seen


def test_curve_add_contrast_preset_seeds_non_identity(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("curves")
    win._on_curve_preset("add_contrast")
    assert win._panel.curve_editor.points() != [(0.0, 0.0), (1.0, 1.0)]
    win._on_curve_preset("reset")
    assert win._panel.curve_editor.points() == [(0.0, 0.0), (1.0, 1.0)]


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
    assert "Export failed: disk full" in win._warning.text()
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
    win._show_warning("some error")
    win._go_to_id("crop")
    assert win._warning.text() == ""


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
    assert win._bottom_bar.isHidden() is True


def test_open_image_loads_astroimage(qtbot, tmp_path):
    import numpy as np
    from nocturne.core.image import AstroImage
    win = _window(qtbot, tmp_path)
    win.open_image(AstroImage(np.zeros((12, 14, 3), np.float32), is_linear=True),
                   "stacked master")
    assert win.project is not None
    assert win.current_stage_id() == "load"
    assert "stacked master" in win.log_panel.text()


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
    win._show_warning("Export failed: disk full")   # stale error from a prior attempt
    out = tmp_path / "pic.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    win.export_final("PNG")
    assert out.exists()
    assert win._warning.text() == ""   # stale error cleared on the successful export


def test_export_fits_writes_wcs_when_solved(qtbot, tmp_path, monkeypatch):
    from astropy.io import fits
    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    win._solve = (win._solve_sig(), SolveResult(True, wc, 100.0, 0.0, 3.6), [])
    out = tmp_path / "out.fits"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    win.export_final("FITS")
    qtbot.waitUntil(lambda: out.exists(), timeout=3000)
    assert "CRVAL1" in fits.getheader(str(out))


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


def test_boost_gold_and_dark_structure_taps_add_steps(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    before = win.project.position
    win._enhance("Boost Gold")
    win._enhance("Dark Structure")
    assert win.project.position == before + 2


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
    assert "Export failed: disk full" in win._warning.text()


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


def test_busy_panel_shows_cancel_and_elapsed_when_visuals_appear(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.show(); qtbot.waitExposed(win)
    win._set_busy(True, "Working…")
    win._show_busy_visuals()                      # force the visuals (bypass the 400ms delay)
    assert win._cancel_btn.isVisible()
    win._cancel_btn.click()                       # wired to _cancel_active (no active token -> no crash)
    win._set_busy(False)


def test_set_progress_switches_to_determinate(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.show(); qtbot.waitExposed(win)
    win._set_busy(True, "Stacking…"); win._show_busy_visuals()
    win._set_progress("integrating", 3, 10)
    assert win._progress.isVisible() and win._progress.maximum() == 10 and win._progress.value() == 3
    win._set_progress("", 0, 0)                   # total 0 -> indeterminate, bar hidden
    assert not win._progress.isVisible()
    win._set_busy(False)


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
    win._go_to_id("stretch"); win.apply_current(0.5)
    # Enhancements taps are now captured, so force a genuinely uncaptured
    # step to exercise the warn+cancel path.
    monkeypatch.setattr("nocturne.ui.main_window.uncaptured_step_names",
                        lambda entries: ["Some Tool Step"])
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
    # No forced warning needed: Enhancements taps are captured, not dropped.
    stages = [s["stage"] for s in load_recipe(out).steps]
    assert "stretch" in stages
    enhance_steps = [s for s in load_recipe(out).steps if s["stage"] == "enhance"]
    assert {"stage": "enhance", "option": "Boost Red"} in enhance_steps


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




def test_levels_auto_sets_sliders(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)   # need a non-linear image for Levels
    win._go_to_id("levels")
    win._on_levels_auto()
    from nocturne.core.levels import auto_levels
    b, g, wt = auto_levels(win.project.current().data)
    assert abs(win._panel.black_slider.value() / 100 - b) < 0.02


def test_clipping_line_is_hidden_before_stretch(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win._canvas_img.is_linear is True
    assert win._clip_line.isHidden()
    assert win._clip_check.isHidden()


def test_clipping_line_appears_once_the_image_is_stretched(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert win._canvas_img.is_linear is False
    assert not win._clip_line.isHidden()
    assert "highlights" in win._clip_line.text()
    assert "shadows" in win._clip_line.text()


def test_clipping_line_reports_a_crushed_shadow_percentage(qtbot, tmp_path):
    import numpy as np
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._show_preview(np.zeros((24, 24, 3), np.float32))   # everything crushed
    assert "100.0% shadows" in win._clip_line.text()


def test_clipping_line_reports_blown_highlights(qtbot, tmp_path):
    import numpy as np
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._show_preview(np.ones((24, 24, 3), np.float32))
    assert "100.0% highlights" in win._clip_line.text()


def _preview_with_clipped(win, black=0, white=0, side=200):
    """A mid-grey preview with exactly `black` crushed and `white` blown pixels,
    so a known clipped fraction reaches the amber logic. 200x200 = 40,000 px, so
    one pixel is 0.0025% — fine enough to sit either side of both trip points."""
    import numpy as np
    data = np.full((side, side, 3), 0.5, np.float32)
    flat = data.reshape(-1, 3)
    flat[:black] = 0.0
    flat[black:black + white] = 1.0
    win._show_preview(data)
    return win._clip_line.text()


def test_floor_level_clipping_stays_quiet(qtbot, tmp_path):
    # The measured no-fault floor on a real NGC 7000 master: 1-2 blown pixels and
    # ~28 crushed ones out of 5.1 M. Scaled here to one pixel each of 40,000
    # (0.0025%) — both trip points must sit above that or the warning cries wolf
    # on every image and the user learns to ignore it.
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert "⚠" not in _preview_with_clipped(win, black=1, white=1)


def test_real_shadow_clipping_raises_the_amber_warning(qtbot, tmp_path):
    # 25 of 40,000 = 0.0625%, just past the 0.05% shadow trip point.
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert "⚠" in _preview_with_clipped(win, black=25)


def test_highlights_are_deliberately_laxer_than_shadows(qtbot, tmp_path):
    # 0.05% blown is quiet (saturated star cores are not a mistake) while the same
    # fraction crushed is not. Highlights trip only at 0.1%.
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert "⚠" not in _preview_with_clipped(win, white=20)     # 0.05%
    assert "⚠" in _preview_with_clipped(win, white=45)         # 0.1125%


def test_clipping_overlay_paints_on_a_non_levels_step(qtbot, tmp_path):
    # The capability that does not exist today: clipping feedback on Curves.
    import numpy as np
    from PySide6.QtGui import qRed, qBlue
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("curves")
    win._on_show_clipping(True)
    win._show_preview(np.zeros((24, 24, 3), np.float32))   # all shadow-clipped
    qi = win.image_view._item.pixmap().toImage()
    assert qBlue(qi.pixel(5, 5)) > 200 and qRed(qi.pixel(5, 5)) < 120


def test_clipping_overlay_off_leaves_the_pixels_alone(qtbot, tmp_path):
    import numpy as np
    from PySide6.QtGui import qBlue
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._show_preview(np.zeros((24, 24, 3), np.float32))
    qi = win.image_view._item.pixmap().toImage()
    assert qBlue(qi.pixel(5, 5)) == 0


def test_histogram_view_exposes_its_counts(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    h = win.histogram_view.hist()
    assert set(h) == {"r", "g", "b"}


def test_saturation_preview_renders(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)                 # need a non-linear image
    win._go_to_id("saturation")
    win._on_sat_change(1.0, 0.0)            # strong boost, no nebula boost
    win._render_saturation_preview()
    pm = win.image_view._item.pixmap()
    assert not pm.isNull()
    h, w = win.project.current().data.shape[:2]
    assert (pm.width(), pm.height()) == (w, h)


def test_local_contrast_preview_renders(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)                 # need a non-linear image
    win._go_to_id("local_contrast")
    win._on_lc_change(1.0)                  # full CLAHE
    win._render_lc_preview()
    pm = win.image_view._item.pixmap()
    assert not pm.isNull()
    h, w = win.project.current().data.shape[:2]
    assert (pm.width(), pm.height()) == (w, h)


def _fake_rc_settings(tmp_path):
    from nocturne.settings import Settings
    rc_bin = tmp_path / "rc"; rc_bin.write_text("#!/bin/sh\n")
    return Settings(rcastro_path=str(rc_bin))


class _FakeSplitRC:
    def __init__(self, *a, **k):
        pass

    def remove_stars(self, img, runner=None):
        starless = AstroImage(img.data * 0.4, is_linear=img.is_linear)
        stars = AstroImage(img.data * 0.6, is_linear=img.is_linear)
        return starless, stars


def test_setup_star_reduction_caches_split(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.settings = _fake_rc_settings(tmp_path)
    monkeypatch.setattr(mw, "RCAstro", _FakeSplitRC)
    win._go_to_id("stretch")
    win.apply_current(0.5)               # non-linear image for the finishing tail
    win._go_to_id("star_reduction")      # triggers _setup_star_reduction (sync)
    assert win._sr_ready is True
    assert win._sr_layers is not None
    assert win._panel.sr_slider.isEnabled() is True
    assert win._panel.apply_btn.isEnabled() is True


def test_setup_star_reduction_ungated_without_rcastro(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("star_reduction")      # no RC-Astro configured -> free split used
    assert win._sr_ready is True
    assert win._sr_layers is not None
    assert win._panel.sr_slider.isEnabled() is True
    assert win._panel.apply_btn.isEnabled() is True
    assert "RC-Astro" in win._panel.sr_status.text()            # free-detection note
    assert "Needs RC-Astro" not in win._panel.sr_status.text()  # not the old gate text


def test_star_reduction_ungated_without_rcastro(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    monkeypatch.setattr(mw, "rcastro_valid", lambda s: False)   # simulate no RC-Astro
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch"); win.apply_current(0.6)
    win._go_to_id("star_reduction")
    # panel slider is ENABLED (not gated) and shows a free-detection note, not "Needs RC-Astro"
    assert win._panel.sr_slider.isEnabled() is True
    assert "RC-Astro" in win._panel.sr_status.text()            # note mentions RC-Astro
    assert "Needs RC-Astro" not in win._panel.sr_status.text()  # but not the old gate text


def test_remove_stars_uses_free_split_without_rcastro(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    import numpy as np
    monkeypatch.setattr(mw, "rcastro_valid", lambda s: False)
    used = {"free": False}
    monkeypatch.setattr(mw, "split_stars",
                        lambda img: (used.__setitem__("free", True) or (img, img)))
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    img = win.project.current()
    win._remove_stars(img)
    assert used["free"] is True                                 # free split, no RC-Astro call


def test_star_reduction_preview_renders(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("star_reduction")
    base = win.project.current()
    starless = AstroImage(base.data * 0.4, is_linear=base.is_linear)
    stars = AstroImage(base.data * 0.6, is_linear=base.is_linear)
    win._sr_layers = (win._sr_sig(base), starless, stars)
    win._sr_ready = True
    win._on_sr_change(0.7)
    win._render_sr_preview()
    pm = win.image_view._item.pixmap()
    assert not pm.isNull()
    h, w = win.project.current().data.shape[:2]
    assert (pm.width(), pm.height()) == (w, h)


def test_apply_star_reduction_commits(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("star_reduction")
    base = win.project.current()
    starless = AstroImage(base.data * 0.4, is_linear=base.is_linear)
    stars = AstroImage(base.data * 0.6, is_linear=base.is_linear)
    win._sr_layers = (win._sr_sig(base), starless, stars)
    win._sr_ready = True
    win._apply_star_reduction(0.5)
    assert win.project.entries()[-1][0] == "Star Reduction"


def test_background_stage_defaults_to_light(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("background")
    assert win._panel.option_box.currentText() == "light"


def test_green_fringe_ungated_without_rcastro(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("green_fringe")               # no RC-Astro configured -> free split used
    assert win._fringe_ready is True
    assert win._panel.fringe_slider.isEnabled() is True
    assert "RC-Astro" in win._panel.fringe_status.text()            # free-detection note
    assert "Needs RC-Astro" not in win._panel.fringe_status.text()  # not the old gate text


def _fake_rc_layers(win, monkeypatch):
    import numpy as np
    from nocturne.core.image import AstroImage
    starless = AstroImage(np.full((16, 16, 3), 0.3, np.float32), is_linear=False)
    stars = np.zeros((16, 16, 3), np.float32); stars[8, 8] = (0.2, 0.9, 0.3)
    stars = AstroImage(stars, is_linear=False)
    monkeypatch.setattr(win, "_remove_stars", lambda img: (starless, stars))
    monkeypatch.setattr("nocturne.ui.main_window.rcastro_valid", lambda s: True)


def test_green_fringe_caches_split_and_previews(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _fake_rc_layers(win, monkeypatch)
    win._go_to_id("green_fringe")               # sync split (_async_enabled False)
    assert win._fringe_ready is True
    assert win._panel.fringe_slider.isEnabled() is True
    entries_before = [name for name, _ in win.project.entries()]
    win._on_fringe_change(0.6)
    win._render_fringe_preview()
    assert not win.image_view._item.pixmap().isNull()
    assert [name for name, _ in win.project.entries()] == entries_before   # no commit


def test_green_fringe_apply_records_step(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _fake_rc_layers(win, monkeypatch)
    win._go_to_id("green_fringe")
    win._apply_green_fringe(0.6)
    names = [name for name, _ in win.project.entries()]
    assert names[-1] == "Remove Green Fringe"


def test_star_spikes_tool_records_step_on_apply(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")                  # ensure a display-space image
    win.apply_current("")                     # commit a stretch so current() is non-linear
    from nocturne.core.image import AstroImage
    import numpy as np
    before = len(win.project.entries())
    result = AstroImage(np.clip(win.project.current().data, 0, 1), is_linear=False)
    win._apply_star_spikes(result)
    names = [name for name, _ in win.project.entries()]
    assert names[-1] == "Star Spikes"
    assert len(win.project.entries()) == before + 1


def test_star_spikes_tool_guarded_when_linear(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))       # freshly loaded image is linear
    opened = []
    monkeypatch.setattr("nocturne.ui.star_spikes_dialog.StarSpikesDialog",
                        lambda *a, **k: opened.append(True))
    win._open_star_spikes()
    assert not opened                         # refused on a linear image


def test_open_fits_starts_in_base_dir(qtbot, tmp_path, monkeypatch):
    from nocturne import ui
    import nocturne.ui.main_window as mw
    win = _window(qtbot, tmp_path)
    win.settings = mw.load_settings(str(tmp_path / "s.json"))
    win.settings.base_dir = str(tmp_path)
    seen = {}
    def _fake_open(*a, **k):
        seen["dir"] = a[2]          # 3rd positional arg is the start `dir`
        return ("", "")             # (path, filter) — path "" so nothing opens
    monkeypatch.setattr(mw.QFileDialog, "getOpenFileName", staticmethod(_fake_open))
    win._choose_fits()
    assert seen["dir"] == str(tmp_path)     # opened at the base folder


def test_open_fits_blank_base_dir_uses_os_default(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    win = _window(qtbot, tmp_path)
    win.settings.base_dir = ""
    seen = {}
    def _fake_open(*a, **k):
        seen["dir"] = a[2]          # 3rd positional arg is the start `dir`
        return ("", "")             # (path, filter) — path "" so nothing opens
    monkeypatch.setattr(mw.QFileDialog, "getOpenFileName", staticmethod(_fake_open))
    win._choose_fits()
    assert seen["dir"] == ""


def test_saturation_nebula_ungated_without_rcastro(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("saturation")
    assert win._panel.neb_slider.isEnabled() is True            # ungated -> free split
    assert "RC-Astro" in win._panel.neb_status.text()           # free-detection note
    assert "Needs RC-Astro" not in win._panel.neb_status.text()  # not the old gate text
    assert win._panel.sat_slider.isEnabled() is True      # global still works


def test_saturation_global_only_applies_without_rcastro(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("saturation")
    win._apply_saturation(0.7, 0.0)
    assert [n for n, _ in win.project.entries()][-1] == "Saturation"


def _fake_sat_split(win, monkeypatch):
    import numpy as np
    from nocturne.core.image import AstroImage
    starless = AstroImage(np.full((16, 16, 3), 0.3, np.float32), is_linear=False)
    stars = np.zeros((16, 16, 3), np.float32); stars[8, 8] = (0.2, 0.9, 0.3)
    stars = AstroImage(stars, is_linear=False)
    monkeypatch.setattr(win, "_remove_stars", lambda img: (starless, stars))
    monkeypatch.setattr("nocturne.ui.main_window.rcastro_valid", lambda s: True)


def test_saturation_nebula_split_keeps_free_note_without_rcastro(qtbot, tmp_path, monkeypatch):
    # Regression: after the free nebula split completes without RC-Astro,
    # _on_sat_split must preserve the free-detection note (not wipe it to "").
    import numpy as np
    from nocturne.core.image import AstroImage
    starless = AstroImage(np.full((16, 16, 3), 0.3, np.float32), is_linear=False)
    stars = AstroImage(np.zeros((16, 16, 3), np.float32), is_linear=False)
    monkeypatch.setattr("nocturne.ui.main_window.rcastro_valid", lambda s: False)
    win = _window(qtbot, tmp_path)
    monkeypatch.setattr(win, "_remove_stars", lambda img: (starless, stars))
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("saturation")
    win._on_sat_change(0.5, 0.6)                       # sync free split -> _on_sat_split
    assert "RC-Astro" in win._panel.neb_status.text()  # free note preserved, not ""


def test_saturation_nebula_caches_split_and_previews(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _fake_sat_split(win, monkeypatch)
    win._go_to_id("saturation")
    entries_before = [n for n, _ in win.project.entries()]
    win._on_sat_change(0.5, 0.6)              # sync split (_async_enabled False)
    win._render_saturation_preview()
    assert not win.image_view._item.pixmap().isNull()
    assert [n for n, _ in win.project.entries()] == entries_before   # no commit
    win._apply_saturation(0.5, 0.6)
    assert [n for n, _ in win.project.entries()][-1] == "Saturation"


def test_spacebar_peek_toggles_before_after(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.6)                      # one applied step -> distinct before/after
    seen = []
    monkeypatch.setattr(win.histogram_view, "set_image", lambda img: seen.append(img))
    before, after = win.project.before_after()
    win._toggle_peek()
    assert win._peek_active is True
    assert np.allclose(seen[-1].data, before.data)     # showing the 'before'
    win._toggle_peek()
    assert win._peek_active is False
    assert np.allclose(seen[-1].data, after.data)      # back to the 'after'


def test_spacebar_peek_noop_without_project(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._toggle_peek()                                 # no project loaded -> no crash
    assert win._peek_active is False


def test_refresh_resets_peek(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.6)
    win._toggle_peek()
    assert win._peek_active is True
    win._refresh()
    assert win._peek_active is False                   # a rebuilt view resets the peek


def test_spacebar_event_filter_toggles_peek(qtbot, tmp_path):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.6)
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    assert win.eventFilter(win, ev) is True            # Space consumed -> peek
    assert win._peek_active is True


def test_peek_is_scoped_to_current_step(qtbot, tmp_path, monkeypatch):
    # Regression: on a step you have NOT applied yet, Space must compare THIS
    # step's entry image, not the last *applied* step's before/after — otherwise
    # peeking on a later step reveals an earlier step's effect (e.g. noise
    # reappearing while sitting on Local Contrast).
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.6)                             # the only APPLIED step
    win._go_to_id("levels")                            # a later step, NOT applied
    seen = []
    monkeypatch.setattr(win.histogram_view, "set_image", lambda img: seen.append(img))
    win._toggle_peek()                                 # peek 'before'
    entry = win._preview_base("levels")                # this step's entry image
    last_applied_before = win.project.before_after()[0]  # the OLD (buggy) 'before'
    assert np.allclose(seen[-1].data, entry.data)      # scoped to the current step
    # entry (post-stretch) must differ from the last-applied step's before
    # (pre-stretch) — proving the peek no longer walks back over an earlier step.
    assert not np.allclose(entry.data, last_applied_before.data)


def test_narrowband_records_recipe_captured_step(qtbot, tmp_path):
    from nocturne.core.narrowband import NarrowbandParams
    from nocturne.recipe import recipe_from_entries
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.6)                                  # need a stretched image
    result = win.project.current()                         # stand-in recoloured result
    win._apply_narrowband(result, NarrowbandParams(palette="HOO", oiii_boost=1.3))
    names = [n for n, _ in win.project.entries()]
    assert "Narrowband" in names
    # and a saved recipe captures it (not dropped)
    recipe = recipe_from_entries(win.project.entries())
    assert any(s["stage"] == "narrowband" for s in recipe.steps)


def test_narrowband_refused_on_linear_image(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))                    # linear, pre-stretch
    win._go_to_id("background")
    win._open_narrowband()                                 # should no-op with a status
    names = [n for n, _ in win.project.entries()]
    assert "Narrowband" not in names


def test_narrowband_refused_on_mono_image(qtbot, tmp_path):
    import numpy as np
    from nocturne.core.image import AstroImage
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.6)                                 # stretched (non-linear)
    mono = AstroImage(np.full((16, 16), 0.5, np.float32), is_linear=False)
    win.project.current = lambda: mono                    # pretend the current image is mono
    win._open_narrowband()                                 # refused (needs colour) — no crash
    names = [n for n, _ in win.project.entries()]
    assert "Narrowband" not in names
    assert "colour" in win._warning.text().lower()


def _solve_now(win):
    """Open the Plate Solve tool AND run a solve.

    The toolbar button now only opens the tool — solving is the panel's Solve
    button — so a test that wants annotations must do both.
    """
    win._open_plate_solve()
    win._on_resolve_requested()


def _show_overlay(win):
    """Re-show the overlay the way the canvas pill does: from cache, no re-solve."""
    win.image_view._on_annotation_toggled(True)


def _hide_overlay(win):
    """Hide the overlay the way the canvas pill does, leaving the solve cached."""
    win.image_view._on_annotation_toggled(False)
    win.image_view.set_annotations(None)


def test_plate_solve_sets_target_and_overlay(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.settings.astap_path = str(tmp_path / "astap"); (tmp_path / "astap").write_text("x")

    # Fake a solve: a WCS centred on the frame + one catalogue object dead-centre.
    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    from nocturne.core.catalog import CatalogObject
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    monkeypatch.setattr(win, "_solve_current",
                        lambda img: (SolveResult(True, wc, 100.0, 0.0, 3.6),
                                 [CatalogObject("NGC 7000", "North America", 100.0, 0.0, 120.0, 12, 12)]))
    _solve_now(win)
    assert win.project.current().metadata.get("target_solved", "").startswith("NGC 7000")
    assert win.image_view._annotations is not None            # overlay shown


def test_plate_solve_not_configured_shows_hint(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    # No astap_path configured — astap_valid(win.settings) should be False.
    _solve_now(win)
    assert win._solve is None
    assert win._warning.text() != ""


def test_plate_solve_no_solution_leaves_no_overlay(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.settings.astap_path = str(tmp_path / "astap"); (tmp_path / "astap").write_text("x")

    from nocturne.tools.astap import SolveResult
    monkeypatch.setattr(win, "_solve_current",
                        lambda img: (SolveResult(False, None, 0.0, 0.0, 0.0), []))
    _solve_now(win)
    assert win._warning.text() != ""
    assert win.image_view._annotations is None
    assert win._solve is None


def test_plate_solve_toggles_overlay_off_when_cached(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.settings.astap_path = str(tmp_path / "astap"); (tmp_path / "astap").write_text("x")

    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    from nocturne.core.catalog import CatalogObject
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    monkeypatch.setattr(win, "_solve_current",
                        lambda img: (SolveResult(True, wc, 100.0, 0.0, 3.6),
                                 [CatalogObject("NGC 7000", "North America", 100.0, 0.0, 120.0, 12, 12)]))
    _solve_now(win)
    assert win.image_view._annotations is not None            # overlay shown

    _hide_overlay(win)                                        # pill off
    assert win.image_view._annotations is None

    _show_overlay(win)                                        # pill on, from cache
    assert win.image_view._annotations is not None


def test_solve_sig_stable_under_tonal_steps_changes_on_geometry(qtbot, tmp_path):
    # The plate-solve cache keys on FRAMING (shape + geometry ops), not pixel
    # content: the WCS is invariant under tonal steps (which don't move stars),
    # so a solve stays valid through them; only Crop/Rotate/Flip re-solve.
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    base = win._solve_sig()

    win._go_to_id("stretch")
    win.apply_current(0.6)                                   # a tonal step
    assert win._solve_sig() == base                         # framing unchanged -> same sig

    win._flip_h()                                           # a geometry op
    assert win._solve_sig() != base                         # framing changed -> re-solve


def test_flip_invalidates_stale_solve_overlay(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.settings.astap_path = str(tmp_path / "astap"); (tmp_path / "astap").write_text("x")

    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    from nocturne.core.catalog import CatalogObject
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    monkeypatch.setattr(win, "_solve_current",
                        lambda img: (SolveResult(True, wc, 100.0, 0.0, 3.6),
                                 [CatalogObject("NGC 7000", "North America", 100.0, 0.0, 120.0, 12, 12)]))
    _solve_now(win)
    assert win.image_view._annotations is not None            # overlay shown

    win._flip_h()                                              # geometry change: mirror-wrong overlay must clear
    win._refresh()
    assert win.image_view._annotations is None


def test_plate_solve_action_checked_state_tracks_overlay(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.settings.astap_path = str(tmp_path / "astap"); (tmp_path / "astap").write_text("x")
    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    from nocturne.core.catalog import CatalogObject
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    monkeypatch.setattr(win, "_solve_current",
                        lambda img: (SolveResult(True, wc, 100.0, 0.0, 3.6),
                                     [CatalogObject("NGC 7000", "North America", 100.0, 0.0, 120.0, 12, 12)]))
    # The toolbar button owns the TOOL PANEL; the canvas pill owns the overlay.
    # Hiding the overlay must NOT close the tool, and closing the tool must NOT
    # discard the overlay -- that separation is the whole point of the split.
    assert win._solve_act.isChecked() is False
    _solve_now(win)                                          # opens the tool and solves
    assert win._solve_act.isChecked() is True                # tool open
    assert win.solve_panel.isHidden() is False
    assert win.image_view._annotations is not None

    _hide_overlay(win)                                       # pill only
    assert win._solve_act.isChecked() is True, "hiding the overlay must not close the tool"
    assert win.solve_panel.isHidden() is False

    _show_overlay(win)                                       # pill again, from cache
    assert win.image_view._annotations is not None

    win._open_plate_solve()                                  # close the tool
    assert win._solve_act.isChecked() is False
    assert win.solve_panel.isHidden() is True
    assert win.image_view._annotations is not None, "closing the tool must keep the overlay"


def test_a_stale_solve_is_never_drawn_even_via_the_pill(qtbot, tmp_path, monkeypatch):
    """A solution is only valid for the framing it was solved against.

    Drawing a pre-flip solve on a flipped image mirrors every position — large
    nebula circles still look plausible while stars land visibly wrong, which is
    how this was found in the running app. The canvas pill's re-show path
    originally skipped the check, so the guard now lives in the single funnel.
    """
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.settings.astap_path = str(tmp_path / "astap"); (tmp_path / "astap").write_text("x")
    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    from nocturne.core.catalog import CatalogObject
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    monkeypatch.setattr(win, "_solve_current",
                        lambda img: (SolveResult(True, wc, 100.0, 0.0, 3.6),
                                     [CatalogObject("NGC 7000", "North America",
                                                    100.0, 0.0, 120.0, 12, 12)]))
    _solve_now(win)
    assert win.image_view._annotations is not None

    win._flip_v()                       # framing changed; the solve no longer applies
    assert win.image_view._annotations is None, "a flip must drop the overlay"

    from nocturne.ui.solve_panel import STATE_LABELS
    _show_overlay(win)                  # the pill tries to bring it back from cache
    assert win.image_view._annotations is None, \
        "a stale solve must never be redrawn, whichever path asks for it"
    assert win.solve_panel.header_btn.text().startswith(
        f"Plate solve · {STATE_LABELS['stale']}")


def test_solve_panel_present_in_right_column(qtbot, tmp_path):
    """The SolvePanel lives in the right column, below the clipping controls
    and above the per-stage step panel — the positional contract Task 8 was
    given (clipping line/checkbox as the reference point)."""
    win = _window(qtbot, tmp_path)
    assert win.solve_panel.parent() is win._right_panel
    idx_clip_check = win._right_layout.indexOf(win._clip_check)
    idx_solve_panel = win._right_layout.indexOf(win.solve_panel)
    idx_step_panel = win._right_layout.indexOf(win._panel)
    assert idx_clip_check != -1 and idx_solve_panel != -1 and idx_step_panel != -1
    assert idx_clip_check < idx_solve_panel < idx_step_panel


def _solved_win(qtbot, tmp_path, monkeypatch):
    """A window with a fresh, live plate-solve already showing, plus a list
    tracking every `_solve_current` (i.e. real ASTAP) invocation -- shared
    setup for the SolvePanel wiring tests below, which must prove certain
    panel interactions never grow this list."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.settings.astap_path = str(tmp_path / "astap"); (tmp_path / "astap").write_text("x")
    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    from nocturne.core.catalog import CatalogObject
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    calls = []

    def fake_solve(img):
        calls.append(img)
        return (SolveResult(True, wc, 100.0, 0.0, 3.6),
                [CatalogObject("NGC 7000", "North America", 100.0, 0.0, 120.0, 12, 12)])

    monkeypatch.setattr(win, "_solve_current", fake_solve)
    _solve_now(win)
    assert win.image_view._annotations is not None
    assert len(calls) == 1                    # the setup solve itself
    return win, calls


def test_layer_toggle_rebuilds_overlay_without_resolving(qtbot, tmp_path, monkeypatch):
    win, calls = _solved_win(qtbot, tmp_path, monkeypatch)
    n_calls = len(calls)
    before = win.image_view._annotations
    win.solve_panel.layer_checks["stars"].setChecked(False)
    after = win.image_view._annotations
    assert after is not None
    assert after is not before                     # overlay rebuilt (new group)
    assert len(calls) == n_calls                    # no re-solve
    assert win.solve_panel.layers()["stars"] is False


def test_density_change_rebuilds_overlay_without_resolving(qtbot, tmp_path, monkeypatch):
    win, calls = _solved_win(qtbot, tmp_path, monkeypatch)
    n_calls = len(calls)
    before = win.image_view._annotations
    idx = win.solve_panel.density_box.findData("minimal")
    win.solve_panel.density_box.setCurrentIndex(idx)
    after = win.image_view._annotations
    assert after is not None
    assert after is not before
    assert len(calls) == n_calls
    assert win.solve_panel.density() == "minimal"


def test_annotation_toggles_persist_to_settings(qtbot, tmp_path, monkeypatch):
    win, _calls = _solved_win(qtbot, tmp_path, monkeypatch)
    win.solve_panel.layer_checks["grid"].setChecked(True)
    idx = win.solve_panel.density_box.findData("all")
    win.solve_panel.density_box.setCurrentIndex(idx)
    assert win.settings.annotation_layers["grid"] is True
    assert win.settings.annotation_density == "all"

    from nocturne.settings import load_settings
    reloaded = load_settings(win._settings_path)
    assert reloaded.annotation_layers["grid"] is True
    assert reloaded.annotation_density == "all"


def test_solve_state_cached_when_reused_after_tonal_edit(qtbot, tmp_path, monkeypatch):
    from nocturne.ui.solve_panel import STATE_LABELS
    win, calls = _solved_win(qtbot, tmp_path, monkeypatch)
    n_calls = len(calls)
    assert win.solve_panel.header_btn.text().startswith(f"Plate solve · {STATE_LABELS['solved']}")

    _hide_overlay(win)                              # pill hides, solve stays cached
    win._go_to_id("stretch")
    win.apply_current(0.6)                                   # a tonal step -- doesn't move stars
    _show_overlay(win)                               # pill re-shows from cache

    assert win.image_view._annotations is not None
    assert win.solve_panel.header_btn.text().startswith(f"Plate solve · {STATE_LABELS['cached']}")
    assert len(calls) == n_calls                              # never re-solved


def test_resolve_button_forces_fresh_solve(qtbot, tmp_path, monkeypatch):
    from nocturne.ui.solve_panel import STATE_LABELS
    win, calls = _solved_win(qtbot, tmp_path, monkeypatch)
    n_calls = len(calls)

    win.solve_panel.resolve_btn.click()                       # cached solution exists, sig unchanged

    assert len(calls) == n_calls + 1                          # forced a fresh solve regardless
    assert win.solve_panel.header_btn.text().startswith(f"Plate solve · {STATE_LABELS['solved']}")


def _render_annotated(win, res, layers, path):
    """Burns a PNG with `_save_png_with_annotations`, but with the layer
    dict swapped out for the call so a test can isolate a single layer's
    contribution -- restores win's real _annotation_layers afterwards."""
    orig = win._annotation_layers
    win._annotation_layers = lambda: layers
    try:
        win._save_png_with_annotations(win.project.current(), path, res)
    finally:
        win._annotation_layers = orig


def test_export_path_includes_named_stars_like_the_live_overlay(qtbot, tmp_path, monkeypatch):
    """PS-07 regression: the live overlay drew named stars, but the burned
    PNG export used to build its primitives independently and silently
    dropped them. Both paths now go through the same _annotation_primitives.

    The star contribution is isolated rather than inferred from a mixed
    scene: with EVERY layer but stars off, the export must differ from a
    plain (un-annotated) render only once stars are the one thing switched
    on, and must match it exactly when stars are the one thing switched
    off -- so a bug that regresses star PAINTING specifically (not just the
    primitive list) cannot hide behind the DSO circle, compass or scale
    bar also being drawn."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.settings.astap_path = str(tmp_path / "astap"); (tmp_path / "astap").write_text("x")

    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    from nocturne.core.catalog import CatalogObject, NamedStar
    from nocturne.core.annotation_layout import Marker
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    monkeypatch.setattr(win, "_solve_current",
                        lambda img: (SolveResult(True, wc, 100.0, 0.0, 3.6),
                                 [CatalogObject("NGC 7000", "North America", 100.0, 0.0, 120.0, 12, 12)]))
    star = NamedStar("Deneb", 100.0, 0.0, 1.25, 10.0, 10.0)
    monkeypatch.setattr("nocturne.core.catalog.named_stars_in_field",
                        lambda wcs, shape: [star])

    _solve_now(win)                                  # solve + show the live overlay
    assert win.image_view._annotations is not None

    sig, res, objs = win._solve
    h, w = win.project.current().data.shape[:2]
    prims = win._annotation_primitives(res, objs, (h, w))
    assert any(isinstance(p, Marker) and p.kind == "star" for p in prims), \
        "the export path must carry the same named-star markers the live overlay shows"

    from PySide6.QtGui import QImage
    from nocturne.ui.preview import to_qimage
    # A "plain" baseline through the SAME base-pixel pipeline the burned
    # export uses (to_qimage), not core.export.save_png (which skips the
    # display autostretch) -- otherwise the two would differ for reasons
    # having nothing to do with annotations at all.
    plain_path = str(tmp_path / "plain.png")
    to_qimage(win.project.current()).save(plain_path)
    plain = QImage(plain_path)

    no_layers = {"objects": False, "stars": False, "grid": False,
                "compass": False, "scale": False, "by_type": False}
    stars_only = dict(no_layers, stars=True)

    stars_path = str(tmp_path / "stars_only.png")
    _render_annotated(win, res, stars_only, stars_path)
    stars_only_img = QImage(stars_path)
    assert not stars_only_img.isNull()
    assert stars_only_img != plain, \
        "the star layer alone must visibly change the burned export"

    off_path = str(tmp_path / "stars_off.png")
    _render_annotated(win, res, no_layers, off_path)
    stars_off_img = QImage(off_path)
    assert stars_off_img == plain, \
        "with every layer off (including stars) the export must match a plain render exactly"


def test_star_marker_painting_specifically_reaches_the_burned_export(qtbot, tmp_path):
    """Tighter than the layer-toggle test above: `build_layout_for` always
    gives a named star BOTH a Marker (the flanking ticks) AND a Label (its
    name) -- so comparing a "stars only" layer render against plain does
    NOT isolate the marker's paint code specifically, a Label-only bug
    would satisfy that assertion just as well. This test drives
    `_save_png_with_annotations` with a primitive list containing ONLY a
    star Marker (via monkeypatching `_annotation_primitives`, the shared
    seam both call sites go through), so the only thing that can make the
    burned PNG differ from plain is `annotation_render._paint_marker`'s
    "star" branch itself."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._solve = ("sig", None, [])   # _save_png_with_annotations unpacks self._solve unconditionally

    from PySide6.QtGui import QImage
    from nocturne.ui.preview import to_qimage
    from nocturne.core.annotation_layout import Marker

    plain_path = str(tmp_path / "plain.png")
    to_qimage(win.project.current()).save(plain_path)
    plain = QImage(plain_path)

    star_marker = Marker(10.0, 10.0, "star", "#5cff5c")
    win._annotation_primitives = lambda *a, **k: [star_marker]
    star_path = str(tmp_path / "star_marker_only.png")
    win._save_png_with_annotations(win.project.current(), star_path, res=None)
    star_img = QImage(star_path)
    assert not star_img.isNull()
    assert star_img != plain, \
        "a star Marker on its own must visibly change the burned export"

    win._annotation_primitives = lambda *a, **k: []
    empty_path = str(tmp_path / "no_primitives.png")
    win._save_png_with_annotations(win.project.current(), empty_path, res=None)
    assert QImage(empty_path) == plain, \
        "with no primitives at all the export must match a plain render exactly"


def test_output_panel_is_copyable_and_receives_output(qtbot, tmp_path):
    from PySide6.QtWidgets import QPlainTextEdit
    from PySide6.QtCore import Qt
    win = _window(qtbot, tmp_path)
    assert isinstance(win.output_panel, QPlainTextEdit)
    assert win.output_panel.isReadOnly()                     # not editable
    assert win.output_panel.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse  # copyable
    win._show_output("142 stars matched")
    assert "142 stars matched" in win.output_panel.toPlainText()


def test_saved_recipe_message_goes_to_output(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "r.json"), "")))
    win._save_recipe()
    assert "Saved recipe" in win.output_panel.toPlainText()


def test_nav_is_last_widget_and_warning_grows_upward(qtbot, tmp_path):
    from PySide6.QtWidgets import QLabel
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.resize(1200, 800)                                     # ensure the stretch has slack
    win.show(); qtbot.waitExposed(win)
    lay = win._right_layout
    last = lay.itemAt(lay.count() - 1)
    assert last.layout() is not None                          # nav is a QHBoxLayout, the last item
    assert win._next_btn in (last.layout().itemAt(i).widget()
                             for i in range(last.layout().count()))
    y0 = win._next_btn.mapTo(win, win._next_btn.rect().topLeft()).y()
    win._show_warning("Stretch the image first — a long wrapping message " * 3)
    qtbot.wait(10)
    y1 = win._next_btn.mapTo(win, win._next_btn.rect().topLeft()).y()
    # The warning grows upward into the stretch's slack, so the nav must not be
    # shoved down by a text line's height (~15-20px). Allow ±1px: absorbing the
    # warning's multi-line growth into a single QSpacerItem is integer division,
    # so the redistributed spacer rounds by up to a pixel depending on how much
    # fixed content sits above it in the column.
    assert abs(y1 - y0) <= 1                                   # buttons never visibly move


def test_warning_channel_and_clear(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._show_warning("Set the ASTAP path in Settings to plate-solve.")
    assert "ASTAP" in win._warning.text()
    win._clear_warning()
    assert win._warning.text() == ""
    assert not hasattr(win, "_status")                        # old surface removed


def test_help_collapse_is_global_sticky_and_persisted(qtbot, tmp_path):
    from nocturne.settings import load_settings
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.show(); qtbot.waitExposed(win)
    win.go_next()  # a stage with a help topic (crop)
    assert win.settings.help_expanded is True
    assert win._explainer_scroll.isVisible()                 # body shown when expanded
    assert win._full_help_link.isVisible()

    win._toggle_help()                                       # collapse
    assert win.settings.help_expanded is False
    assert not win._explainer_scroll.isVisible()             # body hidden
    assert not win._full_help_link.isVisible()               # Full help hidden when collapsed
    assert load_settings(str(tmp_path / "settings.json")).help_expanded is False  # persisted

    win.go_next()                                            # different step
    assert not win._explainer_scroll.isVisible()             # stays collapsed everywhere


def test_help_starts_collapsed_when_setting_off(qtbot, tmp_path):
    import json
    (tmp_path / "settings.json").write_text(json.dumps({"help_expanded": False}))
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.show(); qtbot.waitExposed(win)
    win.go_next()
    assert not win._explainer_scroll.isVisible()             # honours persisted state on launch


def test_peek_label_clears_when_leaving_peek(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win._displayed is not None
    win._toggle_peek()                                       # Space → show 'before'
    assert win._peek_active is True and win._peek_label.text() != ""
    win.go_next()                                            # navigate → _refresh exits peek
    assert win._peek_active is False
    assert win._peek_label.text() == ""                      # cue cleared, not left stale


# --- Auto Enhance ---

def _crop(win):
    """Apply a user crop — Auto Enhance is gated on (and respects) this."""
    from nocturne.core.crop import CropParams
    win._apply_geometry("Crop", CropParams(bounds=(4, 20, 4, 20)))


def test_auto_enhance_action_exists_on_toolbar(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert hasattr(win, "_auto_enhance")
    assert win._auto_enhance_act.text() == "Auto Enhance"


def test_auto_enhance_gated_on_crop(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert not win._auto_enhance_act.isEnabled()   # no crop yet -> disabled
    _crop(win)
    assert win._auto_enhance_act.isEnabled()        # cropped -> enabled


def test_auto_enhance_populates_editable_history(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))              # default filter_card="L" -> broadband
    _crop(win)
    assert hasattr(win, "_auto_enhance")
    win._auto_enhance()
    names = [n for n, _o in win.project.entries()]
    assert len(names) >= 3
    assert "Stretch" in names or "Color" in names


def test_auto_enhance_respects_the_users_crop(qtbot, tmp_path, monkeypatch):
    """Auto Enhance runs from the user's cropped frame: it keeps that crop, adds
    no auto-crop of its own, and discards the intervening processing — rather
    than resetting to the uncropped linear base."""
    import nocturne.ui.main_window as mw
    from PySide6.QtWidgets import QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    cropped_h = win.project.current().data.shape[0]
    win._go_to_id("stretch")
    win.apply_current(0.5)                            # manual processing to discard
    monkeypatch.setattr(mw.QMessageBox, "question",  # discard-processing confirm -> Yes
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    win._auto_enhance()
    names = [n for n, _o in win.project.entries()]
    assert names[0] == "Crop"                          # the user's crop, kept first
    assert names.count("Crop") == 1                     # no extra auto-crop was added
    assert names.count("Stretch") == 1                  # not stacked on the manual Stretch
    assert win.project.current().data.shape[0] == cropped_h   # output honours the crop


def test_auto_enhance_uses_same_path_for_dualband_filter(qtbot, tmp_path):
    # The dual-band/narrowband branch is gone -- LP-filter (Seestar Ha/OIII)
    # data now goes through the same photometric-color plan as everything
    # else; there's no more data-type prompt or Narrowband stage.
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path, filter_card="LP"))
    _crop(win)
    win._auto_enhance()
    names = [n for n, _o in win.project.entries()]
    assert "Narrowband" not in names
    assert "Stretch" in names or "Color" in names


def test_auto_enhance_no_project_cancelled_dialog_does_nothing(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    monkeypatch.setattr(win, "_choose_fits", lambda: None)  # simulate user cancelling the dialog
    win._auto_enhance()  # no project loaded, dialog cancelled — should no-op, not raise
    assert win.project is None
    assert win._warning.text() == ""


def test_auto_enhance_no_project_opens_dialog_then_needs_crop(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    path = _make_fits(tmp_path)
    monkeypatch.setattr(win, "_choose_fits", lambda: win.open_fits(path))
    win._auto_enhance()
    assert win.project is not None                     # the file was opened
    assert not win.project.entries()                   # but with no crop it doesn't enhance
    assert "Crop" in win._warning.text()               # it tells the user to crop first
    _crop(win)
    win._auto_enhance()                                # now it runs
    names = [n for n, _o in win.project.entries()]
    assert len(names) >= 3
    assert "Stretch" in names or "Color" in names


def test_auto_enhance_reports_step_count_and_nudges(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    win._auto_enhance()
    out = win.output_panel.toPlainText()
    assert "Auto-enhanced" in out
    assert "GraXpert" in out  # not installed in a bare test Settings() -> nudge shown
    assert win._peek_label.text() == ""                      # cue cleared, not left stale


def test_open_image_clears_prior_message_channels(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.log_panel.append_entry("stale log line")   # dirty the log + output from image one
    win._show_output("stale output line")
    assert "stale log line" in win.log_panel.text()
    assert "stale output line" in win.output_panel.toPlainText()
    d2 = tmp_path / "second"
    d2.mkdir()
    win.open_fits(_make_fits(d2))                   # opening a new image starts fresh channels
    log = win.log_panel.text()
    assert "stale log line" not in log
    assert log.count("Opened") == 1                 # only the fresh open entry, not the prior image's
    assert win.output_panel.toPlainText() == ""


def test_share_action_disabled_until_image(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert win._share_act.isEnabled() is False
    win.open_fits(_make_fits(tmp_path))
    assert win._share_act.isEnabled() is True


def _stretched_window(qtbot, tmp_path):
    """A window whose current image has been through Stretch, so it is no longer
    linear. Share and Upscale both refuse a linear image."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert win.project.current().is_linear is False
    return win


def test_share_refuses_a_linear_image(qtbot, tmp_path, monkeypatch):
    # 8-bit conversion of linear data (~0.003) is a near-black image; the old
    # behaviour opened the dialog on it and produced an unusable share.
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win.project.current().is_linear is True
    opened = []
    import nocturne.ui.main_window as mw
    monkeypatch.setattr(mw, "ShareDialog", lambda *a, **k: opened.append(True))
    win._share()
    assert not opened
    assert "Stretch" in win._warning.text()


def test_upscale_refuses_a_linear_image(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    opened = []
    import nocturne.ui.main_window as mw
    monkeypatch.setattr(mw, "UpscaleDialog", lambda *a, **k: opened.append(True))
    win._upscale()
    assert not opened
    assert "Stretch" in win._warning.text()


def test_share_opens_dialog(qtbot, tmp_path, monkeypatch):
    win = _stretched_window(qtbot, tmp_path)
    captured = {}
    import nocturne.ui.main_window as mw
    class _Fake:
        def __init__(self, rgb8, metadata, settings, parent=None):
            captured["shape"] = rgb8.shape; captured["target_key"] = "source_label" in metadata
        def exec(self): captured["shown"] = True
    monkeypatch.setattr(mw, "ShareDialog", _Fake)
    win._share()
    assert captured["shown"] and captured["target_key"]
    assert captured["shape"][2] == 3            # RGB 8-bit handed to the dialog


def test_upscale_action_disabled_until_image(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert win._upscale_act.isEnabled() is False
    win.open_fits(_make_fits(tmp_path))
    assert win._upscale_act.isEnabled() is True


def test_upscale_opens_dialog(qtbot, tmp_path, monkeypatch):
    win = _stretched_window(qtbot, tmp_path)
    seen = {}
    import nocturne.ui.main_window as mw
    class _Fake:
        def __init__(self, img, metadata, settings, rc=None, on_open_copy=None, parent=None):
            seen["has_source_label"] = "source_label" in metadata
            seen["is_astroimage"] = hasattr(img, "data")
        def exec(self): seen["shown"] = True
    monkeypatch.setattr(mw, "UpscaleDialog", _Fake)
    win._upscale()
    assert seen["shown"] and seen["has_source_label"] and seen["is_astroimage"]


def test_run_busy_cancel_sets_token_and_is_not_an_error(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._async_enabled = True
    import time
    from nocturne.core.tasks import Cancelled, current
    seen = {}
    def work():
        # the worker sees the ambient token; simulate a cancellable op
        tok = current()
        for _ in range(100):
            if tok and tok.cancelled:
                raise Cancelled()
            time.sleep(0.02)
        return "done"
    def on_result(_): seen["result"] = True
    win._run_busy(work, on_result, "Working…", "Failed")
    qtbot.waitUntil(lambda: win._active_token is not None, timeout=1000)
    win._cancel_active()
    qtbot.waitUntil(lambda: not win._busy, timeout=3000)
    assert "result" not in seen                 # cancelled -> on_result NOT called
    assert win._warning.text() == ""            # cancelled is NOT surfaced as an error


def test_toolerror_diagnostic_is_available(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    from nocturne.tools.base import ToolError
    win._report_tool_error("Denoise failed", ToolError(["graxpert", "-x"], 2, "", "model missing", 1.2))
    txt = win._last_diagnostic_text()             # accessor the impl exposes for the details/copy payload
    assert "graxpert" in txt and "model missing" in txt


def test_auto_progress_drives_determinate_bar(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.show(); qtbot.waitExposed(win)
    win._set_busy(True, "Auto…"); win._show_busy_visuals()
    win._on_auto_progress(2, 7, "Stretch")
    assert win._progress.isVisible() and win._progress.value() == 2 and win._progress.maximum() == 7
    win._set_busy(False)


def test_status_text_does_not_widen_right_panel(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.show(); qtbot.waitExposed(win)
    assert win._busy_label.wordWrap() and win._peek_label.wordWrap()
    win._busy_label.setText("x")
    short = win._right_panel.minimumSizeHint().width()
    win._busy_label.setText("Auto-enhancing — Local Contrast (12/13)… a long status line that must wrap")
    assert win._right_panel.minimumSizeHint().width() == short   # wrapped -> text doesn't drive width


def test_auto_enhance_confirms_only_when_processing_exists(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    from PySide6.QtWidgets import QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    calls = {"n": 0}
    def fake_q(*a, **k):
        calls["n"] += 1
        return QMessageBox.StandardButton.Cancel
    monkeypatch.setattr(mw.QMessageBox, "question", fake_q)
    win._auto_enhance()                       # only a crop, nothing to discard -> NO prompt, runs
    assert calls["n"] == 0
    assert win.project.entries()              # auto-enhance recorded steps
    before = list(win.project.entries())
    win._auto_enhance()                       # now has processing to discard -> prompt -> Cancel
    assert calls["n"] == 1
    assert list(win.project.entries()) == before   # cancelled: nothing reset/re-run


def test_toolbar_tool_icons_all_load(qtbot):
    """Each tool has its own glyph now (was all 'haoiii'); guards the assets."""
    from nocturne.ui.icons import load_icon
    for n in ["haoiii", "star-spikes", "narrowband", "auto-enhance",
              "plate-solve", "share", "upscale"]:
        assert not load_icon(n, "#ffffff").isNull(), f"icon missing/invalid: {n}"


# --- saved projects: Save/Save As/Open Project/Recent + solve-state persistence ---

def test_save_project_as_and_open_project_round_trip(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)  # slider amount -> records a Stretch step
    position_before = win.project.position
    data_before = win.project.current().data.copy()

    out = str(tmp_path / "proj.nocturne")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._save_project_as()
    assert win._project_path == out
    assert (tmp_path / "proj.nocturne").exists()

    win.project = None  # reset in-memory state to prove the reload is real
    win._open_project(out)

    assert win.project is not None
    assert win.project.position == position_before
    np.testing.assert_array_equal(win.project.current().data, data_before)


def test_open_project_newer_version_shows_warning(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))

    def fake_load(path, cache_dir):
        raise mw.NewerVersionError("bundle is newer than this build supports")

    monkeypatch.setattr(mw, "load_project", fake_load)
    win._open_project(str(tmp_path / "future.nocturne"))  # must not raise

    assert win.project is not None  # the old project is left untouched
    assert "newer version" in win._warning.text().lower()


def test_open_project_adds_to_recent(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    out = str(tmp_path / "proj2.nocturne")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._save_project_as()

    win._open_project(out)

    assert win.settings.recent_projects[0] == out
    # persisted to disk too, not just the in-memory Settings object
    from nocturne.settings import load_settings
    assert out in load_settings(win._settings_path).recent_projects


def test_solve_state_round_trips_through_save_and_open(qtbot, tmp_path, monkeypatch):
    from astropy.wcs import WCS
    from PySide6.QtWidgets import QFileDialog
    from nocturne.tools.astap import SolveResult
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    win._solve = (win._solve_sig(), SolveResult(True, wc, 100.0, 0.0, 3.6), [])

    out = str(tmp_path / "solved.nocturne")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._save_project_as()

    win.project = None
    win._solve = None
    win._open_project(out)

    assert win._solve is not None
    _sig, res, objs = win._solve
    assert res.solved is True
    assert res.wcs is not None
    assert round(res.center_ra_deg, 3) == 100.0


def test_open_project_without_solve_leaves_unsolved(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win._solve is None
    out = str(tmp_path / "unsolved.nocturne")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._save_project_as()

    win.project = None
    win._open_project(out)


# --- dirty-state tracking, window title, save-before-close/open guard ---

def test_dirty_false_after_open(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win._dirty is False


def test_dirty_true_after_edit(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert win._dirty is True


def test_dirty_false_after_save_project_as(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert win._dirty is True
    out = str(tmp_path / "dirty.nocturne")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._save_project_as()
    assert win._dirty is False


def test_window_title_reflects_name_and_dirty_marker(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    assert win.windowTitle() == "Nocturne"   # no image yet
    win.open_fits(_make_fits(tmp_path))
    assert "stack" in win.windowTitle()
    assert "•" not in win.windowTitle()
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert "•" in win.windowTitle()
    out = str(tmp_path / "titled.nocturne")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._save_project_as()
    assert "titled" in win.windowTitle()
    assert "•" not in win.windowTitle()


def test_confirm_save_if_dirty_cancel_aborts(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Cancel)
    assert win._confirm_save_if_dirty() is False
    assert win._dirty is True   # nothing changed


def test_confirm_save_if_dirty_discard_returns_true(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Discard)
    assert win._confirm_save_if_dirty() is True
    assert win._dirty is True   # discard doesn't save; caller proceeds to replace the project


def test_confirm_save_if_dirty_save_runs_save_project(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    out = str(tmp_path / "confirmed.nocturne")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Save)
    assert win._confirm_save_if_dirty() is True
    assert win._dirty is False
    assert win._project_path == out


def test_confirm_save_if_dirty_save_dialog_cancelled_returns_false(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")))   # user dismisses Save As
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Save)
    assert win._confirm_save_if_dirty() is False
    assert win._dirty is True


def test_confirm_save_if_dirty_clean_project_no_prompt(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    called = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: called.append(1) or QMessageBox.StandardButton.Cancel)
    assert win._confirm_save_if_dirty() is True
    assert called == []


def test_open_project_guarded_by_confirm_save_if_dirty(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    project_before = win.project
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Cancel)
    win._open_project(str(tmp_path / "nonexistent.nocturne"))
    assert win.project is project_before   # aborted, nothing replaced


def test_open_fits_guarded_by_confirm_save_if_dirty(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    project_before = win.project
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Cancel)
    other_dir = tmp_path / "second"
    other_dir.mkdir()
    win.open_fits(_make_fits(other_dir, filter_card="R"))
    assert win.project is project_before   # aborted


def test_closeevent_dirty_offers_save(qtbot, tmp_path, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    out = str(tmp_path / "closesave.nocturne")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Save)
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert ev.isAccepted()
    assert (tmp_path / "closesave.nocturne").exists()


def test_closeevent_clean_project_does_not_prompt(qtbot, tmp_path, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    called = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: called.append(1) or QMessageBox.StandardButton.Cancel)
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert ev.isAccepted()
    assert called == []

    assert win._solve is None  # no crash, just nothing to annotate


# --- off-thread save: busy-panel progress wiring (core progress/cancel logic
# is tested at the store level in tests/history/test_project_store.py) ---

def test_save_project_as_drives_progress_and_clears_dirty(qtbot, tmp_path, monkeypatch):
    """_async_enabled=False -> _run_busy runs synchronously, so the save still
    round-trips and clears dirty exactly as before; along the way, save_project's
    on_progress must reach the busy panel via _save_signals -> _set_progress."""
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)   # dirties the project + adds a cached-worthy step
    assert win._dirty is True

    seen = []
    orig_set_progress = win._set_progress
    def spy(phase, done, total):
        seen.append((phase, done, total))
        orig_set_progress(phase, done, total)
    monkeypatch.setattr(win, "_set_progress", spy)

    out = str(tmp_path / "progress.nocturne")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._save_project_as()

    assert win._dirty is False
    assert win._project_path == out
    assert (tmp_path / "progress.nocturne").exists()
    assert seen, "save_project's on_progress never reached _set_progress"
    assert all(phase == "Saving project" for phase, _, _ in seen)
    last_done, last_total = seen[-1][1], seen[-1][2]
    assert last_done == last_total > 0


def test_save_signals_wired_to_set_progress(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    seen = []
    win._set_progress = lambda phase, done, total: seen.append((phase, done, total))
    win._save_signals.progress.emit(3, 9)
    assert seen == [("Saving project", 3, 9)]


def test_info_strip_shows_resolution(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert "24 × 24" in win._info_strip.text()


def test_info_strip_reflects_current_crop(qtbot, tmp_path):
    # resolution tracks the current image, so a geometry crop shrinks it
    from nocturne.core.crop import CropParams
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("crop")
    win._apply_geometry("Crop", CropParams(bounds=(4, 20, 4, 20)))
    assert "16 × 16" in win._info_strip.text()


def test_close_project_returns_to_welcome(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win.project is not None
    win._close_project()
    assert win.project is None
    assert win._center_stack.currentWidget() is win._welcome
    assert win._info_strip.text() == ""


def test_close_project_confirms_when_dirty(qtbot, tmp_path, monkeypatch):
    # a dirty project must not be discarded silently — the save guard runs, and
    # declining it (returning False) aborts the close
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    monkeypatch.setattr(win, "_confirm_save_if_dirty", lambda: False)
    win._close_project()
    assert win.project is not None                       # close was aborted
    assert win._center_stack.currentWidget() is win.image_view


def test_provenance_action_builds_report(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    captured = {}
    monkeypatch.setattr("nocturne.ui.main_window.ProvenanceDialog",
                        lambda report, settings, parent=None, source_label=None: (captured.setdefault("r", report), _Stub())[1])
    win._show_provenance()
    assert "# Nocturne processing report" in captured["r"]
    assert "- Camera: Sony IMX585" in captured["r"]   # capture header rendered from the opened FITS


def test_provenance_action_noop_without_project(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._show_provenance()   # no project → must not raise


def test_clear_cache_removes_only_snapshots(qtbot, tmp_path):
    import os
    win = _window(qtbot, tmp_path)
    os.makedirs(win._cache_dir, exist_ok=True)
    open(os.path.join(win._cache_dir, "state_0.npy"), "w").close()
    open(os.path.join(win._cache_dir, "state_9.npy"), "w").close()
    open(os.path.join(win._cache_dir, "keep.txt"), "w").close()
    win._clear_cache()
    left = sorted(os.listdir(win._cache_dir))
    assert left == ["keep.txt"]                      # snapshots gone, other files kept


def test_clear_cache_never_raises_on_missing_dir(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)   # no image opened → _cache_dir doesn't exist yet
    win._clear_cache()               # must be a clean no-op, never raise


def test_open_image_clears_stale_snapshots(qtbot, tmp_path):
    import os
    win = _window(qtbot, tmp_path)
    os.makedirs(win._cache_dir, exist_ok=True)
    open(os.path.join(win._cache_dir, "state_9.npy"), "w").close()   # leftover from a longer prior session
    win.open_fits(_make_fits(tmp_path))
    assert not os.path.exists(os.path.join(win._cache_dir, "state_9.npy"))


def test_close_project_clears_cache(qtbot, tmp_path):
    import os
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert any(n.startswith("state_") for n in os.listdir(win._cache_dir))   # snapshots exist while open
    win._close_project()
    assert not any(n.startswith("state_") for n in os.listdir(win._cache_dir))


def test_close_event_clears_cache_on_quit(qtbot, tmp_path):
    import os
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))

    class _Evt:
        def __init__(self): self.accepted = False
        def accept(self): self.accepted = True
        def ignore(self): pass
    ev = _Evt()
    win.closeEvent(ev)   # not dirty after open, so the save-guard passes
    assert ev.accepted
    assert not any(n.startswith("state_") for n in os.listdir(win._cache_dir))


def test_update_indicator_shows_when_newer(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert not win._update_act.isVisible()          # hidden by default
    win._on_update_check("0.999.0")                 # a much newer release
    assert win._update_act.isVisible()
    assert "0.999.0" in win._update_act.toolTip()


def test_update_indicator_hidden_when_current_or_none(qtbot, tmp_path):
    from nocturne import __version__
    win = _window(qtbot, tmp_path)
    win._on_update_check(__version__)               # same version
    assert not win._update_act.isVisible()
    win._on_update_check(None)                       # check failed / offline
    assert not win._update_act.isVisible()


def test_soft_glow_and_vibrance_taps_add_steps(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    before = win.project.position
    win._enhance("Soft Glow")
    win._enhance("Vibrance")
    assert win.project.position == before + 2      # two undoable Enhancements steps


def test_star_colour_tap_applies_via_busy_path(qtbot, tmp_path, monkeypatch):
    import numpy as np
    from nocturne.core.image import AstroImage
    win = _window(qtbot, tmp_path)     # _async_enabled False -> _run_busy runs inline
    win.open_fits(_make_fits(tmp_path))
    # stub the (slow) star/starless split so the tap doesn't hit real StarX/sep
    def _fake_split(img):
        zeros = np.zeros_like(np.asarray(img.data, np.float32))
        return img, AstroImage(zeros, is_linear=img.is_linear)
    monkeypatch.setattr(win, "_remove_stars", _fake_split)
    before = win.project.position
    win._enhance("Star Colour")
    assert win.project.position == before + 1        # one undoable step added


def test_canvas_img_tracks_the_committed_image(qtbot, tmp_path):
    # Project.current() reloads a fresh AstroImage from disk on every call, so it
    # can never be `is` a second call's result (and AstroImage's dataclass `__eq__`
    # raises on its ndarray field, so `==` isn't available either). _canvas_img is
    # therefore checked against _displayed, the reference _refresh actually set it
    # from -- the same invariant the other _canvas_img tests below check.
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win._canvas_img is win._displayed


def test_canvas_img_follows_peek_rather_than_the_after_image(qtbot, tmp_path):
    # During peek the canvas shows 'before' while _displayed still holds 'after'.
    # The readout samples _canvas_img, so it must swap too.
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("levels")
    after = win._canvas_img
    win._toggle_peek()
    assert win._peek_active is True
    assert win._canvas_img is not after
    win._toggle_peek()
    assert win._canvas_img is win._displayed


def test_canvas_img_tracks_a_live_preview(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)
    win._render_levels_preview()
    assert win._canvas_img is win._displayed
    assert win._canvas_img.is_linear is False


def test_canvas_img_tracks_the_removegreen_live_preview(qtbot, tmp_path):
    # Color is a pre-Stretch (linear) step whose preview bypasses _show_preview
    # (which assumes display-space data), so it must still funnel through
    # _set_canvas rather than writing the canvas directly.
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("color")
    win._on_removegreen_change(0.5)
    win._render_removegreen_preview()
    assert win._canvas_img is win._displayed
    assert win._canvas_img.is_linear is True


def test_to_rgb8_matches_to_qimage_dimensions(qtbot):
    import numpy as np
    from nocturne.ui.preview import to_rgb8, to_qimage
    img = AstroImage(np.full((4, 6, 3), 0.5, np.float32), is_linear=False)
    rgb = to_rgb8(img)
    assert rgb.shape == (4, 6, 3) and rgb.dtype == np.uint8
    assert (rgb == 128).all()
    assert to_qimage(img).width() == 6


def test_to_rgb8_expands_mono_to_three_channels(qtbot):
    import numpy as np
    from nocturne.ui.preview import to_rgb8
    rgb = to_rgb8(AstroImage(np.full((3, 3), 1.0, np.float32), is_linear=False))
    assert rgb.shape == (3, 3, 3) and (rgb == 255).all()


def test_hover_shows_the_pixel_values_in_the_pill(qtbot, tmp_path):
    import numpy as np
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    data = np.zeros((24, 24, 3), np.float32)
    data[7, 5] = (0.8, 0.6, 0.4)
    win._show_preview(data)
    win._on_hover(5, 7, "main")
    text = win.image_view.readout_pill.text()
    assert "5, 7" in text
    assert "R 0.80" in text and "G 0.60" in text and "B 0.40" in text
    assert "L 0.60" in text
    assert "linear" not in text
    assert not win.image_view.readout_pill.isHidden()


def test_hover_before_stretch_labels_linear_and_uses_four_decimals(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win._canvas_img.is_linear is True
    win._on_hover(3, 3, "main")
    text = win.image_view.readout_pill.text()
    assert text.endswith("linear")
    assert len(text.split("R ")[1].split()[0]) == 6      # 0.0031 -> four decimals


def test_hover_leaving_the_image_hides_the_pill(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._on_hover(3, 3, "main")
    assert not win.image_view.readout_pill.isHidden()
    win._on_hover_left()
    assert win.image_view.readout_pill.isHidden()


def test_hover_outside_the_array_hides_the_pill(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._on_hover(9999, 9999, "main")
    assert win.image_view.readout_pill.isHidden()


def test_hover_with_no_project_hides_the_pill(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._on_hover(1, 1, "main")
    assert win.image_view.readout_pill.isHidden()


def test_hover_follows_peek(qtbot, tmp_path):
    import numpy as np
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("levels")
    win._show_preview(np.ones((24, 24, 3), np.float32))
    win._on_hover(5, 5, "main")
    after = win.image_view.readout_pill.text()
    win._toggle_peek()
    win._on_hover(5, 5, "main")
    assert win.image_view.readout_pill.text() != after


def test_hover_on_the_compare_side_samples_the_original(qtbot, tmp_path):
    import numpy as np
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._ba_act.setChecked(True)
    win._toggle_before_after()
    win._on_hover(5, 5, "main")
    main_text = win.image_view.readout_pill.text()
    win._on_hover(5, 5, "compare")
    assert win.image_view.readout_pill.text() != main_text


def test_readout_text_for_a_mono_image_has_no_luminance(qtbot, tmp_path):
    import numpy as np
    win = _window(qtbot, tmp_path)
    img = AstroImage(np.full((8, 8), 0.42, np.float32), is_linear=False)
    text = win._readout_text(img, 2, 2)
    assert "V 0.42" in text
    assert " L " not in text


def test_main_canvas_opts_into_the_pixel_cursor(qtbot, tmp_path):
    from PySide6.QtCore import QPointF, Qt
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.image_view._emit_hover_at_scene_pos(QPointF(5.0, 5.0))
    assert win.image_view.viewport().cursor().shape() == Qt.CursorShape.CrossCursor
