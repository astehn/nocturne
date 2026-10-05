"""Nocturne NR models in Noise Reduction's engine dropdown (spec N3–N5).

Models are the 233-byte fixture (tests/core/test_nr_models.py) copied into a tmp
tray; the real ~/.nocturne/models is sandboxed away by tests/conftest.py.
"""
import json
import pathlib
import shutil

import numpy as np
import pytest

from nocturne.core import nr_models
from tests.ui.test_main_window import _make_fits, _window

pytest.importorskip("onnxruntime")

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "nr" / "tile_noise.onnx"
STRETCHED = {"space": "stretched", "inputs": 3, "tile": 256}


def _deliver(tray, stem, **meta):
    shutil.copy(FIXTURE, tray / f"{stem}.onnx")
    (tray / f"{stem}.json").write_text(json.dumps({**STRETCHED, **meta}))


@pytest.fixture
def tray(tmp_path, monkeypatch):
    d = tmp_path / "tray"
    d.mkdir()
    monkeypatch.setattr(nr_models, "TRAY_DIR", str(d))
    return d


def _tools(monkeypatch, rc: bool, gx: bool):
    import nocturne.ui.main_window as mw
    monkeypatch.setattr(mw, "rcastro_valid", lambda s: rc)
    monkeypatch.setattr(mw, "graxpert_valid", lambda s: gx)


def _at_noise_reduction(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._ask_pending = lambda *a, **k: "discard"
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    win._go_to_id("noise_sharpen")
    return win


def _items(win):
    box = getattr(win._panel, "engine_box", None)
    return None if box is None else [box.itemText(i) for i in range(box.count())]


def test_the_dropdown_exists_with_only_a_model(qtbot, tmp_path, monkeypatch, tray):
    _tools(monkeypatch, rc=False, gx=False)
    _deliver(tray, "v20.0", id="v20.0", name="Odin")
    win = _at_noise_reduction(qtbot, tmp_path)
    assert _items(win) == ["Default", "Nocturne NR — Odin"]


def test_the_dropdown_exists_with_one_tool_and_a_model(qtbot, tmp_path, monkeypatch, tray):
    _tools(monkeypatch, rc=False, gx=True)
    _deliver(tray, "v20.0", id="v20.0", name="Odin")
    win = _at_noise_reduction(qtbot, tmp_path)
    assert _items(win) == ["Default", "Nocturne NR — Odin"]


def test_models_come_after_the_tools_in_a_stable_order(qtbot, tmp_path, monkeypatch, tray):
    _tools(monkeypatch, rc=True, gx=True)
    _deliver(tray, "v20.0", id="v20.0", name="Odin")
    _deliver(tray, "v19p")
    (tray / "v15c.onnx").write_bytes(b"linear, no JSON")
    win = _at_noise_reduction(qtbot, tmp_path)
    assert _items(win) == ["Default", "NoiseXTerminator", "GraXpert",
                           "Nocturne NR — v19p", "Nocturne NR — Odin"]


def test_no_model_and_no_choice_means_no_dropdown(qtbot, tmp_path, monkeypatch, tray):
    """The release case: nothing installed, nothing changes."""
    _tools(monkeypatch, rc=True, gx=False)
    win = _at_noise_reduction(qtbot, tmp_path)
    assert _items(win) is None


def test_two_models_sharing_a_name_stay_distinguishable(qtbot, tmp_path, monkeypatch, tray):
    _tools(monkeypatch, rc=False, gx=False)
    _deliver(tray, "v20.0", id="v20.0", name="Odin")
    _deliver(tray, "v20.1", id="v20.1", name="Odin")
    win = _at_noise_reduction(qtbot, tmp_path)
    assert _items(win) == ["Default", "Nocturne NR — Odin (v20.0)", "Nocturne NR — Odin (v20.1)"]
    win._panel.engine_box.setCurrentText("Nocturne NR — Odin (v20.1)")
    assert win._panel.commit_option()["engine"] == "nr:v20.1"


def test_apply_stores_the_id_and_the_log_names_the_model(qtbot, tmp_path, monkeypatch, tray):
    _tools(monkeypatch, rc=False, gx=False)
    _deliver(tray, "v20.0", id="v20.0", name="Odin")
    win = _at_noise_reduction(qtbot, tmp_path)
    win._panel.engine_box.setCurrentText("Nocturne NR — Odin")
    opt = win._panel.commit_option()
    assert opt == {"engine": "nr:v20.0", "level": "medium"}
    before = win.project.current().data.copy()
    win.apply_current(opt)
    assert win.project.entries()[-1] == ("Noise Reduction", {"engine": "nr:v20.0", "level": "medium"})
    assert "Noise Reduction (medium (Nocturne NR — Odin (v20.0)))" in win.log_panel.text()
    assert not np.array_equal(win.project.current().data, before)
    # Revisited, the step shows what it ran with.
    win._go_to_id("stretch")
    win._go_to_id("noise_sharpen")
    assert win._panel.engine_box.currentText() == "Nocturne NR — Odin"


def test_review_focus_4_a_project_outlives_its_model(qtbot, tmp_path, monkeypatch, tray):
    import datetime

    from nocturne.batch import apply_recipe
    from nocturne.core.provenance import build_report
    from nocturne.recipe import recipe_from_entries
    from nocturne.ui import file_dialogs
    _tools(monkeypatch, rc=False, gx=False)
    _deliver(tray, "v20.0", id="v20.0", name="Odin")
    win = _at_noise_reduction(qtbot, tmp_path)
    win.apply_current({"engine": "nr:v20.0", "level": "strong"})
    denoised = win.project.current().data.copy()
    entries = win.project.entries()
    out = str(tmp_path / "proj.nocturne")
    monkeypatch.setattr(file_dialogs, "save_file", staticmethod(lambda *a, **k: (out, "")))
    win._save_project_as()

    (tray / "v20.0.onnx").unlink()
    win.project = None
    win._open_project(out)

    # It opens, from the cached pixels, with the id still in its history.
    np.testing.assert_array_equal(win.project.current().data, denoised)
    assert win.project.entries() == entries
    report = build_report(win.project.entries(), {}, app_version="x",
                          date=datetime.date(2026, 10, 6), settings=win.settings)
    assert "Noise Reduction — Nocturne NR — v20.0" in report
    # The model is no longer offered, and the step does not pretend it is.
    win._go_to_id("noise_sharpen")
    assert _items(win) is None or "Nocturne NR — Odin" not in _items(win)

    # Re-applying with it fails by name, and records nothing from any other
    # engine. (Apply discards the step it replaces BEFORE running — the app's
    # rule for every step — so what is left is the history up to Stretch.)
    win.apply_current({"engine": "nr:v20.0", "level": "strong"})
    assert "Nocturne NR v20.0 is not installed" in win._warning.text()
    assert win.project.entries() == entries[:-1]
    assert "NoiseXTerminator" not in win.log_panel.text()
    assert "built-in" not in win.log_panel.text()
    with pytest.raises(FileNotFoundError, match="Nocturne NR v20.0 is not installed"):
        apply_recipe(win.project.current(), recipe_from_entries(entries), win.settings)


def test_the_busy_label_does_not_promise_graxpert_for_a_model(qtbot, tmp_path, monkeypatch, tray):
    _tools(monkeypatch, rc=False, gx=True)
    win = _window(qtbot, tmp_path)
    assert win._busy_label_for("noise_sharpen", {"engine": "nr:v20.0", "level": "medium"}) \
        == "Applying Noise Reduction…"


def test_render_engine_names_the_model(tray):
    from nocturne.ui.main_window import render_engine
    _deliver(tray, "v20.0", id="v20.0", name="Odin")
    assert render_engine("NR:v20.0") == "Nocturne NR — Odin (v20.0)"
    assert render_engine("NR:v99") == "Nocturne NR — v99"
    assert render_engine("NoiseX") == "NoiseXTerminator", "others unchanged"
