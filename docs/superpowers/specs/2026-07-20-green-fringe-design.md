# Remove Green Fringe — Design

**Status:** approved (2026-07-20)
**Group:** B (Enhancements), corrective finishing tool
**Author:** Nocturne pipeline-audit initiative

## Problem

OSC/refractor data (including the Seestar) commonly shows a green colour fringe
or halo around stars — a chromatic-aberration / debayering artifact. Stars are
never perceived as green, so any green fringe is always an artifact worth
removing. Nocturne's existing **Remove Green** is a fixed-strength global SCNR
(clamp green to the red/blue average) that lives as a one-shot button in the
**Color** step (early, pre-stretch). Green fringe on bright stars is often most
visible *after* stretch and saturation, where that early pass can't easily reach
it, and the user wants a controllable, late-stage tool.

## Goal

Add a **Remove Green Fringe** finishing step: a strength-controlled green-excess
suppression with live preview, placed late in the pipeline, so the user can dial
out star fringe (and any residual green cast) while watching it — without
disturbing red, blue, or neutral tones.

Non-goal: star detection or spatial masking — the effect self-targets by colour
(green fringe *is* green excess), so no detection is needed.

## Placement

A new pipeline stage inserted **after Saturation, before Noise Reduction**:

```
… Levels → Curves → Saturation → [Remove Green Fringe] → Noise Reduction → Local Contrast → Star Reduction → …
```

Rationale: saturation can amplify a green fringe, so cleaning up immediately
after colour work catches it at its worst. It operates in display space, joins
`POST_STRETCH_IDS`, and is recipe-serializable. The existing Color-step Remove
Green is left unchanged (an early global toggle for a different moment).

## Architecture & Algorithm

A pure-numpy core function in `nocturne/core/color.py`, next to the existing
`remove_green`:

```python
def remove_green_fringe(img: AstroImage, strength: float) -> AstroImage
```

- `strength` clamped to `[0, 1]`; `strength == 0` is an exact no-op.
- Colour images (`data.ndim == 3`): compute `neutral = (R + B) / 2` and
  `excess = G - neutral`; where `excess > 0`, set
  `G_new = G - strength * excess` (equivalently `G_new = G*(1-s) + neutral*s`
  only on the pixels where `G > neutral`). Red and blue are never modified, so
  only the green *excess* is reduced — strongest on bright green star halos, zero
  on neutral / red / blue pixels.
- At `strength == 1`, `G_new == min(G, (R+B)/2)`, which is exactly what the
  existing `remove_green` (average-neutral SCNR) produces — so this is "Remove
  Green, with a strength dial, applied late."
- Mono images (`data.ndim == 2`) → no-op (no green channel).
- Output clipped to `[0, 1]`, dtype `float32`; `is_linear` and `metadata`
  preserved (deep-copied dict).

## UI & data flow

**Panel** (`nocturne/ui/step_panels.py`, `kind == "green_fringe"`) — identical
shape to Recover Core / Local Contrast:
- A description line in novice language.
- One **Strength** slider `ResetSlider(0)` (default 0 = off) + a numeric readout
  (`fringe_val`, `value/100`).
- An **Apply Remove Green Fringe** button (`apply_btn`), enabled per
  `apply_enabled`.
- Slider exposed as `w.fringe_slider`; `on_fringe_change` fires on `valueChanged`
  with `value/100.0`.

**Live preview** (`nocturne/ui/main_window.py`) — the standardized pattern:
- `_fringe_pending` + `_fringe_timer` (90 ms single-shot `QTimer`).
- `_on_fringe_change(strength)` stores the pending value and starts the timer.
- `_render_fringe_preview()` guards `current_stage_id() == "green_fringe"`,
  renders from `img = self._preview_base("green_fringe")` through
  `remove_green_fringe(img, strength)`, and calls the shared
  `self._show_preview(...)` so image and histogram update live. WYSIWYG: the
  preview base is the true pre-step state, so the dragged preview equals what
  Apply commits.
- `_rebuild_panel`: on entering the stage, reset `_fringe_pending = None` and
  wire `on_fringe_change=self._on_fringe_change` into `build_panel(...)`.

**Commit** — Apply runs `remove_green_fringe` on the committed image as a normal
pipeline step via the generic `apply_current` path (option = the float strength),
off-thread through `_run_busy` like the other tail steps.

**Recipe** — the option is a float; add `green_fringe` to the float
serialize/deserialize branch (alongside `local_contrast` / `recover_core`).

## Testing

**`tests/core/test_green_fringe.py`**
- `strength = 0` → exact no-op (`np.allclose`).
- A green-fringe pixel (`G > (R+B)/2`, e.g. `(0.2, 0.8, 0.3)`) has its green
  pulled down at `strength > 0`, while its R and B are unchanged.
- A neutral grey pixel and a red-dominant pixel (`G < (R+B)/2`) are untouched at
  any strength.
- `strength = 1` output equals the existing `remove_green` on a green-excess
  image.
- Output within `[0,1]`, `float32`; `is_linear`/`metadata` preserved.
- Mono (2-D) input → exact no-op.

**`tests/ui/test_step_panels.py`**
- The `green_fringe` panel exposes `fringe_slider`, `fringe_val`, `apply_btn`;
  the readout tracks the slider; `on_fringe_change` fires with the scaled value.

**`tests/ui/test_main_window.py`**
- `_render_fringe_preview` renders without committing (no new history entry) and
  feeds the histogram.
- The frozen-list pipeline/navigation tests (`test_pipeline.py`,
  `test_default_in_app_path_navigation`) updated to include `green_fringe` after
  `saturation`.

**`tests/steps/test_factory.py`, `tests/test_recipe.py`**
- `make_step("green_fringe", ...)` returns the step; recipe round-trips the float.

## Real-data validation (final task)

Drive the Strength slider on a real image that shows green star fringe: confirm
the fringe fades as strength rises while the nebula colour and star cores stay
correct, and the live preview equals the committed result. Present before/after
for sign-off. Do not merge until confirmed.

## Out of scope (future)

- Star-targeted spatial masking (the colour-targeted method already self-targets
  fringe; masking was considered and set aside as unnecessary complexity).
- A "maximum-neutral" (stronger) mode — average-neutral scaled by strength is
  sufficient; re-apply for stubborn fringe.
