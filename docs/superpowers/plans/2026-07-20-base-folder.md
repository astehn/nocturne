# Configurable Base Open Folder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configurable "Base folder" setting so every file/folder picker starts there instead of the OS default.

**Architecture:** Add `Settings.base_dir` + a `start_dir(base_dir)` helper (returns the base dir if it exists, else `""`). Add a "Default folder" row to the Settings dialog. Route all nine `QFileDialog.get*` call-sites through `start_dir(settings.base_dir)`.

**Tech Stack:** Python, PySide6, pytest.

## Global Constraints

- `start_dir(base_dir: str) -> str`: returns `base_dir` when it is a non-empty, existing directory (`os.path.isdir`), else `""`.
- `Settings.base_dir: str = ""` (default empty). `save_settings` already serialises via `asdict` (auto-includes it); `load_settings` must read `data.get("base_dir", "")`.
- Every picker passes the resolved start dir in the `dir` argument position — `getExistingDirectory(parent, caption, dir)`, `getOpenFileName/getSaveFileName(parent, caption, dir, filter)`.
- No behaviour change when `base_dir` is unset (`""` → OS default, exactly as today).

---

### Task 1: `Settings.base_dir` + `start_dir` helper

**Files:**
- Modify: `nocturne/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings.base_dir: str`; `start_dir(base_dir: str) -> str`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settings.py`:

```python
def test_start_dir_returns_existing_dir(tmp_path):
    from nocturne.settings import start_dir
    assert start_dir(str(tmp_path)) == str(tmp_path)


def test_start_dir_empty_or_missing_returns_blank():
    from nocturne.settings import start_dir
    assert start_dir("") == ""
    assert start_dir("   ") == ""
    assert start_dir("/no/such/path/nocturne") == ""


def test_settings_round_trips_base_dir(tmp_path):
    from nocturne.settings import Settings, save_settings, load_settings
    p = str(tmp_path / "settings.json")
    save_settings(Settings(base_dir=str(tmp_path)), p)
    assert load_settings(p).base_dir == str(tmp_path)


def test_load_settings_defaults_base_dir_blank(tmp_path):
    import json
    from nocturne.settings import load_settings
    p = str(tmp_path / "s.json")
    with open(p, "w") as f:
        json.dump({"graxpert_path": "", "rcastro_path": ""}, f)   # no base_dir key
    assert load_settings(p).base_dir == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_settings.py -q`
Expected: FAIL — `ImportError: cannot import name 'start_dir'` / `Settings` has no `base_dir`.

- [ ] **Step 3: Implement**

In `nocturne/settings.py`, add `base_dir` to the dataclass:

```python
@dataclass
class Settings:
    graxpert_path: str = ""
    rcastro_path: str = ""
    base_dir: str = ""
```

Add `base_dir` to `load_settings`:

```python
    return Settings(
        graxpert_path=data.get("graxpert_path", ""),
        rcastro_path=data.get("rcastro_path", ""),
        base_dir=data.get("base_dir", ""),
    )
```

Add the helper (after `load_settings`/`save_settings`, or near the top — anywhere at module level):

```python
def start_dir(base_dir: str) -> str:
    """The directory a file picker should open in: the configured base folder if
    it is a real existing directory, else '' (the OS default)."""
    base_dir = (base_dir or "").strip()
    return base_dir if base_dir and os.path.isdir(base_dir) else ""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_settings.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/settings.py tests/test_settings.py
git commit -m "feat: Settings.base_dir + start_dir() picker-start helper"
```

---

### Task 2: "Default folder" row in the Settings dialog

**Files:**
- Modify: `nocturne/ui/settings_dialog.py`
- Test: `tests/ui/test_settings_dialog.py`

**Interfaces:**
- Consumes: `Settings.base_dir` (Task 1).
- Produces: `SettingsDialog` with a `self._dir` `QLineEdit`; `result_settings()` returns `base_dir=self._dir.text().strip()`.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_settings_dialog.py`:

```python
def test_settings_dialog_round_trips_base_dir(qtbot, tmp_path):
    from nocturne.settings import Settings
    from nocturne.ui.settings_dialog import SettingsDialog
    d = SettingsDialog(Settings(base_dir=str(tmp_path)))
    qtbot.addWidget(d)
    assert d._dir.text() == str(tmp_path)          # prefilled from settings
    d._dir.setText("/tmp/newbase")
    assert d.result_settings().base_dir == "/tmp/newbase"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_settings_dialog.py::test_settings_dialog_round_trips_base_dir -q`
Expected: FAIL — `SettingsDialog` has no `_dir` attribute.

- [ ] **Step 3: Implement**

In `nocturne/ui/settings_dialog.py`, add a folder-row helper next to `_path_row`:

```python
def _folder_row(edit: QLineEdit) -> QWidget:
    row = QWidget()
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    line.addWidget(edit)
    browse = QPushButton("Browse…")
    browse.clicked.connect(
        lambda: edit.setText(QFileDialog.getExistingDirectory(row) or edit.text())
    )
    line.addWidget(browse)
    return row
```

In `SettingsDialog.__init__`, create the field (next to `self._gx`/`self._rc`):

```python
        self._dir = QLineEdit(settings.base_dir)
```

Add the form row as the FIRST row (before the GraXpert row), so `form.addRow` order becomes:

```python
        form.addRow("Default folder", _folder_row(self._dir))
        form.addRow("GraXpert (required)",
                    _path_row(self._gx, self._test_graxpert, self._gx_result))
```

Update `result_settings` to include the base dir:

```python
    def result_settings(self) -> Settings:
        return Settings(self._gx.text().strip(), self._rc.text().strip(),
                        self._dir.text().strip())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ui/test_settings_dialog.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/settings_dialog.py tests/ui/test_settings_dialog.py
git commit -m "feat: Settings dialog — Default folder row"
```

---

### Task 3: Route all pickers through `start_dir(base_dir)`

**Files:**
- Modify: `nocturne/ui/main_window.py`, `nocturne/ui/haoiii_dialog.py`, `nocturne/ui/stack_dialog.py`, `nocturne/ui/batch_dialog.py`
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `start_dir` (Task 1); `self.settings.base_dir` (main_window) / `self._settings.base_dir` (dialogs).

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_main_window.py`:

```python
def test_open_fits_starts_in_base_dir(qtbot, tmp_path, monkeypatch):
    from nocturne import ui
    import nocturne.ui.main_window as mw
    win = _window(qtbot, tmp_path)
    win.settings = mw.load_settings(str(tmp_path / "s.json"))
    win.settings.base_dir = str(tmp_path)
    seen = {}
    def _fake_open(*a, **k):
        seen["dir"] = a[2]          # 3rd positional arg is the start `dir`
        return ("", "")             # (path, filter) — path "" so nothing opens
    monkeypatch.setattr(mw.QFileDialog, "getOpenFileName", staticmethod(_fake_open))
    win._choose_fits()
    assert seen["dir"] == str(tmp_path)     # opened at the base folder


def test_open_fits_blank_base_dir_uses_os_default(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    win = _window(qtbot, tmp_path)
    win.settings.base_dir = ""
    seen = {}
    def _fake_open(*a, **k):
        seen["dir"] = a[2]          # 3rd positional arg is the start `dir`
        return ("", "")             # (path, filter) — path "" so nothing opens
    monkeypatch.setattr(mw.QFileDialog, "getOpenFileName", staticmethod(_fake_open))
    win._choose_fits()
    assert seen["dir"] == ""
```

(These assert the 3rd positional arg — the `dir` — of `getOpenFileName`. If
`_window`/`_choose_fits` differ, adapt the accessor but keep the assertion on the
`dir` argument.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py::test_open_fits_starts_in_base_dir -q`
Expected: FAIL — the `dir` arg is currently the literal `""`, not the base dir.

- [ ] **Step 3a: main_window.py**

Add `start_dir` to the settings import (the line `from ..settings import graxpert_valid, load_settings, rcastro_valid, resolve_binary, save_settings`):

```python
from ..settings import graxpert_valid, load_settings, rcastro_valid, resolve_binary, save_settings, start_dir
```

Update the four call-sites (replace the empty/placeholder `dir` argument):

- Save Recipe (line ~305):
  ```python
  path, _ = QFileDialog.getSaveFileName(self, "Save Recipe", start_dir(self.settings.base_dir), "Recipe (*.json)")
  ```
- Open FITS (line ~454):
  ```python
  path = QFileDialog.getOpenFileName(self, "Open FITS", start_dir(self.settings.base_dir), "FITS (*.fit *.fits)")[0]
  ```
- Export starless folder (line ~1125 — currently has no `dir` arg, add one):
  ```python
  folder = QFileDialog.getExistingDirectory(self, "Export starless + stars to…", start_dir(self.settings.base_dir))
  ```
- Export save (line ~1146 — keep the suggested filename, but root it at the base dir):
  ```python
  path, _ = QFileDialog.getSaveFileName(
      self, "Export", os.path.join(start_dir(self.settings.base_dir), stem + ext),
      filters, selected
  )
  ```
  (`os.path` is already imported in `main_window.py`; `os.path.join("", x) == x`, so a blank base preserves today's behaviour.)

- [ ] **Step 3b: haoiii_dialog.py**

Add the import at the top: `from ..settings import start_dir`. Update:
- Folder of raw subs (line ~95):
  ```python
  path = QFileDialog.getExistingDirectory(self, "Folder of raw subs", start_dir(self._settings.base_dir))
  ```
- Master FITS (line ~103):
  ```python
  path = QFileDialog.getSaveFileName(self, "Master FITS", start_dir(self._settings.base_dir), "FITS (*.fits)")[0]
  ```

- [ ] **Step 3c: stack_dialog.py**

Add the import: `from ..settings import start_dir`. Update:
- Folder of subs (line ~147):
  ```python
  path = QFileDialog.getExistingDirectory(self, "Folder of subs", start_dir(self._settings.base_dir))
  ```
- Master FITS (line ~153):
  ```python
  path = QFileDialog.getSaveFileName(self, "Master FITS", start_dir(self._settings.base_dir), "FITS (*.fits)")[0]
  ```

- [ ] **Step 3d: batch_dialog.py**

Add the import: `from ..settings import start_dir`. Update:
- Recipe (line ~75):
  ```python
  path = QFileDialog.getOpenFileName(self, "Recipe", start_dir(self._settings.base_dir), "Recipe (*.json)")[0]
  ```
- Input folder (line ~80):
  ```python
  path = QFileDialog.getExistingDirectory(self, "Input folder", start_dir(self._settings.base_dir))
  ```
- Output folder (line ~85):
  ```python
  path = QFileDialog.getExistingDirectory(self, "Output folder", start_dir(self._settings.base_dir))
  ```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nocturne/ui/main_window.py nocturne/ui/haoiii_dialog.py nocturne/ui/stack_dialog.py nocturne/ui/batch_dialog.py tests/ui/test_main_window.py
git commit -m "feat: all file pickers start in the configured base folder"
```

---

### Task 4: Smoke check + backlog

**Files:**
- Update: `TODO.md`

- [ ] **Step 1: Smoke-check in the app**

```bash
.venv/bin/python -m nocturne
```

Settings → set **Default folder** to a real folder, OK. Then click **Open FITS**
and confirm the dialog opens in that folder. Clear the Default folder and confirm
Open FITS reverts to the OS default. Spot-check one dialog picker (Stack or Batch)
opens in the base folder too.

- [ ] **Step 2: Mark the backlog item done**

In `TODO.md`, mark the "Configurable base/default open directory" item `- [x]`
with a "done 2026-07-20" note (fixed base folder for all pickers; last-used memory
deliberately out of scope).

```bash
git add TODO.md
git commit -m "docs: mark configurable base open folder done"
```

---

## Self-Review

**Spec coverage:**
- `Settings.base_dir` + `start_dir` helper → Task 1. ✅
- Settings dialog "Default folder" row + `result_settings` → Task 2. ✅
- All nine pickers routed through `start_dir(base_dir)` → Task 3. ✅
- Tests: `start_dir`, settings round-trip, dialog round-trip, picker `dir` arg → Tasks 1–3. ✅
- Smoke check + TODO → Task 4. ✅

**Placeholder scan:** No TBD/"handle edge cases"/"similar to" — every code step shows the exact edit. ✅

**Type consistency:** `start_dir(base_dir: str) -> str` used identically across settings, dialog, and all four picker files; `Settings(...)` positional order (graxpert, rcastro, base_dir) matches the dataclass field order used in `result_settings`; `self.settings.base_dir` (main_window) vs `self._settings.base_dir` (dialogs) matches each class's stored attribute (verified: haoiii/stack/batch all store `self._settings`). ✅
