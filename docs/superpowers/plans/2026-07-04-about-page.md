# Quirky About Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the plain About message box with a fun, data-driven credits dialog (creator, AI, open-source "crew", works-with tools, empty "Photon Donors" section), opened from a new toolbar button left of the tool-status chips.

**Architecture:** A `contributors.json` data file + a pure `about_html()` in `ui/about.py` that renders fun sectioned HTML from it; a custom `AboutDialog` (styled QDialog with the Nocturne wordmark); a new `about` SVG icon + a toolbar button. Data-driven so adding a library or tester is a JSON edit.

**Tech Stack:** PySide6 (QDialog, QScrollArea), Python 3.11+, JSON.

## Global Constraints

- Package `seestar_processor` (no rename). Venv `.venv`; UI tests headless (`QT_QPA_PLATFORM=offscreen`).
- Data-driven: contributors in `seestar_processor/assets/contributors.json`, read at display time.
- Full quirky/fun tone (tasteful). Creator = "not a developer" orchestrator; AI = "in collaboration with Claude (Anthropic),". Testers = "Photon Donors", ships EMPTY until consent.
- About never crashes on a missing/corrupt JSON (safe minimal fallback).
- Visual/additive only — no processing/behaviour change. Help content stays deferred (not built here).
- Assets live under `seestar_processor/assets/` so they ship with the package.
- Commit after each task. Create the `about-page` branch first (do not start on `main`).

---

## File Structure

- `seestar_processor/assets/contributors.json` — NEW data (creator, ai, built_with, works_with, photon_donors).
- `seestar_processor/ui/about.py` — add `load_contributors()`, rewrite `about_html()` (pure, data-driven); `help_html()` untouched.
- `seestar_processor/ui/about_dialog.py` — NEW `AboutDialog(QDialog)`.
- `seestar_processor/assets/icons/about.svg` — NEW icon.
- `seestar_processor/ui/icons.py` — add `"about"` to `ICON_NAMES`.
- `seestar_processor/ui/main_window.py` — About toolbar button (left of chips); `_show_about` opens `AboutDialog`.
- Tests: `tests/ui/test_about.py`, `tests/ui/test_about_dialog.py`, `tests/ui/test_main_window.py` (add).

---

## Task 0: Branch setup

- [ ] **Step 1: Create the feature branch**

```bash
cd /Volumes/Work/Code/Editor
git checkout -b about-page
git status   # expect: On branch about-page, clean
```

---

## Task 1: contributors.json + data-driven `about_html()`

**Files:**
- Create: `seestar_processor/assets/contributors.json`
- Modify: `seestar_processor/ui/about.py`
- Test: `tests/ui/test_about.py`

**Interfaces:**
- Produces: `load_contributors(path: str | None = None) -> dict`; `about_html(data: dict | None = None) -> str`. `help_html()` unchanged.

- [ ] **Step 1: Create the data file**

Create `seestar_processor/assets/contributors.json`:

```json
{
  "creator": {
    "name": "Andreas Stehn",
    "role": "Creator, chief orchestrator & ideas department — not a developer, and proud of it"
  },
  "ai": "Code wrangled in collaboration with Claude (Anthropic)",
  "built_with": [
    { "name": "PySide6 / Qt", "what": "the whole interface" },
    { "name": "NumPy", "what": "the numeric backbone" },
    { "name": "astropy", "what": "reading & writing FITS" },
    { "name": "SciPy", "what": "filters & maths" },
    { "name": "scikit-image", "what": "image operations" },
    { "name": "astroalign", "what": "lining up the stars" },
    { "name": "SEP", "what": "finding & grading stars" },
    { "name": "colour-demosaicing", "what": "turning Bayer data into colour" },
    { "name": "tifffile", "what": "16-bit TIFFs" },
    { "name": "Pillow", "what": "image loading & saving" }
  ],
  "works_with": [
    { "name": "GraXpert", "what": "background extraction (free)" },
    { "name": "RC-Astro", "what": "BlurX / NoiseX / StarX (optional)" }
  ],
  "photon_donors": []
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/ui/test_about.py`:

```python
import json

from seestar_processor.ui.about import load_contributors, about_html


def test_load_contributors_ships_valid_data():
    data = load_contributors()
    assert isinstance(data, dict)
    assert data["built_with"], "built_with is populated"
    assert data["creator"]["name"]


def test_load_contributors_bad_path_is_safe():
    data = load_contributors("/no/such/file.json")
    assert isinstance(data, dict)                 # safe minimal fallback, no raise
    assert "creator" in data


def test_about_html_has_all_credits():
    html = about_html()
    assert "Andreas" in html
    assert "not a developer" in html.lower()
    assert "Claude (Anthropic)" in html
    for lib in ("PySide6", "NumPy", "astropy", "astroalign", "SEP", "Pillow"):
        assert lib in html
    assert "GraXpert" in html and "RC-Astro" in html
    assert "Photon Donors" in html
    assert "Be the first" in html                 # empty donors -> invite line


def test_about_html_lists_a_donor_when_present(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({
        "creator": {"name": "X", "role": "Y"}, "ai": "Z",
        "built_with": [{"name": "NumPy", "what": "n"}],
        "works_with": [], "photon_donors": ["Jane Nebula"],
    }))
    html = about_html(load_contributors(str(p)))
    assert "Jane Nebula" in html
    assert "Be the first" not in html
```

- [ ] **Step 3: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_about.py -q`
Expected: FAIL (`cannot import name 'load_contributors'`).

- [ ] **Step 4: Implement (surgical edits — do NOT touch `help_html`)**

The current `seestar_processor/ui/about.py` has an imports line, an `about_html()` function,
and a `help_html()` function. Make exactly these edits; leave `help_html()` completely alone.

(a) Replace the existing top import line
`from .. import APP_NAME, APP_TAGLINE, __version__`
with:

```python
from __future__ import annotations

import json
from pathlib import Path

from .. import APP_NAME, APP_TAGLINE, __version__

_DATA = Path(__file__).resolve().parent.parent / "assets" / "contributors.json"

_FALLBACK = {
    "creator": {"name": "Andreas Stehn",
                "role": "Creator, chief orchestrator & ideas department — "
                        "not a developer, and proud of it"},
    "ai": "Code wrangled in collaboration with Claude (Anthropic)",
    "built_with": [],
    "works_with": [],
    "photon_donors": [],
}


def load_contributors(path: str | None = None) -> dict:
    """Read the contributors JSON. Returns a safe minimal dict on any error so
    the About page never crashes."""
    p = Path(path) if path else _DATA
    try:
        data = json.loads(p.read_text())
    except Exception:  # noqa: BLE001 — missing/corrupt file must never crash About
        return dict(_FALLBACK)
    for key, val in _FALLBACK.items():
        data.setdefault(key, val)
    return data


def _rows(items: list) -> str:
    return "".join(f"<li><b>{it['name']}</b> — {it['what']}</li>" for it in items)
```

(If `from __future__ import annotations` is already the first line of the file, don't add a
second one — keep a single copy at the very top.)

(b) Replace the ENTIRE existing `about_html(...)` function with:

```python
def about_html(data: dict | None = None) -> str:
    if data is None:
        data = load_contributors()
    creator = data.get("creator", _FALLBACK["creator"])
    donors = data.get("photon_donors", [])
    donors_html = (
        "".join(f"<li>{name}</li>" for name in donors)
        if donors else
        "<li><i>Be the first to lend your light — share your subs and get "
        "immortalised here!</i></li>"
    )
    return (
        f"<h1>{APP_NAME}</h1>"
        f"<p><i>{APP_TAGLINE}</i><br>Version {__version__}</p>"
        "<h3>✦ Dreamed up &amp; directed by</h3>"
        f"<p><b>{creator['name']}</b> — {creator['role']}</p>"
        "<h3>✦ Code</h3>"
        f"<p>{data.get('ai', _FALLBACK['ai'])}</p>"
        "<h3>✦ The crew</h3>"
        "<p>The open-source legends doing the real heavy lifting:</p>"
        f"<ul>{_rows(data.get('built_with', []))}</ul>"
        "<h3>✦ Plays nicely with</h3>"
        f"<ul>{_rows(data.get('works_with', []))}</ul>"
        "<h3>✦ Photon Donors</h3>"
        "<p>The absolute legends who lent their light for testing:</p>"
        f"<ul>{donors_html}</ul>"
        "<hr>"
        "<p>Made under the stars. 🔭 Not affiliated with ZWO — just a fan with "
        "a Seestar and too many clear-sky ambitions.</p>"
    )
```

(c) Leave the existing `help_html()` function exactly as it is.

- [ ] **Step 5: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_about.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add seestar_processor/assets/contributors.json seestar_processor/ui/about.py tests/ui/test_about.py
git commit -m "feat: data-driven quirky about_html + contributors.json"
```

---

## Task 2: `AboutDialog` + `about` icon

**Files:**
- Create: `seestar_processor/ui/about_dialog.py`
- Create: `seestar_processor/assets/icons/about.svg`
- Modify: `seestar_processor/ui/icons.py` (add `"about"` to `ICON_NAMES`)
- Modify: `seestar_processor/ui/theme.py` (QSS for the dialog)
- Test: `tests/ui/test_about_dialog.py`

**Interfaces:**
- Consumes: `about.about_html`, theme tokens.
- Produces: `AboutDialog(parent=None, html: str | None = None)` with a `body` QLabel and a `wordmark` QLabel.

- [ ] **Step 1: Create the icon**

Create `seestar_processor/assets/icons/about.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16"/><circle cx="12" cy="8" r="0.6" fill="#fff"/></svg>
```

- [ ] **Step 2: Add `about` to ICON_NAMES**

In `seestar_processor/ui/icons.py`, add `"about"` to the `ICON_NAMES` tuple (append it after `"actual-size"`):

```python
ICON_NAMES = (
    "open", "settings", "save-recipe", "batch", "stack", "haoiii", "palette",
    "undo", "redo", "before-after", "log", "fit", "actual-size", "about",
)
```

- [ ] **Step 3: Write the failing test**

Create `tests/ui/test_about_dialog.py`:

```python
import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.about_dialog import AboutDialog  # noqa: E402


def test_about_dialog_shows_wordmark_and_body(qtbot):
    dlg = AboutDialog(html="<h1>Nocturne</h1><p>Andreas — not a developer</p>")
    qtbot.addWidget(dlg)
    assert "Nocturne" in dlg.wordmark.text()
    assert "Andreas" in dlg.body.text()


def test_about_dialog_defaults_to_real_content(qtbot):
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    assert "Photon Donors" in dlg.body.text()   # pulled from about_html()
```

- [ ] **Step 4: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_about_dialog.py -q`
Expected: FAIL (module not found).

- [ ] **Step 5: Implement the dialog**

Create `seestar_processor/ui/about_dialog.py`:

```python
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .. import APP_NAME
from .about import about_html


class AboutDialog(QDialog):
    def __init__(self, parent=None, html: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumSize(520, 560)

        self.wordmark = QLabel(APP_NAME)
        self.wordmark.setObjectName("aboutWordmark")
        self.wordmark.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.body = QLabel(html if html is not None else about_html())
        self.body.setObjectName("aboutBody")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setOpenExternalLinks(False)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.addWidget(self.body)
        inner_lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        root = QVBoxLayout(self)
        root.addWidget(self.wordmark)
        root.addWidget(scroll, 1)
        root.addWidget(close_btn)
```

- [ ] **Step 6: Add dialog QSS**

In `seestar_processor/ui/theme.py`, inside the `build_stylesheet()` returned f-string, append
these rules before the closing `"""` (token names single-braced; there are no literal QSS
braces to double here besides the rule bodies, which DO need doubling):

```css
QLabel#aboutWordmark {{ font-size: 34px; font-weight: 700; color: #ffffff; padding: 10px; }}
QLabel#aboutBody {{ font-size: 13px; color: {TEXT}; padding: 4px 12px; }}
QScrollArea {{ border: none; background: {BG_1}; }}
```

- [ ] **Step 7: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_about_dialog.py tests/ui/test_icons.py -q`
Expected: PASS (the icons test now also validates `about.svg`).

- [ ] **Step 8: Commit**

```bash
git add seestar_processor/ui/about_dialog.py seestar_processor/assets/icons/about.svg seestar_processor/ui/icons.py seestar_processor/ui/theme.py tests/ui/test_about_dialog.py
git commit -m "feat: styled AboutDialog + about icon"
```

---

## Task 3: Toolbar About button + wiring + full suite

**Files:**
- Modify: `seestar_processor/ui/main_window.py`
- Test: `tests/ui/test_main_window.py` (add)

**Interfaces:**
- Consumes: `icons.load_icon`, `about_dialog.AboutDialog`.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_main_window.py`:

```python
def test_toolbar_has_about_button(qtbot, tmp_path):
    from PySide6.QtWidgets import QToolBar
    win = _window(qtbot, tmp_path)
    main = next(b for b in win.findChildren(QToolBar) if b.windowTitle() == "Main")
    about = [a for a in main.actions() if a.text() == "About"]
    assert about and not about[0].icon().isNull()


def test_show_about_opens_dialog(qtbot, tmp_path):
    from seestar_processor.ui.about_dialog import AboutDialog
    win = _window(qtbot, tmp_path)
    dlg = win._make_about_dialog()
    qtbot.addWidget(dlg)
    assert isinstance(dlg, AboutDialog)
    assert "Photon Donors" in dlg.body.text()
```

- [ ] **Step 2: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py::test_toolbar_has_about_button tests/ui/test_main_window.py::test_show_about_opens_dialog -q`
Expected: FAIL (no About action / `_make_about_dialog` missing).

- [ ] **Step 3: Implement**

In `seestar_processor/ui/main_window.py`:

(a) Add the import near the other `.ui` imports:

```python
from .about_dialog import AboutDialog
```

(b) In `_build_toolbar`, insert the About button AFTER `tb.addWidget(spacer)` and BEFORE
`self._tools_label = QLabel("")`:

```python
        tb.addWidget(spacer)
        self._about_btn_act = tb.addAction(load_icon("about"), "About", self._show_about)
        self._tools_label = QLabel("")
```

(c) Replace the existing `_show_about` with a version that opens the dialog, and add a small
factory used by the test:

```python
    def _make_about_dialog(self) -> AboutDialog:
        return AboutDialog(self)

    def _show_about(self) -> None:
        self._make_about_dialog().exec()
```

(`about_html`/`QMessageBox` may now be unused in this module — remove the now-dead
`from .about import about_html, help_html` import only if `help_html`/`about_html` are no
longer referenced; `help_html` is still used by `_show_help`, so keep that import as
`from .about import help_html`.)

- [ ] **Step 4: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q`
Expected: PASS.

- [ ] **Step 5: Full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass. If `test_sharpen_changes_image_and_keeps_shape` fails, it's the known pre-existing flake — rerun it alone to confirm.

- [ ] **Step 6: Commit**

```bash
git add seestar_processor/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat: About toolbar button (left of tool-status chips) opens AboutDialog"
```

---

## Definition of Done

- All tasks committed on `about-page`; full suite green.
- An **About** button sits on the toolbar's right side, left of the GraXpert/RC-Astro chips;
  clicking it opens a dark, fun credits dialog (Nocturne wordmark, creator-as-orchestrator, the
  Claude line, the library "crew", works-with tools, empty-but-inviting Photon Donors).
- Adding a library or a tester is a `contributors.json` edit; About never crashes on a bad file.
- No processing/behaviour change; Help content still deferred.
- After merge: screenshot the About dialog for the README.
- Finish with **superpowers:finishing-a-development-branch**.
