# Enhancements Step (targeted colour + sky) — Design

**Date:** 2026-07-06
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — building under standing authorization.

## Motivation

After Colourise + the tone/colour steps, users want quick, targeted finishing moves — deepen the
Ha red, lift the OIII teal, or darken/lighten the sky background — without sliders. AstroWizard does
this with stackable "pop" buttons; we add a professionally-named **Enhancements** step with the same
fluid tap-to-stack feel, integrated with our undoable history.

## Decisions (from discussion)

- New **"Enhancements"** step at the end of the pipeline (**… → Star Reduction → Enhancements →
  Export**).
- **Five tap-to-stack buttons**, no sliders: `Boost Red (Ha)`, `Boost Cyan (OIII)`, `Boost Blue`,
  `Darken Sky`, `Lighten Sky`. Each tap applies one small increment and records **its own undoable
  step** (Undo peels off the last), like the rotate/flip buttons.
- Targeted, not global: colour boosts are **hue-selective** (only pixels near the target hue), sky
  moves are **shadow-masked** (only the dark background). So they don't smear the whole image.
- **Deferred (fast-follow):** recipe/batch capture of these ops (same limitation as Colourise), and
  any overall "enhance all" button (Saturation + Local Contrast already cover general lifts).

## Architecture / changes

### `core/enhance.py` (new) — pure numeric ops
```python
def boost_hue(img, hue, amount=0.12, width=0.12) -> AstroImage:
    """Increase saturation of pixels near `hue` (0..1) with smooth circular
    falloff (Gaussian in hue distance). Mono unchanged. Reuses skimage HSV."""
    # rgb2hsv -> weight = exp(-(circular_hue_dist**2)/(2*width**2))
    # hsv[...,1] *= (1 + amount*weight) -> hsv2rgb

def darken_sky(img, amount=0.08) -> AstroImage:
    """Shadow-masked darken: pull the dark background down, leave bright nebula/
    stars alone. weight = shadow_mask(luminance); out = data*(1 - amount*weight)."""

def lighten_sky(img, amount=0.08) -> AstroImage:
    """Shadow-masked lighten: lift the dark background gently.
    out = data + amount*weight*(1 - data)."""
```
Hue targets: Red `0.0`, Cyan (OIII) `0.5`, Blue `0.667`. `shadow_mask(lum) = clip(1 - lum/knee, 0,
1)**2` (knee ≈ 0.4) — 1 for near-black, 0 above the knee. Exact `amount`/`width`/`knee` defaults are
tuned in the plan against a real image so one tap is a visible-but-gentle nudge.

### `ui/pipeline.py`
- Add `Stage("enhancements", "Enhancements", "enhance")` to `_IN_APP_TAIL` **after `star_reduction`,
  before `export`**.
- Add `ENHANCE_NAMES = ("Boost Red", "Boost Cyan", "Boost Blue", "Darken Sky", "Lighten Sky")`.
- These are **append-only trailing ops** (like `GEOMETRY_NAMES`) — NOT added to `PROCESSING_ORDER`/
  `STEP_NAME`, so re-applying an earlier processing step correctly truncates them
  (edit-early-truncates-later), and no special preservation rule is needed.

### `ui/main_window.py`
- `_enhance(op)` handler (append-only, individually undoable):
  ```python
  def _enhance(self, op):
      if self.project is None or self._busy:
          return
      result = _ENHANCE_FN[op](self.project.current())
      self.project.run_step(_PrecomputedStep(op, result), "")
      self.log_panel.append_entry(format_log_entry(op, "", None))
      self._status.setText("")
      self._refresh()
  ```
  where `_ENHANCE_FN` maps each `ENHANCE_NAMES` entry to its `core/enhance` call (e.g.
  `"Boost Red": lambda i: boost_hue(i, 0.0)`).
- Wire `on_enhance=self._enhance` into `build_panel`.
- `_done_ids`: mark `"enhancements"` done if any `ENHANCE_NAMES` entry is in the applied set.

### `ui/step_panels.py`
- New `elif stage.kind == "enhance":` branch — a title + a short description + five buttons, each
  calling `on_enhance("<name>")`. Expose them as attributes for tests (`w.boost_red_btn`,
  `w.boost_cyan_btn`, `w.boost_blue_btn`, `w.darken_sky_btn`, `w.lighten_sky_btn`).
- `build_panel` gains an `on_enhance=None` param.

## Data flow

Enhancements stage → tap a button → `_enhance(op)` runs the pure `core/enhance` function on the
current image → `run_step` appends an undoable `_PrecomputedStep(op, ...)` → refresh. Taps stack
(each appends); Undo removes the last; navigating back to an earlier step and re-applying it
truncates the trailing enhancements.

## Error handling

- Guarded on `project is None` / `_busy`.
- Mono image → colour boosts return a copy unchanged (guarded); sky moves still work on luminance.
- Values clipped to [0, 1]; no external tools, no new dependency (skimage already used).

## Testing

- **core** (`tests/core/test_enhance.py`):
  - `boost_hue` on a red pixel raises its saturation; a teal pixel is (near) unchanged (hue
    selectivity). Cyan/Blue analogues target their hues.
  - `darken_sky` lowers a dark-background pixel and leaves a bright pixel ~unchanged;
    `lighten_sky` raises a dark pixel; both clip to [0,1]; mono handled.
- **pipeline** (`tests/ui/test_pipeline.py`): an `enhancements` Stage exists after `star_reduction`
  and before `export`; `ENHANCE_NAMES` is the five names; enhancements is NOT in `PROCESSING_ORDER`.
- **step_panels** (`tests/ui/test_step_panels.py`): the enhance panel exposes the five buttons;
  clicking each invokes `on_enhance` with the matching name.
- **main_window** (`tests/ui/test_main_window.py`): `_enhance("Boost Red")` appends a "Boost Red"
  entry and changes the image; two taps stack (two entries); Undo removes one; `_done_ids` marks
  `"enhancements"`; applying an earlier processing step (e.g. Saturation) after an enhancement
  truncates the enhancement (trailing-op behaviour).
- Full suite green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`).

## Verification (by eye)

On a colourised image → Enhancements → tap **Boost Red** a couple of times (Ha deepens, teal
untouched), **Boost Cyan** (OIII lifts), **Darken Sky** ×2 (background sinks, nebula/stars keep
brightness). Undo peels taps off one at a time. Export.
