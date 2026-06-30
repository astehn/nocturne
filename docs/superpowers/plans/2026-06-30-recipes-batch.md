# Recipes + Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline — chosen). Steps use checkbox (`- [ ]`).

**Goal:** Save the current session's steps as a reusable recipe and apply it to a folder of stacked FITS unattended.

**Architecture:** `core/recipe.py` (model + JSON + record-from-session); `steps/factory.py` (shared step construction, used by the live app and batch); `batch.py` (headless `apply_recipe` + `run_batch`); UI Save-Recipe action + Batch dialog.

**Tech Stack:** Python 3.13 (.venv), PySide6, numpy, astropy, pytest+pytest-qt.

## Global Constraints
- Spec: `docs/superpowers/specs/2026-06-30-recipes-batch-design.md`.
- Recipe = processing steps only (JSON `{"version":1,"steps":[{"stage","option"}]}`). Crop stores aspect/rotate/flip (no pixel bounds); batch auto-detects the border per image.
- Export format chosen at batch time (TIFF/PNG/FITS), not stored in the recipe.
- Reuse step classes; GraXpert/RC-Astro come from `settings` (+ `resolve_binary`). RC-Astro flip correction already in the adapter.
- Run tests `.venv/bin/pytest`; Python `.venv/bin/python` (3.13); pytest-qt headless.

---

### Task 1: Recipe model + (de)serialization + save/load + record
**Files:** Create `seestar_processor/core/recipe.py`; Test `tests/core/test_recipe.py`.
**Interfaces:** `Recipe(steps: list[dict])`; `serialize_option(stage_id, option)`; `deserialize_option(stage_id, value)`; `recipe_from_entries(entries) -> Recipe`; `save_recipe(recipe, path)`; `load_recipe(path) -> Recipe`.

- [ ] **Step 1: Write the failing tests**
```python
import numpy as np
from seestar_processor.core.crop import CropParams
from seestar_processor.core.color import ColorSettings
from seestar_processor.core.recipe import (
    Recipe, serialize_option, deserialize_option, recipe_from_entries,
    save_recipe, load_recipe,
)

def test_option_roundtrips():
    assert deserialize_option("stretch", serialize_option("stretch", 0.6)) == 0.6
    assert deserialize_option("noise_sharpen", serialize_option("noise_sharpen", "medium")) == "medium"
    lv = deserialize_option("levels", serialize_option("levels", (0.1, 1.2, 0.9)))
    assert tuple(lv) == (0.1, 1.2, 0.9)
    cs = deserialize_option("color", serialize_option("color", ColorSettings(remove_green=True)))
    assert isinstance(cs, ColorSettings) and cs.remove_green is True

def test_crop_serialize_drops_bounds():
    val = serialize_option("crop", CropParams(bounds=(1, 2, 3, 4), aspect="1:1", rotate=90))
    assert "bounds" not in val
    cp = deserialize_option("crop", val)
    assert cp.bounds is None and cp.aspect == "1:1" and cp.rotate == 90

def test_recipe_from_entries_maps_and_skips():
    entries = [("Crop", CropParams(bounds=(0, 5, 0, 5))), ("Stretch", 0.5),
               ("Unknown Step", "x")]
    r = recipe_from_entries(entries)
    stages = [s["stage"] for s in r.steps]
    assert stages == ["crop", "stretch"]  # Unknown skipped

def test_save_load_roundtrip(tmp_path):
    r = Recipe(steps=[{"stage": "stretch", "option": 0.5}])
    p = tmp_path / "r.json"
    save_recipe(r, str(p))
    assert load_recipe(str(p)).steps == r.steps
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** `core/recipe.py`:
```python
from __future__ import annotations
import json
from dataclasses import dataclass, field

from .color import ColorSettings
from .crop import CropParams
from ..ui.pipeline import STEP_NAME

_NAME_TO_STAGE = {name: sid for sid, name in STEP_NAME.items()}


@dataclass
class Recipe:
    steps: list = field(default_factory=list)


def serialize_option(stage_id, option):
    if stage_id == "crop":
        c = option if isinstance(option, CropParams) else CropParams()
        return {"aspect": c.aspect, "rotate": c.rotate, "flip_h": c.flip_h, "flip_v": c.flip_v}
    if stage_id == "color":
        c = option if isinstance(option, ColorSettings) else ColorSettings()
        return {"neutralize_background": c.neutralize_background,
                "white_balance": c.white_balance, "remove_green": c.remove_green}
    if stage_id == "levels":
        b, g, w = option if option else (0.0, 1.0, 1.0)
        return [b, g, w]
    if stage_id == "stretch":
        return float(option) if option not in (None, "") else 0.5
    return option  # background/noise_sharpen/local_contrast/star_reduction: str


def deserialize_option(stage_id, value):
    if stage_id == "crop":
        return CropParams(bounds=None, aspect=value["aspect"], rotate=value["rotate"],
                          flip_h=value["flip_h"], flip_v=value["flip_v"])
    if stage_id == "color":
        return ColorSettings(**value)
    if stage_id == "levels":
        return tuple(value)
    return value


def recipe_from_entries(entries) -> Recipe:
    steps = []
    for name, option in entries:
        sid = _NAME_TO_STAGE.get(name)
        if sid is None:
            continue
        steps.append({"stage": sid, "option": serialize_option(sid, option)})
    return Recipe(steps=steps)


def save_recipe(recipe: Recipe, path: str) -> None:
    with open(path, "w") as f:
        json.dump({"version": 1, "steps": recipe.steps}, f, indent=2)


def load_recipe(path: str) -> Recipe:
    with open(path) as f:
        data = json.load(f)
    return Recipe(steps=data.get("steps", []))
```
Note: importing `STEP_NAME` from `..ui.pipeline` is fine (pipeline has no Qt imports).
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: add recipe model + serialization`.

---

### Task 2: Shared step factory
**Files:** Create `seestar_processor/steps/factory.py`; Modify `seestar_processor/ui/main_window.py` (`_step_for` delegates); Test `tests/steps/test_factory.py`.
**Interfaces:** `make_step(stage_id, settings, *, bg_runner=run_cli, rc_runner=run_cli) -> Step`.

- [ ] **Step 1: Failing test**
```python
from seestar_processor.settings import Settings
from seestar_processor.steps.factory import make_step
from seestar_processor.steps.crop import CropStep
from seestar_processor.steps.stretch_step import StretchStep
from seestar_processor.steps.local_contrast import LocalContrastStep
from seestar_processor.steps.star_reduction import StarReductionStep

def test_make_step_types():
    s = Settings()
    assert isinstance(make_step("crop", s), CropStep)
    assert isinstance(make_step("stretch", s), StretchStep)
    assert isinstance(make_step("local_contrast", s), LocalContrastStep)
    assert isinstance(make_step("star_reduction", s), StarReductionStep)
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** `steps/factory.py` (mirror current `_step_for`):
```python
from __future__ import annotations
from ..settings import Settings, rcastro_valid, resolve_binary
from ..tools.base import run_cli
from ..tools.graxpert import GraXpert
from ..tools.rcastro import RCAstro
from .background import BackgroundStep
from .color import ColorStep
from .crop import CropStep
from .levels import LevelsStep
from .local_contrast import LocalContrastStep
from .noise_sharpen import NoiseSharpenStep
from .saturation_step import SaturationStep
from .star_reduction import StarReductionStep
from .stretch_step import StretchStep

def make_step(stage_id, settings: Settings, *, bg_runner=run_cli, rc_runner=run_cli):
    if stage_id == "crop":
        return CropStep()
    if stage_id == "background":
        s = BackgroundStep(GraXpert(resolve_binary(settings.graxpert_path)))
        s._runner = bg_runner
        return s
    if stage_id == "color":
        return ColorStep()
    if stage_id == "stretch":
        return StretchStep()
    if stage_id == "levels":
        return LevelsStep()
    if stage_id == "saturation":
        return SaturationStep()
    if stage_id == "local_contrast":
        return LocalContrastStep()
    if stage_id == "noise_sharpen":
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        s = NoiseSharpenStep(rc)
        s._runner = rc_runner
        return s
    if stage_id == "star_reduction":
        s = StarReductionStep(RCAstro(resolve_binary(settings.rcastro_path)))
        s._runner = rc_runner
        return s
    raise ValueError(stage_id)
```
Then in `main_window.py`, replace the body of `_step_for` with:
```python
    def _step_for(self, stage_id: str):
        return make_step(stage_id, self.settings,
                         bg_runner=self._bg_runner, rc_runner=self._rc_runner)
```
(import `from ..steps.factory import make_step`; the now-unused per-step imports in main_window can stay or be removed — keep `StretchStep` etc. only if still referenced; remove genuinely unused ones to keep it clean.)
- [ ] **Step 4: Run → PASS** + full suite (main_window still works via delegation).
- [ ] **Step 5: Commit** `refactor: shared step factory (make_step) used by app + batch`.

---

### Task 3: Headless apply_recipe + run_batch
**Files:** Create `seestar_processor/batch.py`; Test `tests/test_batch.py`.
**Interfaces:** `apply_recipe(base, recipe, settings, *, bg_runner=run_cli, rc_runner=run_cli) -> AstroImage`; `run_batch(recipe, input_paths, output_dir, fmt, settings, *, on_progress=None, bg_runner=run_cli, rc_runner=run_cli) -> list[dict]`.

- [ ] **Step 1: Failing tests**
```python
import numpy as np
from astropy.io import fits
from seestar_processor.core.image import AstroImage
from seestar_processor.core.recipe import Recipe
from seestar_processor.settings import Settings
from seestar_processor.batch import apply_recipe, run_batch

def _fits(path, h=24, w=24):
    fits.PrimaryHDU((np.random.rand(3, h, w) * 1000).astype("uint16")).writeto(str(path))

def test_apply_recipe_runs_inapp_steps():
    img = AstroImage(np.random.rand(20, 20, 3).astype(np.float32))
    r = Recipe(steps=[{"stage": "stretch", "option": 0.6},
                      {"stage": "saturation", "option": 0.4},
                      {"stage": "levels", "option": [0.1, 1.2, 0.9]}])
    out = apply_recipe(img, r, Settings())
    assert out.data.shape == (20, 20, 3)
    assert out.is_linear is False  # stretch ran

def test_apply_recipe_crop_uses_detected_bounds():
    data = np.zeros((40, 50, 3), np.float32); data[5:35, 8:45] = 0.4
    r = Recipe(steps=[{"stage": "crop",
                       "option": {"aspect": "Original", "rotate": 0, "flip_h": False, "flip_v": False}}])
    out = apply_recipe(AstroImage(data), r, Settings())
    assert out.data.shape == (30, 37, 3)

def test_run_batch_writes_outputs_and_reports_failure(tmp_path):
    good = tmp_path / "a.fits"; _fits(good)
    bad = tmp_path / "b.fits"; bad.write_text("not fits")
    outdir = tmp_path / "out"; outdir.mkdir()
    r = Recipe(steps=[{"stage": "stretch", "option": 0.5}])
    results = run_batch(r, [str(good), str(bad)], str(outdir), "PNG", Settings())
    oks = [x for x in results if x["ok"]]
    assert len(oks) == 1
    assert (outdir / "a.png").exists()
    assert any(not x["ok"] for x in results)
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** `batch.py`:
```python
from __future__ import annotations
import os

from .core.crop import detect_content_bounds
from .core.export import save_fits, save_png, save_tiff
from .core.recipe import Recipe, deserialize_option
from .steps.factory import make_step
from .steps.load import load_fits
from .tools.base import run_cli

_EXPORTERS = {"TIFF": (save_tiff, ".tiff"), "PNG": (save_png, ".png"), "FITS": (save_fits, ".fits")}


def apply_recipe(base, recipe: Recipe, settings, *, bg_runner=run_cli, rc_runner=run_cli):
    img = base
    for step in recipe.steps:
        sid = step["stage"]
        option = deserialize_option(sid, step["option"])
        st = make_step(sid, settings, bg_runner=bg_runner, rc_runner=rc_runner)
        if sid == "crop":
            t, b, l, r = detect_content_bounds(img)
            option.bounds = (t, b, l, r)
        img = st.apply(img, option)
    return img


def run_batch(recipe, input_paths, output_dir, fmt, settings, *,
              on_progress=None, bg_runner=run_cli, rc_runner=run_cli) -> list:
    exporter, ext = _EXPORTERS[fmt]
    results = []
    n = len(input_paths)
    for i, path in enumerate(input_paths):
        try:
            out = apply_recipe(load_fits(path), recipe, settings,
                               bg_runner=bg_runner, rc_runner=rc_runner)
            stem = os.path.splitext(os.path.basename(path))[0]
            exporter(out, os.path.join(output_dir, stem + ext))
            results.append({"path": path, "ok": True, "message": ""})
        except Exception as exc:
            results.append({"path": path, "ok": False, "message": str(exc)})
        if on_progress is not None:
            on_progress(i + 1, n, path)
    return results
```
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: headless apply_recipe + run_batch`.

---

### Task 4: UI — Save Recipe + Batch dialog
**Files:** Create `seestar_processor/ui/batch_dialog.py`; Modify `seestar_processor/ui/main_window.py`; Test `tests/ui/test_batch_dialog.py`, `tests/ui/test_main_window.py`.

**Interfaces:** `BatchDialog(settings, parent=None)` with `_batch_runner` (default `run_batch`), fields `recipe_edit`, `input_edit`, `output_edit`, `format_box`, `run()`; `MainWindow._save_recipe()` and a "Batch…" action opening the dialog.

- [ ] **Step 1: Failing tests**
```python
# tests/ui/test_main_window.py (add)
def test_save_recipe_writes_loadable_file(qtbot, tmp_path, monkeypatch):
    from seestar_processor.core.recipe import load_recipe
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch"); win.apply_current(0.5)
    out = str(tmp_path / "r.json")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, "")))
    win._save_recipe()
    assert [s["stage"] for s in load_recipe(out).steps] == ["stretch"]
```
```python
# tests/ui/test_batch_dialog.py
import pytest
pytest.importorskip("PySide6")
from seestar_processor.settings import Settings  # noqa: E402
from seestar_processor.ui.batch_dialog import BatchDialog  # noqa: E402

def test_batch_dialog_runs_with_fake_runner(qtbot, tmp_path):
    (tmp_path / "r.json").write_text('{"version":1,"steps":[{"stage":"stretch","option":0.5}]}')
    (tmp_path / "in").mkdir(); (tmp_path / "out").mkdir()
    dlg = BatchDialog(Settings()); qtbot.addWidget(dlg)
    captured = {}
    def fake_runner(recipe, paths, outdir, fmt, settings, on_progress=None, **kw):
        captured["fmt"] = fmt
        if on_progress:
            on_progress(1, 1, "x")
        return [{"path": "x", "ok": True, "message": ""}]
    dlg._batch_runner = fake_runner
    dlg.recipe_edit.setText(str(tmp_path / "r.json"))
    dlg.input_edit.setText(str(tmp_path / "in"))
    dlg.output_edit.setText(str(tmp_path / "out"))
    dlg.format_box.setCurrentText("PNG")
    dlg.run()
    qtbot.waitUntil(lambda: "fmt" in captured, timeout=2000)
    assert captured["fmt"] == "PNG"
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement `ui/batch_dialog.py`** — a `QDialog` with three path rows (QLineEdit + Browse), a format `QComboBox` (TIFF/PNG/FITS), a `QProgressBar`, a status `QLabel`, and Run/Close buttons. Collect FITS via `glob` of `*.fit`/`*.fits` in the input folder; call `self._batch_runner(recipe, paths, outdir, fmt, settings, on_progress=cb)` via `ui.worker.run_async`; `cb` updates the progress bar (use a `Signal` or `QMetaObject.invokeMethod`; simplest: a `WorkerSignals`-style progress signal). Set `self._batch_runner = run_batch` by default; load the recipe with `load_recipe`. (Full code written during execution.)
- [ ] **Step 4: Implement `main_window`** — `_save_recipe()`:
```python
    def _save_recipe(self) -> None:
        if self.project is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Recipe", "", "Recipe (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        save_recipe(recipe_from_entries(self.project.entries()), path)
```
Toolbar: add `tb.addAction("Save Recipe", self._save_recipe)` and `tb.addAction("Batch…", self._open_batch)` where `_open_batch` does `BatchDialog(self.settings, self).exec()`. Imports: `recipe_from_entries`, `save_recipe`, `BatchDialog`.
- [ ] **Step 5: Run → PASS** + full suite, pristine.
- [ ] **Step 6: Commit** `feat: Save Recipe + Batch dialog`.

---

## Verification (end to end)
`.venv/bin/python -m seestar_processor`: process an image; **Save Recipe** → a `.json`. **Batch…** → pick that recipe, a folder of Seestar FITS, an output folder, a format → Run → progress bar advances; each FITS is processed with the recipe (border auto-cropped per image) and exported; a ✓/✗ summary shows.

## Self-Review
- Coverage: recipe model+serialize+record+save/load (T1), shared factory (T2), headless apply+batch (T3), Save Recipe + Batch UI (T4).
- Types: `Recipe.steps` list of `{stage,option}`; `serialize/deserialize_option(stage_id, …)`; `make_step(stage_id, settings, *, bg_runner, rc_runner)`; `apply_recipe`/`run_batch` signatures; `BatchDialog` fields — consistent across tasks and the app delegation.
- No-import-cycle note: `core/recipe.py` imports `ui.pipeline` (Qt-free); `ui` imports `core.recipe` — pipeline must stay Qt-free (it is).
