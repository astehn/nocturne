# HDR Core / Highlight Recovery — Design

**Status:** approved (2026-07-20)
**Group:** B (Enhancements), item 1 of 4
**Author:** Nocturne pipeline-audit initiative

## Problem

Short Seestar S30 Pro subs clip the bright cores of high-dynamic-range targets
(M42, M8, galaxy nuclei, bright nebula knots). After the stretch lifts the faint
signal, those cores are compressed hard against the top of the tone range and
render as a featureless white blob — the internal structure (swirls, dust lanes,
trapezium region) is still present in the data but visually indistinguishable
because it is crushed into the last few percent of display brightness.

This is the most Seestar-relevant gap found in the enhancement research: the
target-defining detail is exactly what gets lost.

## Goal

Add a **Recover Core** step that pulls the blown highlights down and re-expands
the structure hiding inside them, so bright cores show detail instead of a flat
white blob — with a single novice-proof strength slider and live preview.

Non-goal: recovering signal that is genuinely clipped flat to 1.0 in the data
(no variation left to recover). When there is no surviving structure the step
darkens the region smoothly, which is physically correct.

## Placement

A new pipeline stage inserted **right after Stretch, before Levels**:

```
Stretch → [Recover Core] → Levels → Saturation → Noise → Local Contrast → Star Reduction → Enhancements → Export
```

Rationale: the blown core is a post-stretch (display-space) phenomenon, so the
step operates on the stretched image. Placing it first in the finishing tail
means Levels / Saturation / Local Contrast all work on the recovered image —
the most WYSIWYG, and the clearest novice mental model: "brighten everything
(Stretch), then pull the blown center back."

The stage joins `POST_STRETCH_IDS` (it requires a stretched image; navigating to
it auto-stretches like the other tail steps). It is recipe-serializable via
`STEP_NAME` / `PROCESSING_ORDER`.

## Architecture

One pure-numpy core module, mirroring `core/local_contrast.py`:

**`nocturne/core/hdr.py`**

```python
def recover_core(img: AstroImage, amount: float) -> AstroImage
```

- `amount ∈ [0, 1]`, clamped. `0` = exact no-op (untouched image).
- Runs in display space, operates on luminance only, preserves hue by rescaling
  RGB with the luminance ratio (the same technique `local_contrast.enhance`
  uses).
- Returns a new `AstroImage` preserving `is_linear` and `metadata`.
- Greyscale (2-D) images take the same path on the single channel.

No new dependencies — `scipy.ndimage.gaussian_filter` (already used elsewhere in
the codebase) provides the blur.

## Algorithm — single-scale local HDR

Chosen over a pure global highlight curve (which mostly just darkens the blob
rather than revealing structure) and over full multiscale à-trous HDR (best
recovery but several blurs — too slow for a live slider on 3840×2160, and more
halo tuning and code). Single-scale local HDR is the value-for-complexity sweet
spot: it genuinely reveals structure, stays pure-numpy + one blur, and keeps the
live preview snappy. Multiscale remains a clean future upgrade on the same mask
and luminance plumbing.

Working on the clipped-to-[0,1] display-space image, with `L = mean(RGB)` over
the channel axis (or `L = data` for greyscale):

1. **Feathered highlight mask** — soft so only bright regions are touched and
   edges never produce halos:
   ```
   m = smoothstep(L, t0=0.55, t1=0.92)   # 0 in sky/midtones → 1 in the core
   ```
   `smoothstep(x, a, b) = t*t*(3 - 2t)` where `t = clip((x - a)/(b - a), 0, 1)`.
   Thresholds are fixed constants (auto — no user knob).

2. **Split into local-average + fine-detail** — one Gaussian blur, radius
   auto-scaled to the image so it adapts to full-frame vs a crop:
   ```
   sigma = max(1.0, 0.015 * min(H, W))    # ~1.5% of the short edge
   blur   = gaussian_filter(L, sigma)     # local brightness (the "DC" of the core)
   detail = L - blur                      # the structure hiding in the blob
   ```

3. **Recombine** — pull the local average down and re-expand the detail, blended
   by `amount × mask`:
   ```
   compressed = blur ** (1 + amount)          # exponent > 1 darkens the bright blur
   boosted    = compressed + (1 + amount) * detail
   new_L      = L * (1 - amount*m) + boosted * (amount*m)
   new_L      = clip(new_L, 0, 1)
   ```

4. **Preserve hue**:
   ```
   ratio = new_L / maximum(L, 1e-6)
   out   = clip(RGB * ratio[..., None], 0, 1)
   ```

### Properties (become the core tests)

- `amount = 0` → exact no-op (the `amount*m` blend weight is zero everywhere).
- Regions below the mask ramp (sky, midtone nebula) are untouched.
- Inside a bright blob with embedded low-amplitude structure: the region mean is
  **lowered** and the structure's **relative contrast is raised**.
- Output always within [0, 1].
- `is_linear` and `metadata` preserved; greyscale path works.
- Strength is internally bounded by the `1 + amount` exponents (max exponent 2.0
  at `amount = 1`), so a novice cannot drive it into hard haloing.

The auto constants (`t0`, `t1`, `sigma` fraction, exponents) are the tuning
surface for the real-data validation task; they may be adjusted there.

## UI & data flow

**Panel** (`nocturne/ui/step_panels.py`, `kind == "recover_core"`) — identical
shape to Local Contrast:

- A description line explaining the step in novice language.
- One "Strength" slider: `ResetSlider(0)` (default `0` = off).
- A numeric readout `QLabel` exposed as `w.recover_val`, tracking the slider
  (`{value/100:.2f}`).
- An "Apply" button (`w.apply_btn`), enabled per `apply_enabled`.
- Slider exposed as `w.recover_slider`; `on_recover_change` callback fires on
  `valueChanged` with `value/100.0`.

**Live preview** (`nocturne/ui/main_window.py`) — follows the pattern
standardized in group A:

- `_recover_pending` + `_recover_timer` (90 ms single-shot `QTimer`) in
  `__init__`.
- `_on_recover_change(amount)` stores pending value and starts the timer.
- `_render_recover_preview()` guards `current_stage_id() == "recover_core"`,
  renders from `img = self._preview_base("recover_core")` through
  `recover_core(img, amount)`, and calls the shared `self._show_preview(...)`
  so the image **and** the histogram update live.
- Because `_preview_base` returns the true pre-step state, the dragged preview
  equals what Apply commits (WYSIWYG).
- `_rebuild_panel` resets `_recover_pending = None` on entering the stage and
  wires `on_recover_change=self._on_recover_change` into `build_panel(...)`.

**Commit** — Apply runs `recover_core` on the committed image as a normal
pipeline step via `_PrecomputedStep`, off-thread through `_run_busy`, exactly
like the other tail steps.

## Testing

**`tests/core/test_hdr.py`**
- `amount = 0` is an exact no-op (`np.allclose` to input).
- A synthetic bright blob (near-flat high core + faint embedded ripple) on a
  mid/low background: core-region mean is lowered, and the ripple's relative
  contrast (peak-to-trough / mean) is raised, versus the input.
- A mid-grey region below the mask ramp is unchanged.
- Output within [0, 1] for a random image.
- `is_linear` and `metadata` preserved.
- Greyscale (2-D) input returns a valid 2-D result.

**`tests/ui/test_step_panels.py`**
- The `recover_core` panel exposes `recover_slider` and `recover_val`; the
  readout tracks the slider; `on_recover_change` fires with the scaled value.

**`tests/ui/test_main_window.py`**
- `_render_recover_preview` renders without committing (project state remains
  linear-flag correct) and feeds the histogram (shared `_show_preview`).

## Real-data validation (final task)

Run the app on the NGC 7000 master (and a bright-core target if available),
navigate to Recover Core, and eyeball the slider on the real core. Tune the auto
constants (`t0`/`t1`, sigma fraction, exponents) as needed. Present before/after
crops for sign-off. Refinement is expected here — the algorithm constants are
provisional until validated on real data.

## Out of scope (future)

- Full multiscale à-trous HDR (deluxe upgrade on the same plumbing).
- A separate threshold slider (kept auto for novice simplicity).
