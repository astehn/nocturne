# Crop — Decouple Rotate/Flip from Apply Crop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Rotate/Flip immediate undoable buttons and Apply Crop crop-only, so flipping never re-crops; each geometry op is its own history step and processing steps preserve all geometry.

**Architecture:** Rotate/Flip/Crop become append-only immediate ops (via `_apply_geometry` → `CropStep.apply` → `_PrecomputedStep`). Remove `crop` from `PROCESSING_ORDER`/`STEP_NAME`, add `GEOMETRY_NAMES`, and make each processing step's history-truncation `preceding` set include all geometry names so geometry is preserved.

**Tech Stack:** PySide6, numpy, Python 3.11+.

## Global Constraints

- Package `seestar_processor` (no rename). Venv `.venv`; UI tests headless (`QT_QPA_PLATFORM=offscreen`).
- Rotate 90° / Flip H / Flip V = immediate buttons, each its own undoable history step (append-only). Flip buttons NOT checkable. Apply Crop crops only (bounds).
- Overlay resets to detected content box after every geometry op. Apply Crop with the box at the full frame is a no-op (no history entry).
- Remove `"crop"` from `PROCESSING_ORDER` and `STEP_NAME`; add `GEOMETRY_NAMES = ("Crop", "Rotate", "Flip H", "Flip V")`. Every processing step's `preceding` set = `set(GEOMETRY_NAMES) | {STEP_NAME[sid] for earlier processing}`.
- `CropStep` stays the single geometry engine (rotate/flip/crop all go through `CropStep.apply(img, CropParams(...))`).
- The three UI files (pipeline, main_window, step_panels) are coupled through this model — Task 1 changes them together with their tests so the suite is coherent at each commit.
- Commit after each task. Create the `crop-decouple` branch first (do not start on `main`).

---

## File Structure

- `seestar_processor/ui/pipeline.py` — remove `crop` from PROCESSING_ORDER + STEP_NAME; add `GEOMETRY_NAMES`.
- `seestar_processor/ui/main_window.py` — `_apply_geometry` + `_rotate`/`_flip_h`/`_flip_v`; slim `_apply_crop`; `apply_current` `preceding` union; `_done_ids` crop marking; build_panel wiring; remove dead crop line.
- `seestar_processor/ui/step_panels.py` — crop branch: immediate rotate/flip buttons (non-checkable), new callbacks.
- Tests: `tests/ui/test_pipeline.py`, `tests/ui/test_main_window.py`, `tests/ui/test_step_panels.py`.

---

## Task 0: Branch setup

- [ ] **Step 1: Create the feature branch**

```bash
cd /Volumes/Work/Code/Editor
git checkout -b crop-decouple
git status   # expect: On branch crop-decouple, clean
```

---

## Task 1: Decouple geometry (pipeline + main_window + panels + tests)

**Files:**
- Modify: `seestar_processor/ui/pipeline.py`
- Modify: `seestar_processor/ui/main_window.py`
- Modify: `seestar_processor/ui/step_panels.py`
- Modify: `tests/ui/test_pipeline.py`, `tests/ui/test_main_window.py`, `tests/ui/test_step_panels.py`

**Interfaces:**
- Produces: `pipeline.GEOMETRY_NAMES`; `PROCESSING_ORDER`/`STEP_NAME` without `crop`; `MainWindow._apply_geometry(name, params)`, `_rotate()`, `_flip_h()`, `_flip_v()`, slimmed `_apply_crop()`; `build_panel(..., on_rotate=None, on_flip_h=None, on_flip_v=None)`.

- [ ] **Step 1: Update the pipeline tests**

In `tests/ui/test_pipeline.py`, update `test_step_name_and_order` and add a geometry test:

```python
def test_step_name_and_order():
    assert STEP_NAME["noise_sharpen"] == "Noise & Sharpen"
    assert STEP_NAME["levels"] == "Levels"
    assert STEP_NAME["star_reduction"] == "Star Reduction"
    assert "crop" not in STEP_NAME
    assert PROCESSING_ORDER == [
        "background", "color", "stretch", "levels", "saturation",
        "noise_sharpen", "local_contrast", "star_reduction",
    ]


def test_geometry_names():
    from seestar_processor.ui.pipeline import GEOMETRY_NAMES
    assert GEOMETRY_NAMES == ("Crop", "Rotate", "Flip H", "Flip V")
```

(`test_path_stages_single_linear_flow` still asserts the full stage id list including `"crop"` —
the Crop *stage* stays; leave that test unchanged.)

- [ ] **Step 2: Run pipeline tests, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_pipeline.py -q`
Expected: FAIL (`GEOMETRY_NAMES` missing; PROCESSING_ORDER/STEP_NAME still contain crop).

- [ ] **Step 3: Implement `pipeline.py`**

In `seestar_processor/ui/pipeline.py`: remove the `"crop": "Crop",` line from `STEP_NAME`;
remove `"crop", ` from the front of `PROCESSING_ORDER`; add after `PROCESSING_ORDER`:

```python
GEOMETRY_NAMES = ("Crop", "Rotate", "Flip H", "Flip V")
```

(Leave `_CORE` — the Crop `Stage` — unchanged.)

- [ ] **Step 4: Run pipeline tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Update the step_panels tests**

In `tests/ui/test_step_panels.py`, replace the crop panel controls test (the one building
`build_panel(_stage("crop"), ...)` and clicking rotate/flip via staged state) with immediate-
callback assertions:

```python
def test_crop_panel_immediate_buttons(qtbot):
    got = []
    w = build_panel(
        _stage("crop"),
        on_rotate=lambda: got.append("rotate"),
        on_flip_h=lambda: got.append("flip_h"),
        on_flip_v=lambda: got.append("flip_v"),
        on_crop_apply=lambda: got.append("crop"),
    )
    qtbot.addWidget(w)
    assert w.flip_h_btn.isCheckable() is False   # momentary, not sticky
    assert w.flip_v_btn.isCheckable() is False
    w.rotate_btn.click()
    w.flip_h_btn.click()
    w.flip_v_btn.click()
    w.apply_btn.click()
    assert got == ["rotate", "flip_h", "flip_v", "crop"]
```

(If any other crop-panel test asserts `w.rotate` staged state or checkable flips, delete/adjust
it.)

- [ ] **Step 6: Run step_panels tests, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_step_panels.py -q`
Expected: FAIL (`on_rotate`/`on_flip_h`/`on_flip_v` unknown; flips still checkable).

- [ ] **Step 7: Implement `step_panels.py` (crop branch)**

Change the `build_panel` signature to add the three callbacks (next to `on_crop_apply`):
`on_rotate=None, on_flip_h=None, on_flip_v=None,`.

Replace the entire `elif stage.kind == "crop":` branch with:

```python
    elif stage.kind == "crop":
        lay.addWidget(_desc_label(
            "Drag the box then Apply Crop. Rotate/Flip apply instantly."))
        aspect = QComboBox()
        aspect.addItems(ASPECTS)
        if on_crop_change is not None:
            aspect.currentTextChanged.connect(lambda t: on_crop_change(t))
        rotate_btn = QPushButton("Rotate 90°")
        if on_rotate is not None:
            rotate_btn.clicked.connect(lambda: on_rotate())
        flip_h = QPushButton("Flip H")
        if on_flip_h is not None:
            flip_h.clicked.connect(lambda: on_flip_h())
        flip_v = QPushButton("Flip V")
        if on_flip_v is not None:
            flip_v.clicked.connect(lambda: on_flip_v())
        apply_btn = QPushButton("Apply Crop")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_crop_apply is not None:
            apply_btn.clicked.connect(lambda: on_crop_apply())
        lay.addWidget(QLabel("Aspect ratio"))
        lay.addWidget(aspect)
        lay.addWidget(rotate_btn)
        flips = QHBoxLayout()
        flips.addWidget(flip_h)
        flips.addWidget(flip_v)
        lay.addLayout(flips)
        lay.addWidget(apply_btn)
        w.aspect_box = aspect
        w.rotate_btn = rotate_btn
        w.flip_h_btn = flip_h
        w.flip_v_btn = flip_v
        w.apply_btn = apply_btn
```

- [ ] **Step 8: Run step_panels tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_step_panels.py -q`
Expected: PASS.

- [ ] **Step 9: Update the main_window tests**

In `tests/ui/test_main_window.py`:

Rewrite `test_apply_crop_with_params_changes_dimensions` to use the new geometry path, and add
the new tests:

```python
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
```

Also update `test_apply_crop_with_params_changes_dimensions` removal — replace it entirely with
`test_apply_geometry_crop_changes_dimensions` above (delete the old one).

- [ ] **Step 10: Run main_window tests, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q`
Expected: FAIL (`_apply_geometry`/`_rotate`/`_flip_h` missing; geometry not preserved).

- [ ] **Step 11: Implement `main_window.py`**

(a) Add `GEOMETRY_NAMES` to the pipeline import line, e.g.:
`from .pipeline import GEOMETRY_NAMES, PROCESSING_ORDER, STEP_NAME, next_enabled, path_stages, prev_enabled`.

(b) In `apply_current`, change the `preceding` computation to include geometry:

```python
        preceding = set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index(stage_id)]
        }
```

and delete the `if stage_id == "crop": self._setup_crop_overlay()` line in the `done` callback
(crop no longer routes through `apply_current`).

(c) Replace `_apply_crop` and add the geometry engine + handlers (put them near `_apply_crop`):

```python
    def _apply_geometry(self, name: str, params) -> None:
        if self.project is None or self._busy:
            return
        result = self._step_for("crop").apply(self.project.current(), params)
        self.project.run_step(_PrecomputedStep(name, result), "")
        self.log_panel.append_entry(format_log_entry(name, "", None))
        self._status.setText("")
        self._refresh()
        self._setup_crop_overlay()

    def _rotate(self) -> None:
        self._apply_geometry("Rotate", CropParams(rotate=90))

    def _flip_h(self) -> None:
        self._apply_geometry("Flip H", CropParams(flip_h=True))

    def _flip_v(self) -> None:
        self._apply_geometry("Flip V", CropParams(flip_v=True))

    def _apply_crop(self) -> None:
        if self.project is None or self._busy:
            return
        top, bottom, left, right = self.image_view.crop_bounds()
        h, w = self.project.current().data.shape[:2]
        if (top, bottom, left, right) == (0, h, 0, w):
            return  # box is the full frame -> no real crop
        self._apply_geometry("Crop", CropParams(bounds=(top, bottom, left, right)))
```

(d) In `_done_ids`, after the `for sid, name in STEP_NAME.items()` loop, mark the crop stage
done if any geometry op was applied:

```python
        if any(g in applied for g in GEOMETRY_NAMES):
            done.add("crop")
```

(e) In the `build_panel(...)` call in `_rebuild_panel`, add the three callbacks:
`on_rotate=self._rotate, on_flip_h=self._flip_h, on_flip_v=self._flip_v,`.

- [ ] **Step 12: Run main_window tests + full suite, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q`
then `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass. If `test_sharpen_changes_image_and_keeps_shape` fails, it's the known
pre-existing flake — rerun it alone to confirm.

- [ ] **Step 13: Commit**

```bash
git add seestar_processor/ui/pipeline.py seestar_processor/ui/main_window.py seestar_processor/ui/step_panels.py tests/ui/test_pipeline.py tests/ui/test_main_window.py tests/ui/test_step_panels.py
git commit -m "feat: crop — immediate rotate/flip as own undoable steps; Apply Crop crops only"
```

---

## Task 2: Backlog

- [ ] **Step 1: Mark the crop item done**

In `TODO.md`, if the crop-rework item exists as an open bullet, mark it `- [x]`; otherwise add
under a suitable section:
`- [x] **Crop rotate/flip decoupled.** Rotate/Flip are immediate undoable buttons; Apply Crop crops only; flipping no longer re-crops; processing preserves geometry.`
(Leave the deferred "Crop preview framing stretch" bullet as `- [ ]`.)

- [ ] **Step 2: Full suite once more**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add TODO.md
git commit -m "docs: mark crop rotate/flip decouple done in backlog"
```

---

## Definition of Done

- Committed on `crop-decouple`; full suite green.
- Rotate/Flip apply instantly as their own undoable steps; Apply Crop crops only; flip-after-crop
  does not re-crop; a processing step after geometry preserves the crop/rotate/flips; Undo
  reverses one op at a time.
- After merge: by-eye check — Flip H mirrors instantly (no crop), Apply Crop crops, Rotate
  rotates, Undo steps back one op, Background after crop keeps the crop.
- Finish with **superpowers:finishing-a-development-branch**.
