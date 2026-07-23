# Drizzle (×2 super-resolution stacking) — Design

**Date:** 2026-07-23
**Status:** Design (awaiting user review)
**Register:** app feature (stacking)
**Gap-analysis origin:** Tier 3 "Drizzle / super-resolution" — genuine S30-Pro community demand; the free, honest form of super-resolution (vs. AI upscaling, which is deliberately out of scope).

## Goal

Add an optional **Drizzle ×2** integration mode to Nocturne's stacker that recovers real sub-pixel detail from the many dithered, undersampled subs a Seestar S30 Pro produces — surfaced as a single, data-aware checkbox that tells the user whether it will actually help *their* data.

## Why it fits (and its limits)

- **Seestar is undersampled** (~3.7″/px; stars often ~1.5–2 px FWHM under decent conditions) and shoots **hundreds of naturally-dithered subs** (alt-az field rotation + re-centering). That is drizzle's sweet spot.
- **It only helps when stacking raw subs *in Nocturne*** (drizzle needs the subs + their sub-pixel transforms; it can't run on an imported master). The audience that asks about drizzle is the same audience that keeps raw subs, so interested ≈ addressable.
- **Misapplied, it just adds noise** (poor dither / too few frames / already-well-sampled). So the suitability gate is not a caveat — it is the feature's headline.

## Design

### 1. Engine — the STScI `drizzle` library (not from-scratch)

Use **`drizzle`** (github.com/spacetelescope/drizzle, PyPI `drizzle`):
- **License BSD-3** — GPLv3-compatible (confirmed from `LICENSE.rst`).
- **Runtime dependency: numpy only** (astropy/gwcs are optional test/doc deps).
- Core API (v2.x): `Drizzle.add_image(data, exptime, pixmap, weight_map=..., pixfrac=...)`, where `pixmap` is an `(Ny, Nx, 2)` array giving each input pixel's `(x, y)` **output** coordinate. That maps directly onto what we already have — no astropy WCS needed.

Rationale: the flux-conserving fractional-overlap math is the part that is subtle and easy to get quietly wrong; the library's is battle-tested C. We provide the geometry (from our own registration) and let it accumulate.

**Task-1 verification:** install `drizzle`, confirm the exact `add_image` signature and version against a tiny smoke test before building on it (the API differed across major versions).

### 2. Integration path — reuses registration, adds a new accumulator

`run_stack` currently: register each sub → 3×3 similarity transform → warp to ref grid → average / sigma-clip. Drizzle adds a **third integration method** (`StackOptions.method == "drizzle"`), which:
- Keeps **Phase A (registration) unchanged** — the same astroalign 3×3 transforms.
- Replaces Phase B with a drizzle accumulator that builds, per frame, a **pixmap** from that frame's 3×3 transform composed with a ×2 scale (input pixel → 2×-reference output grid), and calls `add_image`.
- Output grid = **2 × ref_shape**; the library also tracks a weight map; the final master is the (exptime-/weight-normalized) drizzled science array.

Frame grading (bad-sub rejection) runs before integration exactly as today.

### 3. Preserving sigma-clip cleanliness (the one real engineering call)

Today's default (sigma-clip) removes satellite trails / cosmic rays that survive into an otherwise-good frame. A naïve drizzle-average would lose that. Drizzle mode therefore keeps per-pixel outlier rejection via **two passes**:
1. **Stats pass** — warp each frame to the **2× reference grid** (bilinear) and accumulate streaming per-output-pixel mean/std (the Welford logic we already have in `sigma_clip_integrate`).
2. **Drizzle pass** — for each frame, build an input **weight mask**: for each input pixel, sample the 2×-grid mean/std at its mapped output location (via the pixmap) and set weight 0 where the input value is beyond `kappa·sigma`. Drizzle the frame with that mask, so trailed/outlier pixels never land in the output.

Result: drizzle's resolution **and** sigma-clip's cleanliness, reusing existing statistics code. This is the design's most involved piece; it stays entirely inside the stacker (invisible to the user).

### 4. Hidden defaults (never exposed)

- **Scale ×2**, **kernel `square`** (flux-conserving; gaussian/lanczos do *not* conserve flux), **pixfrac ≈ 0.6**.
- No user-facing drizzle-factor / pixfrac / kernel knobs. (`pixfrac` exact value in 0.5–0.7 is tuned during real-data validation.)

### 5. The suitability gate — a soft, graduated recommendation

When a folder is graded, compute three metrics we already measure or can derive:
- **Undersampling** — median star **FWHM in px** (from grading). Drizzle benefits when small (guidance ≈ FWHM < ~2 px; **exact threshold re-derived on real S30-Pro data**, not generic numbers).
- **Dither adequacy** — spread of the sub-pixel translation components across the registration transforms (well-scattered fractional offsets = good dither).
- **Frame count** — enough kept frames (guidance spans ~15–20 up to a conservative 50+; the gate treats more as better, not a hard cutoff).

These combine into a **graduated recommendation** (e.g. Recommended / Marginal / Not recommended) with a one-line human reason. Soft, not pass/fail — the thresholds live in one place and are tuned against real data.

### 6. UX — one data-aware checkbox (warn-but-allow)

In the Stack dialog, a single checkbox: **"Drizzle — extra detail (×2)."** It is **always usable**, with a live recommendation label driven by the gate:
- Green — *"Recommended: your frames are undersampled and well-dithered."*
- Amber — *"Won't help this data (stars too soft / little dither / too few frames) — leave off."*

It teaches the *why* and lets the user decide (no grey-out, no silent block) — matching Nocturne's explain-as-you-go ethos. The output filename/metadata note ×2 (e.g. `…_drizzle2x.fits`) and the stack report states drizzle was applied.

## Scope / non-goals (v1)

- **v1 = post-debayer ×2 drizzle + the gate.** Only ×2 (no user-selectable factor).
- **Bayer/CFA drizzle is phase 2** — the Ha/OIII resolution win. It is materially more complex (color-aware CFA accumulation, runs at scale 1 / pixfrac 1, calibration on raw CFA) and is explicitly deferred.
- **No drizzle-native CR rejection** (median/blot/re-drizzle) — we reuse the sigma-clip mask instead.
- **No AI super-resolution** — out of scope on principle (hallucinated detail) and license (proprietary weights).
- Drizzle applies only to Nocturne's own stacking, not imported masters (inherent).

## Dependency / data changes

- Add **`drizzle`** to `pyproject.toml` dependencies and bundle it in the PyInstaller spec (numpy-only, small).

## Testing

- **Unit:** pixmap construction from a 3×3 transform ×2 (a known shift maps to the expected output coords); drizzle of a synthetic star field yields a 2×-size master with the star at the expected sub-pixel location; the sigma-clip mask zeroes an injected outlier pixel; the gate returns the right recommendation for undersampled+dithered vs soft+undithered synthetic inputs.
- **Integration:** `run_stack(method="drizzle")` end-to-end on the synthetic NGC 7000 subs → 2× master, no crash, reasonable output.
- **Real-data validation (yours, before merge):** drizzle a genuinely well-dithered S30-Pro set and confirm the detail gain is **visibly** there (not marginal), and calibrate the gate's FWHM/dither/frame thresholds against what actually helps. If it's marginal on real data, that's the signal to stop.

## Open items (resolved in plan / validation)

1. Exact `drizzle` `add_image` signature + version (Task-1 smoke test).
2. `pixfrac` value (0.5–0.7) — tuned on real data.
3. Gate thresholds (FWHM / dither / count) — calibrated on real S30-Pro data.
4. Drizzle output normalization (exptime/weight) to a proper average — nailed in the plan.
5. Autocrop at ×2 (coverage bounds computed on / scaled to the 2× grid).
