# "Reset Image" Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A toolbar "Reset" button that restarts editing on the already-loaded image (fresh Project, history cleared) behind a confirmation, without re-picking the file.

**Architecture:** `open_image` stashes the loaded base + label; a `_reset_image` handler confirms via `QMessageBox.question` then re-calls `open_image` on the stashed base. A new tinted `reset.svg` icon backs the toolbar action, which starts disabled and is enabled by `_refresh` once an image is loaded.

**Tech Stack:** Python 3.13 (`.venv`), PySide6 (Qt), pytest-qt (`QT_QPA_PLATFORM=offscreen`).

## Global Constraints

- Use `.venv/bin/python` / `.venv/bin/pytest`; system python is 3.9 and will fail. Qt tests: prefix `QT_QPA_PLATFORM=offscreen`.
- Reset must be a true "start over": fresh `Project`, all history + redo cleared, back on the Import stage, using the in-memory base (no disk re-read).
- Reset requires a Yes confirmation (default button No). Declining changes nothing.
- The action is disabled until an image is loaded.
- `reset.svg` matches the existing icon style: `viewBox="0 0 24 24"`, `stroke="#fff"`, `stroke-width="2"`, round caps/joins.
- Commit co-author trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Known flake: `test_sharpen_changes_image_and_keeps_shape` — rerun alone if it trips.

---

### Task 1: Reset icon, toolbar action, and handler

**Files:**
- Create: `seestar_processor/assets/icons/reset.svg`
- Modify: `seestar_processor/ui/icons.py` (`ICON_NAMES` tuple ~line 14)
- Modify: `seestar_processor/ui/main_window.py` (`open_image` ~289; toolbar Edit group ~216-217; new `_reset_image`; `_refresh` ~575)
- Test: `tests/ui/test_main_window.py` (icon test in `tests/ui/test_icons.py` is auto-covered)

**Interfaces:**
- Produces: `MainWindow._reset_image()`; `MainWindow._reset_act`; `MainWindow._source_base` / `_source_label`; `load_icon("reset")`.

- [ ] **Step 1: Create the icon and register it**

Create `seestar_processor/assets/icons/reset.svg`:
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 4 3 10 9 10"/><path d="M5.5 15a8 8 0 1 0 1.9-8.3L3 10"/></svg>
```

In `seestar_processor/ui/icons.py`, add `"reset"` to the `ICON_NAMES` tuple (e.g. after `"about"`):
```python
ICON_NAMES = (
    "open", "settings", "save-recipe", "batch", "stack", "haoiii", "palette",
    "undo", "redo", "before-after", "log", "fit", "actual-size", "about", "reset",
)
```

- [ ] **Step 2: Run the icon test to verify the new icon is valid**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_icons.py -q`
Expected: PASS (the parametrized `test_all_named_svgs_exist_and_are_valid_xml` now includes `reset` and finds a valid SVG; `test_load_icon_unknown_raises` still passes).

- [ ] **Step 3: Write the failing main-window tests**

Add to `tests/ui/test_main_window.py` (uses the file's existing `_window` / `_make_fits` helpers):

```python
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
```

- [ ] **Step 4: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q -k reset`
Expected: FAIL with `AttributeError: 'MainWindow' object has no attribute '_reset_act'` / `_source_base`.

- [ ] **Step 5: Stash the source in `open_image`**

In `seestar_processor/ui/main_window.py`, at the top of `open_image` (before `self.project = Project(...)`):
```python
        self._source_base = base
        self._source_label = label
```

- [ ] **Step 6: Add the toolbar action (starts disabled)**

In `_build_toolbar`, in the Edit/compare group right after the Redo action:
```python
        self._reset_act = tb.addAction(load_icon("reset"), "Reset", self._reset_image)
        self._reset_act.setEnabled(False)  # enabled by _refresh once an image is loaded
```

- [ ] **Step 7: Add the `_reset_image` handler**

Add the method (near `open_image` / the other handlers):
```python
    def _reset_image(self) -> None:
        if self.project is None:
            return
        resp = QMessageBox.question(
            self, f"{APP_NAME} — Reset",
            "Discard all edits and start over from the loaded image?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        self.open_image(self._source_base, self._source_label)
```
(`QMessageBox` and `APP_NAME` are already imported.)

- [ ] **Step 8: Gate the action in `_refresh`**

In `_refresh`, alongside the undo/redo enable lines:
```python
        self._reset_act.setEnabled(self.project is not None)
```

- [ ] **Step 9: Run the main-window tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q`
Expected: PASS.

- [ ] **Step 10: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass (rerun the known sharpen flake alone if it trips).

- [ ] **Step 11: Commit**

```bash
git add seestar_processor/assets/icons/reset.svg seestar_processor/ui/icons.py \
        seestar_processor/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat: Reset button restarts editing on the loaded image (with confirm)"
```

---

## Self-Review

- **Spec coverage:** icon+registration (Step 1), source stash (Step 5), toolbar action disabled-until-load (Steps 6+8), confirm handler (Step 7), fresh-Project reset via re-open (Step 7), tests for enabled-state/confirmed/declined (Step 3) — covered.
- **Placeholders:** none.
- **Type consistency:** `_reset_act`, `_reset_image`, `_source_base`, `_source_label`, `load_icon("reset")`, and `ICON_NAMES` entry used identically across production and tests.
- **Confirm testability:** the handler calls `QMessageBox.question` (monkeypatched in tests) — no blocking modal in the suite.
- **Disabled-at-start:** created with `setEnabled(False)` because `_refresh` isn't called at construction; `_refresh` keeps it in sync thereafter.
