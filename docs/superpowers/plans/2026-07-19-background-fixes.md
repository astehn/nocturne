# Background step — audit fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Preselect each process step's recommended default (fixing Background's "off" no-op), and add beginner-clarity copy to the Background panel. UI only.

**Architecture:** `build_panel` gains an `option_default` param that preselects the process combo; `MainWindow._rebuild_panel` passes each process step's `default_option()`. The Background panel gets a plain-language explainer + a Before/After cue.

**Tech Stack:** Python, PySide6, pytest-qt.

## Global Constraints

- UI only — no change to `steps/*`, `core/*`, or apply logic.
- Source the default from the step's `default_option()` (DRY) — do not hard-code per-stage defaults in the panel.
- Run tests via `.venv/bin/python -m pytest`. Reuse `_stage(...)`/`qapp` in `tests/ui/test_step_panels.py` and the window-test pattern in `tests/ui/test_main_window.py`.

---

### Task 1: Preselect the recommended default + Background clarity copy

**Files:** Modify `nocturne/ui/step_panels.py`, `nocturne/ui/main_window.py`. Test: `tests/ui/test_step_panels.py`, `tests/ui/test_main_window.py`.

**Interfaces:** `build_panel(..., option_default: str | None = None)` — when set and the stage is process-kind, the combo is preselected to it.

- [ ] **Step 1: Failing tests.**

`tests/ui/test_step_panels.py`:
```python
def test_process_panel_preselects_default_option(qapp):
    w = build_panel(_stage("background"), option_default="light")
    assert w.option_box.currentText() == "light"   # not "off"


def test_background_panel_explains_gradient(qapp):
    from PySide6.QtWidgets import QLabel
    w = build_panel(_stage("background"))
    texts = " ".join(l.text().lower() for l in w.findChildren(QLabel))
    assert "gradient" in texts and "before/after" in texts
```

`tests/ui/test_main_window.py` (reuse the window+load pattern; navigate to background):
```python
def test_background_stage_defaults_to_light(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("background")
    assert win._panel.option_box.currentText() == "light"
```
(Use whatever `_window`/`_make_fits`/`_bordered_window` helpers the file already provides — match the existing background/crop window tests.)

- [ ] **Step 2: Confirm fail** — `.venv/bin/python -m pytest tests/ui/test_step_panels.py tests/ui/test_main_window.py -q`.

- [ ] **Step 3: Implement `build_panel` (`step_panels.py`).**
  - Add `option_default: str | None = None` to the signature (keyword-only, alongside the other `on_*`/`*_enabled` params).
  - In the `stage.kind == "process"` branch, immediately after `box.addItems(_PROCESS_OPTIONS[stage.id])`, add:
    ```python
    if option_default:
        box.setCurrentText(option_default)
    ```
    (Place before the final `_update_enabled()` call so the gate/enabled state reflects the default.)
  - At the very top of the `process` branch (right after `elif stage.kind == "process":`), add a Background-only explainer:
    ```python
    if stage.id == "background":
        lay.addWidget(_desc_label(
            "A gradient is uneven sky-glow — brighter toward one edge or corner. "
            "Light suits most images; use Strong when it's heavy. After applying, "
            "use Before/After (toolbar) to check the result."))
    ```

- [ ] **Step 4: Wire `main_window._rebuild_panel`.** In the `build_panel(...)` call, add:
    ```python
    option_default=(self._step_for(stage.id).default_option()
                    if stage.kind == "process" else None),
    ```
  (`_step_for` already exists and returns the step for a stage id; `default_option()` is defined on each process step.)

- [ ] **Step 5: Confirm pass** — `.venv/bin/python -m pytest tests/ui/test_step_panels.py tests/ui/test_main_window.py -q`.

- [ ] **Step 6: Full suite + commit** — `.venv/bin/python -m pytest tests/ -q`; then
  `git add nocturne/ui/step_panels.py nocturne/ui/main_window.py tests/ui/ && git commit -m "fix(background): preselect recommended default (no more 'off' no-op); explain gradient + Before/After"`.
