# Visual Polish (Tier 1) — Design

**Date:** 2026-07-03
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — ready for implementation planning

## Motivation

The app is fully functional but looks bland: a single-accent dark theme, a plain-text stepper
where completed steps only get a grey `✓` prefix, text-only toolbar buttons, and unstyled
Fusion sliders. For recruiting testers and "selling" the app, polished, screenshot-worthy UI
matters as much as the feature list. This is a **purely visual** pass — no processing-engine
or behavioural changes. Tier 1 (this spec) covers the highest impact-per-effort items;
Tiers 2–3 are documented as a roadmap but NOT built here.

## Scope

**In scope (Tier 1)**
1. A semantic **colour-token system** in `theme.py`, with the QSS rebuilt from tokens.
2. **Coloured step states** in the stepper (done / current / upcoming / locked) via a custom
   item delegate driven by a pure `step_state()` function.
3. **Toolbar icons + grouping** — hand-authored monochrome SVGs, a tinting icon loader,
   icon-above-label toolbar, separators between logical groups.
4. **Styled sliders + dialog polish** (checkboxes, radios, progress bars, table headers,
   scrollbars) — pure QSS from the tokens.

**Out of scope (deferred — see Roadmap)**
- All Tier 2 and Tier 3 items below. No canvas/panel/histogram/branding changes now.
- No changes to processing, pipeline logic, or dialog behaviour.

## Global constraints

- Package `seestar_processor` (no rename). Venv `.venv`; UI tests headless (`QT_QPA_PLATFORM=offscreen`).
- Visual only: no behavioural changes; existing widget wiring and tests for behaviour stay green
  (the stepper's text-assertion tests get updated to match the new rendering).
- Icons are original hand-authored SVGs (no third-party licensing).

## Architecture

```
seestar_processor/
  ui/theme.py       # tokens (BG_*, ACCENT, SUCCESS, WARNING, DANGER, TEXT*) + QSS built from them
  ui/stepper.py     # step_state() pure fn + StepDelegate (QStyledItemDelegate) painting badges
  ui/icons.py       # NEW: load_icon(name, color) -> QIcon (render SVG, tint via source-in composite)
  ui/main_window.py # toolbar: set icons, icon-above-label, group separators
  assets/icons/*.svg # NEW: monochrome line icons
```

## 1. Colour tokens (`theme.py`)

Named tokens defined once, QSS built from them:

```python
BG_0   = "#16171a"   # deepest (canvas)
BG_1   = "#1e1f22"   # window
BG_2   = "#26282c"   # panels / toolbar
BG_3   = "#2f3237"   # inputs / raised
BORDER = "#3c4046"
ACCENT = "#2dd4bf"   # teal — current step, primary actions, slider fill
ACCENT_HI = "#34e3cd"
SUCCESS = "#3fb950"  # green — done steps, valid tool
WARNING = "#e3b341"  # amber — fallback notices
DANGER  = "#f85149"  # red — errors, invalid tool
TEXT      = "#e6e6e6"
TEXT_DIM  = "#8a9099"
TEXT_FAINT = "#5e636b"
```

`apply_dark_theme(app)` stays the entry point; the QSS is a template built from these tokens.
Refinements: consistent 8px radius, slightly larger base font (14px), a bit more padding/line
height. `ACCENT` remains the existing teal so nothing else shifts unexpectedly.

## 2. Coloured step states (`stepper.py`)

Replace the `✓ `-prefix `_label` with a delegate. The state decision is a **pure function**
(unit-tested); the delegate only paints:

```python
def step_state(index, current_index, done_ids_indexes, enabled) -> str:
    # returns "current" | "done" | "upcoming" | "locked"
    if not enabled: return "locked"
    if index == current_index: return "current"
    if index in done_ids_indexes: return "done"
    return "upcoming"
```

`Stepper` keeps its `set_stages` / `set_current` / `mark_done` API; internally it stores
current index + done set and the delegate reads a per-row state (via `Qt.UserRole` data or a
lookup) to paint:

| State | Badge | Text colour | Extra |
|---|---|---|---|
| done | filled `SUCCESS` circle + check glyph | `TEXT` | — |
| current | `ACCENT` ring badge | `TEXT`, bold | `ACCENT` bar on the row's left edge |
| upcoming | hollow `TEXT_FAINT` circle | `TEXT_DIM` | — |
| locked | small faint dot | `TEXT_FAINT` | "soon" pill on the right |

The delegate paints badge + label; selection highlight from QSS still applies. Row height a
touch taller for breathing room.

## 3. Toolbar icons (`ui/icons.py` + `assets/icons/`)

Hand-authored monochrome SVG line icons (24×24, single-path where possible): `open`,
`settings`, `save-recipe`, `batch`, `stack`, `haoiii`, `palette`, `undo`, `redo`,
`before-after`, `log`, `fit`, `actual-size`.

`load_icon(name, color=TEXT) -> QIcon`: locate `assets/icons/<name>.svg`, render at 2× for
crispness (QSvgRenderer → QPixmap), then tint by painting `color` with
`CompositionMode_SourceIn` over the rendered alpha. Raises `FileNotFoundError` for an unknown
name. A module-level cache avoids re-rendering.

`main_window._build_toolbar`: give each action its icon, set
`toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)`, and insert `addSeparator()` between
groups: **File** (Open, Settings) · **Tools** (Save Recipe, Batch, Stack, Ha/OIII, Palette) ·
**Edit** (Undo, Redo, Before/After, Log) · **View** (Fit, 100%). The primary feature tools may
use the `ACCENT` tint to stand out.

## 4. Sliders + dialog polish (QSS from tokens)

- **QSlider**: themed groove (`BG_3`), `ACCENT` filled sub-page up to the handle, rounded
  `TEXT`/`ACCENT` handle with a hover state.
- **QCheckBox / QRadioButton**: `ACCENT` checked indicator.
- **QProgressBar**: `BG_3` trough, `ACCENT` chunk (Stack / Ha/OIII dialogs).
- **QTableWidget / QHeaderView**: styled header row, subtle row hover (grade tables).
- **QScrollBar**: slim, dark, low-contrast.

All additive QSS — no widget code changes.

## Error handling

Visual-only; no new runtime failure modes. The icon loader raises a clear `FileNotFoundError`
on a missing asset (caught at wiring time would be a programming error, surfaced in tests). If
an SVG fails to render, `load_icon` returns an empty `QIcon` rather than crashing the toolbar.

## Testing

Headless, fast:
- `theme`: generated stylesheet is non-empty and contains the semantic tokens (ACCENT,
  SUCCESS, DANGER) and the base surfaces.
- `step_state`: returns correct state for locked / current / done / upcoming across cases,
  including current-takes-precedence-over-done.
- `icons.load_icon`: returns a non-null `QIcon` for each known name; raises `FileNotFoundError`
  for an unknown name; caching returns the same object.
- Assets: every referenced `assets/icons/<name>.svg` exists and is well-formed XML.
- `main_window`: toolbar actions each have a non-null icon (smoke); existing behaviour tests
  stay green.
- Update existing stepper tests that assert on the old `✓ `/`(soon)` text to assert on the new
  `step_state`/rendering instead.

## Roadmap (Tier 2 / Tier 3 — documented, NOT built in this pass)

**Tier 2 — canvas & panels (the "hero shot")**
- Image canvas: radial-gradient backdrop instead of flat fill; framed image with soft shadow;
  floating zoom pill (– 100% +) bottom-right.
- Empty-state screen when nothing is loaded: centered logo + "Open a file or Stack a folder to
  begin" + the two primary buttons.
- Right panel: card-style grouping with a section header and a one-line description strip
  (with a small icon) per step.
- Histogram: translucent filled RGB curves + faint grid.

**Tier 3 — branding & finish**
- App icon + "Nocturne" wordmark (crescent/star glyph) in the corner.
- Splash screen on launch (ties into packaging).
- Before/After: labelled divider handle.
- Busy overlay: spinner + label instead of plain text.

These are added to `TODO.md` under a "Visual polish — later tiers" heading.

## Verification (by eye)

1. Launch the app: toolbar shows grouped icons + labels; stepper shows a green check on done
   steps, a teal ring + left bar on the current step, dim upcoming, faint "soon".
2. Open the Stretch / Palette panels: sliders show an accent-filled track and rounded handle.
3. Open the Stack / Ha/OIII dialogs: progress bar and table header look themed.
4. Take screenshots — the left rail reads as a guided workflow at a glance.
