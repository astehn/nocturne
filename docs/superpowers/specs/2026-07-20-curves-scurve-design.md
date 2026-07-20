# Curves / S-Curve Tone Control — Design

**Status:** approved (2026-07-20)
**Group:** B (Enhancements), item 2 of 4
**Author:** Nocturne pipeline-audit initiative

## Problem

Nocturne can set black/white points and a single midtone gamma (Levels), but it
has no way to add **midtone contrast** — steepening the slope through the middle
of the tone range while leaving the ends anchored. A single gamma lightens or
darkens all midtones together; it cannot make the nebula "pop" by increasing
local contrast where the signal lives. Curves is the one classic tone control
the app lacks.

## Goal

Add an interactive **Curves** step: a draggable tone curve on luminance, with a
histogram backdrop so the user can see where the sky and nebula sit and place
points accordingly. Ship a background-aware "Add contrast" preset so a novice
gets a good result in one click, and a "Reset" to return to linear. Live
preview throughout, hue preserved, sky not lifted.

Non-goal: black/white-point lifting (that is Levels' job — the curve's endpoints
stay pinned at the corners).

## Placement

A new pipeline stage inserted **right after Levels, before Saturation**:

```
Stretch → Recover Core → Levels → [Curves] → Saturation → Noise → Local Contrast → Star Reduction → Enhancements → Export
```

Rationale: Levels sets black/white/gamma; Curves then shapes midtone contrast —
the natural order. It operates in display space, joins `POST_STRETCH_IDS`
(requires a stretched image), and is recipe-serializable.

## Architecture

Two new modules plus the usual wiring.

**`nocturne/core/curves.py`** — pure numpy, no new dependency:

```python
def apply_curve(img: AstroImage, points: list[tuple[float, float]]) -> AstroImage
def gentle_s_points(data: np.ndarray) -> list[tuple[float, float]]
```

- `apply_curve` builds a 1024-entry monotone-cubic LUT from the control points
  and applies it to luminance only; hue preserved by rescaling RGB with the
  luminance ratio (same technique as `local_contrast.enhance`, `hdr.recover_core`).
- `gentle_s_points` returns the background-aware "Add contrast" preset points.

**`nocturne/ui/curve_editor.py`** — a custom `CurveEditor(QWidget)` (the
draggable graph). Holds its own point model so it is testable without simulating
raw pixel events.

## The curve model & algorithm

### Control points
- A list of `(x, y)` in `[0, 1]`, always sorted by `x`. Identity is
  `[(0.0, 0.0), (1.0, 1.0)]`.
- The two **endpoints are pinned at the corners** `(0,0)` and `(1,1)`: they
  cannot be moved or removed. All shaping is done with interior points. The user
  "pins the background" by dropping an interior point on the sky peak and leaving
  it while lifting midtones.
- Interior points are clamped so their `x` stays strictly between their
  neighbors' `x` (a small epsilon apart), and `y` stays in `[0, 1]`. Points never
  cross.

### Interpolation → LUT
- Monotone cubic (Fritsch–Carlson) interpolation through the sorted points,
  sampled to a **1024-entry LUT** over `[0, 1]`. Monotone cubic never overshoots
  between points and cannot invert, so the tone mapping can never solarize.
- With only the two identity endpoints, the LUT is the identity ramp.

### apply_curve
```
L      = data if mono else data.mean(axis=2)      # luminance
lut    = build_lut(points)                         # 1024 entries, monotone cubic
idx    = L * (len(lut) - 1)
new_L  = interp(idx, lut)                           # linear lookup into the LUT
# hue preserved:
out    = new_L                if mono else clip(RGB * (new_L / maximum(L, 1e-6)))
```
- Identity points → exact no-op (`build_lut` returns the identity ramp; `new_L == L`).
- Output clipped to `[0, 1]`, dtype `float32`; `is_linear` and `metadata`
  preserved; greyscale takes the single-channel path.

### gentle_s_points (background-aware "Add contrast")
Reads the image luminance:
- `bg` = a low percentile of luminance (the sky/background level, e.g. 10th pct).
- Returns points that place a **pinned anchor at `(bg, bg)`** (so the sky is
  neither lifted nor crushed), then **lift a lower-midtone point slightly below
  the identity and a raise an upper-midtone point above it** — a gentle S that
  increases the slope through the midtones (slope at the midpoint > 1) without
  moving the sky. All points sorted, in `[0,1]`, strictly increasing in `x`,
  corners included.

The Reset preset restores `[(0,0), (1,1)]`.

## The CurveEditor widget

`nocturne/ui/curve_editor.py`, `CurveEditor(QWidget)`:

**Paints** (in `paintEvent`):
- A square-ish box with a reference grid and the identity diagonal.
- The faint luminance **histogram** behind the grid (set via `set_histogram`).
- The live curve, sampled from the LUT.
- The control points as draggable handles (corners visually distinct / fixed).

**Mouse:**
- Click empty space on/near the curve → **add** a control point there.
- Drag a handle → **move** it (`x` clamped between neighbors, `y` in `[0,1]`;
  corners locked).
- Double-click a handle → **remove** it (corners cannot be removed).
- Emits `curveChanged` (Qt signal carrying the current points list) on every edit.

**API:**
- `points() -> list[tuple[float, float]]`
- `set_points(pts)` — replace the model (clamped/sorted; corners enforced).
- `set_histogram(data)` — stash luminance histogram bins for the backdrop.
- `reset()` — restore identity points.

Keeping the model in plain methods means the add/move/remove/clamp logic is
unit-testable directly, with only a couple of qtbot mouse interactions for
coverage of the event handlers.

## UI & data flow

**Panel** (`nocturne/ui/step_panels.py`, `kind == "curves"`):
- A description line in novice language.
- The `CurveEditor` (exposed as `w.curve_editor`).
- A **Reset** button and an **Add contrast** button, wired to
  `on_curve_preset("reset")` / `on_curve_preset("add_contrast")`.
- An **Apply Curves** button (`w.apply_btn`), enabled per `apply_enabled`.
- The editor's `curveChanged` → `on_curve_change(points)`.

**Live preview** (`nocturne/ui/main_window.py`) — the standardized pattern:
- `_curve_pending` + `_curve_timer` (90 ms single-shot `QTimer`).
- `_on_curve_change(points)` stores pending points and starts the timer.
- `_render_curve_preview()` guards `current_stage_id() == "curves"`, renders from
  `img = self._preview_base("curves")` through `apply_curve(img, points)`, and
  calls the shared `self._show_preview(...)` so image and histogram update live.
  WYSIWYG: the preview base is the true pre-step state, so the dragged preview
  equals what Apply commits.
- `_on_curve_preset(kind)`: computes points (`gentle_s_points(_preview_base…)`
  for `"add_contrast"`, identity for `"reset"`), pushes them into the editor via
  `set_points`, and triggers a preview render.
- `_rebuild_panel`: on entering the `curves` stage, seed the editor histogram
  from `_preview_base("curves")`, reset it to identity, clear `_curve_pending`,
  and wire the callbacks into `build_panel(...)`.

**Commit** — Apply runs `apply_curve` on the committed image as a normal pipeline
step via the generic `apply_current` path (option = the points list), off-thread
through `_run_busy` like the other tail steps.

**Recipe** — the option is a list of `[x, y]` pairs; serialize as a list of
2-element lists, deserialize back to a list of tuples. `RecoverCore`-style float
handling does not apply here; Curves gets its own serialize/deserialize branch.

## Testing

**`tests/core/test_curves.py`**
- Identity points `[(0,0),(1,1)]` → exact no-op (`np.allclose` to input).
- A lifted interior midtone point raises the midtones but leaves values at
  luminance 0 and 1 unchanged (endpoints pinned).
- The built LUT is monotonic non-decreasing for a reasonable point set.
- Output within `[0,1]`, `float32`; `is_linear`/`metadata` preserved; greyscale
  path returns valid 2-D result.
- `gentle_s_points(data)` returns a sorted, strictly-increasing-in-x list within
  `[0,1]` including both corners, whose anchor sits at/near the background level,
  and whose curve has midpoint slope > 1 (adds contrast) while the sky point is
  not lifted.

**`tests/ui/test_curve_editor.py`**
- Starts at identity `[(0,0),(1,1)]`.
- `set_points` / `points()` round-trip (with clamping/sorting and corner
  enforcement).
- Adding an interior point sorts and clamps it between neighbors.
- Removing an interior point works; removing/moving a corner is refused.
- `reset()` restores identity.
- `curveChanged` fires on edits.
- `set_histogram` accepts mono and RGB data without error.

**`tests/ui/test_step_panels.py`**
- The `curves` panel exposes `curve_editor`, `apply_btn`, and the Reset /
  Add-contrast buttons; the preset buttons call `on_curve_preset` with the right
  kind; `curveChanged` routes to `on_curve_change`.

**`tests/ui/test_main_window.py`**
- `_render_curve_preview` renders without committing (no new history entry) and
  feeds the histogram.
- The Add-contrast preset seeds non-identity points computed from the real image.

## Real-data validation (final task)

Drive the curve editor on a real image: confirm the histogram backdrop lines up
with the data, dragging/add/remove feel right, the Add-contrast preset gives a
pleasing result without lifting the sky, and live preview equals the committed
result. Present before/after for sign-off. Do not merge until confirmed.

## Out of scope (future)

- Per-channel (R/G/B) curves — luminance only for now.
- Draggable endpoints / black-white lifting in Curves (Levels covers it).
- Saving/loading named curve presets beyond Reset + Add contrast.
