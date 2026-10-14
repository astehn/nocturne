import pytest
pytest.importorskip("PySide6")
from tests.ui.test_main_window import _make_fits
from nocturne import user_presets as up

STEPS = [{"stage": "stretch", "option": {"amount": 0.3, "linked": True}},
         {"stage": "levels", "option": [0.02, 1.0, 1.0]},
         {"stage": "local_contrast", "option": 0.15},
         {"stage": "enhance", "option": "Vibrance"}]


def _jpeg():
    import io
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (30, 20)).save(b, "JPEG"); return b.getvalue()


def _win(qtbot, tmp_path):
    """test_main_window._window, registered so the close at teardown finds it
    clean: a preset run leaves it dirty, and a dirty close asks a question
    (answered only by the conftest's blanket "Discard")."""
    from nocturne.ui.main_window import MainWindow
    win = MainWindow(settings_path=str(tmp_path / "settings.json"), check_updates=False,
                     telemetry=False)
    win._async_enabled = False
    qtbot.addWidget(win, before_close_func=lambda w: setattr(w, "_dirty", False))
    return win


def _setup(qtbot, tmp_path, card="L", steps=STEPS, name="M 8", dt="broadband"):
    win = _win(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path, filter_card=card))
    win._go_to_id("crop", user_initiated=False)
    p = win._presets.save(name, steps, _jpeg(), target="M 8", data_type=dt)
    return win, p


def _choose(win, p):
    win._choose_preset(p)            # what the browser's Choose calls back with


def _box(win, bounds=(4, 20, 4, 20)):
    win.image_view.show_crop_box()
    win.image_view.crop_bounds = lambda: bounds


def test_choosing_applies_nothing_and_renames_the_button(qtbot, tmp_path):
    win, p = _setup(qtbot, tmp_path)
    before = win.project.entries()
    _choose(win, p)
    assert win.project.entries() == before
    _box(win); win._sync_step_controls()
    assert win._panel.apply_btn.text() == "Apply Crop + M 8"
    assert win._panel.preset_chip.isVisibleTo(win._panel)
    assert "M 8" in win._panel.preset_chip_name.text()


def test_without_a_preset_apply_crop_only_crops(qtbot, tmp_path):
    win, _p = _setup(qtbot, tmp_path)
    _box(win)
    assert win._panel.apply_btn.text() == "Apply Crop"
    win._apply_crop()
    assert [n for n, _ in win.project.entries()] == ["Crop"]


def test_apply_crop_plus_preset_crops_then_records_every_step(qtbot, tmp_path):
    win, p = _setup(qtbot, tmp_path)
    _choose(win, p); _box(win)
    win._apply_crop()
    names = [n for n, _ in win.project.entries()]
    assert names == ["Crop", "Stretch", "Levels", "Local Contrast", "Vibrance"]
    opts = dict(win.project.entries())
    assert opts["Levels"] == [0.02, 1.0, 1.0]        # saved values, not re-derived
    assert opts["Vibrance"] == ""                     # as a hand tap records it
    assert win.current_stage_id() == "enhancements"
    assert win._chosen_preset is None
    assert win._presets.find("M 8").last_used != ""


def test_each_recorded_step_is_an_ordinary_undoable_step(qtbot, tmp_path):
    win, p = _setup(qtbot, tmp_path)
    _choose(win, p); _box(win); win._apply_crop()
    n = len(win.project.entries())
    win._undo()
    assert len(win.project.entries()) == n - 1 and win.project.can_redo()


def test_apply_without_a_box_applies_the_preset_to_the_current_geometry(qtbot, tmp_path):
    from tests.ui.test_main_window import _crop
    win, p = _setup(qtbot, tmp_path)
    _crop(win)
    win._go_to_id("crop", user_initiated=False)
    _choose(win, p)
    assert win._panel.apply_btn.text() == "Apply M 8" and win._panel.apply_btn.isEnabled()
    win._apply_crop()
    assert [n for n, _ in win.project.entries()][:2] == ["Crop", "Stretch"]
    assert [n for n, _ in win.project.entries()].count("Crop") == 1


def test_existing_processing_is_only_discarded_after_asking(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from tests.ui.test_main_window import _crop
    win, p = _setup(qtbot, tmp_path)
    _crop(win); win._go_to_id("stretch", user_initiated=False); win._panel.apply_btn.click()
    win._go_to_id("crop", user_initiated=False)
    before = list(win.project.entries())
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Cancel)
    _choose(win, p); win._apply_crop()
    assert win.project.entries() == before                # unchanged, not merely different


def test_a_stage_that_raises_on_this_picture_is_named_and_the_rest_run(qtbot, tmp_path, monkeypatch):
    from nocturne.steps.local_contrast import LocalContrastStep
    monkeypatch.setattr(LocalContrastStep, "apply",
                        lambda self, img, o: (_ for _ in ()).throw(RuntimeError("boom\nmore")))
    win, p = _setup(qtbot, tmp_path)
    _choose(win, p); _box(win); win._apply_crop()
    names = [n for n, _ in win.project.entries()]
    assert "Local Contrast" not in names and names[-1] == "Vibrance"
    assert win._warning.text() == "Preset M 8: 3 of 4 steps — Local Contrast failed: boom"


def test_a_step_the_machine_cannot_run_is_left_out_and_named_before_running(qtbot, tmp_path):
    steps = [{"stage": "background", "option": "strong"}] + STEPS   # no GraXpert configured
    win, p = _setup(qtbot, tmp_path, steps=steps)
    _choose(win, p); _box(win); win._apply_crop()
    assert "Background" not in [n for n, _ in win.project.entries()]
    out = win.output_panel.toPlainText()
    assert "Background was left out" in out, out


def test_cancel_mid_run_leaves_the_crop_and_no_preset_steps(qtbot, tmp_path, monkeypatch):
    from nocturne.steps.levels import LevelsStep
    win, p = _setup(qtbot, tmp_path)
    real = LevelsStep.apply
    def cancel_then_apply(self, img, o):
        win._cancel_active()
        return real(self, img, o)
    monkeypatch.setattr(LevelsStep, "apply", cancel_then_apply)
    _choose(win, p); _box(win); win._apply_crop()
    assert [n for n, _ in win.project.entries()] == ["Crop"]
    assert win.project.position == 1 and not win.project.can_redo()
    assert win._chosen_preset is not None                       # kept: press again to retry


def test_dual_band_preset_is_refused_on_broadband(qtbot, tmp_path):
    win, p = _setup(qtbot, tmp_path, card="IRCUT", dt="dualband")
    before = list(win.project.entries())
    _choose(win, p); _box(win); win._apply_crop()
    assert win.project.entries() == before          # checked BEFORE the crop: nothing happens
    assert "dual-band" in win._warning.text()


def test_the_choice_does_not_survive_a_new_picture(qtbot, tmp_path):
    win, p = _setup(qtbot, tmp_path)
    _choose(win, p)
    second = tmp_path / "second"; second.mkdir()
    win.open_fits(_make_fits(second))
    win._go_to_id("crop", user_initiated=False)
    assert win._chosen_preset is None and win._panel.apply_btn.text() == "Apply Crop"


def test_deleting_the_chosen_preset_clears_the_choice(qtbot, tmp_path, monkeypatch):
    win, p = _setup(qtbot, tmp_path)
    _choose(win, p)
    import nocturne.ui.preset_browser as pb
    def fake_exec(self):
        self._ask_delete = lambda q: True
        self.items.setCurrentRow(0); self.delete_btn.click()
        self.reject(); return 0
    monkeypatch.setattr(pb.PresetBrowser, "exec", fake_exec)
    win._open_presets()
    assert win._chosen_preset is None and not win._panel.preset_chip.isVisibleTo(win._panel)


def test_the_choice_survives_leaving_and_returning_to_crop(qtbot, tmp_path):
    win, p = _setup(qtbot, tmp_path)
    _choose(win, p)
    win._go_to_id("background", user_initiated=False)
    win._go_to_id("crop", user_initiated=False)
    assert win._panel.preset_chip.isVisibleTo(win._panel)


def test_clear_restores_plain_apply_crop(qtbot, tmp_path):
    win, p = _setup(qtbot, tmp_path)
    _choose(win, p); _box(win)
    win._panel.preset_chip_clear.click()
    assert win._chosen_preset is None and win._panel.apply_btn.text() == "Apply Crop"


def test_a_long_name_is_elided_on_the_button_and_whole_in_the_tooltip(qtbot, tmp_path):
    long = "Heart and Soul with the Fish Head, both panels, July and August"   # MAX_NAME is 80
    win, p = _setup(qtbot, tmp_path, name=long)
    _choose(win, p); _box(win); win._sync_step_controls()
    btn = win._panel.apply_btn
    assert btn.text().startswith("Apply Crop + ") and "…" in btn.text()
    assert long in btn.toolTip()


def test_the_presets_button_is_in_the_card_and_the_header_is_untouched(qtbot, tmp_path):
    from PySide6.QtWidgets import QPushButton, QToolButton
    win, _p = _setup(qtbot, tmp_path)
    hdr = win._panel.header
    crop_h = hdr.sizeHint().height()
    assert not hdr.isAncestorOf(win._panel.presets_btn)
    assert win._panel.isAncestorOf(win._panel.presets_btn)
    assert hdr.findChildren(QPushButton) == [] and hdr.findChildren(QToolButton) == []
    win._go_to_id("background", user_initiated=False)
    assert win._panel.header.sizeHint().height() == crop_h


def test_a_rename_in_the_browser_refreshes_the_chip_and_button(qtbot, tmp_path, monkeypatch):
    win, p = _setup(qtbot, tmp_path)
    _choose(win, p)
    import nocturne.ui.preset_browser as pb
    def fake_exec(self):
        self._library.rename(p, "Orion wide")
        self.reject(); return 0
    monkeypatch.setattr(pb.PresetBrowser, "exec", fake_exec)
    win._open_presets()
    assert win._chosen_preset.id == p.id and win._chosen_preset.name == "Orion wide"
    assert win._panel.apply_btn.text() == "Apply Orion wide"


def test_rotating_with_a_preset_chosen_keeps_apply_live(qtbot, tmp_path):
    win, p = _setup(qtbot, tmp_path)
    _choose(win, p)
    win._rotate()
    btn = win._panel.apply_btn
    assert btn.isEnabled() and btn.text() == "Apply M 8"


def test_choosing_in_the_browser_holds_the_choice(qtbot, tmp_path, monkeypatch):
    win, p = _setup(qtbot, tmp_path)
    import nocturne.ui.preset_browser as pb
    def fake_exec(self):
        self.items.setCurrentRow(0); self.choose_btn.click(); return 1
    monkeypatch.setattr(pb.PresetBrowser, "exec", fake_exec)
    before = list(win.project.entries())
    win._open_presets()
    assert win._chosen_preset is not None and win._chosen_preset.id == p.id
    assert win.project.entries() == before


# --- fix round 1 ---------------------------------------------------------------

def test_apply_and_continue_on_crop_crops_only_and_keeps_the_choice(qtbot, tmp_path):
    """Next's "Apply and continue" commits the box; the preset only ever runs
    from the button that names it (ruling I1-b)."""
    win, p = _setup(qtbot, tmp_path)
    _choose(win, p); _box(win)
    win.image_view.crop_box_modified = lambda: True
    win._ask_pending = lambda label: "apply"
    win._go_to_id("background")
    assert [n for n, _ in win.project.entries()] == ["Crop"]
    assert win.current_stage_id() == "background"
    assert win._chosen_preset is not None and win._chosen_preset.id == p.id


POST_ONLY = [{"stage": "levels", "option": [0.02, 1.0, 1.0]},
             {"stage": "enhance", "option": "Vibrance"}]


def test_a_preset_that_starts_after_stretch_is_refused_on_a_linear_picture(qtbot, tmp_path):
    win, p = _setup(qtbot, tmp_path, steps=POST_ONLY)
    before = list(win.project.entries())
    _choose(win, p); _box(win); win._apply_crop()
    assert win.project.entries() == before            # not even the crop
    assert win._warning.text() == ("This preset was made on an already-stretched picture, "
                                   "so it can only be used on pictures that open already "
                                   "stretched.")
    assert win._chosen_preset is not None and win.current_stage_id() == "crop"


def test_stretch_later_in_history_does_not_count_it_is_discarded(qtbot, tmp_path, monkeypatch):
    """The preset runs on the cropped base, which is still linear: a Stretch
    after the crop would be discarded first, so it is refused before asking."""
    from PySide6.QtWidgets import QMessageBox
    from tests.ui.test_main_window import _crop
    win, p = _setup(qtbot, tmp_path, steps=POST_ONLY)
    _crop(win)
    win._go_to_id("stretch", user_initiated=False); win._panel.apply_btn.click()
    win._go_to_id("crop", user_initiated=False)
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(1) or QMessageBox.StandardButton.Yes)
    before = list(win.project.entries())
    _choose(win, p); win._apply_crop()
    assert win.project.entries() == before and asked == []
    assert "already-stretched picture" in win._warning.text()


def test_a_run_that_stays_linear_does_not_land_on_enhancements(qtbot, tmp_path):
    """A preset of linear steps only. Landing on Enhancements would commit a
    default Stretch on the way (_ensure_stretched) that nobody asked for."""
    win, p = _setup(qtbot, tmp_path, steps=[{"stage": "background", "option": "off"}])
    win._ask_auto_stretch = lambda names, label: True
    _choose(win, p); _box(win); win._apply_crop()
    assert [n for n, _ in win.project.entries()] == ["Crop", "Background"]
    assert win.project.current().is_linear
    assert win.current_stage_id() == "crop"
    assert win._warning.text() == ""         # no "Wait for the current step…" either
    assert "Applied preset M 8 \u2014 1 step." in win.output_panel.toPlainText()


def test_a_run_with_no_successful_step_is_not_a_success(qtbot, tmp_path, monkeypatch):
    from nocturne.steps.levels import LevelsStep
    monkeypatch.setattr(LevelsStep, "apply",
                        lambda self, img, o: (_ for _ in ()).throw(RuntimeError("bad")))
    steps = [{"stage": "stretch", "option": {"amount": 0.3, "linked": True}},
             {"stage": "levels", "option": [0.02, 1.0, 1.0]}]
    from nocturne.steps.stretch_step import StretchStep
    monkeypatch.setattr(StretchStep, "apply",
                        lambda self, img, o: (_ for _ in ()).throw(RuntimeError("bad")))
    win, p = _setup(qtbot, tmp_path, steps=steps)
    _choose(win, p); _box(win); win._apply_crop()
    assert [n for n, _ in win.project.entries()] == ["Crop"]
    assert win._presets.find("M 8").last_used == ""
    assert win._chosen_preset is not None and win.current_stage_id() == "crop"
    assert win._warning.text() == "Preset M 8: 0 of 2 steps \u2014 Stretch and Levels failed: bad; bad"
    assert "Applied preset" not in win.output_panel.toPlainText()


def test_a_broadband_preset_on_dual_band_data_says_so(qtbot, tmp_path):
    win, p = _setup(qtbot, tmp_path, card="LP", dt="broadband")
    _choose(win, p); _box(win); win._apply_crop()
    from nocturne.user_presets import _BROADBAND_NOTE
    assert _BROADBAND_NOTE in win.output_panel.toPlainText()
    assert "Vibrance" in [n for n, _ in win.project.entries()]


def test_a_substituted_engine_is_named(qtbot, tmp_path):
    steps = STEPS + [{"stage": "noise_sharpen",
                      "option": {"strength": "strong", "engine": "rcastro"}}]
    win, p = _setup(qtbot, tmp_path, steps=steps)
    _choose(win, p); _box(win); win._apply_crop()
    out = win.output_panel.toPlainText()
    assert ("Noise Reduction used Nocturne (built-in denoise): NoiseXTerminator "
            "is not configured in Settings.") in out, out


def test_an_auto_levels_preset_records_auto(qtbot, tmp_path):
    """A preset saying "auto" runs the CURRENT Auto and records it with its
    version (2026-10-14), so the project replays what was made."""
    from nocturne.core.levels import new_levels_option
    steps = [STEPS[0], {"stage": "levels", "option": "auto"}]
    win, p = _setup(qtbot, tmp_path, steps=steps)
    _choose(win, p); _box(win); win._apply_crop()
    assert ("Levels", new_levels_option(auto=True)) in win.project.entries()


def test_the_split_stage_lists_match_their_sources():
    from nocturne.ui import main_window as mw
    assert mw._SPLIT_STAGES == {"star_reduction", "saturation", "green_fringe",
                                "narrowband", "color_balance", "starless_levels"}
    assert mw._SPLIT_TAPS == {"Star Colour", "Sharpen Nebulosity"}


def test_a_project_saved_after_a_preset_reopens_with_the_same_picture(qtbot, tmp_path):
    import numpy as np
    from nocturne.history.project_store import load_project, save_project
    win, p = _setup(qtbot, tmp_path)
    _choose(win, p); _box(win); win._apply_crop()
    assert [n for n, _ in win.project.entries()][-1] == "Vibrance", "fixture"
    n = len(win.project.entries())
    saved = [win.project.state_at(i).data.copy() for i in range(n + 1)]
    path = str(tmp_path / "preset.nocturne")
    save_project(win.project, path, source_label="stack.fits")
    loaded = load_project(path, str(tmp_path / "cache2"))
    assert [n for n, _ in loaded.project.entries()] == [n for n, _ in win.project.entries()]
    assert np.array_equal(loaded.project.current().data, saved[-1])
    # Every position, not only the last: Stretch, Levels and Local Contrast
    # REPLAY from their recorded options, and only Vibrance is a cached snapshot.
    for i in range(n + 1):
        assert np.array_equal(loaded.project.state_at(i).data, saved[i]), i


def test_auto_enhance_log_and_warning_are_unchanged(qtbot, tmp_path, monkeypatch):
    """Golden lines captured before the recording was shared with presets."""
    from nocturne.core import sessionlog
    from nocturne.steps.local_contrast import LocalContrastStep
    from tests.ui.test_main_window import _crop
    monkeypatch.setattr(LocalContrastStep, "apply",
                        lambda self, img, o: (_ for _ in ()).throw(RuntimeError("boom\nmore")))
    win = _win(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path)); _crop(win)
    lines, log = [], []
    monkeypatch.setattr(sessionlog, "write", lambda line: lines.append(line))
    monkeypatch.setattr(win.log_panel, "append_entry", lambda b: log.append(b))
    win._auto_enhance("natural")
    tail = " \u2014 Auto Enhance (Natural)"
    expected = ["Color", "Stretch (0.30 linked)", "Levels (auto)",
                "Saturation (0.50 / neb 0.20 (built-in))", "De-green Stars (1.00 (built-in))",
                "Noise Reduction (strong (built-in))", "Star Reduction (0.30 (built-in))"]
    assert log == [e + tail for e in expected]
    assert lines[:-1] == ["step  " + e + tail for e in expected]
    assert lines[-1].startswith("ERROR Auto Enhance (Natural): Local Contrast failed\nTraceback")
    assert lines[-1].endswith("RuntimeError: boom\nmore")
    assert win._warning.text() == ("Auto Enhance (Natural): 7 of 8 steps \u2014 "
                                   "Local Contrast failed: boom")
    assert win.output_panel.toPlainText() == (
        "Auto-enhanced (Natural) \u2014 7 steps. Background and Deconvolution were left "
        "out: GraXpert and RC-Astro aren't set up. StarNet2 (free) or StarXTerminator "
        "gives cleaner stars.")


def _crop_state(win):
    b, r = win._panel.apply_btn, win._panel.reset_step_btn
    return (b.text(), b.state(), b.isEnabled(), r.isEnabled(),
            win._panel.preset_chip.isVisibleTo(win._panel))


def test_all_steps_failing_after_a_confirmed_discard_leaves_crop_consistent(
        qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from nocturne.steps.stretch_step import StretchStep
    from nocturne.steps.levels import LevelsStep
    from tests.ui.test_main_window import _crop
    steps = [{"stage": "stretch", "option": {"amount": 0.3, "linked": True}},
             {"stage": "levels", "option": [0.02, 1.0, 1.0]}]
    win, p = _setup(qtbot, tmp_path, steps=steps)
    _crop(win)
    win._go_to_id("stretch", user_initiated=False); win._panel.apply_btn.click()
    win._go_to_id("crop", user_initiated=False)
    assert [n for n, _ in win.project.entries()] == ["Crop", "Stretch"], "fixture"
    win._dirty = False                                   # as if just saved
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    for cls in (StretchStep, LevelsStep):
        monkeypatch.setattr(cls, "apply",
                            lambda self, img, o: (_ for _ in ()).throw(RuntimeError("bad")))
    _choose(win, p); win._apply_crop()
    assert [n for n, _ in win.project.entries()] == ["Crop"]
    assert win._dirty                                    # the discard is an unsaved change
    shown = _crop_state(win)
    win._rebuild_panel()                                 # what a fresh panel says
    assert _crop_state(win) == shown


def test_cancel_after_a_confirmed_discard_leaves_crop_consistent(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from nocturne.steps.levels import LevelsStep
    from tests.ui.test_main_window import _crop
    win, p = _setup(qtbot, tmp_path)
    _crop(win)
    win._go_to_id("stretch", user_initiated=False); win._panel.apply_btn.click()
    win._go_to_id("crop", user_initiated=False)
    win._dirty = False
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    real = LevelsStep.apply
    def cancel_then_apply(self, img, o):
        win._cancel_active()
        return real(self, img, o)
    monkeypatch.setattr(LevelsStep, "apply", cancel_then_apply)
    _choose(win, p); win._apply_crop()
    assert [n for n, _ in win.project.entries()] == ["Crop"] and win._dirty
    shown = _crop_state(win)
    win._rebuild_panel()
    assert _crop_state(win) == shown


def test_the_browser_is_told_whether_the_cropped_base_is_linear(qtbot, tmp_path, monkeypatch):
    from tests.ui.test_main_window import _crop
    import nocturne.ui.preset_browser as pb
    seen = []
    monkeypatch.setattr(pb.PresetBrowser, "exec",
                        lambda self: seen.append(self._base_linear) or 0)
    win, _p = _setup(qtbot, tmp_path)
    win._open_presets()
    _crop(win)
    win._go_to_id("stretch", user_initiated=False); win._panel.apply_btn.click()
    win._go_to_id("crop", user_initiated=False)
    win._open_presets()                    # stretched now, but the base it runs on is not
    assert seen == [True, True]


def test_a_post_stretch_preset_applies_on_a_picture_that_opens_stretched(qtbot, tmp_path):
    from tests.ui.test_open_tiff import _write_stretched_tiff
    win = _win(qtbot, tmp_path)
    win.open_any(_write_stretched_tiff(tmp_path))
    win._go_to_id("crop", user_initiated=False)
    p = win._presets.save("Finished", POST_ONLY, _jpeg(), data_type="unknown")
    _choose(win, p); _box(win, (2, 10, 2, 10)); win._apply_crop()
    assert [n for n, _ in win.project.entries()] == ["Crop", "Levels", "Vibrance"]


def _starfield(tmp_path, name, seed):
    """A noise floor well above zero (so Auto Levels derives a non-default black
    point, different per picture) plus a few bright stars, so the split and the
    spikes have something real to work on. Big enough that the spikes draw
    arms, not only blooms."""
    import numpy as np
    from astropy.io import fits
    rng = np.random.default_rng(seed)
    arr = rng.normal(18000, 1200, (3, 160, 160))
    yy, xx = np.mgrid[:160, :160]
    for _ in range(6):
        cy, cx = rng.uniform(30, 130, 2)
        arr += rng.uniform(20000, 40000) * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / 4.0)
    hdu = fits.PrimaryHDU(np.clip(arr, 0, 65535).astype(np.uint16))
    hdu.header["FILTER"] = "LP"
    p = tmp_path / name
    hdu.writeto(str(p))
    return str(p)


# Full length on a 128 px crop: shorter arms stay inside the saturated cores
# (or under a pixel and are skipped), leaving only blooms that ignore the angle.
SPIKES = {"length": 1.0, "count": 6, "angle": 30.0, "intensity": 0.8,
          "variation": 0.1, "colour": 0.5}
_BOX = (16, 144, 16, 144)


def _by_hand_after_crop(win):
    """Stretch, Levels Auto, Vibrance, Starless Levels and Star Spikes the way
    their own tools do it, on whatever picture is cropped in `win`."""
    from nocturne.core.enhance import starless_levels_layers
    from nocturne.core.star_spikes import add_spikes, detect_stars
    win._go_to_id("stretch", user_initiated=False); win._panel.apply_btn.click()
    win._go_to_id("levels", user_initiated=False)
    win._on_levels_auto(); win._panel.apply_btn.click()
    win._enhance("Vibrance")
    base = win.project.current()
    sl, st, _tag = win._split_tagged(base)
    win._apply_starless_levels(starless_levels_layers(sl, st, 0.05, 0.9), (0.05, 0.9))
    base = win.project.current()
    s = SPIKES
    win._apply_star_spikes(add_spikes(base, detect_stars(base.data), s["length"], s["count"],
                                      s["angle"], s["intensity"], s["variation"],
                                      s["colour"]), dict(SPIKES))


def test_save_on_one_picture_apply_on_another_round_trip(qtbot, tmp_path, monkeypatch):
    """The spec's core promise in one test: what was done to picture A, saved
    from Enhancements, is done to picture B through the real Crop button — as
    the same named steps with the same options, and to the same pixels as
    doing those steps on B by hand."""
    import numpy as np
    from nocturne.recipe import deserialize_option, recipe_from_entries
    from tests.ui.test_save_preset import _answer
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir(); (tmp_path / "hand").mkdir()
    pic_a = _starfield(tmp_path / "a", "a.fits", 1)
    pic_b = _starfield(tmp_path / "b", "b.fits", 2)

    # Picture A, by hand.
    win = _win(qtbot, tmp_path)
    win.open_fits(pic_a)
    win._go_to_id("crop", user_initiated=False); _box(win, _BOX); win._apply_crop()
    _by_hand_after_crop(win)
    a_entries = win.project.entries()
    assert [n for n, _ in a_entries] == ["Crop", "Stretch", "Levels", "Vibrance",
                                         "Starless Levels", "Star Spikes"], "fixture"
    assert dict(a_entries)["Levels"] == "auto", "fixture: Auto must be what was pressed"

    win._go_to_id("export", user_initiated=False)
    assert win._panel.save_preset_btn.isEnabled()
    _answer(monkeypatch, name="Round trip")
    win._panel.save_preset_btn.click()
    [p] = win._presets.list()

    # Picture B, through the Crop step's own button.
    win._dirty = False
    win.open_fits(pic_b)
    win._go_to_id("crop", user_initiated=False)
    _choose(win, p); _box(win, _BOX)
    assert win._panel.apply_btn.text() == "Apply Crop + Round trip"
    win._panel.apply_btn.click()

    b_entries = win.project.entries()
    assert [n for n, _ in b_entries] == [n for n, _ in a_entries]
    assert win.current_stage_id() == "enhancements"
    a_steps = recipe_from_entries(a_entries[1:], scope="preset").steps
    b_steps = recipe_from_entries(b_entries[1:], scope="preset").steps
    assert [s["stage"] for s in b_steps] == [s["stage"] for s in a_steps]
    for sa, sb in zip(a_steps, b_steps):
        assert deserialize_option(sb["stage"], sb["option"]) == \
            deserialize_option(sa["stage"], sa["option"]), sa["stage"]
    # The preset re-derives Auto in the current version and records it so.
    from nocturne.core.levels import new_levels_option
    assert dict(b_entries)["Levels"] == new_levels_option(auto=True)

    # The same steps on B by hand, in a window of its own.
    hand = _win(qtbot, tmp_path / "hand")
    hand.open_fits(pic_b)
    hand._go_to_id("crop", user_initiated=False); _box(hand, _BOX); hand._apply_crop()
    _by_hand_after_crop(hand)
    assert [n for n, _ in hand.project.entries()] == [n for n, _ in b_entries]
    # current(), not state_at(i): earlier positions REPLAY from the recorded
    # options through the same steps the preset ran, so they would agree with
    # each other even if the preset's replay drew something the tool never did.
    assert np.allclose(win.project.current().data, hand.project.current().data, atol=1e-6)
    assert not np.allclose(win.project.current().data,
                           hand.project.state_at(len(b_entries) - 1).data, atol=1e-3), \
        "fixture: the last step (Star Spikes) must change the picture"


FITS_STEPS = [{"stage": "background", "option": "off"},
              {"stage": "stretch", "option": {"amount": 0.3, "linked": True}},
              {"stage": "levels", "option": [0.02, 1.0, 1.0]}]


def test_a_preset_with_a_stretch_is_refused_on_a_picture_that_opens_stretched(qtbot, tmp_path):
    from tests.ui.test_open_tiff import _write_stretched_tiff
    win = _win(qtbot, tmp_path)
    win.open_any(_write_stretched_tiff(tmp_path))
    win._go_to_id("crop", user_initiated=False)
    p = win._presets.save("FITS", FITS_STEPS, _jpeg(), data_type="unknown")
    before = list(win.project.entries())
    _choose(win, p); _box(win, (2, 10, 2, 10)); win._apply_crop()
    assert win.project.entries() == before
    assert win._warning.text() == ("This preset was made on an unstretched picture, so it "
                                   "can only be used on pictures that aren't stretched yet.")


def test_the_browser_hears_a_stretched_base(qtbot, tmp_path, monkeypatch):
    from tests.ui.test_open_tiff import _write_stretched_tiff
    import nocturne.ui.preset_browser as pb
    seen = []
    monkeypatch.setattr(pb.PresetBrowser, "exec", lambda self: seen.append(self._base_linear) or 0)
    win = _win(qtbot, tmp_path)
    win.open_any(_write_stretched_tiff(tmp_path))
    win._go_to_id("crop", user_initiated=False)
    win._open_presets()
    assert seen == [False]


def test_a_held_preset_replaced_by_save_as_preset_applies_the_new_steps(qtbot, tmp_path, monkeypatch):
    from tests.ui.test_save_preset import _answer
    from PySide6.QtWidgets import QMessageBox
    win, p = _setup(qtbot, tmp_path)           # "M 8" = STEPS
    _choose(win, p); _box(win)
    win.image_view.crop_box_modified = lambda: True
    win._ask_pending = lambda label: "apply"
    win._go_to_id("stretch")                   # Next: the crop only, the choice held
    assert [n for n, _ in win.project.entries()] == ["Crop"] and win._chosen_preset.id == p.id
    win._panel.apply_btn.click()               # Stretch by hand
    win._go_to_id("enhancements", user_initiated=False)
    win._enhance("Vibrance")
    _answer(monkeypatch, name="M 8", replace=True)
    win._save_preset()                         # replaces "M 8": a new id, new steps
    new = win._presets.find("M 8")
    assert new.id != p.id and [s["stage"] for s in new.steps] == ["stretch", "enhance"]
    win._go_to_id("crop", user_initiated=False)
    assert win._chosen_preset.id == new.id     # re-resolved, chip and label with it
    assert win._panel.apply_btn.text() == "Apply M 8"
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    win._apply_crop()
    assert [n for n, _ in win.project.entries()] == ["Crop", "Stretch", "Vibrance"]


def test_a_held_preset_deleted_elsewhere_is_cleared(qtbot, tmp_path):
    win, p = _setup(qtbot, tmp_path)
    _choose(win, p)
    win._presets.delete(p)
    win._go_to_id("background", user_initiated=False)
    win._go_to_id("crop", user_initiated=False)
    assert win._chosen_preset is None and win._panel.apply_btn.text() == "Apply Crop"
