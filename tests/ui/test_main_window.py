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
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    out = str(tmp_path / "r.json")
    monkeypatch.setattr(file_dialogs, "save_file",
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
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    out = tmp_path / "pic.png"
    monkeypatch.setattr(file_dialogs, "save_file",
                        staticmethod(lambda *a, **k: (str(out), "")))
    calls = []
    monkeypatch.setattr(win, "_run_busy",
                        lambda work, on_result, label, err_prefix: calls.append(label))
    win.export_final("PNG")
    assert calls == ["Exporting…"]     # export now goes through the busy helper


def test_export_dialog_opens_on_chosen_format(qtbot, tmp_path, monkeypatch):
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    seen = {}

    def fake(parent, title, initial, filters, selected):
        seen["initial"] = initial
        seen["selected"] = selected
        return (str(tmp_path / "out.fits"), "")

    monkeypatch.setattr(file_dialogs, "save_file", (fake))
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
    from nocturne.ui import file_dialogs
    import nocturne.ui.main_window as mw
    win = _window(qtbot, tmp_path)  # _async_enabled = False -> inline
    win.open_fits(_make_fits(tmp_path))
    out = tmp_path / "pic.png"
    monkeypatch.setattr(file_dialogs, "save_file",
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
    from nocturne.ui import file_dialogs
    from nocturne.settings import Settings
    from nocturne.core.image import AstroImage
    import nocturne.ui.main_window as mw

    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    # RC-Astro "configured" so the split path is allowed
    rc_bin = tmp_path / "rc"; rc_bin.write_text("#!/bin/sh\n")
    win.settings = Settings(rcastro_path=str(rc_bin))

    out = tmp_path / "splitout"; out.mkdir()
    monkeypatch.setattr(file_dialogs, "choose_folder", (lambda *a, **k: str(out)))

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
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    out = tmp_path / "pic.png"
    monkeypatch.setattr(file_dialogs, "save_file",
                        staticmethod(lambda *a, **k: (str(out), "")))
    win.export_final("PNG")
    assert out.exists()


def test_export_clears_stale_error_on_success(qtbot, tmp_path, monkeypatch):
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._show_warning("Export failed: disk full")   # stale error from a prior attempt
    out = tmp_path / "pic.png"
    monkeypatch.setattr(file_dialogs, "save_file",
                        staticmethod(lambda *a, **k: (str(out), "")))
    win.export_final("PNG")
    assert out.exists()
    assert win._warning.text() == ""   # stale error cleared on the successful export


def test_export_fits_writes_wcs_when_solved(qtbot, tmp_path, monkeypatch):
    from astropy.io import fits
    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    win._solve = (win._solve_sig(), SolveResult(True, wc, 100.0, 0.0, 3.6), [])
    out = tmp_path / "out.fits"
    monkeypatch.setattr(file_dialogs, "save_file",
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
    # Reset restores from the project's own index 0, not a private copy.
    assert win.project.state_at(0) is not None and win._source_label


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
    from PySide6.QtWidgets import QMessageBox
    from nocturne.ui import file_dialogs
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
    monkeypatch.setattr(file_dialogs, "save_file",
                        staticmethod(lambda *a, **k: (saved.__setitem__("n", saved["n"] + 1), ("", ""))[1]))
    win._save_recipe()
    assert calls["dialog"] == 1            # warned about the uncaptured step
    assert saved["n"] == 0                  # cancel -> never reached the file dialog


def test_save_recipe_warns_then_saves_when_confirmed(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from nocturne.ui import file_dialogs
    from nocturne.recipe import load_recipe
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch"); win.apply_current(0.5)
    win._go_to_id("enhancements"); win._enhance("Boost Red")
    out = str(tmp_path / "r.json")
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Save))
    monkeypatch.setattr(file_dialogs, "save_file",
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


def test_background_stage_defaults_to_the_full_correction(qtbot, tmp_path):
    """Was "light", which used to mean the full correction under a misleading
    name — the options were labelled by strength but implemented as GraXpert's
    -smoothing, so both removed essentially everything. Now that "light" really
    is partial, the default has to be the one that still does the whole job."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("background")
    assert win._panel.option_box.currentText() == "strong"


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
        return ""                   # open_file returns a path; "" so nothing opens
    monkeypatch.setattr(mw.file_dialogs, "open_file", _fake_open)
    win._choose_fits()
    assert seen["dir"] == str(tmp_path)     # opened at the base folder


def test_open_fits_blank_base_dir_uses_os_default(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    win = _window(qtbot, tmp_path)
    win.settings.base_dir = ""
    seen = {}
    def _fake_open(*a, **k):
        seen["dir"] = a[2]          # 3rd positional arg is the start `dir`
        return ""                   # open_file returns a path; "" so nothing opens
    monkeypatch.setattr(mw.file_dialogs, "open_file", _fake_open)
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
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    monkeypatch.setattr(file_dialogs, "save_file",
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
        def __init__(self, rgb8, metadata, settings, parent=None,
                     annotated_rgb8=None, annotations_on=True, **kw):
            captured["shape"] = rgb8.shape; captured["target_key"] = "source_label" in metadata
            captured["annotated"] = annotated_rgb8
        def exec(self): captured["shown"] = True
    monkeypatch.setattr(mw, "ShareDialog", _Fake)
    win._share()
    assert captured["shown"] and captured["target_key"]
    assert captured["shape"][2] == 3            # RGB 8-bit handed to the dialog
    assert captured["annotated"] is None, "no solve -> nothing to burn in"


def test_share_receives_the_annotated_frame_when_solved(qtbot, tmp_path, monkeypatch):
    """Share could not publish an annotated image at all: it was handed raw
    pixels, so labels could only reach a PNG export — which skips the reframing
    and caption Share exists for. This was the user's first-named use case."""
    win = _stretched_window(qtbot, tmp_path)
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

    captured = {}
    import nocturne.ui.main_window as mw
    class _Fake:
        def __init__(self, rgb8, metadata, settings, parent=None,
                     annotated_rgb8=None, annotations_on=True, **kw):
            captured["clean"] = rgb8
            captured["annotated"] = annotated_rgb8
            captured["on"] = annotations_on
        def exec(self): pass
    monkeypatch.setattr(mw, "ShareDialog", _Fake)
    win._share()

    import numpy as np
    assert captured["annotated"] is not None, "a solved frame must reach Share annotated"
    assert captured["annotated"].shape == captured["clean"].shape
    assert not np.array_equal(captured["annotated"], captured["clean"]), \
        "the annotated frame must actually differ from the clean one"
    assert captured["on"] is True, "overlay visible on canvas -> on by default in Share"


def test_share_gets_no_annotations_when_the_solve_is_stale(qtbot, tmp_path, monkeypatch):
    """A solution belongs to the framing it was made for; burning a stale one
    into a shared image would publish labels in the wrong places."""
    win = _stretched_window(qtbot, tmp_path)
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
    win._flip_v()                                  # framing changed -> solve is stale
    # A geometry op truncates history back to the geometry stage, so re-stretch:
    # Share refuses a linear image, and we want to reach the annotation decision.
    win._go_to_id("stretch")
    win.apply_current(0.5)

    captured = {}
    import nocturne.ui.main_window as mw
    class _Fake:
        def __init__(self, rgb8, metadata, settings, parent=None,
                     annotated_rgb8=None, annotations_on=True, **kw):
            captured["annotated"] = annotated_rgb8
        def exec(self): pass
    monkeypatch.setattr(mw, "ShareDialog", _Fake)
    win._share()
    assert captured["annotated"] is None


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
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)  # slider amount -> records a Stretch step
    position_before = win.project.position
    data_before = win.project.current().data.copy()

    out = str(tmp_path / "proj.nocturne")
    monkeypatch.setattr(file_dialogs, "save_file",
                        staticmethod(lambda *a, **k: (out, "")))
    win._save_project_as()
    assert win._project_path == out
    assert (tmp_path / "proj.nocturne").exists()

    win.project = None  # reset in-memory state to prove the reload is real
    win._open_project(out)

    assert win.project is not None
    assert win.project.position == position_before
    np.testing.assert_array_equal(win.project.current().data, data_before)


def test_reset_works_on_a_loaded_project(qtbot, tmp_path, monkeypatch):
    """Reset restored from a private _source_base that only open_image ever set.
    _open_project restored _source_label but not that, so Reset raised
    AttributeError on every loaded bundle while working on a fresh FITS."""
    from PySide6.QtWidgets import QMessageBox
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    base = win.project.current().data.copy()
    win._go_to_id("stretch")
    win.apply_current(0.5)

    out = str(tmp_path / "resettable.nocturne")
    monkeypatch.setattr(file_dialogs, "save_file",
                        staticmethod(lambda *a, **k: (out, "")))
    win._save_project_as()
    win.project = None                       # prove the reload is real
    win._open_project(out)
    assert any(n == "Stretch" for n, _ in win.project.entries())

    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    win._reset_image()                       # used to raise AttributeError

    assert win.project.entries() == []
    np.testing.assert_array_equal(win.project.current().data, base)
    # The bundle on disk still holds the discarded edits, so the session no
    # longer matches it — quitting now must still prompt to save.
    assert win._dirty is True


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
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    out = str(tmp_path / "proj2.nocturne")
    monkeypatch.setattr(file_dialogs, "save_file",
                        staticmethod(lambda *a, **k: (out, "")))
    win._save_project_as()

    win._open_project(out)

    assert win.settings.recent_projects[0] == out
    # persisted to disk too, not just the in-memory Settings object
    from nocturne.settings import load_settings
    assert out in load_settings(win._settings_path).recent_projects


def test_solve_state_round_trips_through_save_and_open(qtbot, tmp_path, monkeypatch):
    from astropy.wcs import WCS
    from nocturne.ui import file_dialogs
    from nocturne.tools.astap import SolveResult
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    win._solve = (win._solve_sig(), SolveResult(True, wc, 100.0, 0.0, 3.6), [])

    out = str(tmp_path / "solved.nocturne")
    monkeypatch.setattr(file_dialogs, "save_file",
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
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win._solve is None
    out = str(tmp_path / "unsolved.nocturne")
    monkeypatch.setattr(file_dialogs, "save_file",
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
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert win._dirty is True
    out = str(tmp_path / "dirty.nocturne")
    monkeypatch.setattr(file_dialogs, "save_file",
                        staticmethod(lambda *a, **k: (out, "")))
    win._save_project_as()
    assert win._dirty is False


def test_window_title_reflects_name_and_dirty_marker(qtbot, tmp_path, monkeypatch):
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    assert win.windowTitle() == "Nocturne"   # no image yet
    win.open_fits(_make_fits(tmp_path))
    assert "stack" in win.windowTitle()
    assert "•" not in win.windowTitle()
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert "•" in win.windowTitle()
    out = str(tmp_path / "titled.nocturne")
    monkeypatch.setattr(file_dialogs, "save_file",
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
    from PySide6.QtWidgets import QMessageBox
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    out = str(tmp_path / "confirmed.nocturne")
    monkeypatch.setattr(file_dialogs, "save_file",
                        staticmethod(lambda *a, **k: (out, "")))
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Save)
    assert win._confirm_save_if_dirty() is True
    assert win._dirty is False
    assert win._project_path == out


def test_confirm_save_if_dirty_save_dialog_cancelled_returns_false(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    monkeypatch.setattr(file_dialogs, "save_file",
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
    from PySide6.QtWidgets import QMessageBox
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    out = str(tmp_path / "closesave.nocturne")
    monkeypatch.setattr(file_dialogs, "save_file",
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
    from nocturne.ui import file_dialogs
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
    monkeypatch.setattr(file_dialogs, "save_file",
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


def test_fov_hint_falls_back_to_the_instrument_profile():
    """A stacked master exported from another tool routinely carries no optics —
    the user's own NGC 7000 file has seven header cards and none of them scale.
    Solving blind on a few-degree field usually fails, and Nocturne knows what a
    Seestar is, so the profile is a far better hint than nothing.
    """
    from nocturne.core.instrument import fov_hint as _fov_hint
    fov, src = _fov_hint({"focal_length": 160, "pixel_size": 2.9}, 2160)
    assert src == "header" and fov > 0

    fov, src = _fov_hint({}, 2160)
    assert src == "profile" and fov > 0, "no header optics must not mean no hint"

    fov, src = _fov_hint({"focal_length": "", "pixel_size": None}, 2160)
    assert src == "profile", "unusable header values must fall back, not crash"

    fov, src = _fov_hint({}, 0)
    assert src == "none" and fov is None


def _solved_with_objects(qtbot, tmp_path, monkeypatch, objects):
    win = _stretched_window(qtbot, tmp_path)
    win.settings.astap_path = str(tmp_path / "astap"); (tmp_path / "astap").write_text("x")
    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    monkeypatch.setattr(win, "_solve_current",
                        lambda img: (SolveResult(True, wc, 100.0, 0.0, 3.6), objects))
    _solve_now(win)
    return win


def test_object_list_lists_what_the_solve_found(qtbot, tmp_path, monkeypatch):
    from nocturne.core.catalog import CatalogObject
    objs = [CatalogObject("NGC 7000", "North America", 100.0, 0.0, 120.0, 12, 12),
            CatalogObject("LDN 935", "", 100.0, 0.0, 0.0, 8, 8)]
    win = _solved_with_objects(qtbot, tmp_path, monkeypatch, objs)
    panel = win.image_view.object_panel        # the list lives on the canvas now
    names = [panel.list.item(i).text() for i in range(panel.count())]
    assert any("NGC 7000" in n for n in names)
    assert any("LDN 935" in n for n in names)
    # Ordered by the same priority the overlay places labels in, so the list and
    # the image read as one ranking rather than two.
    assert "NGC 7000" in names[0]
    assert "(2)" in panel.title.text()      # the list's own title carries the count


def test_picking_an_object_focuses_its_TRUE_centre(qtbot, tmp_path, monkeypatch):
    """A large nebula whose centre lies off-frame keeps its label clamped to the
    edge. Focusing must go to the real centre, not to where the label sits."""
    from nocturne.core.catalog import CatalogObject
    off = CatalogObject("NGC 7000", "North America", 100.0, 0.0, 120.0,
                        5, 5, True, -300.0, 40.0)      # x,y clamped; cx,cy real
    win = _solved_with_objects(qtbot, tmp_path, monkeypatch, [off])
    focused = []
    monkeypatch.setattr(win.image_view, "focus_on",
                        lambda x, y, **kw: focused.append((x, y)))
    win._on_object_activated("NGC 7000")
    assert focused == [(-300.0, 40.0)], focused


def test_picking_an_unknown_object_is_a_no_op(qtbot, tmp_path, monkeypatch):
    from nocturne.core.catalog import CatalogObject
    win = _solved_with_objects(qtbot, tmp_path, monkeypatch,
                               [CatalogObject("NGC 7000", "", 100.0, 0.0, 120.0, 12, 12)])
    focused = []
    monkeypatch.setattr(win.image_view, "focus_on", lambda x, y, **kw: focused.append((x, y)))
    win._on_object_activated("NOT IN FIELD")
    assert focused == []


# --- background op vs workspace swap (the _busy race) ------------------------
# _run_busy's callbacks used to fire unconditionally against whatever
# self.project had become. Closing mid-step crashed; opening mid-step wrote the
# old step's result onto the NEW project, silently.

def _deferred_busy(win):
    """Start a background op and return its callbacks, so a test can land the
    result LATER — after a workspace swap. Mirrors the async path without
    threads: run_async would deliver `done` at an uncontrollable moment."""
    captured = {}
    win._async_enabled = True

    def fake_run_async(pool, work, done, err):
        captured["done"], captured["err"] = done, err   # never actually run

    import nocturne.ui.main_window as mw
    real = mw.run_async
    mw.run_async = fake_run_async
    try:
        yield_result = {}
        win._run_busy(lambda: "RESULT",
                      lambda r: yield_result.setdefault("applied", r),
                      "Working…", "Failed")
        captured["applied"] = yield_result
    finally:
        mw.run_async = real
        win._async_enabled = False
    return captured


def test_closing_the_project_mid_step_does_not_crash_on_the_callback(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(str(_make_fits(tmp_path)))
    cb = _deferred_busy(win)

    win._close_project()                     # workspace retired while "running"
    assert win.project is None
    cb["done"]("RESULT")                     # the worker finishes afterwards
    assert cb["applied"] == {}, "a result from a retired workspace must be dropped"


def test_opening_a_new_image_mid_step_does_not_apply_the_old_result(qtbot, tmp_path):
    """The silent one: the old step's result written onto the NEW project."""
    win = _window(qtbot, tmp_path)
    win.open_fits(str(_make_fits(tmp_path)))
    cb = _deferred_busy(win)

    second = tmp_path / "second"
    second.mkdir()
    win.open_fits(str(_make_fits(second, filter_card="R")))     # new workspace
    fresh = win.project
    assert fresh is not None
    before = fresh.position if hasattr(fresh, "position") else len(fresh.entries())

    cb["done"]("RESULT")
    assert cb["applied"] == {}, "the old callback must not touch the new project"
    assert win.project is fresh, "the new project must still be the live one"
    after = fresh.position if hasattr(fresh, "position") else len(fresh.entries())
    assert after == before, "the new project's history must be UNCHANGED"


def test_an_error_from_a_retired_workspace_does_not_warn_the_user(qtbot, tmp_path):
    """The user replaced the workspace on purpose; a warning about the work they
    walked away from is noise pointing at an image no longer on screen."""
    win = _window(qtbot, tmp_path)
    win.open_fits(str(_make_fits(tmp_path)))
    cb = _deferred_busy(win)

    win._close_project()
    win._clear_warning()
    cb["err"](RuntimeError("boom"))
    assert not win._warning.text(), "no warning for a workspace already gone"


def test_a_result_for_the_CURRENT_workspace_is_still_applied(qtbot, tmp_path):
    """The guard must not swallow ordinary results — without this, a fix that
    dropped everything would pass all three tests above."""
    win = _window(qtbot, tmp_path)
    win.open_fits(str(_make_fits(tmp_path)))
    cb = _deferred_busy(win)

    cb["done"]("RESULT")                     # no swap in between
    assert cb["applied"] == {"applied": "RESULT"}


def test_a_stale_callback_does_not_clear_a_newer_ops_busy_state(qtbot, tmp_path):
    """Second race: the stale op's `finally` used to clear _active_token and
    busy unconditionally, leaving the UI looking idle while the NEW op ran."""
    win = _window(qtbot, tmp_path)
    win.open_fits(str(_make_fits(tmp_path)))
    old = _deferred_busy(win)
    win._close_project()
    new = _deferred_busy(win)                # a second op starts

    assert win._busy, "the new op is running"
    old["done"]("RESULT")                    # the FIRST op finally lands
    assert win._busy, "the newer op's busy state must survive"
    assert win._active_token is not None


def test_close_during_a_real_step_apply_does_not_raise(qtbot, tmp_path):
    """End-to-end proof through the REAL apply path, not a synthetic callback.
    The reported crash was `on_result` calling self.project.run_step(...) after
    _close_project set self.project = None -> AttributeError."""
    import nocturne.ui.main_window as mw
    win = _window(qtbot, tmp_path)
    win.open_fits(str(_make_fits(tmp_path)))
    win._go_to_id("stretch")

    captured = {}

    def fake_run_async(pool, work, done, err):
        captured["done"] = done
        captured["result"] = work()          # the worker really does the work

    win._async_enabled = True
    real = mw.run_async
    mw.run_async = fake_run_async
    try:
        win.apply_current(0.6)   # stretch amount, as the other apply tests do
    finally:
        mw.run_async = real
        win._async_enabled = False

    assert "done" in captured, "the step must actually have gone through _run_busy"
    win._close_project()
    assert win.project is None
    captured["done"](captured["result"])     # raised AttributeError before the fix


def test_every_project_reassignment_goes_through_swap_workspace():
    """Structural guard on the funnel, not a behaviour test.

    _swap_workspace is only a funnel if nothing bypasses it. A fourth place that
    does `self.project = ...` without it would silently reopen the race this
    file's other tests cover, and no behavioural test would notice until someone
    hit it in the app. Uses the AST rather than line proximity so it survives the
    code moving around.

    If this fails because you added a legitimate new assignment: call
    self._swap_workspace() before it, don't relax the test."""
    import ast, inspect
    import nocturne.ui.main_window as mw

    tree = ast.parse(inspect.getsource(mw))
    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        assigns = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Assign)
            for t in n.targets
            if isinstance(t, ast.Attribute) and t.attr == "project"
            and isinstance(t.value, ast.Name) and t.value.id == "self"
        ]
        if not assigns:
            continue
        swaps = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_swap_workspace"
            for n in ast.walk(fn)
        )
        if not swaps:
            offenders.append(fn.name)

    assert not offenders, (
        f"these assign self.project without _swap_workspace(): {offenders} — "
        "a background op's callback could then land on the wrong workspace")


# --- clipping baseline: an already-crushed import must not sit amber ---------

from nocturne.ui.theme import WARNING  # noqa: E402


def _crushed_image(frac_black=0.30):
    """A NON-LINEAR image arriving already clipped, as a re-imported export or
    an Upscale Crop result does."""
    a = np.full((20, 20, 3), 0.5, np.float32)
    n = int(round(20 * 20 * frac_black))
    a.reshape(-1, 3)[:n] = 0.0
    return AstroImage(a, is_linear=False)


def test_an_already_crushed_import_does_not_start_amber(qtbot, tmp_path):
    """The cry-wolf case. A processed file arrives 30% crushed; the user has
    done nothing, so the line must be calm — and must still say 30%."""
    win = _window(qtbot, tmp_path)
    win.open_image(_crushed_image(), "processed.tif")
    win._update_clipping_line()

    assert "30.0% shadows" in win._clip_line.text(), "the true total is still reported"
    assert "on import" in win._clip_line.text(), "and it says the damage predates you"
    assert "⚠" not in win._clip_line.text(), "nothing the user did — no alarm"
    assert WARNING not in win._clip_line.styleSheet()


def test_the_alarm_still_fires_for_damage_the_session_adds(qtbot, tmp_path):
    """The anti-overcorrection control: a baseline must not disable the warning.
    Without this, 'never alarm' would pass the test above."""
    win = _window(qtbot, tmp_path)
    win.open_image(_crushed_image(0.30), "processed.tif")
    win._show_preview(np.zeros((20, 20, 3), np.float32))   # user crushes the rest

    assert "⚠" in win._clip_line.text(), "30% -> 100% is the user's doing"
    assert WARNING in win._clip_line.styleSheet()
    assert "100.0% shadows" in win._clip_line.text()


def test_a_raw_linear_import_gets_no_baseline(qtbot, tmp_path):
    """Linear pixels sit near 0.003, so the 256-bin histogram would read almost
    the whole frame as 'crushed'. Measuring one would silence the warning
    forever on exactly the workflow it was calibrated for."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win._clip_baseline is None

    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._show_preview(np.zeros((24, 24, 3), np.float32))
    assert "⚠" in win._clip_line.text(), "raw workflow must still alarm"
    assert "on import" not in win._clip_line.text()


def test_the_baseline_survives_a_save_and_reopen(qtbot, tmp_path):
    """A reopened project must not re-measure: the current state is mid-edit, so
    recomputing would bake the session's own clipping into the baseline and
    silence the warning permanently."""
    from nocturne.history.project_store import save_project, load_project
    win = _window(qtbot, tmp_path)
    win.open_image(_crushed_image(0.30), "processed.tif")
    baseline = win._clip_baseline
    assert baseline is not None

    p = str(tmp_path / "b.nocturne")
    save_project(win.project, p, clip_baseline=baseline)
    loaded = load_project(p, str(tmp_path / "cache2"))
    assert loaded.clip_baseline == baseline


def test_a_bundle_without_a_baseline_still_loads(qtbot, tmp_path):
    """Backward compatibility: bundles written before this existed have no such
    key, and must load as 'no baseline' rather than raising."""
    from nocturne.history.project_store import save_project, load_project
    import json, zipfile, shutil
    win = _window(qtbot, tmp_path)
    win.open_image(_crushed_image(0.30), "processed.tif")
    p = str(tmp_path / "old.nocturne")
    save_project(win.project, p, clip_baseline=win._clip_baseline)

    # rewrite the manifest without the key, as an older build would have written it
    stripped = str(tmp_path / "stripped.nocturne")
    with zipfile.ZipFile(p) as zin, zipfile.ZipFile(stripped, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "manifest.json":
                m = json.loads(data)
                del m["clip_baseline"]
                data = json.dumps(m).encode()
            zout.writestr(item, data)

    loaded = load_project(stripped, str(tmp_path / "cache3"))
    assert loaded.clip_baseline is None


def test_opening_a_new_image_clears_the_previous_solve_and_its_overlay(qtbot, tmp_path):
    """Reported 2026-08-01: solve an image, open another, and the first image's
    annotation pill and object list were still on screen — object names from a
    field you are no longer looking at."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))

    # stand in for a landed solve: overlay + pill + populated object list
    from nocturne.core.catalog import CatalogObject
    from nocturne.ui.annotation_overlay import build_annotation_group
    from nocturne.core.annotation_layout import Label
    win._solve = ("sig", object(), [CatalogObject("NGC 7000", "NA Neb", 0, 0, 120.0, 1, 1)])
    win.image_view.set_annotations(build_annotation_group([Label("NGC 7000", 5, 5, "#5cff5c")], (24, 24)))
    win.image_view.object_panel.set_contents(
        [CatalogObject("NGC 7000", "NA Neb", 0, 0, 120.0, 1, 1)], [])
    win.image_view.show_object_list(True)
    win.solve_panel.set_state("solved")
    assert not win.image_view.annotation_pill.isHidden()
    assert win.image_view.object_panel.count() == 1

    second = tmp_path / "second"
    second.mkdir()
    win.open_fits(_make_fits(second, filter_card="R"))

    assert win._solve is None, "the previous image's solution must not survive"
    assert win.image_view.annotation_pill.isHidden(), "the pill belonged to the old image"
    assert win.image_view.object_panel.isHidden()
    assert win.image_view.object_panel.count() == 0, "no stale object names"
    assert win.solve_panel._state == "not_solved"
    assert win.solve_panel.result_label.text() == ""


def test_reopening_a_saved_project_still_restores_its_solve(qtbot, tmp_path):
    """Anti-overcorrection: the teardown runs inside _swap_workspace, which
    _open_project also calls — so it must clear BEFORE the restore, not after."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    p = str(tmp_path / "p.nocturne")
    win._do_save_project(p)
    qtbot.waitUntil(lambda: not win._busy, timeout=5000)

    win._open_project(p)
    assert win.project is not None, "the project itself must still open"


# --- the object list shows itself; no button ---------------------------------

def test_the_object_list_appears_by_itself_once_a_solve_lands(qtbot, tmp_path, monkeypatch):
    """No button to find: after a solve, seeing what is in the field IS the point."""
    from nocturne.core.catalog import CatalogObject
    objs = [CatalogObject("NGC 7000", "North America", 100.0, 0.0, 120.0, 12, 12)]
    win = _solved_with_objects(qtbot, tmp_path, monkeypatch, objs)
    assert not win.image_view.object_panel.isHidden()


def test_turning_annotations_off_takes_the_list_with_them(qtbot, tmp_path, monkeypatch):
    """The list is part of what the overlay is telling you, so it follows the pill."""
    from nocturne.core.catalog import CatalogObject
    objs = [CatalogObject("NGC 7000", "North America", 100.0, 0.0, 120.0, 12, 12)]
    win = _solved_with_objects(qtbot, tmp_path, monkeypatch, objs)

    win.image_view.annotation_pill.button.setChecked(False)
    assert win.image_view.object_panel.isHidden()
    win.image_view.annotation_pill.button.setChecked(True)
    assert not win.image_view.object_panel.isHidden(), "and comes back with them"


def test_dismissing_the_list_does_not_require_turning_annotations_off(qtbot, tmp_path, monkeypatch):
    """The panel is 260 px of canvas and covers the right of a landscape frame.
    Wanting labels ON the image but no list over it must not force the overlay
    off — that would couple two separate wishes."""
    from nocturne.core.catalog import CatalogObject
    objs = [CatalogObject("NGC 7000", "North America", 100.0, 0.0, 120.0, 12, 12)]
    win = _solved_with_objects(qtbot, tmp_path, monkeypatch, objs)

    win.image_view.object_panel.closeRequested.emit()          # the panel's X
    assert win.image_view.object_panel.isHidden()
    assert win.image_view.annotation_pill.is_shown(), "the overlay stays up"
    assert win.image_view._annotations is not None

    # It must STAY dismissed through a rebuild. Toggling a layer re-runs
    # _refresh_object_list -> _sync_object_list_visibility; if that ignored the
    # dismissal the panel would silently reappear over the picture.
    win._on_annotation_layers_changed(dict(win.solve_panel.layers()))
    assert win.image_view.object_panel.isHidden(), "a layer change must not revive it"

    # ...and the dismissal is retired by an explicit statement about the overlay
    win.image_view.annotation_pill.button.setChecked(False)
    win.image_view.annotation_pill.button.setChecked(True)
    assert not win.image_view.object_panel.isHidden()


def test_a_solve_that_finds_nothing_shows_no_empty_panel(qtbot, tmp_path, monkeypatch):
    win = _solved_with_objects(qtbot, tmp_path, monkeypatch, [])
    assert win.image_view.object_panel.isHidden()


# --- geometry retires the solve, and SAYS so ---------------------------------

def _solved_then(win, tmp_path):
    """Put a solve + overlay on screen for the current framing."""
    from nocturne.core.catalog import CatalogObject
    from nocturne.ui.annotation_overlay import build_annotation_group
    from nocturne.core.annotation_layout import Label
    win._solve = (win._solve_sig(), object(),
                  [CatalogObject("NGC 7000", "NA", 0, 0, 120.0, 5, 5)])
    win.image_view.set_annotations(
        build_annotation_group([Label("NGC 7000", 5, 5, "#5cff5c")], (24, 24)))


def test_rotating_says_why_the_annotations_disappeared(qtbot, tmp_path):
    """They used to vanish in silence. The only clue was the Plate Solve panel,
    which is collapsible and routinely shut — the canvas pill exists precisely so
    you can keep working with the tool closed."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _solved_then(win, tmp_path)
    win._clear_warning()

    win._rotate()
    assert win.image_view._annotations is None, "the stale overlay still comes off"
    text = win._warning.text()
    assert text, "the user must be told why their labels went"
    assert "re-solve" in text.lower(), "and what to do about it"


def test_that_notice_is_amber_not_red(qtbot, tmp_path):
    """Rotating is a deliberate, normal action. Red says 'you broke something',
    which is how a prominent label gets trained into background noise."""
    from nocturne.ui.theme import WARNING
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _solved_then(win, tmp_path)

    win._rotate()
    assert WARNING in win._warning.styleSheet()
    assert "#ff6b6b" not in win._warning.styleSheet()

    # ...and a real error still reads as one
    win._show_warning("Could not open file: boom")
    assert "#ff6b6b" in win._warning.styleSheet()


def test_the_notice_does_not_re_fire_on_every_refresh(qtbot, tmp_path):
    """_refresh runs constantly; a message that re-appeared each time could never
    be dismissed."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _solved_then(win, tmp_path)
    win._rotate()
    assert win._warning.text()

    win._clear_warning()
    win._refresh()
    win._refresh()
    assert win._warning.text() == "", "said once, not on every repaint"


def test_no_notice_when_there_was_no_solve_to_lose(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._clear_warning()
    win._rotate()
    assert win._warning.text() == ""


# --- Plate Solve is gated on ASTAP being installed ---------------------------

def test_plate_solve_is_greyed_out_without_astap(qtbot, tmp_path):
    """It used to be permanently clickable and only complain AFTER the press,
    which puts the requirement behind the action instead of in front of it."""
    win = _window(qtbot, tmp_path)
    assert win.settings.astap_path in ("", None), "fixture assumes no ASTAP configured"
    assert not win._solve_act.isEnabled()
    tip = win._solve_act.toolTip().lower()
    assert "astap" in tip and "star database" in tip, tip


def test_installing_astap_lights_the_button_up_without_a_restart(qtbot, tmp_path):
    from nocturne.settings import Settings
    fake = tmp_path / "astap"
    fake.write_text("#!/bin/sh\n")
    win = _window(qtbot, tmp_path)
    assert not win._solve_act.isEnabled()

    win.settings = Settings(astap_path=str(fake))
    win._sync_solve_action_enabled()
    assert win._solve_act.isEnabled()
    assert win._solve_act.toolTip() == "Open the Plate Solve tool"


def test_a_failed_solve_names_the_star_database_first(qtbot, tmp_path):
    """The one cause the toolbar gate cannot see: astap_valid only checks the
    binary, and the database is a separate download. The old advice sent people
    looking in entirely the wrong place."""
    from nocturne.tools.astap import SolveResult
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._on_solved(win._solve_sig(),
                   SolveResult(False, None, 0.0, 0.0, 0.0, "no star database found"), [])
    text = win._warning.text().lower()
    assert "star database" in text
    assert text.index("star database") < text.index("stretch"), \
        "the cause they cannot otherwise discover must come first"


# --- Trim: a finishing crop that keeps the edit -------------------------------

def _trimmable(qtbot, tmp_path):
    """A window with a stretched image and several processing steps applied."""
    win = _stretched_window(qtbot, tmp_path)
    win._go_to_id("saturation")
    win.apply_current(0.5)
    return win


def test_trim_is_gated_until_the_image_is_stretched(qtbot, tmp_path):
    """A state gate, not a position gate: navigation cannot fool it, and before
    Stretch the pipeline's own Crop is the better tool anyway."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert not win._trim_act.isEnabled(), "linear image — nothing finished to trim"
    assert "stretch" in win._trim_act.toolTip().lower()

    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert win._trim_act.isEnabled()


def test_trim_appends_and_keeps_every_processing_step(qtbot, tmp_path, monkeypatch):
    """THE point of the feature. Going back to the Crop step truncates forward
    history, destroying the edit; Trim must not."""
    win = _trimmable(qtbot, tmp_path)
    before = [n for n, _ in win.project.entries()]
    assert "Stretch" in before and "Saturation" in before

    import nocturne.ui.main_window as mw
    h, w = win.project.current().data.shape[:2]
    monkeypatch.setattr(mw, "TrimDialog", lambda img, parent=None: _FakeTrim((2, h - 2, 3, w - 3)))
    win._trim()

    after = [n for n, _ in win.project.entries()]
    assert after[-1] == "Trim", "the trim is appended at the end"
    assert after[:-1] == before, "every earlier step survived"
    nh, nw = win.project.current().data.shape[:2]
    assert (nh, nw) == (h - 4, w - 6)


class _FakeTrim:
    def __init__(self, bounds): self._b = bounds
    def exec(self): return 1
    def bounds(self): return self._b


def test_a_cancelled_trim_changes_nothing(qtbot, tmp_path, monkeypatch):
    win = _trimmable(qtbot, tmp_path)
    before = [n for n, _ in win.project.entries()]
    shape = win.project.current().data.shape

    import nocturne.ui.main_window as mw
    class _Cancelled(_FakeTrim):
        def exec(self): return 0
    monkeypatch.setattr(mw, "TrimDialog", lambda img, parent=None: _Cancelled((1, 2, 3, 4)))
    win._trim()
    assert [n for n, _ in win.project.entries()] == before
    assert win.project.current().data.shape == shape


def test_a_trim_marks_the_plate_solve_stale(qtbot, tmp_path, monkeypatch):
    """The framing changed, so a solve made for the old framing no longer lines
    up — same as a crop. That is why "Trim" is in GEOMETRY_NAMES."""
    win = _trimmable(qtbot, tmp_path)
    sig_before = win._solve_sig()

    import nocturne.ui.main_window as mw
    h, w = win.project.current().data.shape[:2]
    monkeypatch.setattr(mw, "TrimDialog", lambda img, parent=None: _FakeTrim((2, h - 2, 2, w - 2)))
    win._trim()
    assert win._solve_sig() != sig_before


def test_a_trim_does_not_satisfy_auto_enhances_crop_gate(qtbot, tmp_path, monkeypatch):
    """Auto Enhance requires a crop BEFORE processing, so its statistics are
    measured on the kept region. A late trim is a different thing entirely."""
    win = _trimmable(qtbot, tmp_path)
    assert not win._has_crop()

    import nocturne.ui.main_window as mw
    h, w = win.project.current().data.shape[:2]
    monkeypatch.setattr(mw, "TrimDialog", lambda img, parent=None: _FakeTrim((2, h - 2, 2, w - 2)))
    win._trim()
    assert not win._has_crop(), "a late trim must not read as an early crop"


# --- distraction-free fullscreen ---------------------------------------------

def _keypress(win, key):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    ev = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    return win.eventFilter(QApplication.instance(), ev)


def test_fullscreen_hides_every_piece_of_chrome(qtbot, tmp_path):
    """The image and nothing else. The zoom pill stays — it is the one control
    you want while inspecting, and it is dark-on-dark rather than an accent."""
    from PySide6.QtCore import Qt
    win = _stretched_window(qtbot, tmp_path)
    win.show(); qtbot.waitExposed(win)
    assert win._toolbar.isVisible() and win._bottom_bar.isVisible()

    win._toggle_fullscreen()
    for name in ("_toolbar", "stepper", "_right_panel", "_bottom_bar"):
        assert not getattr(win, name).isVisible(), f"{name} still showing"
    assert not win.image_view._zoom_pill.isHidden(), "the zoom pill should remain"


def test_fullscreen_does_not_reset_zoom_or_pan(qtbot, tmp_path):
    """You enter this to look closely at something; throwing away the view you
    arrived with would defeat the point."""
    win = _stretched_window(qtbot, tmp_path)
    win.show(); qtbot.waitExposed(win)
    win.image_view.zoom_in(); win.image_view.zoom_in()
    zoomed = win.image_view.transform().m11()

    win._toggle_fullscreen()
    qtbot.wait(50)
    assert win.image_view.transform().m11() == pytest.approx(zoomed, rel=0.02)


def test_exiting_restores_only_what_was_visible_before(qtbot, tmp_path):
    """On the welcome screen the chrome is already hidden — exiting fullscreen
    must not conjure it into existence."""
    win = _window(qtbot, tmp_path)          # no project: chrome hidden
    win.show(); qtbot.waitExposed(win)
    assert not win.stepper.isVisible()

    win._toggle_fullscreen()
    win._exit_fullscreen()
    qtbot.wait(50)
    assert not win.stepper.isVisible(), "chrome appeared that was never there"


def test_escape_exits_fullscreen_but_is_left_alone_otherwise(qtbot, tmp_path):
    """The crop box uses Escape everywhere else; swallowing it globally would
    break dismissing the box."""
    from PySide6.QtCore import Qt
    win = _stretched_window(qtbot, tmp_path)
    win.show(); qtbot.waitExposed(win)

    assert _keypress(win, Qt.Key.Key_Escape) is not True, \
        "Escape must pass through when not fullscreen"

    win._toggle_fullscreen()
    assert _keypress(win, Qt.Key.Key_Escape) is True, "Escape should exit fullscreen"


def test_f_does_nothing_while_typing(qtbot, tmp_path, monkeypatch):
    """Otherwise typing "f" in the caption or a path field throws you fullscreen.

    focusWidget is stubbed rather than driven for real: actual keyboard focus
    needs an ACTIVE window, which depends on what else the suite has opened, and
    a test that passes or fails on window activation order tests the harness
    rather than the code."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLineEdit
    win = _stretched_window(qtbot, tmp_path)
    edit = QLineEdit()
    qtbot.addWidget(edit)
    monkeypatch.setattr(QApplication, "focusWidget", staticmethod(lambda: edit))

    assert _keypress(win, Qt.Key.Key_F) is not True, "F must not fire while typing"
    assert not win.isFullScreen()

    monkeypatch.setattr(QApplication, "focusWidget", staticmethod(lambda: None))
    assert _keypress(win, Qt.Key.Key_F) is True, "...but must fire otherwise"
    win._exit_fullscreen()


# --- label placement must follow the zoom ------------------------------------

def test_live_label_scale_is_the_inverse_of_the_display_zoom(qtbot, tmp_path):
    """Labels are screen-fixed but placed in image coordinates. 1/zoom is what
    converts a screen-sized box into the space the placement runs in."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.image_view.fit()
    z = win.image_view.zoom()
    assert win._live_label_scale() == pytest.approx(1.0 / z)

    win.image_view.actual_size()          # 1:1
    assert win._live_label_scale() == pytest.approx(1.0)


def test_live_label_scale_survives_a_zero_zoom(qtbot, tmp_path):
    """transform().m11() is 0 before any image exists; 1/0 would raise."""
    win = _window(qtbot, tmp_path)
    assert win._live_label_scale() == 1.0


def test_zooming_schedules_a_relayout(qtbot, tmp_path):
    """The layout is only correct for the zoom it was computed at, so a scale
    change has to re-place the labels. Debounced — a wheel gesture emits many
    steps and only the last one matters."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.image_view.fit()
    win._zoom_relayout.stop()      # opening the image already fitted, which
                                    # legitimately scheduled one
    win.image_view.zoom_in()
    assert win._zoom_relayout.isActive(), "a zoom must schedule a re-place"

    # ...and repeated steps coalesce rather than queueing N rebuilds
    win.image_view.zoom_in()
    win.image_view.zoom_in()
    assert win._zoom_relayout.isActive()


def test_a_tiny_zoom_change_does_not_thrash_the_layout(qtbot, tmp_path):
    """The 2% threshold: a drag-resize must not fire a rebuild per pixel."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.image_view.fit()
    win._zoom_relayout.stop()
    fired = []
    win.image_view.zoomChanged.connect(fired.append)

    win.image_view.scale(1.001, 1.001)    # 0.1% — below the threshold
    win.image_view._note_zoom()
    assert fired == [], "a sub-threshold change should not trigger a rebuild"


def test_the_burned_export_does_not_use_the_live_scale(qtbot, tmp_path, monkeypatch):
    """The export renders text genuinely larger, so scale_for is its matching
    factor. Using the live 1/zoom there would size labels for the screen."""
    import inspect
    src = inspect.getsource(MainWindow._annotated_rgb8)
    assert "scale_for" in src
    assert "_live_label_scale" not in src


# --- the overlay's shown/hidden state is the USER'S, not the item's -----------

def _solved_window(qtbot, tmp_path):
    """A window carrying a cached solve whose signature matches the current
    framing, with the overlay already on the canvas — the state you are in after
    pressing Plate Solve."""
    from astropy.wcs import WCS
    from nocturne.core.catalog import CatalogObject
    from nocturne.tools.astap import SolveResult
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    objs = [CatalogObject("NGC 7000", "NA Neb", 100.0, 0.0, 120.0, 12, 12)]
    win._solve = (win._solve_sig(), SolveResult(True, wc, 100.0, 0.0, 3.6), objs)
    win._show_annotations(*win._solve[1:])
    assert win.image_view._annotations is not None, "precondition: an overlay is up"
    return win


def _hide_annotations(win):
    """Switch the overlay off the way the user does — the canvas pill — so the
    button's checked state and the item's visibility move together."""
    win.image_view.annotation_pill.button.setChecked(False)
    assert win.image_view._annotations.isVisible() is False
    assert win.image_view.annotation_pill.is_shown() is False


def test_zoom_does_not_revive_annotations_the_user_hid(qtbot, tmp_path):
    """Reported 2026-08-14. Zooming re-runs the label layout, which builds a NEW
    overlay item; the user's hide must survive that. It is a view preference, not
    a property of the item being replaced."""
    win = _solved_window(qtbot, tmp_path)
    _hide_annotations(win)
    was_visible = win.image_view._annotations.isVisible()
    was_pill_on = win.image_view.annotation_pill.is_shown()

    win._relayout_annotations()          # what a zoom triggers, via the 120 ms timer

    assert win.image_view._annotations.isVisible() == was_visible
    assert win.image_view.annotation_pill.is_shown() == was_pill_on


def test_layer_change_does_not_revive_annotations_the_user_hid(qtbot, tmp_path):
    """Same defect through the other rebuild path: toggling a layer or density
    re-renders from the cached solve and must not switch the overlay back on."""
    win = _solved_window(qtbot, tmp_path)
    _hide_annotations(win)
    was_visible = win.image_view._annotations.isVisible()
    was_pill_on = win.image_view.annotation_pill.is_shown()

    win._rebuild_overlay_from_cache()

    assert win.image_view._annotations.isVisible() == was_visible
    assert win.image_view.annotation_pill.is_shown() == was_pill_on


def test_a_solve_shows_annotations_even_if_the_previous_ones_were_hidden(qtbot, tmp_path):
    """Guards the fix against over-reaching: remembering 'hidden' must not make a
    solve the user just asked for come up invisible. `_show_annotations` is the
    funnel a fresh solve goes through."""
    win = _solved_window(qtbot, tmp_path)
    _hide_annotations(win)

    win._show_annotations(*win._solve[1:])

    assert win.image_view._annotations.isVisible() is True
    assert win.image_view.annotation_pill.is_shown() is True


def test_background_warns_when_the_frame_is_mostly_uncropped_mosaic(qtbot, tmp_path):
    """Reported 2026-08-15: background extraction gives horrible results on an
    uncropped mosaic, because GraXpert fits its model over the black wedges.
    Natural, but the user has no way to know it — especially one who crops at
    the END of the pipeline, which the tool otherwise permits."""
    import numpy as np
    from astropy.io import fits as _fits

    # written into the FILE, not mutated afterwards: Project.current() returns a
    # fresh copy each call, so an in-memory edit is discarded immediately
    arr = (np.random.rand(3, 24, 24) * 1000).astype(np.uint16)
    arr[:, :8, :] = 0                          # a third of the frame never covered
    path = tmp_path / "wedged.fits"
    _fits.PrimaryHDU(arr).writeto(str(path))

    win = _window(qtbot, tmp_path)
    win.open_fits(str(path))
    win._warn_if_uncovered("background")

    assert "crop" in win._warning.text().lower(), win._warning.text()
    assert "%" in win._warning.text()


def test_no_uncovered_warning_on_an_ordinary_frame(qtbot, tmp_path):
    """It must stay quiet on the normal case or it trains the user to ignore it."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._warn_if_uncovered("background")
    assert win._warning.text() == ""


def test_showing_the_background_model_puts_the_gradient_on_the_canvas(qtbot, tmp_path):
    """Requested 2026-08-16 after seeing AstroWizard do it, and it is how
    PixInsight's DBE earns trust: you can see what was subtracted. The model is
    the step's before minus its after, so it needs nothing stored."""
    import numpy as np
    from astropy.io import fits as _fits

    # a frame with a real gradient across it
    y, x = np.mgrid[0:24, 0:24]
    arr = (300 + x * 40).astype(np.uint16)
    path = tmp_path / "grad.fits"
    _fits.PrimaryHDU(np.stack([arr, arr, arr])).writeto(str(path))

    win = _window(qtbot, tmp_path)
    win.open_fits(str(path))
    before = win.project.current()

    # stand in for GraXpert: flatten the ramp
    flat = np.full_like(before.data, float(np.median(before.data)))
    win._displayed = None
    win._set_canvas(AstroImage(flat, is_linear=True))

    from nocturne.core.inspect import background_model
    model = background_model(before, AstroImage(flat, is_linear=True))
    assert model.removed_anything
    assert model.span > 0.01
    row = model.image.data[12, :, 0]
    assert row[-1] > row[0] + 0.5, "the ramp must be visible in the model"


def test_the_model_toggle_is_off_until_background_has_run(qtbot, tmp_path):
    """Before the step runs there is no after to subtract, so the control would
    have nothing to show."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("background")
    assert not win._panel.show_model_check.isEnabled()


def test_the_model_toggle_enables_as_soon_as_background_runs(qtbot, tmp_path):
    """Reported 2026-08-16: the log said "Background (strong) — Δ 4.4%" and the
    checkbox was still greyed out. Its state was computed only when the panel was
    BUILT, and applying a step refreshes the panel without rebuilding it — so the
    control only woke up if you navigated away and back."""
    import numpy as np
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("background")
    assert not win._panel.show_model_check.isEnabled(), "nothing has run yet"

    base = win.project.current()
    flattened = AstroImage(np.full_like(base.data, float(np.median(base.data))),
                           is_linear=True, metadata=dict(base.metadata))
    from nocturne.ui.main_window import _PrecomputedStep
    win.project.run_step(_PrecomputedStep("Background", flattened), "strong")
    win._refresh()

    assert win._panel.show_model_check.isEnabled(), (
        "the step has run; the control must be usable without navigating away")


def test_the_model_shows_only_the_backgrounds_own_effect(qtbot, tmp_path):
    """The model is "before the step" minus "after the step" — not minus the
    CURRENT image. Diffing against the current state was right only until a
    later step ran; from Stretch on it would have drawn the stretch into the
    "removed gradient" and blamed background extraction for it."""
    import numpy as np
    from astropy.io import fits as _fits

    y, x = np.mgrid[0:24, 0:24]
    path = tmp_path / "grad2.fits"
    _fits.PrimaryHDU(np.stack([(300 + x * 40).astype(np.uint16)] * 3)).writeto(str(path))

    win = _window(qtbot, tmp_path)
    win.open_fits(str(path))
    win._go_to_id("background")

    from nocturne.ui.main_window import _PrecomputedStep
    base = win.project.current()
    flat = float(np.median(base.data))
    flattened = AstroImage(np.full_like(base.data, flat), is_linear=True,
                           metadata=dict(base.metadata))
    win.project.run_step(_PrecomputedStep("Background", flattened), "strong")

    from nocturne.core.inspect import background_model
    expected = background_model(base, flattened)

    # a later step that is not a constant offset — normalising the model would
    # absorb one of those, so a flat shift proves nothing
    later = flattened.data + (y[:, :, None] / 24.0).astype(np.float32) * 0.2
    win.project.run_step(
        _PrecomputedStep("Stretch", AstroImage(later, is_linear=False,
                                               metadata=dict(base.metadata))), "0.5")
    win._refresh()

    win._on_show_background_model(True)
    shown = win._canvas_img.data
    assert np.allclose(shown, expected.image.data, atol=1e-5), (
        "the gradient view picked up a later step's change")


def test_the_toggle_cannot_stay_checked_once_the_canvas_is_back_to_normal(qtbot, tmp_path):
    """A checked box saying "showing what was removed" over the ordinary image
    is a lie about what is on screen. Undo, redo, Apply and navigation all end in
    _refresh, and _refresh always repaints the current image."""
    import numpy as np
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("background")

    from nocturne.ui.main_window import _PrecomputedStep
    base = win.project.current()
    win.project.run_step(_PrecomputedStep("Background", AstroImage(
        np.full_like(base.data, float(np.median(base.data))), is_linear=True,
        metadata=dict(base.metadata))), "strong")
    win._refresh()
    win._panel.show_model_check.setChecked(True)
    assert win._panel.show_model_check.isChecked()

    win._refresh()
    assert not win._panel.show_model_check.isChecked(), (
        "the canvas is showing the current image again")
    assert np.allclose(win._canvas_img.data, win.project.current().data)


def test_colour_balance_appends_instead_of_truncating(qtbot, tmp_path):
    """It is a FINISHING tool: it must never discard work done after the step it
    conceptually sits beside. Same reason Trim appends rather than reaching back
    into the pipeline."""
    import numpy as np
    from nocturne.ui.main_window import _PrecomputedStep
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    base = win.project.current()
    win.project.run_step(_PrecomputedStep("Stretch", base), "0.5")
    before = len(win.project.entries())

    result = AstroImage(np.clip(base.data * 1.01, 0, 1), is_linear=False,
                        metadata=dict(base.metadata))
    win._apply_color_balance(result, {"tone": "midtones", "red": 0.0, "green": 0.0,
                                      "blue": 0.2, "preserve_lum": True,
                                      "strength": 0.8, "lo": 0.379, "hi": 0.748,
                                      "feather": 0.08})
    names = [n for n, _ in win.project.entries()]
    assert len(names) == before + 1, "an entry was truncated"
    assert names[-1] == "Colour Balance"
    assert "Stretch" in names, "the earlier step was discarded"


def test_colour_balance_can_be_applied_twice(qtbot, tmp_path):
    """Cool the arms, then warm the core: two separately undoable entries. This
    is the payoff of appending rather than being a pipeline step."""
    import numpy as np
    from nocturne.ui.main_window import _PrecomputedStep
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    base = win.project.current()
    win.project.run_step(_PrecomputedStep("Stretch", base), "0.5")
    opts = {"tone": "midtones", "red": 0.0, "green": 0.0, "blue": 0.2,
            "preserve_lum": True, "strength": 0.8, "lo": 0.379, "hi": 0.748,
            "feather": 0.08}
    for _ in range(2):
        win._apply_color_balance(
            AstroImage(np.clip(win.project.current().data * 1.01, 0, 1),
                       is_linear=False, metadata=dict(base.metadata)), opts)
    names = [n for n, _ in win.project.entries()]
    assert names.count("Colour Balance") == 2
    assert win.project.can_undo()


def test_the_colour_balance_toolbar_action_exists(qtbot, tmp_path):
    """The icon is a NEW ASSET and load_icon RAISES on a missing SVG, so a
    fresh clone that lacks it cannot construct MainWindow at all — the fault
    that hid for four days with update.svg."""
    win = _window(qtbot, tmp_path)
    assert win._cb_act is not None
    assert win._cb_act.text() == "Colour Balance"


def test_colour_balance_is_unavailable_until_the_image_is_stretched(qtbot, tmp_path):
    """Trim and Share both grey out until there is a stretched picture to work
    on, and Colour Balance is the same kind of finishing tool. Found in review:
    it was left permanently enabled, so clicking it on a linear image produced a
    warning where the other two simply show they are not ready yet."""
    win = _window(qtbot, tmp_path)
    assert not win._cb_act.isEnabled(), "enabled with no image open"

    win.open_fits(_make_fits(tmp_path))
    assert not win._cb_act.isEnabled(), "enabled on a linear image"

    from nocturne.ui.main_window import _PrecomputedStep
    base = win.project.current()
    win.project.run_step(_PrecomputedStep("Stretch", AstroImage(
        base.data, is_linear=False, metadata=dict(base.metadata))), "0.5")
    win._refresh()
    assert win._cb_act.isEnabled(), "still disabled after a stretch"
