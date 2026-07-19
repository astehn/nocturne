# Levels step rework — Design

**Date:** 2026-07-19 · **Status:** Approved (audit + design Q&A)
**Source:** `docs/audit/PIPELINE_AUDIT.md` → Step 7 (Levels).

Make Levels novice-friendly: live preview, one-click Auto, clipping protection,
readable values. The core remap (`apply_levels`) is unchanged; this adds a
preview path + helpers + panel controls.

## Findings recap
Levels today has **no live preview** (sliders only fire on Apply → guess-and-check),
no auto/starting point, no clipping/data-loss protection, no numeric values, and a
jargon "gamma" label. It IS colour-safe and correctly gated after Stretch.

## Scope
1. **Live preview** (foundational) — dragging any slider updates the canvas in
   real time (debounced ~90 ms), without committing. Apply still commits.
2. **Auto levels** — a button that computes a sensible (black, gamma, white) and
   sets the sliders (which drives the preview); user fine-tunes or Applies.
3. **Clipping indicators** — a "Show clipping" checkbox; when on, the live preview
   paints crushed-shadow pixels **blue** and blown-highlight pixels **red**.
4. **Numeric readouts** beside each slider; **"Midtones"** label (drop "(gamma)").

## Core (`nocturne/core/levels.py`)
Keep `apply_levels(img, black, gamma, white)`. Add:

```python
def auto_levels(data: np.ndarray) -> tuple[float, float, float]:
    """Suggested (black, gamma, white) for a stretched image. Gentle: a low
    shadow percentile for black, near-max white, mild gamma toward a pleasant
    midtone. Never clips real signal hard."""
    lum = data.mean(axis=2) if data.ndim == 3 else data
    black = float(np.clip(np.percentile(lum, 1.0), 0.0, 0.5))
    white = float(np.percentile(lum, 99.9))
    white = max(white, black + 0.05)
    med = float(np.median(lum))
    x = float(np.clip((med - black) / max(white - black, 1e-4), 1e-3, 0.999))
    gamma = float(np.clip(np.log(x) / np.log(0.35), 0.4, 2.5))  # median -> ~0.35
    return black, gamma, white


def clipping_masks(data: np.ndarray, black: float, white: float):
    """Boolean (shadow_clipped, highlight_clipped) per pixel: luminance at/below
    the black point is crushed; at/above the white point is blown."""
    lum = data.mean(axis=2) if data.ndim == 3 else data
    return lum <= black, lum >= white
```

## Preview render (`nocturne/ui/main_window.py`)
- New state: `self._levels_show_clipping = False`; a single-shot debounce
  `QTimer` (~90 ms) and the pending `(black, gamma, white)`.
- `_on_levels_change(black, gamma, white)`: store values, (re)start the debounce.
- Debounce timeout → `_render_levels_preview()`: on the Levels stage with a
  project, `out = apply_levels(current, b, g, w).data`; build a uint8 RGB; if
  `_levels_show_clipping`, paint `clipping_masks(current.data, b, w)` — shadow →
  `(40,120,255)`, highlight → `(255,60,40)`; `image_view.set_image(<qimage>)`.
  Factor a small `rgb_to_qimage(rgb_uint8)` helper (or reuse `to_qimage`'s tail).
- `_on_levels_auto()`: `b,g,w = auto_levels(current.data)`; set the panel sliders
  (`black_slider.setValue(round(b*100))`, etc.) — that fires `_on_levels_change`.
- `_on_levels_clipping(checked)`: set flag, `_render_levels_preview()`.
- Leaving the step / `_refresh()` already re-renders from `project.current()`,
  so an un-applied preview reverts automatically. No commit happens until Apply.

## Panel (`nocturne/ui/step_panels.py`, `levels` branch)
- Wire each slider's `valueChanged` → `on_levels_change(b, g, w)` (new callback).
- Add an **"Auto"** button → `on_levels_auto`; a **"Show clipping"** `QCheckBox`
  → `on_levels_clipping`.
- Beside each slider show a live **numeric readout** label (e.g. `black.value()/100`
  formatted `.2f`; gamma `.2f`; white `.2f`), updated on `valueChanged`.
- Relabel "Midtones (gamma)" → **"Midtones"**.
- `build_panel(..., on_levels_change=None, on_levels_auto=None, on_levels_clipping=None)`.

## Testing
- **core:** `auto_levels` returns `0 ≤ black < white ≤ ~1`, `0.4 ≤ gamma ≤ 2.5`,
  and on a synthetic stretched frame the values are sane (black below median,
  white above). `clipping_masks` flags the darkest/brightest pixels correctly.
- **panel:** levels panel exposes `black_slider`/`gamma_slider`/`white_slider`,
  an Auto button, a Show-clipping checkbox, and numeric readout labels that
  update when a slider moves; "Midtones" label present, no "(gamma)".
- **window:** `_on_levels_auto()` sets the sliders to `auto_levels` of the
  current image; `_on_levels_change` schedules a render; `_render_levels_preview`
  with clipping on produces an image containing the blue/red overlay colours
  (assert a clipped pixel got painted). Debounce timer fires a render.
- Full suite green.

## Out of scope
Applying live preview to the other slider steps (Saturation, etc.) — note as a
follow-up; per-channel clipping (luminance-based is enough for v1).
