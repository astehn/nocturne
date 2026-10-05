"""Old projects that mention Linear Denoise keep working after it is gone.

Linear Denoise (stage `ai_denoise`) ran a model on the linear stack, straight
after Crop. It never shipped, and on 2026-10-05 Andreas retired the whole
pre-stretch track: "a track we have abandoned completely". The step goes; a
`.nocturne` bundle that already carries one does not stop opening.

Every fixture here is written by the REAL save path and then has its manifest
put back into the shape the build that recorded the step wrote ("ai_denoise"
as the stage, "AI Denoise" as the name before the 2026-09-20 rename), so the
tests describe an old bundle whichever build runs them.
"""
import json
import zipfile

import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.ui.main_window import MainWindow  # noqa: E402

LD_OPTION = {"engine": "nr:v10", "level": "medium"}


@pytest.fixture(autouse=True)
def _no_blocking_questions(monkeypatch):
    """tests/ui/conftest.py does this for the ui folder; this file is not in it.
    closeEvent asks about unsaved edits, which would block forever headless."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard))


def _make_fits(tmp_path):
    rng = np.random.default_rng(7)
    arr = (rng.random((3, 24, 24)) * 1000).astype(np.uint16)
    p = tmp_path / "stack.fits"
    fits.PrimaryHDU(arr).writeto(str(p))
    return str(p)


def _window(qtbot, tmp_path):
    win = MainWindow(settings_path=str(tmp_path / "settings.json"),
                     check_updates=False, telemetry=False)
    win._async_enabled = False
    win._ask_geometry = lambda names, label: True
    win._ask_truncation = lambda *a, **k: True
    win._ask_pending = lambda *a, **k: "discard"   # a real one blocks headless
    qtbot.addWidget(win)
    return win


def _wait_idle(qtbot, win):
    qtbot.waitUntil(lambda: not win._busy, timeout=10000)


def _write_old_bundle(win, path, legacy_name):
    """Save through the real path, then make the manifest say what an old build
    wrote for the step: its stage id and, optionally, its pre-rename name."""
    win._do_save_project(path)
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        members = {n: zf.read(n) for n in zf.namelist()}
    for step in manifest["steps"]:
        if step["name"] == "Linear Denoise":
            assert step["cached"], "a model step can only come back from its pixels"
            step["stage"] = "ai_denoise"
            step["name"] = legacy_name
    members["manifest.json"] = json.dumps(manifest, default=str).encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def _build_history(win):
    """Crop -> Linear Denoise -> Deconvolution -> Stretch -> Levels.

    The Linear Denoise entry sits in the MIDDLE, between real steps, where the
    stage put it (after Crop's geometry, before everything else). Its pixels
    are deliberately distinct from its input, so a restore from the wrong
    snapshot cannot pass for a right one.
    """
    from nocturne.core.crop import CropParams
    win._apply_geometry("Crop", CropParams(bounds=(2, 22, 1, 23)))   # what Crop's Apply runs
    cur = win.project.current()
    denoised = np.clip(cur.data * 0.8 + 0.01, 0.0, 1.0).astype(np.float32)
    win.project.record_precomputed(
        "Linear Denoise", dict(LD_OPTION),
        AstroImage(denoised, is_linear=True, metadata=dict(cur.metadata)))
    win._go_to_id("deconvolution")
    win.apply_current("medium")
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("levels")
    win.apply_current((0.02, 1.1, 0.98))
    names = [n for n, _ in win.project.entries()]
    assert names == ["Crop", "Linear Denoise", "Deconvolution", "Stretch", "Levels"], names


def _snapshot(project):
    """Every history position's pixels, linearity, and the entries."""
    n = len(project.entries())
    return ([project.state_at(i).data.copy() for i in range(n + 1)],
            [project.state_at(i).is_linear for i in range(n + 1)],
            [(name, opt) for name, opt in project.entries()],
            project.position)


def _legacy_window(qtbot, tmp_path, legacy_name="Linear Denoise", position=None):
    """A window holding a REOPENED old bundle, plus what was saved."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _build_history(win)
    if position is not None:          # saved part-way back, as Undo leaves it
        while win.project.position > position:
            win.project.undo()
    saved = _snapshot(win.project)
    out = str(tmp_path / "old.nocturne")
    _write_old_bundle(win, out, legacy_name)
    _wait_idle(qtbot, win)
    win.project = None
    win._open_project(out)
    _wait_idle(qtbot, win)
    assert win.project is not None, "the old bundle did not open"
    return win, saved


def _assert_unchanged(project, saved):
    datas, linear, entries, position = saved
    assert project.position == position
    got = [(n, o) for n, o in project.entries()]
    want = list(entries)
    assert got == want
    assert got[1] == ("Linear Denoise", LD_OPTION)
    for i in range(position + 1):
        np.testing.assert_array_equal(project.state_at(i).data, datas[i],
                                      err_msg=f"history position {i} changed")
        assert project.state_at(i).is_linear == linear[i], f"position {i}"


# --- Review focus 1 and 2: the bundle opens, every position unchanged ---------

@pytest.mark.parametrize("legacy_name", ["Linear Denoise", "AI Denoise"])
def test_an_old_bundle_with_the_step_in_the_middle_reopens_unchanged(
        qtbot, tmp_path, legacy_name):
    win, saved = _legacy_window(qtbot, tmp_path, legacy_name)
    # "AI Denoise" comes back under the readable name (project_store._RENAMED_STEPS).
    _assert_unchanged(win.project, saved)


def test_an_old_bundle_saved_AT_the_step_reopens_unchanged(qtbot, tmp_path):
    """Saved with Linear Denoise as the current step: the window lands on the
    restored step by its name, which then names no stage at all."""
    win, saved = _legacy_window(qtbot, tmp_path, position=2)
    assert [n for n, _ in win.project.entries()] == ["Crop", "Linear Denoise"]
    _assert_unchanged(win.project, saved)
    # And work carries on from there: the next step lands after it.
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert [n for n, _ in win.project.entries()] == ["Crop", "Linear Denoise", "Stretch"]
    np.testing.assert_array_equal(win.project.state_at(2).data, saved[0][2])


@pytest.mark.parametrize("legacy_name", ["Linear Denoise", "AI Denoise"])
def test_navigation_over_a_legacy_entry_changes_nothing(qtbot, tmp_path, legacy_name):
    win, saved = _legacy_window(qtbot, tmp_path, legacy_name)
    before = _snapshot(win.project)
    # Back/Next across the whole stepper, then a jump to every stage.
    win._go_to_id("load")
    for _ in range(len(win._stages) + 2):
        win.go_next()
    for _ in range(len(win._stages) + 2):
        win.go_back()
    for stage in list(win._stages):
        if stage.enabled:
            win._go_to_id(stage.id)
    # Jumping "to the step" from the history: the name owns no stage, so stay put.
    win._go_to_id("stretch")
    win._navigate_to_step("Linear Denoise")
    assert win.current_stage_id() == "stretch"
    after = _snapshot(win.project)
    assert after[2] == before[2] and after[3] == before[3]
    for a, b in zip(after[0], before[0]):
        np.testing.assert_array_equal(a, b)
    # Undo back onto the legacy entry and past it, then redo to the end.
    for _ in range(4):
        win._undo()
    assert win.project.position == 1
    for _ in range(4):
        win._redo()
    _assert_unchanged(win.project, saved)


@pytest.mark.parametrize("stage_id,option,kept", [
    # Re-applying a step AFTER the legacy entry keeps it and everything before.
    ("stretch", 0.3, ["Crop", "Linear Denoise", "Deconvolution", "Stretch"]),
    ("deconvolution", "light", ["Crop", "Linear Denoise", "Deconvolution"]),
])
def test_applying_a_later_step_keeps_the_legacy_entry(qtbot, tmp_path, stage_id, option, kept):
    win, saved = _legacy_window(qtbot, tmp_path)
    win._go_to_id(stage_id)
    win.apply_current(option)
    assert [n for n, _ in win.project.entries()] == kept
    # The prefix it kept is the SAVED prefix, pixel for pixel — the legacy
    # entry was not dropped and re-derived, nor moved.
    for i in range(len(kept)):
        np.testing.assert_array_equal(win.project.state_at(i).data, saved[0][i],
                                      err_msg=f"position {i} changed")
    assert win.project.entries()[1] == ("Linear Denoise", LD_OPTION)


def test_the_bundle_saves_again_and_reopens_unchanged(qtbot, tmp_path):
    """Opening is half of it: a user who opens an old project saves it again,
    with THIS build, and must be able to open that too."""
    win, saved = _legacy_window(qtbot, tmp_path)
    again = str(tmp_path / "again.nocturne")
    win._do_save_project(again)
    _wait_idle(qtbot, win)
    win.project = None
    win._open_project(again)
    _wait_idle(qtbot, win)
    _assert_unchanged(win.project, saved)


# --- Review focus 4: provenance report and activity log ----------------------

def test_the_provenance_report_and_log_name_the_legacy_step(qtbot, tmp_path):
    import datetime

    from nocturne import __version__
    from nocturne.core.provenance import build_report
    win, _saved = _legacy_window(qtbot, tmp_path, "AI Denoise")
    report = build_report(win.project.entries(), win.project.current().metadata,
                          app_version=__version__, date=datetime.date.today(),
                          settings=win.settings, saved_version="0.45.0")
    assert "Linear Denoise" in report
    assert "Levels" in report
    # The session log over the reopened project: Undo/Redo across the entry.
    win._undo()
    win._redo()
    assert "Redo" in win.log_panel.toPlainText()


# --- Review focus 3 (project half): Save Recipe leaves it out, and says so ---

def test_save_recipe_on_a_legacy_project_leaves_the_step_out_and_says_so(
        qtbot, tmp_path, monkeypatch):
    """There is nothing left to replay it with, so it is uncapturable — and
    Save Recipe's existing warning is what names an uncapturable step."""
    from PySide6.QtWidgets import QMessageBox

    from nocturne.ui import file_dialogs
    win, _saved = _legacy_window(qtbot, tmp_path)
    out = str(tmp_path / "r.json")
    warned = []
    monkeypatch.setattr(file_dialogs, "save_file", staticmethod(lambda *a, **k: (out, "")))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(
        lambda _p, _t, text, *a, **k: warned.append(text) or QMessageBox.StandardButton.Save))
    win._save_recipe()
    assert len(warned) == 1 and "Linear Denoise" in warned[0], warned
    with open(out) as fh:
        stages = [s["stage"] for s in json.load(fh)["steps"]]
    assert stages == ["crop", "deconvolution", "stretch", "levels"]


@pytest.mark.parametrize("name", ["Linear Denoise", "AI Denoise"])
def test_the_step_is_uncapturable_under_either_name(name):
    from nocturne.recipe import recipe_from_entries, uncaptured_step_names
    entries = [("Stretch", 0.5), (name, dict(LD_OPTION)), ("Levels", (0.0, 1.0, 1.0))]
    assert uncaptured_step_names(entries) == [name]
    assert [s["stage"] for s in recipe_from_entries(entries).steps] == ["stretch", "levels"]


# --- Review focus 3 (recipe half): an old recipe loads and runs the rest -----

_STRETCH = {"stage": "stretch", "option": {"amount": 0.5, "linked": True}}
_LD = {"stage": "ai_denoise", "option": dict(LD_OPTION)}
_LEVELS = {"stage": "levels", "option": [0.02, 1.1, 0.98]}
SKIPPED = "Linear Denoise is no longer part of Nocturne — skipped"


def _recipe_file(tmp_path, steps, name="r.json"):
    """A recipe this build accepts (load_recipe refuses another build's while
    in beta), carrying the step as the old build serialised it."""
    from nocturne import __version__
    p = tmp_path / name
    p.write_text(json.dumps({"version": 1, "app": __version__, "steps": steps}))
    return str(p)


def _base():
    rng = np.random.default_rng(3)
    return AstroImage((rng.random((16, 16, 3)) * 0.05 + 0.01).astype(np.float32),
                      is_linear=True)


def test_an_old_recipe_runs_every_other_step(tmp_path):
    from nocturne.batch import apply_recipe
    from nocturne.recipe import load_recipe
    from nocturne.settings import Settings
    with_it = load_recipe(_recipe_file(tmp_path, [_STRETCH, _LD, _LEVELS]))
    without = load_recipe(_recipe_file(tmp_path, [_STRETCH, _LEVELS], "w.json"))
    got = apply_recipe(_base(), with_it, Settings())
    want = apply_recipe(_base(), without, Settings())
    np.testing.assert_array_equal(got.data, want.data)


def test_the_batch_dialog_says_once_that_the_step_is_skipped(qtbot, tmp_path):
    """Before Run, in the status line that already says what a recipe will and
    will not do — once, however many times the recipe names the step."""
    from nocturne.settings import Settings
    from nocturne.ui.batch_dialog import BatchDialog
    dlg = BatchDialog(Settings())
    qtbot.addWidget(dlg)
    dlg.recipe_edit.setText(_recipe_file(tmp_path, [_LD, _STRETCH, dict(_LD), _LEVELS]))
    text = dlg.status.text()
    assert text.count(SKIPPED) == 1, text
    assert dlg.run_btn.isEnabled(), "a skipped step must not block the batch"
    # The rest is still described, and honestly: two steps, both run.
    assert "2 steps will run as saved" in text, text


def test_a_batch_run_with_the_old_recipe_succeeds(tmp_path):
    from nocturne.batch import run_batch
    from nocturne.recipe import load_recipe
    from nocturne.settings import Settings
    src = tmp_path / "in"
    src.mkdir()
    fits_path = _make_fits(src)
    out = tmp_path / "out"
    out.mkdir()
    recipe = load_recipe(_recipe_file(tmp_path, [_STRETCH, _LD, _LEVELS]))
    results = run_batch(recipe, [fits_path], str(out), "TIFF", Settings())
    assert results == [{"path": fits_path, "ok": True, "message": ""}], results


# --- Review focus 5: a model left in ~/.nocturne/models changes nothing ------

def test_a_model_in_the_old_models_folder_changes_nothing(qtbot, tmp_path, monkeypatch):
    import importlib.util

    home = tmp_path / "home"
    models = home / ".nocturne" / "models"
    models.mkdir(parents=True)
    (models / "v10.onnx").write_bytes(b"not a real model")
    (models / "v10.json").write_text("{}")
    monkeypatch.setenv("HOME", str(home))
    # Where the folder is still read, it was resolved at import: aim it here as
    # well, so this describes the app and not a test-suite override.
    if importlib.util.find_spec("nocturne.core.denoise_model") is not None:
        import nocturne.core.denoise_model as dm
        monkeypatch.setattr(dm, "EXTERNAL_DIR", str(models))

    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert "ai_denoise" not in [s.id for s in win._stages]
    assert "Linear Denoise" not in [s.label for s in win._stages]
    win._go_to_id("noise_sharpen")
    box = getattr(win._panel, "engine_box", None)
    items = [box.itemText(i) for i in range(box.count())] if box is not None else []
    assert not any("Nocturne NR" in t for t in items), items
    assert importlib.util.find_spec("nocturne.core.denoise_model") is None
    assert importlib.util.find_spec("nocturne.steps.ai_denoise") is None
