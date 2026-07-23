# GUI Message-Areas + Flush Nav + Collapsible Help — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split feedback into three intent-based channels (log / copyable output / prominent warning), pin Back/Next flush so they never move, and make the detailed help a global, sticky, persisted collapsible section.

**Architecture:** All changes are in the Qt UI layer. The right-pane column is reordered so the nav row is the last widget with a stretch above it (warnings/busy grow upward, buttons stay put). The bottom bar becomes a horizontal split of the existing log and a new copyable output box. Message routing moves from scattered `self._status.setText(...)` to three intent-named methods. Help gains a persisted collapse flag in `Settings`.

**Tech Stack:** Python 3.13, PySide6 (Qt Widgets), pytest + pytest-qt (`qtbot`).

## Global Constraints

- Run Python via `.venv/bin/python` (e.g. `.venv/bin/python -m pytest -q`).
- Baseline before Task 1: **697 tests green**. Each task ends green.
- Stage only the named files in each commit — **never `git add -A`** (pre-existing untracked strays exist: icon.png, logo.png, site.zip, nocturne_icon.svg, docs/TESTERS_GUIDE.md).
- Every commit message ends with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- `Settings.help_expanded` default is **True** (novice-first: first-run users are guided).
- The nav row (`Back`/`Next`) must be the **last** widget in `_right_layout`, with an existing `addStretch(1)` above the help/busy/warning cluster, so those areas grow **upward** and the buttons never move. This is the regression the whole plan exists to kill — do not reintroduce any widget below the nav.
- **Do not touch** the per-panel status labels (`_panel.sr_status`, `_panel.fringe_status`, `_panel.neb_status`) or the `help_content` topic data — out of scope.
- The per-step one-liner (`_desc_label` in `step_panels.py`, e.g. "Final targeted tweaks — tap to stack…") stays always-visible; only the detailed `_explainer` block becomes collapsible.

## File Structure

- `nocturne/settings.py` — add `help_expanded` field + load/save (Task 1).
- `nocturne/ui/log_panel.py` — add a thin `OutputPanel` (copyable message box) alongside `LogPanel` (Task 2).
- `nocturne/ui/main_window.py` — bottom-bar split + output routing (Task 2); warning channel + flush nav + `_status` removal (Task 3); collapsible help (Task 4).
- `tests/test_settings.py` — `help_expanded` round-trip (Task 1).
- `tests/ui/test_main_window.py` — new routing/layout/help tests + migrate existing `_status` assertions (Tasks 2–4).

Reference for message routing (which call site → which channel): `docs/superpowers/specs/2026-07-23-gui-message-areas-design.md`.

---

## Task 1: `Settings.help_expanded` persisted flag

**Files:**
- Modify: `nocturne/settings.py:26-46` (dataclass + `load_settings`)
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings.help_expanded: bool` (default `True`); persisted by `save_settings` (via `asdict`) and read by `load_settings` (default `True` when absent from an old file).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_settings.py`:

```python
def test_help_expanded_defaults_true_and_round_trips(tmp_path):
    from nocturne.settings import Settings, save_settings, load_settings
    assert Settings().help_expanded is True                 # novice-first default
    p = tmp_path / "s.json"
    save_settings(Settings(help_expanded=False), str(p))
    assert load_settings(str(p)).help_expanded is False       # survives round-trip

def test_help_expanded_absent_in_old_file_defaults_true(tmp_path):
    import json
    from nocturne.settings import load_settings
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"base_dir": "/x"}))              # pre-feature settings.json
    assert load_settings(str(p)).help_expanded is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings.py -q`
Expected: FAIL (`AttributeError: ... 'help_expanded'` / `TypeError`).

- [ ] **Step 3: Implement**

In `nocturne/settings.py`, add the field to the dataclass (after `astap_path`):

```python
@dataclass
class Settings:
    graxpert_path: str = ""
    rcastro_path: str = ""
    base_dir: str = ""
    denoise_engine: str = "rcastro"
    astap_path: str = ""
    help_expanded: bool = True     # detailed step-help section shown by default (novice-first)
```

And in `load_settings`, add the read (keeps old files working):

```python
    return Settings(
        graxpert_path=data.get("graxpert_path", ""),
        rcastro_path=data.get("rcastro_path", ""),
        base_dir=data.get("base_dir", ""),
        denoise_engine=data.get("denoise_engine", "rcastro"),
        astap_path=data.get("astap_path", ""),
        help_expanded=data.get("help_expanded", True),
    )
```

`save_settings` uses `asdict(s)`, so it serialises the new field with no change.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_settings.py -q`
Expected: PASS. Also run `.venv/bin/python -m pytest tests/test_settings_migration.py -q` — Expected: PASS (no regression).

- [ ] **Step 5: Commit**

```bash
git add nocturne/settings.py tests/test_settings.py
git commit -m "feat(settings): persist help_expanded flag (default on)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Bottom-bar split — copyable Output box beside the Log

**Files:**
- Modify: `nocturne/ui/log_panel.py` (add `OutputPanel`)
- Modify: `nocturne/ui/main_window.py:247-248` (bottom-bar layout), `:1440-1441` (`_toggle_log`), and the OUTPUT-class `_status.setText` call sites
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: existing `LogPanel` (`nocturne/ui/log_panel.py`), `self.log_panel`.
- Produces: `self.output_panel` (an `OutputPanel`, read-only copyable `QPlainTextEdit`); `self._show_output(text: str)` appends a line to it. The bottom bar is a container `self._bottom_bar` holding `[log_panel | output_panel]`; `_toggle_log` toggles `self._bottom_bar`.
- NOTE for Task 3: warning-class messages still go through `self._status` after this task; Task 3 removes `_status`.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_main_window.py`:

```python
def test_output_panel_is_copyable_and_receives_output(qtbot, tmp_path):
    from PySide6.QtWidgets import QPlainTextEdit
    from PySide6.QtCore import Qt
    win = _window(qtbot, tmp_path)
    assert isinstance(win.output_panel, QPlainTextEdit)
    assert win.output_panel.isReadOnly()                     # not editable
    assert win.output_panel.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse  # copyable
    win._show_output("142 stars matched")
    assert "142 stars matched" in win.output_panel.toPlainText()

def test_saved_recipe_message_goes_to_output(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    monkeypatch.setattr("nocturne.ui.main_window.QFileDialog.getSaveFileName",
                        lambda *a, **k: (str(tmp_path / "r.json"), ""))
    win.save_recipe()
    assert "Saved recipe" in win.output_panel.toPlainText()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -k "output_panel or saved_recipe" -q`
Expected: FAIL (`AttributeError: ... 'output_panel'`).

- [ ] **Step 3: Add `OutputPanel`**

In `nocturne/ui/log_panel.py`, add below `LogPanel`:

```python
class OutputPanel(QPlainTextEdit):
    """Copyable box for routine results and progress (distinct from the timestamped
    Log). Read-only but selectable, so the user can copy a status line."""
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(140)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

    def show_line(self, text: str) -> None:
        if not text:
            return
        self.appendPlainText(text)
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())
```

(`QPlainTextEdit` read-only default text-interaction is selectable-by-mouse/keyboard, so copy works.)

- [ ] **Step 4: Split the bottom bar + add `_show_output`**

In `nocturne/ui/main_window.py`, replace the bottom-bar construction (`:247-248`):

```python
        self.log_panel = LogPanel()
        outer.addWidget(self.log_panel)
```

with a horizontal container holding log + output:

```python
        self.log_panel = LogPanel()
        self.output_panel = OutputPanel()
        self._bottom_bar = QWidget()
        bottom = QHBoxLayout(self._bottom_bar)
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addWidget(self.log_panel, 3)      # history gets the wider share
        bottom.addWidget(self.output_panel, 2)   # results/progress, copyable
        outer.addWidget(self._bottom_bar)
```

Update the import at `:36`:

```python
from .log_panel import LogPanel, OutputPanel, format_log_entry
```

Add the method (near `_update_explainer`):

```python
    def _show_output(self, text: str) -> None:
        """Routine results & progress → the copyable Output box."""
        self.output_panel.show_line(text)
```

Point `_toggle_log` (`:1440-1441`) at the container:

```python
    def _toggle_log(self) -> None:
        self._bottom_bar.setVisible(self._log_act.isChecked())
```

- [ ] **Step 5: Route the OUTPUT-class messages to `_show_output`**

Change these `self._status.setText(...)` sites to `self._show_output(...)` (results & progress — see spec routing table). Leave every WARNING-class site on `self._status` for now (Task 3 handles them):

- `:331` `Saved recipe: …`
- `:433` `Plate-solving…`
- `:673` the `msg = getattr(step, "last_message", "")` result (`if msg: self._show_output(msg)`)
- `:1009`, `:1157`, `:1281` `Separating stars…`
- `:1020`, `:1149`, `:1186`, `:1273`, `:1296` star-split result lines

Do **not** change the `self._status.setText("")` clears in this task.

- [ ] **Step 6: Migrate the two existing tests that asserted these on `_status`**

In `tests/ui/test_main_window.py`, update the result-line assertions that now land in output:
- `:173` → `assert "sky balance" in win.output_panel.toPlainText().lower()`
- `:1440` → `assert "colour" in win.output_panel.toPlainText().lower()`

(Leave `:331`/`:507`/`:520`/`:667`/`:844`/`:1468`/`:1480` for Task 3.)

- [ ] **Step 7: Run tests**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -q`
Expected: PASS (the two migrated assertions + new tests green; warning-class tests still pass on `_status`).

- [ ] **Step 8: Commit**

```bash
git add nocturne/ui/log_panel.py nocturne/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat(ui): copyable Output box in a split bottom bar; route results/progress to it

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Warning channel + flush nav; remove `_status`

**Files:**
- Modify: `nocturne/ui/main_window.py` (`:229-244` right-pane cluster, `_set_busy`/busy visuals `:730-765`, all remaining `_status` sites)
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `self._back_btn`, `self._next_btn`, the existing `addStretch(1)` at `:209`, `self._busy_label`.
- Produces: `self._warning` (`QLabel`, red/amber, word-wrap) as the second-to-last widget above the nav; `self._show_warning(text)` and `self._clear_warning()`. `self._status` is **removed**. `self._busy_label` sits just above `self._warning`. Nav row is the **last** item in `_right_layout`.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_main_window.py`:

```python
def test_nav_is_last_widget_and_warning_grows_upward(qtbot, tmp_path):
    from PySide6.QtWidgets import QLabel
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.resize(1200, 800)                                     # ensure the stretch has slack
    win.show(); qtbot.waitExposed(win)
    lay = win._right_layout
    last = lay.itemAt(lay.count() - 1)
    assert last.layout() is not None                          # nav is a QHBoxLayout, the last item
    assert win._next_btn in (last.layout().itemAt(i).widget()
                             for i in range(last.layout().count()))
    y0 = win._next_btn.mapTo(win, win._next_btn.rect().topLeft()).y()
    win._show_warning("Stretch the image first — a long wrapping message " * 3)
    qtbot.wait(10)
    y1 = win._next_btn.mapTo(win, win._next_btn.rect().topLeft()).y()
    assert y1 == y0                                            # buttons never move

def test_warning_channel_and_clear(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._show_warning("Set the ASTAP path in Settings to plate-solve.")
    assert "ASTAP" in win._warning.text()
    win._clear_warning()
    assert win._warning.text() == ""
    assert not hasattr(win, "_status")                        # old surface removed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -k "nav_is_last or warning_channel" -q`
Expected: FAIL (`AttributeError: ... '_warning'` / `_status` still present).

- [ ] **Step 3: Rebuild the right-pane bottom cluster**

In `nocturne/ui/main_window.py`, replace the block that today runs from the `_full_help_link` add through the `_busy_label` add (`:228-244`) so the order becomes **help-link → busy → warning → nav (last)**, and delete `_status`:

```python
        self._right_layout.addWidget(self._full_help_link)
        # peek + busy + warning sit above the nav, inside the stretch's grow-upward
        # zone, so the nav row stays pinned flush to the pane bottom and never moves.
        self._peek_label = QLabel("")                         # transient before/after cue
        self._peek_label.setStyleSheet("color: #9aa0a6;")
        self._right_layout.addWidget(self._peek_label)
        self._busy_label = QLabel("")
        self._busy_label.setStyleSheet("color: #9aa0a6;")     # neutral grey progress
        self._right_layout.addWidget(self._busy_label)
        self._warning = QLabel("")
        self._warning.setObjectName("warning")
        self._warning.setWordWrap(True)
        self._warning.setStyleSheet("color: #ff6b6b;")        # blocking guidance / errors
        self._right_layout.addWidget(self._warning)
        nav = QHBoxLayout()
        self._back_btn = QPushButton("← Back")
        self._next_btn = QPushButton("Next →")
        self._next_btn.setObjectName("nav")
        self._back_btn.clicked.connect(self.go_back)
        self._next_btn.clicked.connect(self.go_next)
        nav.addWidget(self._back_btn)
        nav.addWidget(self._next_btn)
        self._right_layout.addLayout(nav)                     # LAST widget — flush bottom
```

Remove the old `self._back_btn`/`self._next_btn`/`nav` creation that previously sat *above* `_status` (it now lives here), remove the `self._status = QLabel(...)` creation, and remove the old `self._busy_label` creation from its previous spot. Net: `_status` gone; busy + warning + nav in that order; nav last.

Add the methods (near `_show_output`):

```python
    def _show_warning(self, text: str) -> None:
        """Blocking guidance / errors → prominent right-pane label near the buttons."""
        self._warning.setText(text)

    def _clear_warning(self) -> None:
        self._warning.setText("")
```

- [ ] **Step 4: Migrate remaining `self._status` sites**

**CRITICAL SCOPE NOTE:** match `self._status` **exactly**. The per-panel labels
`self._panel.neb_status` / `panel.fringe_status` / `panel.sr_status` — including
all `_FREE_STAR_NOTE` and "Separating stars…" messages — also contain the text
`_status` but are **OUT OF SCOPE; do NOT touch them**. Route by message content,
not line number (numbers shift as you edit). After Task 2, the true `self._status`
sites are exactly: 11 warning-class, 14 empty-string clears, and 1 peek.

Replace every `self._status.setText(...)`:
- Warning-class (non-empty) → `self._show_warning(...)` — these exact messages:
  "Stacking unavailable — install astroalign and sep.",
  "Ha/OIII extract unavailable — install astroalign and sep.",
  "Stretch the image first — Star Spikes works on the …",
  "Stretch the image first — Narrowband works on the …",
  "Narrowband needs a colour image.",
  "Set the ASTAP path in Settings to plate-solve.",
  "Couldn't plate-solve this image — try after Stretch, …",
  "Could not open file: {exc}",
  "Apply Stretch first — Levels works on the stretched image.",
  "{err_prefix}: {exc}",
  "Starless + stars split needs RC-Astro (see Settings)."
- Every `self._status.setText("")` clear → `self._clear_warning()` (all 14 clear sites).
- The peek indicator needs set/clear (not append) semantics → its own tiny label:
  `self._peek_label.setText("Before — press Space to compare" if self._peek_active else "")`.

Confirm with `grep -nE "self\._status" nocturne/ui/main_window.py` returning
**nothing** afterward (the panel `*_status` labels must remain).

- [ ] **Step 5: Migrate the remaining `_status` test assertions**

In `tests/ui/test_main_window.py`, change every remaining `win._status` reference
to `win._warning` (locate by content — Task 2 already migrated the two output
ones to `win.output_panel`):
- the "Stretch" assertion → `win._warning.text()`
- the "open" (could-not-open-file) assertion → `win._warning.text().lower()`
- both "Export failed: disk full" assertions → `win._warning.text()`
- `test_status_cleared_on_navigation`: `win._show_warning("some error")`, then assert `win._warning.text() == ""` after nav.
- the stale-error-cleared-on-export test: `win._show_warning("Export failed: disk full")`, then assert `win._warning.text() == ""`.
- the "colour" (Narrowband-needs-a-colour-image) assertion → `win._warning.text().lower()`.
- the two `!= ""` gate-warning assertions → `win._warning.text()`.

Confirm `grep -nE "win\._status|self\._status" tests/ui/test_main_window.py` returns **nothing**
(only panel `sr_status`/`fringe_status`/`neb_status` references may remain).

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -q`
Expected: PASS (new nav/warning tests + all migrated assertions).

- [ ] **Step 7: Commit**

```bash
git add nocturne/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat(ui): prominent warning channel + flush non-moving nav; drop _status

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Global, sticky, persisted collapsible help

**Files:**
- Modify: `nocturne/ui/main_window.py` (`:213-228` explainer construction, `_update_explainer` `:292-302`)
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `self.settings.help_expanded`, `self._settings_path`, `save_settings`, `self._explainer`, `self._explainer_scroll`, `self._full_help_link`, `help_content`.
- Produces: `self._help_header` (clickable toggle `QLabel`/`QToolButton`) that flips `self.settings.help_expanded`, persists via `save_settings`, and shows/hides the body + `_full_help_link`. `self._apply_help_expanded()` applies current state; called on toggle and in `_update_explainer`.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_main_window.py`:

```python
def test_help_collapse_is_global_sticky_and_persisted(qtbot, tmp_path):
    from nocturne.settings import load_settings
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.go_next()  # a stage with a help topic (crop)
    assert win.settings.help_expanded is True
    assert win._explainer_scroll.isVisible()                 # body shown when expanded
    assert win._full_help_link.isVisible()

    win._toggle_help()                                       # collapse
    assert win.settings.help_expanded is False
    assert not win._explainer_scroll.isVisible()             # body hidden
    assert not win._full_help_link.isVisible()               # Full help hidden when collapsed
    assert load_settings(str(tmp_path / "settings.json")).help_expanded is False  # persisted

    win.go_next()                                            # different step
    assert not win._explainer_scroll.isVisible()             # stays collapsed everywhere

def test_help_starts_collapsed_when_setting_off(qtbot, tmp_path):
    import json
    (tmp_path / "settings.json").write_text(json.dumps({"help_expanded": False}))
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.go_next()
    assert not win._explainer_scroll.isVisible()             # honours persisted state on launch
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -k "help_collapse or help_starts" -q`
Expected: FAIL (`AttributeError: ... '_toggle_help'`).

- [ ] **Step 3: Add the collapsible header + apply/toggle logic**

In `nocturne/ui/main_window.py`, add a clickable header just above the explainer scroll (`:218`, before `self._right_layout.addWidget(self._explainer_scroll)`):

```python
        self._help_header = QLabel("")
        self._help_header.setObjectName("helpHeader")
        self._help_header.setOpenExternalLinks(False)
        self._help_header.linkActivated.connect(lambda _: self._toggle_help())
        self._right_layout.addWidget(self._help_header)
```

Add the methods (near `_update_explainer`):

```python
    def _toggle_help(self) -> None:
        self.settings.help_expanded = not self.settings.help_expanded
        save_settings(self.settings, self._settings_path)
        self._apply_help_expanded()

    def _apply_help_expanded(self) -> None:
        """Show/hide the detailed help body per the global sticky flag. The one-line
        step description (in the panel) is always visible regardless."""
        expanded = self.settings.help_expanded
        has_topic = self._current_topic_id is not None
        self._help_header.setText(
            '<a href="#">How this works ▾</a>' if expanded
            else '<a href="#">How this works ▸</a>')
        self._help_header.setVisible(has_topic)
        self._explainer_scroll.setVisible(has_topic and expanded)
        self._full_help_link.setVisible(has_topic and expanded)
```

- [ ] **Step 4: Route `_update_explainer` through the collapse state**

Replace `_update_explainer` (`:292-302`) so it sets the body text but defers visibility to `_apply_help_expanded`:

```python
    def _update_explainer(self) -> None:
        tid = help_content.stage_topic_id(self.current_stage_id()) if self.project else None
        t = help_content.topic(tid) if tid else None
        self._current_topic_id = tid
        if t is not None:
            self._explainer.setText(f"<b>{t.summary}</b>{t.body}")
        self._apply_help_expanded()
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -k "help" -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nocturne/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat(ui): collapsible step-help — global, sticky, persisted (default expanded)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final: full regression + branch review

- [ ] **Step 1: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, count ≥ 697 + new tests (≈ 705+). If any pre-existing test still references `win._status`, it was missed in Task 2/3 migration — fix and re-run.

- [ ] **Step 2: Manual smoke (headless offscreen)**

Confirm construction + routing without a display:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=/Volumes/Work/Code/Editor .venv/bin/python -c "
from PySide6.QtWidgets import QApplication; app=QApplication([])
from nocturne.ui.main_window import MainWindow
w=MainWindow(settings_path='/tmp/s.json'); w._show_output('142 stars matched'); w._show_warning('Stretch first')
assert '142 stars' in w.output_panel.toPlainText() and 'Stretch' in w._warning.text()
assert not hasattr(w,'_status'); print('smoke ok')
"
```

- [ ] **Step 3: Whole-branch review** (subagent-driven: dispatch the final code-reviewer on the branch diff), then hand to the user for real-data visual validation before merge.

## Self-Review notes

- **Spec coverage:** three channels (Tasks 2–3), flush nav (Task 3), collapsible-sticky-persisted help + hidden Full-help when collapsed (Task 4), successes-not-red (Task 2 output is neutral; Task 3 warning stays red) — all covered. Busy relocation is in Task 3.
- **Ordering:** Task 2 moves outputs off `_status` first; Task 3 then safely deletes `_status`. No task leaves a dangling `_status` reference except the interim (warnings) which Task 3 resolves.
- **Type consistency:** `_show_output`/`_show_warning`/`_clear_warning`, `output_panel`, `_warning`, `_help_header`, `_toggle_help`, `_apply_help_expanded` are named identically across tasks and tests.
