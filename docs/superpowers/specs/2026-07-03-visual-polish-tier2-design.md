# Visual Polish (Tier 2 — Canvas & Panels) — Design

**Date:** 2026-07-03
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved (autonomous — standing authorization from the user to design, build, and
merge Tier 2 without interference; decisions made against the Tier 2 roadmap already approved
in `2026-07-03-visual-polish-design.md`).

## Motivation

Tier 1 made the chrome (theme, stepper, toolbar) look designed. Tier 2 is the "hero shot"
work — the parts that make a *nebula screenshot* pop and give a polished first impression:
the image canvas, an empty-state welcome screen, a floating zoom control, styled histogram,
and card-style step panels. Purely visual; no processing/behaviour changes.

## Scope (Tier 2)

1. **Canvas backdrop** — a subtle radial gradient behind the image instead of the flat fill.
2. **Framed image** — a soft drop shadow on the image so it lifts off the backdrop.
3. **Floating zoom pill** — a small `–  ⤢  +` control bottom-right of the canvas.
4. **Empty-state welcome screen** — shown when nothing is loaded: wordmark + tagline +
   "Open a file or Stack a folder to begin" + Open / Stack buttons.
5. **Styled histogram** — translucent filled RGB curves + a faint grid.
6. **Card-style step panels** — the right-hand step panel wrapped as a card with a title and a
   one-line description strip.

**Out of scope** — Tier 3 (app icon/wordmark asset, splash, labelled before/after handle,
spinner busy-overlay); any processing/behaviour change. The empty-state uses a **text**
wordmark, not a logo asset (that's Tier 3).

## Global constraints

- Package `seestar_processor` (no rename). Venv `.venv`; UI tests headless (`QT_QPA_PLATFORM=offscreen`).
- **Visual only** — no behaviour change to processing, navigation, crop overlay, or
  before/after compare. Existing tests stay green.
- Reuse Tier 1 theme tokens (`BG_0..3`, `ACCENT`, `TEXT*`, etc.).
- Pure/paint split: keep any logic in testable functions; accept paint code as pixels with
  smoke tests (renders without error).

## Architecture

```
seestar_processor/
  ui/histogram_view.py  # filled translucent RGB curves + faint grid
  ui/image_view.py      # drawBackground radial gradient + image drop shadow + zoom pill child
  ui/zoom_pill.py       # NEW: small floating zoom control (– / fit / +)
  ui/welcome.py         # NEW: empty-state welcome widget
  ui/step_panels.py     # card container + description strip
  ui/theme.py           # QSS for the card, welcome, and zoom pill
  ui/main_window.py     # QStackedWidget [welcome, image_view]; switch on open
```

## 1. Canvas backdrop (`image_view.py`)

Override `drawBackground(painter, rect)` to paint a **radial gradient** (centre `BG_1` →
edges `BG_0`) across the viewport, giving depth instead of the flat `BG_0`. The QSS
`QGraphicsView { background: … }` rule is removed for `ImageView` so the gradient shows.

## 2. Framed image shadow (`image_view.py`)

Attach a `QGraphicsDropShadowEffect` (blur ~24, offset 0, ~50% black) to the image
`QGraphicsPixmapItem` so it lifts off the backdrop. Applied once in `__init__`; unaffected by
`set_image`/crop/compare (the effect lives on the item).

## 3. Floating zoom pill (`ui/zoom_pill.py` + `image_view.py`)

`ZoomPill(QWidget)` — a rounded pill with three flat buttons: **–** (zoom out), **⤢** (fit),
**+** (zoom in), wired via callbacks. It's a child of `ImageView`, positioned bottom-right in
`ImageView.resizeEvent` (with a margin). `ImageView` gains `zoom_in()` / `zoom_out()` methods
(scale by 1.25 / 0.8 — the same factors as `wheelEvent`, refactored to call them). The middle
button calls `fit()`. Fully testable: clicking a button changes the view transform / calls the
callback.

## 4. Empty-state welcome (`ui/welcome.py` + `main_window.py`)

`WelcomeScreen(QWidget, on_open, on_stack)` — a centred column: a large **"Nocturne"** text
wordmark, `APP_TAGLINE`, a muted line "Open a file or Stack a folder to begin", and two
buttons ("Open FITS" → `on_open`, "Stack…" → `on_stack`). In `main_window`, the centre
`image_view` is wrapped in a `QStackedWidget` with page 0 = welcome, page 1 = image_view;
`open_image` switches to page 1. `main_window` exposes `_center_stack` for tests. Behaviour
of everything else is unchanged (the stack just swaps which centre widget is visible).

## 5. Styled histogram (`histogram_view.py`)

Rewrite `paintEvent`: for each channel build a filled polygon (translucent channel colour,
alpha ~70) from the binned counts, drawn over a faint horizontal **grid** (3–4 lines in a
low-contrast `BORDER`), on the `BG_0` background. Keep `set_image`/`_hist`/`_COLORS`. A short
pure helper `_polygon_points(counts, w, h, peak)` is unit-tested; the fill is paint.

## 6. Card-style step panels (`step_panels.py` + `theme.py`)

`build_panel` sets the returned panel widget's `objectName` to `"stepCard"` and ensures a
**description strip** (the existing `_desc_label`, or a stage-appropriate one) sits under the
stage title. `theme.py` styles `QWidget#stepCard` (surface `BG_2`, 10px radius, padding) and a
`QLabel#stepDesc` (muted `TEXT_DIM`, smaller). No control/logic change — the same widgets,
grouped as a card.

## Error handling

Visual only; no new runtime failure modes. The zoom pill and welcome buttons call existing
slots. Paint code guards on "no image / empty histogram" (already present / added).

## Testing

Headless, fast:
- `histogram`: `_polygon_points` returns points within bounds for known counts; `set_image`
  populates `_hist` and `paintEvent` renders to a pixmap without error.
- `image_view`: `zoom_in()` increases the transform scale, `zoom_out()` decreases it; the zoom
  pill's buttons invoke the right callbacks; `set_image`/compare/crop still work (existing
  tests).
- `zoom_pill`: constructing with fake callbacks and clicking each button calls the right one.
- `welcome`: the two buttons invoke `on_open` / `on_stack`.
- `main_window`: `_center_stack` shows the welcome page before load and the image page after
  `open_fits`; all existing behaviour tests stay green.
- `step_panels`: a built panel has `objectName() == "stepCard"` and contains a `stepDesc` label.

## Verification (by eye, after merge)

Launch, screenshot the empty state (welcome), then load a real stack: the image sits on a
gradient backdrop with a soft shadow, the zoom pill floats bottom-right, the histogram shows
filled RGB curves, and the step panel reads as a titled card. Capture fresh screenshots for
the testers/README.
