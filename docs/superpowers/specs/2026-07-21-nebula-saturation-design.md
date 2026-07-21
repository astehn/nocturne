# Masked Nebula Saturation — Design

**Status:** approved (2026-07-21)
**Group:** B (Enhancements), last item
**Author:** Nocturne pipeline-audit initiative

## Problem

Today's global `saturate()` softly tapers its boost away from the noisy
background and bright stars *by luminance*, but that also under-saturates
genuinely faint nebulosity, and star cores/halos still receive some colour push
(garish when boosted hard). Users want to lift nebula colour — including faint
nebulosity — while leaving the sky background and stars completely untouched.

## Goal

Add a **Nebula boost** to the existing Saturation step: a mask-aware,
star-separated saturation that boosts only the nebulosity. Stars are hard-removed
via StarXTerminator (untouched), and within the starless layer a sky-anchored
nebula mask limits the boost to real signal (faint included), sparing empty sky.
It lives on the Saturation panel alongside the existing global slider (which is
unchanged and works for everyone); the Nebula boost is RC-Astro-gated.

## Placement

No new stage — this extends the **existing `saturation` step**. The Saturation
panel gains a second slider. Order in the result: **nebula boost first, then the
existing global saturation on top.**

## Architecture & Algorithm

**Core** (`nocturne/core/saturation.py`):
- `saturate(img, amount)` — UNCHANGED (global re-centred saturation).
- New `_nebula_mask(lum: np.ndarray) -> np.ndarray`: a sky-anchored, feathered
  mask. `sky_lo, sky_hi = np.percentile(lum, [25, 60])` (adaptive); raw mask
  `smoothstep(lum, sky_lo, sky_hi)` → 0 at/below the sky level, ramping to 1 as
  signal rises above it; Gaussian-blur it (`skimage.filters.gaussian`,
  `sigma ≈ 1.5% of the short edge`) so the boundary is smooth. Returns a float
  mask in `[0,1]`.
- New `nebula_saturate(starless: AstroImage, stars: AstroImage, strength: float)
  -> AstroImage`:
  - `strength` clamped `[0,1]`; `strength == 0` → plain screen recombine
    `1-(1-starless)*(1-stars)` (exact no-op relative to the split).
  - `L = starless.mean(axis=2)`; `m = _nebula_mask(L)`.
  - Boost the starless chroma within the mask, hue-preserving:
    `sat = L + (starless - L) * (1 + _GAIN * strength * m)` (with `_GAIN` capping
    the maximum push, e.g. `1.5`).
  - Screen the untouched stars back: `out = 1 - (1 - sat) * (1 - stars)`.
  - Output clipped `[0,1]` float32; `is_linear`/`metadata` from `starless`.

The Saturation step's full result = `saturate(nebula_saturate(starless, stars,
nebula), amount)`.

**Step** (`nocturne/steps/saturation_step.py`) — mirrors `StarReductionStep`'s
RC-Astro construction:
```python
class SaturationStep(Step):
    def __init__(self, rcastro: RCAstro) -> None: ...
    def apply(self, img, option):
        amount, nebula = _parse_saturation_option(option)   # tuple / list / legacy float / ""
        if nebula > 0.0:
            starless, stars = self._rc.remove_stars(img, runner=self._runner)
            img = nebula_saturate(starless, stars, nebula)
        return saturate(img, amount)
```
- `_parse_saturation_option(option)` → `(amount, nebula)`: accepts a 2-tuple/2-list
  `(amount, nebula)`, a legacy bare float `amount` (→ `(amount, 0.0)`), or empty
  `""`/`None` (→ `(0.5, 0.0)`, native). Factory constructs `SaturationStep(RCAstro(
  resolve_binary(settings.rcastro_path)))` with `step._runner = rc_runner`.

## UI & data flow

**Panel** (`nocturne/ui/step_panels.py`, `kind == "saturation"`):
- Existing **Saturation** `ResetSlider` + readout (`sat_slider`, `sat_val`) —
  unchanged.
- New **Nebula boost** `ResetSlider(0)` + readout (`neb_slider`, `neb_val`) + a
  status label (`neb_status`).
- The Nebula slider starts enabled but is disabled + gated by main_window when
  RC-Astro is absent; the Saturation slider always works.
- Slider changes call `on_sat_change(sat_slider.value()/100, neb_slider.value()/100)`;
  Apply calls `on_sat_apply(<amount>, <nebula>)`.

**main_window** (`nocturne/ui/main_window.py`) — extends the current saturation
preview with the Green-Fringe-style cached StarX split, triggered lazily:
- State: `_sat_pending = (amount, nebula)`, `_sat_layers = (sig, starless, stars)`,
  `_sat_split_ready` bool, existing `_sat_timer`.
- `_setup_saturation()` on entering the step: reset pending; if `not
  rcastro_valid(self.settings)`, disable the Nebula slider + set the "Needs
  RC-Astro" message (Saturation slider stays enabled); do NOT split yet.
- `_on_sat_change(amount, nebula)`: stash `(amount, nebula)`; if `nebula > 0`,
  `rcastro_valid`, and no cached split for this base, kick off `_remove_stars`
  off-thread (status "Separating stars…"); start the 90 ms preview timer.
- `_render_saturation_preview()`: base `= _preview_base("saturation")`. If
  `nebula > 0` and `_sat_layers` cached → `img = nebula_saturate(starless, stars,
  nebula)`; else `img = base` (global-only while the split is pending/absent).
  Then `_show_preview(saturate(img, amount).data)`.
- `_on_sat_split(sig, layers)`: cache `(sig, starless, stars)`, set ready,
  re-render.
- `_apply_saturation(amount, nebula)`: commit from the cached split when
  `nebula > 0` (instant, no re-split), else global-only; `jump_back` to the
  saturation predecessors, compute `saturate(nebula_saturate(...)|base, amount)`,
  `run_step(_PrecomputedStep("Saturation", result), (amount, nebula))`, log,
  refresh. Replaces the generic `apply_current` path for the saturation panel.
- `_rebuild_panel` wires `on_sat_change`/`on_sat_apply` and calls
  `_setup_saturation()` on entry. Reuse `_sr_sig` for the cache key.

`saturation` is already in `POST_STRETCH_IDS` / `PROCESSING_ORDER`; no pipeline
change.

**Recipe** (`nocturne/recipe.py`): add a `saturation` branch —
`serialize_option` → `[float(amount), float(nebula)]`; `deserialize_option` →
`(amount, nebula)` from a 2-list, or `(float(v), 0.0)` from a legacy bare float
(old recipes still replay, nebula off).

**Log label** (`_log_step`): saturation option is now a tuple → format it, e.g.
`elif stage_id == "saturation": label = f"{option[0]:.2f} / neb {option[1]:.2f}"`.

## Testing

**`tests/core/test_saturation.py`**
- Existing `saturate` tests unchanged (still green).
- `_nebula_mask`: ~0 for a sky-level (low, uniform) region, ~1 for a bright
  signal region.
- `nebula_saturate(starless, stars, 0)` equals `1-(1-starless)*(1-stars)`.
- `nebula_saturate` with `strength>0`: a nebula pixel (above sky) gains chroma
  (distance from its luminance grows) while a sky-level pixel is unchanged; the
  stars layer is screened back (a star-only pixel matches the plain recombine).
- Output `[0,1]` float32; `is_linear`/`metadata` from starless; mono starless →
  no chroma change (returns recombine).

**`tests/steps/test_saturation_step.py`**
- With a fake RC (synthetic starless/stars), `SaturationStep(fake).apply(img,
  (0.7, 0.6))` equals `saturate(nebula_saturate(starless, stars, 0.6), 0.7)`.
- A legacy bare float `0.7` applies global-only (`saturate(img, 0.7)`, no split).
- `""`/`None` → `saturate(img, 0.5)` (native, no split).

**`tests/ui/test_step_panels.py`**
- The saturation panel exposes `sat_slider`, `neb_slider`, `neb_status`,
  `apply_btn`; `on_sat_change` fires with `(amount, nebula)`; `on_sat_apply`
  fires with both.

**`tests/ui/test_main_window.py`**
- Entering saturation without RC-Astro disables the Nebula slider + shows the
  message; the Saturation slider still previews and `_apply_saturation(0.7, 0.0)`
  records a "Saturation" step (no split needed).
- With a monkeypatched `_remove_stars` + `rcastro_valid` true, `_on_sat_change(
  0.5, 0.6)` caches the split (sync) and `_render_saturation_preview` renders
  without committing; `_apply_saturation(0.5, 0.6)` records a "Saturation" step.

**`tests/test_recipe.py`**
- `serialize_option("saturation", (0.7, 0.4)) == [0.7, 0.4]`;
  `deserialize_option("saturation", [0.7, 0.4]) == (0.7, 0.4)`;
  `deserialize_option("saturation", 0.7) == (0.7, 0.0)` (legacy).

## Real-data validation (final task)

Drive the Nebula boost on a real image: confirm faint nebulosity gains colour,
the sky background stays neutral, and stars are visibly unchanged; the global
Saturation slider still behaves as before; the live preview equals the commit.
Present before/after for sign-off. Do not merge until confirmed. Tune `_GAIN`,
the mask percentiles, and the feather sigma here if needed.

## Out of scope (future)

- A non-RC-Astro fallback for the Nebula boost (luminance/structure mask without
  StarX) — deferred; the Nebula slider is simply gated off without RC-Astro.
