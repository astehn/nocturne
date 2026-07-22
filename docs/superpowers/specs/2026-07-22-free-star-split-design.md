# Free Star Split (no-RC-Astro fallback) — Design

**Status:** design approved by the user 2026-07-22 (scope = the three gated steps only, Narrowband
left on its whole-image fallback). Spec awaiting user review before the implementation plan.

## Problem & goal

Without RC-Astro **StarXTerminator**, three star-separation steps are **gated (unavailable)**:
**Star Reduction, Remove Green Fringe, and the Nebula-boost** (the Saturation step's second slider).
That's a wall for the free/novice audience — the exact users the free fallbacks exist for.

Goal: a **free star split** — `split_stars(img) → (starless, stars)` using `sep` (already a dependency)
— so those three steps **work without RC-Astro**, gated no more. This is an **availability** feature,
not a quality one: it will be visibly rougher than StarX (see *Honest limitations*), presented as
such, and the user decides whether to use it — consistent with the agreed philosophy ("nothing to
gatekeep; it works but doesn't look as good; up to the user").

**Out of scope this cycle:** Narrowband keeps its existing whole-image fallback (may upgrade later).

## Validated mechanism (prototype)

`sep`-detect → feathered star mask → fill masked regions toward a local-median background →
**screen-compatible** stars. Verified on synthetic data:
- **Screen recombine reconstructs the original EXACTLY** — `max|screen(starless,stars) − original| =
  0.00000`. So the free split is drop-in compatible with the steps' existing screen recombine
  (`1-(1-starless)*(1-stars)`) and consistent with the StarX-`--unscreen` fix.
- Detected ~73% of stars (real stars caught; fainter ones missed). Nebula preserved (starless median
  = original median).

## Architecture

### 1. Core — `nocturne/core/starless.py`

`split_stars(img: AstroImage) → (starless: AstroImage, stars: AstroImage)`, operating on the
**display-space (stretched)** image the steps run on:

1. **Detect** — `sep.Background` + `sep.extract` on the luminance (mirrors `star_spikes.detect_stars`).
2. **Mask** — for each detection, a disc of radius `~2.5·√(a·b)` clamped to `[2, 12]` px; union,
   dilate 1px, then Gaussian-feather (σ≈2) for soft edges.
3. **Starless** — blend the original toward a `median_filter` background under the feathered mask,
   never brightening: `starless = (1-f)·img + f·min(img, median_bg)`.
4. **Stars (screen-compatible)** — `stars = clip(1 - (1-img)/max(1-starless, ε), 0, 1)`, so
   `screen(starless, stars) == img` exactly.
5. **Degenerate** — no detections / `sep` failure → `starless = img.copy()`, `stars = zeros`
   (a plain screen recombine is then the identity; the steps behave as "no stars").

Tunable module constants (calibrated during validation): detection threshold (σ), mask radius factor
and clamp, median size, feather σ.

### 2. Resolver — StarX if present, else free

A single helper `resolve_star_split(img, rc, runner) → (starless, stars)`:
`rc.remove_stars(img, runner=runner)` when `rc` is not None, else `split_stars(img)`. Used by:
- `StarReductionStep`, `GreenFringeStep`, `SaturationStep` (nebula path) — their `apply` calls the
  resolver instead of `self._rc.remove_stars` directly.
- `MainWindow._remove_stars` (the live-preview split used by all three panels).

Factory builds these steps with `rc = RCAstro(...) if rcastro_valid(settings) else None` (matching
the Deconvolution/Noise pattern), so batch/recipe replay without RC-Astro uses the free split too.

### 3. UI — ungate the three steps

Remove the `rcastro_valid` **gate/return** for Star Reduction, Remove Green Fringe, and Nebula boost
(main_window `_apply_star_reduction`, `_apply_green_fringe`, `_apply_saturation`/`_on_sat_split`, and
the panel `split_enabled` plumbing). They now always work. When RC-Astro is **absent**, show an
honest note in the panel instead of a disabled control, e.g.:
> *"Using free star detection — install RC-Astro (StarX) in Settings for cleaner separation."*

The live-preview flows already split async and cache the layers; they just resolve StarX-or-free.
`split_stars` (sep + median filter) is faster than StarX but not instant on full-res, so the existing
async "Separating stars…" busy path stays.

## Honest limitations (set expectations)

- **Fainter stars are missed** (sep threshold) — they stay in the "starless" and are *not*
  reduced/de-greened.
- **Big/bright stars** leave some residual after the median fill; Star Reduction may reveal a faint
  halo where StarX would inpaint cleanly.
- Per-step reality: **Remove Green Fringe** and **Nebula boost** mostly need to know *where* the stars
  are, so they fare well; **Star Reduction** needs the cleanest split, so it's the roughest of the
  three — acceptable, not StarX-grade.

## Error handling

- `sep` unavailable/raises → degenerate path (starless = img, stars = 0); the step becomes a no-op
  rather than crashing.
- Mono image → detection on the single channel; split still valid.
- No behavioural change when RC-Astro *is* present (StarX is always used then).

## Testing

- **Core (`tests/core/test_starless.py`):** `split_stars` on a synthetic nebula+stars frame —
  `screen(starless, stars)` reconstructs the original (max|Δ| < 1e-5); bright star peaks are reduced in
  the starless; nebula (non-star) regions unchanged; no-stars/`sep`-failure → identity split; mono works.
- **Steps (`tests/steps/`):** each of the three steps, constructed with `rc=None`, produces a changed
  image via the free split (a fake/monkeypatched `split_stars` verifies the resolver picks the free path
  when rc is None and StarX when rc is present). Recipe replay of these steps works with `rc=None`.
- **UI (`tests/ui/`):** with RC-Astro absent, the three panels are **enabled** (not gated) and show the
  free-detection note; with it present, unchanged.
- Keep the full suite green.

## Validation (before merge)

User validates on real Seestar data **without RC-Astro**: do Star Reduction / Remove Green Fringe /
Nebula boost now work and look acceptable? Tune the `split_stars` constants (detection σ, mask radius,
fill) for the best free result. Confirm no regression when RC-Astro *is* configured.

## Build process

Subagent-driven, TDD: core `split_stars` → resolver + step wiring + factory → UI ungate + note →
whole-branch review → user real-data validation (no-RC-Astro) → merge.
