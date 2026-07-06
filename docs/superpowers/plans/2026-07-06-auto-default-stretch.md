# Auto Default Stretch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-commit a default Stretch (amount 0.5, matching the preview) when the user navigates to a post-stretch finishing step while the image is still linear, so those steps always have real stretched data.

**Architecture:** Add a `POST_STRETCH_IDS` set to `ui/pipeline.py` naming the post-stretch processing stages (Export excluded). Add `_ensure_stretched()` to `MainWindow`, mirroring the manual Stretch apply path (same predecessor truncation), and call it from the single navigation choke point `_go_to(index)` when the target is a post-stretch step and `project.current().is_linear`.

**Tech Stack:** Python 3.13 (`.venv`), PySide6 (Qt), pytest-qt (headless via `QT_QPA_PLATFORM=offscreen`).

## Global Constraints

- Python interpreter: `.venv/bin/python`; tests: `.venv/bin/pytest` (system python3 is 3.9 — do NOT use it).
- Run the suite with: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`.
- Default stretch amount is **0.5**, applied via the existing Stretch step's default option (`self._step_for("stretch").apply(base, "")` — `""` maps to amount 0.5 in `StretchStep`).
- History entry name is exactly `"Stretch"` (so existing truncation/preceding logic treats it identically to a manual stretch); the log entry is logged as `"Stretch (auto)"` via `format_log_entry("Stretch", "auto", ...)`.
- `POST_STRETCH_IDS` = `{"levels","saturation","noise_sharpen","local_contrast","star_reduction","enhancements"}` — the `_IN_APP_TAIL` stages minus `export`. Export is deliberately excluded.
- Preserve the existing Levels-on-linear guard in `apply_current` (belt-and-suspenders).
- Preserve test seams: `_window(qtbot, tmp_path)` sets `_async_enabled=False`; `_make_fits(tmp_path)` produces a linear image; `win.open_fits(path)` loads it and leaves the view on `load`.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: `POST_STRETCH_IDS` constant in the pipeline

**Files:**
- Modify: `seestar_processor/ui/pipeline.py`
- Test: `tests/ui/test_pipeline.py`

**Interfaces:**
- Produces: module-level `POST_STRETCH_IDS: frozenset[str]` in `seestar_processor/ui/pipeline.py`, value
  `frozenset({"levels","saturation","noise_sharpen","local_contrast","star_reduction","enhancements"})`.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_pipeline.py`:

```python
def test_post_stretch_ids_are_the_finishing_steps_minus_export():
    from seestar_processor.ui.pipeline import POST_STRETCH_IDS, PROCESSING_ORDER
    assert POST_STRETCH_IDS == frozenset({
        "levels", "saturation", "noise_sharpen",
        "local_contrast", "star_reduction", "enhancements",
    })
    # Export and the stretch stage itself must NOT be in the set.
    assert "export" not in POST_STRETCH_IDS
    assert "stretch" not in POST_STRETCH_IDS
    # Every pre-stretch processing id must be excluded.
    pre = PROCESSING_ORDER[: PROCESSING_ORDER.index("stretch")]
    assert POST_STRETCH_IDS.isdisjoint(pre)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_pipeline.py::test_post_stretch_ids_are_the_finishing_steps_minus_export -q`
Expected: FAIL with `ImportError: cannot import name 'POST_STRETCH_IDS'`.

- [ ] **Step 3: Add the constant**

In `seestar_processor/ui/pipeline.py`, add near the other module-level name sets (e.g. next to `ENHANCE_NAMES`):

```python
# Finishing steps that operate in display space and require a stretched image.
# These are the in-app tail stages minus "export" (exporting a linear file is
# legitimate, so Export never forces a stretch).
POST_STRETCH_IDS = frozenset({
    "levels", "saturation", "noise_sharpen",
    "local_contrast", "star_reduction", "enhancements",
})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_pipeline.py -q`
Expected: PASS (all pipeline tests green).

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/pipeline.py tests/ui/test_pipeline.py
git commit -m "feat: POST_STRETCH_IDS — finishing steps that require a stretched image

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Auto-stretch on navigation to a post-stretch step

**Files:**
- Modify: `seestar_processor/ui/main_window.py` (import line ~37; `_go_to` ~341-350; add `_ensure_stretched` near it)
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `POST_STRETCH_IDS` from `seestar_processor/ui/pipeline.py` (Task 1); existing `self._step_for`, `self._leading_kept`, `self.project`, `_PrecomputedStep`, `GEOMETRY_NAMES`, `STEP_NAME`, `PROCESSING_ORDER`, `format_log_entry`, `rms_delta` (all already in `main_window.py`).
- Produces: `MainWindow._ensure_stretched(self) -> None`; a guard at the top of `_go_to` that calls it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_main_window.py`:

```python
def test_navigating_to_levels_auto_stretches(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win.project.current().is_linear          # nothing stretched yet
    win._go_to_id("levels")                          # jump past Stretch while linear
    names = [n for n, _ in win.project.entries()]
    assert "Stretch" in names                        # auto-committed
    assert not win.project.current().is_linear       # data is now stretched
    assert "Stretch (auto)" in win.log_panel.text()
    # Levels itself now applies (no longer refused/black):
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
    win._go_to_id("export")                           # Export is excluded
    assert "Stretch" not in [n for n, _ in win.project.entries()]
    assert win.project.current().is_linear


def test_already_stretched_is_not_double_stretched(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)                            # manual Stretch
    win._go_to_id("saturation")                       # navigate to a post-stretch step
    names = [n for n, _ in win.project.entries()]
    assert names.count("Stretch") == 1               # no second stretch appended


def test_auto_stretch_is_undoable(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("levels")                           # auto-stretches
    assert not win.project.current().is_linear
    win._undo()
    assert win.project.current().is_linear            # back to linear
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q -k "auto_stretch or double_stretch or pre_stretch"`
Expected: FAIL — `test_navigating_to_levels_auto_stretches` fails (no "Stretch" entry; and the Levels guard from the prior fix refuses the apply). The others may pass incidentally before the change; they pin the correct behaviour after it.

- [ ] **Step 3: Import `POST_STRETCH_IDS`**

In `seestar_processor/ui/main_window.py`, extend the pipeline import (currently:
`from .pipeline import ENHANCE_NAMES, GEOMETRY_NAMES, PROCESSING_ORDER, STEP_NAME, next_enabled, path_stages, prev_enabled`) to add `POST_STRETCH_IDS`:

```python
from .pipeline import (
    ENHANCE_NAMES, GEOMETRY_NAMES, POST_STRETCH_IDS, PROCESSING_ORDER,
    STEP_NAME, next_enabled, path_stages, prev_enabled,
)
```

- [ ] **Step 4: Add `_ensure_stretched` and hook `_go_to`**

Add the method (place it directly above `_go_to`):

```python
    def _ensure_stretched(self) -> None:
        """Commit a default Stretch (amount 0.5) at the stretch position so the
        post-stretch finishing steps have real stretched data. The caller invokes
        this only when the current image is still linear."""
        preceding = set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index("stretch")]
        }
        self.project.jump_back(self._leading_kept(self.project.entries(), preceding))
        base = self.project.current()
        result = self._step_for("stretch").apply(base, "")   # "" -> default amount 0.5
        self.project.run_step(_PrecomputedStep("Stretch", result), "")
        self.log_panel.append_entry(
            format_log_entry("Stretch", "auto", rms_delta(base, result)))
```

Then add the guard at the top of `_go_to`, right after the bounds/enabled check:

```python
    def _go_to(self, index: int) -> None:
        if not (0 <= index < len(self._stages)) or not self._stages[index].enabled:
            return
        if (self.project is not None
                and self._stages[index].id in POST_STRETCH_IDS
                and self.project.current().is_linear):
            self._ensure_stretched()
        self._stage = index
        self._status.setText("")  # clear any stale error when changing steps
        if self.image_view.compare_active():  # before/after is per-image; reset on nav
            self._ba_act.setChecked(False)
            self.image_view.set_compare(None)
        self._rebuild_panel()
        self._refresh()
```

- [ ] **Step 5: Run the new tests, then the full main-window file**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q`
Expected: PASS — the five new tests plus all existing tests (including `test_apply_levels_stays_on_step_and_logs`, which already stretches first).

- [ ] **Step 6: Full suite + commit**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: PASS (all tests green).

```bash
git add seestar_processor/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat: auto-commit default Stretch when entering a post-stretch step

Navigating (Next or stepper) to a finishing step while the image is still
linear now auto-commits a default Stretch (amount 0.5, matching the preview),
logged as 'Stretch (auto)' and fully undoable. Export excluded. Keeps the
Levels-on-linear guard as a safety net.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- `POST_STRETCH_IDS` (six finishing steps, Export excluded) → Task 1. ✅
- Auto-commit default Stretch on navigation to a post-stretch step while linear → Task 2 (`_ensure_stretched` + `_go_to` hook). ✅
- Default amount 0.5 via `apply(base, "")` → Task 2 Step 4. ✅
- Committed as undoable "Stretch" entry, logged "Stretch (auto)" → Task 2 (`_ensure_stretched`, tests `..._auto_stretches`, `..._is_undoable`). ✅
- Export excluded → Task 2 test `..._to_export_does_not_auto_stretch`. ✅
- Pre-stretch nav does nothing; already-stretched not double-stretched → Task 2 tests. ✅
- Levels guard preserved → not modified (still present in `apply_current`); no task removes it. ✅
- Works for Next and stepper jumps → both route through `_go_to`; the hook lives there. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✅

**Type consistency:** `POST_STRETCH_IDS` frozenset name/value identical in Task 1, Task 2 import, and tests. `_ensure_stretched(self) -> None` signature consistent. `format_log_entry("Stretch", "auto", ...)` and history name `"Stretch"` consistent with the Global Constraints. ✅
