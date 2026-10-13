import pytest
pytest.importorskip("PySide6")
from tests.ui.test_main_window import _make_fits, _window
from nocturne import user_presets as up

STEPS = [{"stage": "stretch", "option": {"amount": 0.3, "linked": True}},
         {"stage": "levels", "option": [0.02, 1.0, 1.0]},
         {"stage": "local_contrast", "option": 0.15},
         {"stage": "enhance", "option": "Vibrance"}]


def _jpeg():
    import io
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (30, 20)).save(b, "JPEG"); return b.getvalue()


_WINDOWS = []


@pytest.fixture(autouse=True)
def _clean_teardown():
    """A preset run leaves the window dirty; closing it must not ask."""
    yield
    while _WINDOWS:
        _WINDOWS.pop()._dirty = False


def _setup(qtbot, tmp_path, card="L", steps=STEPS, name="M 8", dt="broadband"):
    win = _window(qtbot, tmp_path)
    _WINDOWS.append(win)
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


def test_the_presets_button_is_in_the_header_and_the_header_did_not_grow(qtbot, tmp_path):
    win, _p = _setup(qtbot, tmp_path)
    crop_h = win._panel.header.sizeHint().height()
    assert win._panel.header.isAncestorOf(win._panel.presets_btn)
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
    assert win._warning.text() == ("This preset starts after Stretch \u2014 stretch the "
                                   "picture first, then apply it.")
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
    assert "starts after Stretch" in win._warning.text()


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
    steps = [STEPS[0], {"stage": "levels", "option": "auto"}]
    win, p = _setup(qtbot, tmp_path, steps=steps)
    _choose(win, p); _box(win); win._apply_crop()
    assert ("Levels", "auto") in win.project.entries()


def test_the_split_stage_lists_match_their_sources():
    from nocturne.core import receipt
    from nocturne.steps import enhance_step
    from nocturne.ui import main_window as mw
    free = {s for s, e in receipt._FALLBACKS.items() if e == receipt._FREE_SPLIT}
    assert free <= mw._SPLIT_STAGES
    assert mw._SPLIT_TAPS == frozenset(enhance_step._LAYERED)


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
    win = _window(qtbot, tmp_path); _WINDOWS.append(win)
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
