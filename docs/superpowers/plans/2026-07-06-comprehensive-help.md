# Comprehensive Help Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A comprehensive, beginner-friendly Help — a single content module feeding a bottom-anchored inline explainer in each step panel and a browsable Help window (sidebar TOC + content pane).

**Architecture:** `ui/help_content.py` holds all content as structured topics (summary + HTML body) grouped into TOC sections. `ui/help_dialog.py` renders it in a browsable window. `MainWindow` gains a persistent bottom-anchored explainer that shows the current step's topic and a "Full help →" link into the window.

**Tech Stack:** Python 3.13 (`.venv`), PySide6 (Qt: QDialog, QListWidget, QTextBrowser, QLabel, QScrollArea), pytest-qt (headless via `QT_QPA_PLATFORM=offscreen`).

## Global Constraints

- Python interpreter: `.venv/bin/python`; tests: `.venv/bin/pytest` (system python3 is 3.9 — do NOT use it). Run the suite with `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`.
- Content is **HTML in a Python data module** (`ui/help_content.py`) — no markdown/asset files. Renders in both `QLabel` (inline) and `QTextBrowser` (window).
- Tone: **beginner-friendly, concept-teaching**. Every step topic body is structured as `<h4>What it does</h4> … <h4>How to use it</h4> … <h4>Tips</h4>` (the last two optional for pure concept topics). Content must be accurate to the app's real behaviour (see per-topic briefs in Task 1).
- The inline explainer renders the topic's `summary` + full `body` (same text as the window — DRY), bounded/scrollable, pinned near the bottom of the right column above Back/Next.
- External links disabled in rendered HTML (match `AboutDialog`).
- Deferred (do NOT build): a search box; embedded screenshots.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: `help_content.py` — the single content source

**Files:**
- Create: `seestar_processor/ui/help_content.py`
- Test: `tests/ui/test_help_content.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class HelpTopic: id: str; title: str; summary: str; body: str`
  - `@dataclass(frozen=True) class HelpSection: title: str; topic_ids: tuple[str, ...]`
  - `TOPICS: dict[str, HelpTopic]` — keyed by topic id.
  - `SECTIONS: tuple[HelpSection, ...]` — ordered TOC.
  - `topic(topic_id: str) -> HelpTopic | None`
  - `stage_topic_id(stage_id: str) -> str | None`

**Topic ids and stage mapping (`stage_topic_id`):**
`load→"getting-started"`, `crop→"crop"`, `background→"background"`, `color→"color"`,
`deconvolution→"deconvolution"`, `stretch→"stretch"`, `levels→"levels"`,
`saturation→"saturation"`, `noise_sharpen→"noise_sharpen"`,
`local_contrast→"local_contrast"`, `star_reduction→"star_reduction"`,
`enhancements→"enhancements"`, `export→"export"`. Any other stage id → `None`.

**SECTIONS (ordered):**
1. `"Getting Started"` → `("getting-started",)`
2. `"Concepts"` → `("linear-vs-stretched", "dualband", "step-order", "history")`
3. `"The Steps"` → `("crop","background","color","deconvolution","stretch","colourise","levels","saturation","noise_sharpen","local_contrast","star_reduction","enhancements","export")`
4. `"Tools"` → `("tools",)`
5. `"Stacking & Ha/OIII"` → `("stacking","haoiii")`
6. `"Recipes & Batch"` → `("recipes",)`
7. `"Troubleshooting"` → `("troubleshooting",)`

**Per-topic content briefs** (author each `body` accurately to these — grounded in the real app behaviour verified earlier this project):

- **getting-started** — Nocturne finishes stacked Seestar S30 Pro FITS into a shareable image via a guided, one-step-at-a-time flow; every step is non-destructive (undo/redo, jump back). How to begin: open Settings, point to GraXpert (required) and RC-Astro (optional), Test them; open a stacked FITS; walk the steps left-to-right or click any step. Import view = see the image + metadata.
- **linear-vs-stretched** — Raw stacked data is *linear*: values are tiny (~0.003) so it looks black without help; the preview auto-stretches for display only (like PixInsight's STF). The **Stretch** step commits a real stretch so the data matches the preview; the finishing steps (Levels etc.) need real stretched data — Nocturne auto-applies a default Stretch if you skip it.
- **dualband** — The Seestar S30 Pro "LP" filter is a **dualband** narrowband filter passing Ha (red) + OIII (teal). That's why raw frames look red. You can't do SHO (needs 3 filters); HOO/Foraxx-style two-gas palettes are the fit. **Colourise** turns a dualband master into a finished colour image in one press.
- **step-order** — Why order matters: gradient removal and deconvolution belong on *linear* data (before Stretch); tone/colour finishing (Levels, Saturation, Local Contrast, Star Reduction, Enhancements) belong *after* Stretch. Nocturne enforces this so results are predictable.
- **history** — Non-destructive: each step caches its result; Undo/Redo and Before/After are instant; jumping back to a step and re-applying re-runs only from there. Nothing is overwritten until you export.
- **crop** — What it does: trims edges/rotates/flips (stacking edges, framing). How to use: drag the box, pick an aspect ratio, rotate/flip. Tips: crop early so later steps work on final framing.
- **background** — What it does: removes light-pollution gradients (GraXpert) so the sky is even. How to use: light vs strong. Tips: the sky may look *redder* afterwards — that's expected (it removed the blueish light-pollution glow; the next Color step neutralises the residual cast). Needs GraXpert.
- **color** — What it does: automatic background neutralisation + grey-world white balance; optional green removal (SCNR). How to use: just apply; use Remove Green if stars/background look green. Tips: this is what cleans up the colour cast left after Background.
- **deconvolution** — What it does: sharpens stars and recovers fine detail on the *linear* image before stretch (BlurXTerminator; free unsharp fallback). How to use: light/medium/strong. Tips: the Seestar is undersampled, keep it conservative. Best with RC-Astro.
- **stretch** — What it does: the real non-linear stretch, linear→display; reveals faint detail. How to use: aggressiveness slider (mid = matches preview). Tips: for a dualband master use **Colourise** instead for a finished colour result; if you skip Stretch, Nocturne auto-applies a default when you move on.
- **colourise** — What it does: one-press dualband→colour (Foraxx-style): removes stars, colour-maps the starless Ha/OIII, screens the stars back. How to use: press Colourise on the Stretch view; "Advanced…" exposes palette sliders. Tips: needs RC-Astro for best star handling; star brightness/palette are tunable in Advanced.
- **levels** — What it does: fine black/white/gamma against the histogram. How to use: nudge black up to deepen the background, white/gamma for midtones. Tips: works on the *stretched* image — on a still-linear image it would clip to black, so stretch first (Nocturne handles this for you).
- **saturation** — What it does: mute or boost overall colour. How to use: drag left to mute, right to boost, centre = no change. Tips: small boosts look natural; heavy boosts amplify noise.
- **noise_sharpen** — What it does: reduces grain (NoiseXTerminator; free fallback). How to use: light/medium/strong. Tips: denoise *after* stretch; over-doing it smears fine detail.
- **local_contrast** — What it does: boosts mid-scale structure so nebulosity gains depth. How to use: light/medium/strong. Tips: subtle is usually better; strong can look crunchy.
- **star_reduction** — What it does: shrinks stars so nebulosity stands out (StarXTerminator). How to use: light/medium/strong. Tips: needs RC-Astro; pairs well before Enhancements.
- **enhancements** — What it does: targeted finishing — Boost Red (Ha), Boost Cyan (OIII), Boost Blue, Darken Sky, Lighten Sky. How to use: tap a button to nudge; tap again to stack; each tap is individually undoable. Tips: colour boosts only affect their target hue; sky moves only affect the dark background.
- **export** — What it does: save the finished image. How to use: 16-bit TIFF / PNG / FITS, or a starless + stars pair (needs RC-Astro). Tips: TIFF/FITS preserve the most for further editing; you can also export a linear file as a clean base for other tools.
- **tools** — GraXpert (free, **required** — background extraction) and RC-Astro (paid, **optional** — BlurX/NoiseX/StarX). Set paths in Settings and Test them. Every RC-Astro step has a free fallback, so the app works without it (just better with it). Not affiliated with either.
- **stacking** — What it does: build a master from a folder of subs — grades/rejects, registers (handles alt-az field rotation), integrates. How to use: Stack toolbar button → pick folder → grade → stack. Tips: more subs = cleaner master; feed the master straight into the flow.
- **haoiii** — What it does: split a dualband master into Ha and OIII masters for external SHO-style work. How to use: Ha/OIII toolbar button. Tips: optional; the in-app Colourise already does two-gas colour without splitting.
- **recipes** — What it does: save your sequence of steps and apply it to another image or a whole folder (Batch). How to use: Save Recipe; Batch → pick recipe + folder. Tips: great for a night of the same target. (Note: Colourise/Enhancements are not yet captured in recipes.)
- **troubleshooting** — FAQ: *Image went black at Levels* → it needs a stretched image; stretch first (Nocturne now auto-stretches). *Sky went red after Background* → expected; the blue light-pollution was removed, Color neutralises it. *Dualband looks red* → use Colourise. *Tool not detected* → set its path in Settings and Test. *Δ 0.0% in the log* → older builds; the change metric now reflects the visible change.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_help_content.py`:

```python
import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui import help_content as hc  # noqa: E402
from seestar_processor.ui.pipeline import path_stages  # noqa: E402


def test_every_stage_has_a_topic():
    for stage in path_stages():
        tid = hc.stage_topic_id(stage.id)
        assert tid is not None, f"stage {stage.id} has no topic"
        t = hc.topic(tid)
        assert t is not None and t.title and t.summary and t.body


def test_sections_reference_only_real_topics():
    for section in hc.SECTIONS:
        assert section.title
        for tid in section.topic_ids:
            assert tid in hc.TOPICS, f"TOC references missing topic {tid}"


def test_concept_topics_exist():
    for tid in ("getting-started", "linear-vs-stretched", "dualband", "colourise",
                "tools", "stacking", "recipes", "troubleshooting"):
        assert tid in hc.TOPICS


def test_unknown_lookups_are_none():
    assert hc.topic("nope") is None
    assert hc.stage_topic_id("nope") is None


def test_bodies_are_substantial():
    # Guard against stub content: every topic body is real prose, not a stub.
    for t in hc.TOPICS.values():
        assert len(t.body) > 120, f"topic {t.id} body too short"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_help_content.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'seestar_processor.ui.help_content'`.

- [ ] **Step 3: Write the module**

Create `seestar_processor/ui/help_content.py` with the data model, `topic`, `stage_topic_id`, `SECTIONS`, and `TOPICS`. Author every topic's `body` as beginner-friendly HTML following the per-topic briefs above and the `What it does / How to use it / Tips` structure. Skeleton (fill every topic — no stubs):

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HelpTopic:
    id: str
    title: str
    summary: str
    body: str


@dataclass(frozen=True)
class HelpSection:
    title: str
    topic_ids: tuple[str, ...]


_STAGE_TO_TOPIC = {
    "load": "getting-started", "crop": "crop", "background": "background",
    "color": "color", "deconvolution": "deconvolution", "stretch": "stretch",
    "levels": "levels", "saturation": "saturation", "noise_sharpen": "noise_sharpen",
    "local_contrast": "local_contrast", "star_reduction": "star_reduction",
    "enhancements": "enhancements", "export": "export",
}


def stage_topic_id(stage_id: str) -> str | None:
    return _STAGE_TO_TOPIC.get(stage_id)


def topic(topic_id: str) -> "HelpTopic | None":
    return TOPICS.get(topic_id)


def _t(id, title, summary, body) -> HelpTopic:
    return HelpTopic(id, title, summary, body)


TOPICS: dict[str, HelpTopic] = {t.id: t for t in (
    _t("getting-started", "Getting started",
       "Finish a stacked Seestar FITS in a guided, non-destructive flow.",
       "<h4>What it does</h4><p>…</p><h4>How to use it</h4><p>…</p>"),
    # … every topic id listed in SECTIONS, authored to its brief …
)}


SECTIONS: tuple[HelpSection, ...] = (
    HelpSection("Getting Started", ("getting-started",)),
    HelpSection("Concepts", ("linear-vs-stretched", "dualband", "step-order", "history")),
    HelpSection("The Steps", ("crop", "background", "color", "deconvolution", "stretch",
                              "colourise", "levels", "saturation", "noise_sharpen",
                              "local_contrast", "star_reduction", "enhancements", "export")),
    HelpSection("Tools", ("tools",)),
    HelpSection("Stacking & Ha/OIII", ("stacking", "haoiii")),
    HelpSection("Recipes & Batch", ("recipes",)),
    HelpSection("Troubleshooting", ("troubleshooting",)),
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_help_content.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/help_content.py tests/ui/test_help_content.py
git commit -m "feat: help_content — single source of comprehensive help topics

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `help_dialog.py` — the browsable Help window

**Files:**
- Create: `seestar_processor/ui/help_dialog.py`
- Test: `tests/ui/test_help_dialog.py`

**Interfaces:**
- Consumes: `help_content.SECTIONS`, `help_content.TOPICS`, `help_content.topic` (Task 1).
- Produces: `class HelpDialog(QDialog)` with `show_topic(self, topic_id: str) -> None` and an exposed `self.viewer` (`QTextBrowser`) and `self.nav` (`QListWidget`) for tests.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_help_dialog.py`:

```python
import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.help_dialog import HelpDialog  # noqa: E402


def test_help_dialog_lists_sections_and_topics(qtbot):
    dlg = HelpDialog()
    qtbot.addWidget(dlg)
    # Section headers + topics are all present as rows.
    labels = [dlg.nav.item(i).text() for i in range(dlg.nav.count())]
    assert any("Concepts" in x for x in labels)
    assert any("Stretch" in x for x in labels)


def test_show_topic_renders_body(qtbot):
    dlg = HelpDialog()
    qtbot.addWidget(dlg)
    dlg.show_topic("background")
    from seestar_processor.ui import help_content as hc
    assert hc.TOPICS["background"].title in dlg.viewer.toPlainText()


def test_show_unknown_topic_does_not_raise(qtbot):
    dlg = HelpDialog()
    qtbot.addWidget(dlg)
    dlg.show_topic("nope")   # no exception
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_help_dialog.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'seestar_processor.ui.help_dialog'`.

- [ ] **Step 3: Write the dialog**

Create `seestar_processor/ui/help_dialog.py`:

```python
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
    QTextBrowser, QVBoxLayout,
)

from .. import APP_NAME
from . import help_content as hc

_TOPIC_ROLE = Qt.ItemDataRole.UserRole


class HelpDialog(QDialog):
    """Browsable help: section/topic list on the left, content on the right."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Help")
        self.setMinimumSize(760, 560)

        self.nav = QListWidget()
        self.nav.setMaximumWidth(240)
        for section in hc.SECTIONS:
            header = QListWidgetItem(section.title)
            header.setFlags(Qt.ItemFlag.NoItemFlags)   # non-selectable header
            self.nav.addItem(header)
            for tid in section.topic_ids:
                t = hc.topic(tid)
                if t is None:
                    continue
                item = QListWidgetItem(f"   {t.title}")
                item.setData(_TOPIC_ROLE, tid)
                self.nav.addItem(item)
        self.nav.currentItemChanged.connect(self._on_row)

        self.viewer = QTextBrowser()
        self.viewer.setOpenExternalLinks(False)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        top = QHBoxLayout()
        top.addWidget(self.nav)
        top.addWidget(self.viewer, 1)
        root = QVBoxLayout(self)
        root.addLayout(top, 1)
        root.addWidget(close_btn)

        self.show_topic("getting-started")

    def _on_row(self, current, _prev=None) -> None:
        if current is None:
            return
        tid = current.data(_TOPIC_ROLE)
        if tid:
            self._render(hc.topic(tid))

    def show_topic(self, topic_id: str) -> None:
        t = hc.topic(topic_id)
        if t is None:
            return
        # select the matching row (blocks signal to avoid double render)
        for i in range(self.nav.count()):
            if self.nav.item(i).data(_TOPIC_ROLE) == topic_id:
                self.nav.blockSignals(True)
                self.nav.setCurrentRow(i)
                self.nav.blockSignals(False)
                break
        self._render(t)

    def _render(self, t) -> None:
        if t is None:
            return
        self.viewer.setHtml(f"<h2>{t.title}</h2>{t.body}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_help_dialog.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/help_dialog.py tests/ui/test_help_dialog.py
git commit -m "feat: HelpDialog — browsable help window (sidebar TOC + content pane)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Inline bottom explainer + wiring; retire old help

**Files:**
- Modify: `seestar_processor/ui/main_window.py` (right column ~122-139; `_build_menu`/`_show_help` ~166-171; `_rebuild_panel` ~688)
- Modify: `seestar_processor/ui/step_panels.py` (remove `_DESCRIPTIONS` + its use ~23-31, 116-118)
- Modify: `seestar_processor/ui/about.py` (remove `help_html`)
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `help_content.stage_topic_id`, `help_content.topic` (Task 1); `HelpDialog` (Task 2).
- Produces: `MainWindow._update_explainer() -> None`; `MainWindow._open_help(topic_id: str | None = None) -> HelpDialog`; a persistent `self._explainer` (`QLabel` in a bounded `QScrollArea`) and `self._full_help_link` (`QLabel` with a clickable link) in the right column.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_main_window.py`:

```python
def test_explainer_shows_current_step_help(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("background")
    from seestar_processor.ui import help_content as hc
    assert hc.TOPICS["background"].summary in win._explainer.text()


def test_open_help_shows_requested_topic(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    dlg = win._open_help("stretch")
    qtbot.addWidget(dlg)
    from seestar_processor.ui import help_content as hc
    assert hc.TOPICS["stretch"].title in dlg.viewer.toPlainText()
    dlg.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q -k "explainer or open_help"`
Expected: FAIL with `AttributeError: 'MainWindow' object has no attribute '_explainer'`.

- [ ] **Step 3a: Add imports**

In `seestar_processor/ui/main_window.py` add:

```python
from PySide6.QtWidgets import QScrollArea   # add to the existing QtWidgets import group
from . import help_content
from .help_dialog import HelpDialog
```

(Remove the now-unused `from .about import help_html` — keep `AboutDialog`.)

- [ ] **Step 3b: Add the explainer to the right column**

In `__init__`, after `self._right_layout.addStretch(1)` (line ~130) and BEFORE the `nav` row, insert a bounded, bottom-anchored explainer:

```python
        self._explainer = QLabel("")
        self._explainer.setObjectName("stepExplainer")
        self._explainer.setWordWrap(True)
        self._explainer.setTextFormat(Qt.TextFormat.RichText)
        self._explainer.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._explainer_scroll = QScrollArea()
        self._explainer_scroll.setWidgetResizable(True)
        self._explainer_scroll.setWidget(self._explainer)
        self._explainer_scroll.setMaximumHeight(240)   # never crowd the nav row
        self._right_layout.addWidget(self._explainer_scroll)
        self._full_help_link = QLabel('<a href="#">Full help →</a>')
        self._full_help_link.setOpenExternalLinks(False)
        self._full_help_link.linkActivated.connect(lambda _: self._open_help(self._current_topic_id))
        self._right_layout.addWidget(self._full_help_link)
        self._current_topic_id = None
```

- [ ] **Step 3c: Add `_update_explainer` and `_open_help`, and call from `_rebuild_panel`**

```python
    def _update_explainer(self) -> None:
        tid = help_content.stage_topic_id(self.current_stage_id()) if self.project else None
        t = help_content.topic(tid) if tid else None
        self._current_topic_id = tid
        if t is None:
            self._explainer_scroll.setVisible(False)
            self._full_help_link.setVisible(False)
            return
        self._explainer.setText(f"<b>{t.summary}</b>{t.body}")
        self._explainer_scroll.setVisible(True)
        self._full_help_link.setVisible(True)

    def _open_help(self, topic_id: str | None = None) -> HelpDialog:
        dlg = HelpDialog(self)
        if topic_id:
            dlg.show_topic(topic_id)
        dlg.show()
        return dlg
```

In `_rebuild_panel` (end of the method, after the panel is swapped in), add:

```python
        self._update_explainer()
```

- [ ] **Step 3d: Point the Help menu at the new window**

Change `_show_help`:

```python
    def _show_help(self) -> None:
        self._open_help("getting-started")
```

(Remove the `QMessageBox` help path; `QMessageBox` may still be used elsewhere — leave its import.)

- [ ] **Step 3e: Remove the superseded per-panel descriptions**

In `seestar_processor/ui/step_panels.py`, delete the `_DESCRIPTIONS` dict (lines ~23-31, the process-stage one-liners) and the three lines in the `process` branch that use it:

```python
        desc = _DESCRIPTIONS.get(stage.id)
        if desc:
            lay.addWidget(_desc_label(desc))
```

Keep `_desc_label` (still used elsewhere) and `_GATE_NOTE`/`note` (tool-gating message stays by the controls).

- [ ] **Step 3f: Remove `help_html` from `about.py`**

Delete the `help_html()` function from `seestar_processor/ui/about.py` (its only caller was `_show_help`, now changed). Confirm with `grep -rn help_html seestar_processor tests` returning nothing.

- [ ] **Step 4: Run the new tests, then the full main-window file**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py tests/ui/test_step_panels.py -q`
Expected: PASS — new explainer/help tests plus existing tests green (any test asserting an old `_DESCRIPTIONS` string must be updated to the new explainer; if a `test_help` referencing `help_html` exists, update it to `HelpDialog`).

- [ ] **Step 5: Full suite + commit**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: PASS (all green).

```bash
git add seestar_processor/ui/main_window.py seestar_processor/ui/step_panels.py seestar_processor/ui/about.py tests/ui/test_main_window.py
git commit -m "feat: bottom-anchored step explainer + browsable Help window wiring

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Single content source (`help_content.py`, topics + sections + lookups) → Task 1. ✅
- Beginner-friendly, concept-teaching bodies (What it does / How to use / Tips) → Task 1 per-topic briefs. ✅
- Browsable Help window (sidebar TOC + content pane, `show_topic`) → Task 2. ✅
- Bottom-anchored inline explainer (summary + full body, bounded/scrollable, above nav) → Task 3 Step 3b. ✅
- "Full help →" opens the window at the current topic → Task 3 (`_full_help_link`, `_open_help`). ✅
- Help menu opens the window at Getting Started → Task 3 Step 3d. ✅
- Content is HTML in a Python module; no markdown/assets → Task 1. ✅
- External links disabled → Task 2 (`setOpenExternalLinks(False)`). ✅
- Retire stale help (`help_html`) and superseded `_DESCRIPTIONS` → Task 3 Steps 3e/3f. ✅
- Deferred (no search, no screenshots) → not built. ✅
- TOC scope (Getting Started, Concepts, Steps, Tools, Stacking & Ha/OIII, Recipes & Batch, Troubleshooting) → Task 1 SECTIONS. ✅

**Placeholder scan:** The Task 1 module skeleton shows the pattern with `…` because the deliverable IS the authored prose (guided by the complete per-topic briefs above); every other code block is complete. No vague "add X" instructions. ✅

**Type consistency:** `HelpTopic(id,title,summary,body)`, `HelpSection(title,topic_ids)`, `topic()`, `stage_topic_id()`, `SECTIONS`, `TOPICS` identical across Tasks 1–3. `HelpDialog.show_topic`, `.viewer`, `.nav` consistent between Task 2 and its tests. `_update_explainer`, `_open_help`, `_explainer`, `_full_help_link`, `_current_topic_id` consistent in Task 3. ✅
