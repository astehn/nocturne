# Comprehensive Help — Design

**Date:** 2026-07-06
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — building under standing authorization.

## Motivation

Nocturne is approaching a release version, but its Help is a single stale "Quick help"
blob (`help_html()` in `ui/about.py`) shown in a `QMessageBox` — it still lists steps that
no longer exist ("Destination", "Noise & Sharpen") and omits Deconvolution, Colourise,
Local Contrast, Star Reduction, Enhancements, Stacking, Ha/OIII, Recipes and Batch. New
Seestar owners are often new to astro post-processing and need help that **teaches the
concepts** (what "linear vs stretched" means, dualband/narrowband, why order matters) as
well as how to use each feature.

## Decisions (from discussion)

- **Audience:** beginner-friendly and concept-teaching, not just a dry reference.
- **Two consumers, one content source.** A single content module feeds (a) a richer inline
  explainer in each step panel and (b) a full browsable Help window — so each explanation is
  authored once and the two can never drift apart.
- **Inline explainer is bottom-anchored** in the right column (just above Back/Next), a
  persistent region owned by the column and refreshed on navigation — NOT baked into each
  panel builder. So adding more toggles to a view later grows the controls downward while
  the explanation stays in a consistent spot. Height-bounded (scrolls internally) so it
  never pushes the nav buttons off-screen.
- **Help window** is a browsable dialog: sidebar section list + content pane, opened from
  the Help menu and from the inline "Full help →" link (jumps to the current topic).
- **Content is HTML in a Python data module** (not markdown/asset files): renders identically
  in a panel `QLabel` and the window's `QTextBrowser`, needs no new asset/rendering
  machinery, matches how `about.py` already works, and is easily testable.
- **Deferred (YAGNI for v1):** a search box, and embedded screenshots. Text-first ships
  faster and is far easier to keep accurate.

## Content scope (table of contents)

```
Getting Started        install GraXpert (required) / RC-Astro (optional); open a FITS; the guided flow
Concepts               Linear vs stretched · Dualband/narrowband (Ha/OIII) · Why step order matters · Non-destructive history
The Steps              Crop · Background · Color · Deconvolution · Stretch · Colourise · Levels ·
                       Saturation · Noise Reduction · Local Contrast · Star Reduction · Enhancements · Export
Tools                  GraXpert (required) & RC-Astro (optional) + free fallbacks
Stacking & Ha/OIII     build a master from subs; extract Ha/OIII
Recipes & Batch        save steps; apply to a folder
Troubleshooting / FAQ  "image went black" · red shift after Background · dualband looks red · tools not detected
```

## Architecture / changes

### `ui/help_content.py` (new) — the single content source

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class HelpTopic:
    id: str          # stage id (e.g. "background") or concept id (e.g. "linear-vs-stretched")
    title: str       # "Background extraction"
    summary: str     # one line (the current under-controls blurb)
    body: str        # comprehensive HTML: What it does / How to use it / Tips

@dataclass(frozen=True)
class HelpSection:
    title: str               # "The Steps"
    topic_ids: tuple[str, ...]

TOPICS: dict[str, HelpTopic] = { ... }         # every topic, keyed by id
SECTIONS: tuple[HelpSection, ...] = ( ... )     # ordered TOC grouping (see scope above)

def topic(topic_id: str) -> HelpTopic | None:   # safe lookup, None if missing
    return TOPICS.get(topic_id)

def stage_topic_id(stage_id: str) -> str | None:
    """The help topic id for a pipeline stage id, or None if the stage has no
    topic. Most map 1:1; 'load' -> 'getting-started'."""
```

Every pipeline stage id that appears in the panel has a matching topic whose `body` is a
comprehensive, beginner-friendly explanation structured as **What it does / How to use it /
Tips** (HTML `<h4>`/`<p>`/`<ul>`). Concept topics (linear-vs-stretched, dualband, etc.) and
feature topics (stacking, recipes, tools, troubleshooting) have no stage but appear in the
TOC.

### `ui/help_dialog.py` (new) — the browsable Help window

`HelpDialog(QDialog)`, modelled on `AboutDialog`:
- Left: a `QListWidget` (or tree) listing sections and their topics from `SECTIONS`.
- Right: a `QTextBrowser` rendering the selected topic's `title` + `body`.
- Selecting a list row shows that topic; `show_topic(topic_id)` selects and displays a
  topic programmatically (used by "Full help →").
- A Close button. Sized like `AboutDialog` (resizable, generous default).

```python
class HelpDialog(QDialog):
    def __init__(self, parent=None) -> None: ...
    def show_topic(self, topic_id: str) -> None:
        """Select the topic in the sidebar and render it; no-op for unknown ids."""
```

### `ui/step_panels.py` — feed the inline explainer from the content source

- Remove the scattered short `_DESCRIPTIONS` one-liners and the per-panel `_desc_label(desc)`
  calls for process stages (superseded by the unified bottom explainer). Panels keep only
  their controls (and the existing tool-gating `note`).
- The gating note (`_GATE_NOTE`, "Needs GraXpert…") stays in the panel by the controls.

### `ui/main_window.py` — the persistent bottom explainer + wiring

- Add a persistent **explainer widget** to the right column, positioned after the panel's
  stretch and directly above the Back/Next row: a bounded (max-height, scrollable) area
  rendering the current topic's `summary` + full `body` (same text as the window — DRY, no
  separate excerpt to maintain; the area scrolls internally if the body is long), plus a
  **"Full help →"** link. The Help *window's* added value is browsing every topic and the
  concept sections, not a longer version of the same topic.
- New `_update_explainer()` called from `_rebuild_panel()`/navigation: looks up
  `stage_topic_id(current_stage_id())` → `topic(id)`; if found, fills the explainer and
  shows the "Full help →" link (wired to open the Help window at that topic); if none, hides
  the explainer.
- `_show_help()` now opens the `HelpDialog` (browsable window) instead of the
  `QMessageBox`; the Help menu action is unchanged. "Full help →" calls
  `self._open_help(topic_id)`, which constructs the dialog and calls `show_topic`.
- `help_html()` in `about.py` is removed (its only caller was `_show_help`).

### Interfaces (summary)

- `help_content.topic(id) -> HelpTopic | None`, `stage_topic_id(stage_id) -> str | None`,
  `TOPICS`, `SECTIONS`.
- `HelpDialog(parent).show_topic(id)`.
- `MainWindow._update_explainer()`, `MainWindow._open_help(topic_id: str | None = None)`.

## Data flow

Navigate to a step → `_rebuild_panel()` builds the controls and calls `_update_explainer()`
→ the explainer looks up the step's topic and shows its summary + body excerpt at the bottom
of the column → clicking "Full help →" opens `HelpDialog` scrolled to that topic. Opening
Help from the menu opens the same window at Getting Started. All text comes from
`help_content`.

## Error handling

- `topic()` / `stage_topic_id()` return `None` for unknown ids; the explainer simply hides
  and `show_topic` is a no-op — no crash if a stage lacks a topic.
- `QTextBrowser`/`QLabel` render trusted in-repo HTML only; external links are disabled
  (matching `AboutDialog`).
- The Help window is non-modal-safe and reusable; opening it twice reuses/creates cleanly.

## Testing

- **help_content** (`tests/ui/test_help_content.py`):
  - Every pipeline stage that has a panel maps to a topic: for each id in `PROCESSING_ORDER`
    plus `"crop"`, `"enhancements"`, `"export"`, `stage_topic_id(id)` is not None and
    `topic(stage_topic_id(id))` exists with non-empty `title`, `summary`, `body`.
  - `SECTIONS` reference only ids present in `TOPICS` (no dangling TOC entries).
  - The concept topics exist: `linear-vs-stretched`, `dualband`, and `getting-started` are
    in `TOPICS`.
  - `topic("nope")` is None; `stage_topic_id("nope")` is None.
- **help_dialog** (`tests/ui/test_help_dialog.py`):
  - `HelpDialog()` constructs; its sidebar lists at least one row per section.
  - `show_topic("background")` selects the row and the content pane text contains the
    topic's title.
  - `show_topic("nope")` does not raise.
- **main_window** (`tests/ui/test_main_window.py`):
  - Navigating to a step with a topic populates the explainer (its text contains the
    topic summary); navigating to a step without one hides it.
  - `_open_help("stretch")` returns/opens a `HelpDialog` showing the Stretch topic
    (assert via the dialog's content, constructed with the test's no-exec path).
- Full suite green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`).

## Verification (by eye)

Open a FITS; each step now shows a clear "What it does / How to use / Tips" explanation
pinned at the bottom of the right column, consistent across every view. Click "Full help →"
and the Help window opens to that step; the sidebar browses Getting Started, Concepts, every
step, Tools, Stacking, Recipes, and Troubleshooting. Help ▸ Help… opens the same window at
Getting Started. Adding more controls to a panel does not move the explanation.
