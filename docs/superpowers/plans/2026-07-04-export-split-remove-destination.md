# Export Split + Remove Destination Step Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the Destination fork into one linear flow and offer the starless+stars split as a 4th format at the single Export step.

**Architecture:** Remove the `destination` stage + `external` branch from `pipeline.py`; delete the destination/export_external panels and move the split into the unified export panel + `export_final`; the export format string alone selects whole-file vs split (no branch state). Update the coupled tests.

**Tech Stack:** PySide6, Python 3.11+.

## Global Constraints

- Package `seestar_processor` (no rename). Venv `.venv`; UI tests headless (`QT_QPA_PLATFORM=offscreen`).
- Keep the "Export" label. One dropdown: `TIFF (16-bit) · PNG · FITS · Starless + Stars (two TIFFs)`; the split entry greyed when RC-Astro not configured.
- One linear path (no early-exit). Split still writes two TIFFs (`starless.tif` + `stars.tif`) to a chosen folder.
- `pipeline.py`, `step_panels.py`, `main_window.py` are coupled through the removed branch — Task 1 changes them together so the suite is coherent at each commit.
- Commit after each task. Create the `export-split` branch first (do not start on `main`).

---

## File Structure

- `seestar_processor/ui/pipeline.py` — remove `destination` stage + `_EXTERNAL_TAIL`; `path_stages()` parameterless.
- `seestar_processor/ui/step_panels.py` — delete `destination`/`export_external` branches; extend `EXPORT_FORMATS`; add `split_enabled` to the export panel; drop `on_destination`/`on_export_external` params.
- `seestar_processor/ui/main_window.py` — remove `destination`/`set_destination`/`export_external`; `export_final` absorbs the split; wire `split_enabled`.
- Tests: `tests/ui/test_pipeline.py`, `tests/ui/test_step_panels.py`, `tests/ui/test_main_window.py` (update to the collapsed flow).

---

## Task 0: Branch setup

- [ ] **Step 1: Create the feature branch**

```bash
cd /Volumes/Work/Code/Editor
git checkout -b export-split
git status   # expect: On branch export-split, clean
```

---

## Task 1: Pipeline + panels + main_window (coordinated) with updated tests

**Files:**
- Modify: `seestar_processor/ui/pipeline.py`
- Modify: `seestar_processor/ui/step_panels.py`
- Modify: `seestar_processor/ui/main_window.py`
- Modify: `tests/ui/test_pipeline.py`, `tests/ui/test_step_panels.py`, `tests/ui/test_main_window.py`

**Interfaces:**
- Produces: `path_stages() -> list[Stage]` (no arg); `build_panel(..., split_enabled: bool = False)` (no `on_destination`/`on_export_external`); `EXPORT_FORMATS` includes `"Starless + Stars (two TIFFs)"`; `main_window.export_final(fmt)` handles the split; `set_destination`/`export_external` removed.

- [ ] **Step 1: Update the pipeline tests (write them to the new shape first)**

In `tests/ui/test_pipeline.py`, replace the three destination/path tests
(`test_core_stages_shared_prefix`, `test_external_path_stops_after_stretch_with_export`,
`test_in_app_path_has_cosmetic_then_export`) with:

```python
def test_core_stages_no_destination():
    assert [s.id for s in core_stages()] == [
        "load", "crop", "background", "color", "stretch",
    ]


def test_path_stages_single_linear_flow():
    ids = [s.id for s in path_stages()]
    assert ids == [
        "load", "crop", "background", "color", "stretch", "levels",
        "saturation", "noise_sharpen", "local_contrast", "star_reduction", "export",
    ]
    assert "destination" not in ids and "export_external" not in ids
```

Update the `test_next_prev_enabled_on_stage_list` test's `path_stages("in_app")` call to
`path_stages()` (no arg). Leave `test_step_name_and_order` as is.

- [ ] **Step 2: Run pipeline tests, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_pipeline.py -q`
Expected: FAIL (`path_stages()` still requires an arg / `destination` still present).

- [ ] **Step 3: Implement `pipeline.py`**

In `seestar_processor/ui/pipeline.py`:

Replace the `_CORE` list (remove the destination stage):

```python
_CORE = [
    Stage("load", "Import", "import"),
    Stage("crop", "Crop", "crop"),
    Stage("background", "Background", "process"),
    Stage("color", "Color", "auto"),
    Stage("stretch", "Stretch", "stretch"),
]
```

Delete the `_EXTERNAL_TAIL = [...]` line entirely. Replace `path_stages`:

```python
def path_stages() -> list[Stage]:
    return list(_CORE) + list(_IN_APP_TAIL)
```

(Keep `_IN_APP_TAIL`, `core_stages`, `next_enabled`, `prev_enabled`, `STEP_NAME`,
`PROCESSING_ORDER` unchanged.)

- [ ] **Step 4: Run pipeline tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Update the step_panels tests**

In `tests/ui/test_step_panels.py`:

Delete `test_destination_buttons_emit_choice` (the `destination` kind is gone).

Replace `test_export_external_split_disabled_without_rcastro` with:

```python
def test_export_panel_split_disabled_without_rcastro(qtbot):
    w = build_panel(_stage("export"), split_enabled=False)
    qtbot.addWidget(w)
    assert w.fmt_box.count() == 4
    assert w.fmt_box.model().item(3).isEnabled() is False  # split needs RC-Astro


def test_export_panel_split_enabled_with_rcastro(qtbot):
    w = build_panel(_stage("export"), split_enabled=True)
    qtbot.addWidget(w)
    assert w.fmt_box.model().item(3).isEnabled() is True
```

(Leave `test_export_panel_formats` — but note it will now see 4 formats; if it asserts an exact
count of 3, update that assertion to 4. If it only checks that selecting a format calls
`on_export`, leave it.)

- [ ] **Step 6: Run step_panels tests, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_step_panels.py -q`
Expected: FAIL (`split_enabled` unknown / export panel still has 3 formats / destination kind referenced).

- [ ] **Step 7: Implement `step_panels.py`**

In `seestar_processor/ui/step_panels.py`:

(a) Replace the formats constants:

```python
EXPORT_FORMATS = ["TIFF (16-bit)", "PNG", "FITS", "Starless + Stars (two TIFFs)"]
```

Delete the `EXTERNAL_FORMATS = [...]` line.

(b) Change the `build_panel` signature: remove `on_destination=None` and
`on_export_external=None`; add `split_enabled: bool = False` (put it next to `apply_enabled`).

(c) Delete the entire `elif stage.kind == "destination":` branch and the entire
`elif stage.kind == "export_external":` branch.

(d) Replace the `elif stage.kind == "export":` branch with:

```python
    elif stage.kind == "export":
        box = QComboBox()
        box.addItems(EXPORT_FORMATS)
        if not split_enabled:
            box.model().item(3).setEnabled(False)  # starless+stars split needs StarX
        export_btn = QPushButton("Export…")
        export_btn.setObjectName("primary")
        if on_export is not None:
            export_btn.clicked.connect(lambda: on_export(box.currentText()))
        lay.addWidget(QLabel("Format"))
        lay.addWidget(box)
        lay.addWidget(export_btn)
        if not split_enabled:
            lay.addWidget(_desc_label(
                "Starless + stars split needs RC-Astro (set its path in Settings)."))
        w.fmt_box = box
        w.export_btn = export_btn
```

- [ ] **Step 8: Update the main_window tests**

In `tests/ui/test_main_window.py`:

- In `test_default_in_app_path_navigation` (~line 35), remove `"destination", ` from the `seq`
  list so it starts `["crop", "background", ...]`.
- Delete `test_external_destination_changes_tail` entirely.
- Delete `test_export_external_panel_split_gated` entirely.
- In `test_status_cleared_on_navigation` (~line 213), change `win._go_to_id("destination")` to
  `win._go_to_id("crop")`.
- Add these new tests:

```python
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


def test_no_destination_attrs(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert not hasattr(win, "set_destination")
    assert not hasattr(win, "export_external")


def test_next_from_load_is_crop(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("load")
    win.go_next()
    assert win.current_stage_id() == "crop"
```

- [ ] **Step 9: Run main_window tests, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q`
Expected: FAIL (still has destination attrs / export_final doesn't handle split / imports).

- [ ] **Step 10: Implement `main_window.py`**

In `seestar_processor/ui/main_window.py`:

(a) In `__init__`, change the stages init from
`self.destination = "in_app"` + `self._stages = path_stages(self.destination)` to just:

```python
        self._stages = path_stages()
```

(Delete the `self.destination = "in_app"` line.)

(b) Delete the entire `set_destination` method and the entire `export_external` method.

(c) In `_rebuild_panel`, delete the `if stage.id == "export_external":` apply_enabled line, and
add a `split_enabled` computation + pass it to `build_panel`, dropping the removed kwargs:

```python
        split_enabled = loaded and rcastro_valid(self.settings)
        new_panel = build_panel(
            stage,
            on_open=self._choose_fits,
            on_apply=self.apply_current,
            on_crop_apply=self._apply_crop,
            on_crop_change=self._on_crop_change,
            on_export=self.export_final,
            apply_enabled=apply_enabled,
            split_enabled=split_enabled,
        )
```

(d) Replace `export_final` to handle the split format (keep the single-file branch as-is):

```python
    def export_final(self, fmt: str) -> None:
        if self.project is None:
            return
        img = self.project.current()
        if fmt == "Starless + Stars (two TIFFs)":
            if not rcastro_valid(self.settings):
                self._status.setText("Starless + stars split needs RC-Astro (see Settings).")
                return
            folder = QFileDialog.getExistingDirectory(self, "Export starless + stars to…")
            if not folder:
                return

            def _do():
                rc = RCAstro(resolve_binary(self.settings.rcastro_path))
                starless, stars = rc.remove_stars(img, runner=self._rc_runner)
                save_tiff(starless, os.path.join(folder, "starless.tif"))
                save_tiff(stars, os.path.join(folder, "stars.tif"))

            self._guarded(_do, "Exported starless.tif + stars.tif")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", "", "TIFF (*.tiff);;PNG (*.png);;FITS (*.fits)"
        )
        if not path:
            return
        if fmt == "PNG":
            if not path.lower().endswith(".png"):
                path += ".png"
            self._guarded(lambda: save_png(img, path), f"Exported {os.path.basename(path)}")
        elif fmt == "FITS":
            if not path.lower().endswith((".fits", ".fit")):
                path += ".fits"
            self._guarded(lambda: save_fits(img, path), f"Exported {os.path.basename(path)}")
        else:
            if not path.lower().endswith((".tiff", ".tif")):
                path += ".tiff"
            self._guarded(lambda: save_tiff(img, path), f"Exported {os.path.basename(path)}")
```

(Keep the existing `RCAstro`, `resolve_binary`, `rcastro_valid`, `save_tiff/png/fits` imports —
they are now used by `export_final`. If `set_destination` was the only caller of anything else,
leave other imports alone.)

- [ ] **Step 11: Run the full suite, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass. If `test_sharpen_changes_image_and_keeps_shape` fails, it's the known
pre-existing flake — rerun it alone to confirm.

- [ ] **Step 12: Commit**

```bash
git add seestar_processor/ui/pipeline.py seestar_processor/ui/step_panels.py seestar_processor/ui/main_window.py tests/ui/test_pipeline.py tests/ui/test_step_panels.py tests/ui/test_main_window.py
git commit -m "feat: fold starless+stars split into Export; remove the Destination step"
```

---

## Task 2: Sweep stray references + backlog

**Files:**
- Modify: `TODO.md`
- (Check-only): any remaining `destination` / `export_external` references.

- [ ] **Step 1: Grep for stray references**

Run:
```bash
grep -rn "destination\|export_external\|set_destination\|EXTERNAL_FORMATS\|_EXTERNAL_TAIL" seestar_processor/ tests/
```
Expected: no matches in `seestar_processor/` or `tests/` (only historical mentions in `docs/`
are fine). If any code/test match remains, fix it (remove the reference) and re-run the full
suite.

- [ ] **Step 2: Update the backlog**

In `TODO.md`, mark the item done: change the "Export options at the final Save step + remove the
Destination step" bullet from `- [ ]` to `- [x]` and append: `Shipped: single Export step with a
'Starless + Stars (two TIFFs)' 4th format (RC-Astro-gated); Destination step + external branch
removed; one linear flow.`

- [ ] **Step 3: Full suite once more**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add TODO.md
git commit -m "docs: mark export-split / remove-destination done in backlog"
```

---

## Definition of Done

- All tasks committed on `export-split`; full suite green; no `destination`/`export_external`
  references remain in `seestar_processor/` or `tests/`.
- The app flows Import → Crop → … → Export (no Destination); the Export dropdown offers
  TIFF/PNG/FITS + "Starless + Stars (two TIFFs)" (greyed without RC-Astro), and the split writes
  `starless.tif` + `stars.tif` to a chosen folder.
- After merge: quick by-eye check of the Export dropdown and a split export with RC-Astro.
- Finish with **superpowers:finishing-a-development-branch**.
