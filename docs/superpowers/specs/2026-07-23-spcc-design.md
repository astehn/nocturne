# Photometric Colour Calibration (SPCC-lite) — Design Spec

**Status:** Draft for review · 2026-07-23
**Depends on:** the plate-solve WCS (merged), online access to ESA's Gaia archive
**Builds toward:** better OSC/dual-band colour ("why is my nebula magenta/green")

## Goal

Add a **star-based (photometric) white balance** to the Colour step, calibrated against the real colours of stars from Gaia DR3, as an alternative to today's sky-based background balance. This fixes the colour-cast problem a sky-only balance can't — it sets a physically-referenced white point ("a Sun-like star should look white") from catalogued star colours.

It is deliberately **"SPCC-lite"**: an empirical population fit that aligns the sensor's colour response to a solar-neutral reference using Gaia colours — a real, principled step up from sky balance, but NOT the full per-star spectral synthesis with sensor QE curves that PixInsight does (we don't have the IMX585 response curves, and chasing them is out of scope).

## Scope

**In scope (v1):**
- A **method selector** in the Colour step: `Sky balance` (today's default) vs `Photometric (SPCC)`.
- Photometric mode: get a WCS (reuse cached plate-solve or solve the linear image), detect stars, query Gaia online for the field, cross-match, fit, and apply a per-channel gain — **fully automatic, no knobs**.
- Robust **fallback to sky balance** on any failure (no internet, solve fails, too few matched stars, degenerate fit), with a one-line status message. Never errors out.
- Recipe/batch: the Colour step records `method: photometric`; on replay it re-runs SPCC per image (each target solved + calibrated independently), falling back to sky balance per image if unavailable.

**Out of scope (not now):**
- Full spectral-synthesis SPCC with the IMX585/Bayer QE curves.
- Bundling any Gaia data (query is online-only).
- A new pip dependency — the Gaia query uses stdlib `urllib` + `csv`.
- Narrowband/duo-band-specific colour handling (SPCC runs on the OSC broadband colour; the Narrowband tool is separate).
- Any UI knobs (strength, reference-star selection, etc.).

## Global constraints

- No new pip dependency; `astropy` (WCS/coords), `sep` (star detection), `numpy` are already present.
- SPCC operates on the **linear** image (colour calibration belongs before Stretch, like the current Colour step).
- Never `git add -A`; the repo has untracked strays.
- Green removal stays a separate button, unchanged.

## User experience / flow

The Colour step's panel gains a small **method selector** (two choices): `Sky balance` and `Photometric (SPCC)`. Default stays `Sky balance` (offline, instant).

Choosing **Photometric** and applying runs, asynchronously (via the existing `_run_busy` "Calibrating colour…" progress path):

1. **WCS** — reuse the cached plate-solve (`self._solve`) if it matches the current framing; otherwise solve the current linear image with ASTAP (same path `_solve_current` uses).
2. **Detect stars** — `sep` on luminance → star pixel positions; measure per-channel (R,G,B) flux in a small aperture; reject saturated and low-SNR stars.
3. **Query Gaia** — one HTTPS call to ESA's Gaia TAP service for stars in the field → `(ra, dec, bp_rp, g_mag)`.
4. **Cross-match** detected stars ↔ Gaia stars by projected position, **fit**, and **apply** a per-channel gain to the linear image.

On any failure it falls back to sky balance and reports why (e.g. "Couldn't reach Gaia — used sky balance", "Too few matched stars — used sky balance"). The result previews live and commits like any Colour apply.

## Architecture & components

New/changed units, each with a clear boundary:

### `nocturne/tools/gaia.py` (new) — online catalogue query
- `@dataclass GaiaStar: ra_deg: float; dec_deg: float; bp_rp: float; g_mag: float`
- `query_field(ra_deg, dec_deg, radius_deg, *, mag_min=7.0, mag_max=16.0, fetch=None) -> list[GaiaStar]`
  - Builds an ADQL cone-search query, GETs ESA's Gaia TAP **sync** endpoint (`https://gea.esac.esa.int/tap-server/tap/sync`) with `REQUEST=doQuery&LANG=ADQL&FORMAT=csv&QUERY=…`, parses the CSV.
  - ADQL: `SELECT TOP 3000 ra, dec, phot_g_mean_mag, bp_rp FROM gaiadr3.gaia_source WHERE CONTAINS(POINT('ICRS',ra,dec), CIRCLE('ICRS', <ra>, <dec>, <radius>))=1 AND bp_rp IS NOT NULL AND phot_g_mean_mag BETWEEN <min> AND <max>`
  - `fetch` is an injectable `fetch(url) -> str` (default: `urllib.request.urlopen` with a timeout) so tests use a canned CSV and never hit the network. Any network/parse error raises `GaiaError` (caller handles fallback).
- Pure I/O + parsing; no astropy, no image logic.

### `nocturne/core/spcc.py` (new) — the algorithm (pure, no Qt, no network)
- `@dataclass SpccResult: gains: tuple[float, float, float]; n_matched: int` (gains = (gR, gG, gB)).
- `photometric_gains(img: AstroImage, wcs, gaia: list[GaiaStar], *, min_stars=15) -> SpccResult | None`
  - Detect stars (`sep` on luminance), measure R/G/B aperture flux, drop saturated (any channel ≥ ~0.95 of max) and low-SNR.
  - Project each Gaia star (ra,dec)→pixel via `wcs.world_to_pixel` with the `FITS_Y_DOWN` flip (as `catalog.objects_in_field` does), cross-match to the nearest detected star within a few px (1:1, nearest-neighbour with a distance cap).
  - For matched pairs compute `x = bp_rp`, `yR = log10(R/G)`, `yB = log10(B/G)`.
  - **Sigma-clipped least-squares** linear fit `yR = aR + bR·x`, `yB = aB + bB·x` (iteratively reject >~2.5σ outliers — bad matches, doubles, residual saturation).
  - Solar reference `BP_RP_SUN = 0.82`: `gR = 10**-(aR + bR·0.82)`, `gB = 10**-(aB + bB·0.82)`, `gG = 1`. Then **normalise** the triple by its geometric mean so overall brightness is preserved.
  - Return `None` if `n_matched < min_stars` or the fit is degenerate (→ caller falls back).
- `apply_gains(img, gains) -> AstroImage` — multiply linear channels, clip [0,1], preserve metadata (or reuse a helper in `core/color.py`).

### `nocturne/core/color.py` (modified) — Colour-step option model
- Extend the recorded Colour option to carry a method: `{"method": "sky"|"photometric", "gains": [gR,gG,gB] | None}` (kept backward-compatible with the existing boolean/settings option — see Recipes below).
- `apply_color` gains a photometric branch: if `method == "photometric"` and `gains` are present → apply those gains (fast, deterministic; used by history replay/undo and by the interactive commit). Sky method unchanged.

### `nocturne/steps/…` + `nocturne/ui/…` (modified) — orchestration
- **`ColorStep`** (factory-built): holds the ASTAP settings + a Gaia fetcher so that, for **headless/batch replay** of a `method: photometric` option **with no cached gains**, its `apply()` runs the full SPCC (solve → `query_field` → `photometric_gains`) synchronously, falling back to sky balance on failure.
- **Colour panel** (`ui/step_panels.py`): add the method selector (default Sky).
- **`main_window`**: when the user applies with Photometric selected, run async (`_run_busy`): resolve the WCS (cached `self._solve` if the framing matches, else solve), `query_field`, `photometric_gains`; on success commit a Colour step whose option is `{method: photometric, gains: [...]}` (so undo/redo and preview are instant and deterministic); on any failure fall back to `background_neutralize` and set the status message.

## Data flow

```
[Colour step, Photometric] ──► WCS (cached solve or ASTAP on the linear image)
        │                              │  centre RA/Dec + field radius (from WCS + shape)
        │                              ▼
   sep star detect + R/G/B flux   gaia.query_field(ra,dec,radius)  ──► [GaiaStar…]
        │                              │
        └──────────────┬───────────────┘
                       ▼
        spcc.photometric_gains(img, wcs, gaia)   (cross-match → sigma-clip fit → solar-neutral gains)
                       │  SpccResult(gains, n_matched)  or  None
                       ▼
   apply gains → commit Colour(method=photometric, gains)     |   None → sky balance + status
```

## Error handling / fallback

Every failure path degrades to sky balance and reports a one-line reason; none raises to the user:
- **Not colour** image → nothing to balance (as today).
- **No WCS / solve fails** → "Couldn't plate-solve — used sky balance."
- **Gaia unreachable / query error / empty** (`GaiaError`) → "Couldn't reach Gaia — used sky balance."
- **Too few matched stars / degenerate fit** (`photometric_gains` returns None) → "Too few matched stars — used sky balance."
- Gains are sanity-clamped (e.g. each within [0.2, 5]) so a pathological fit can't wildly miscolour the image; out-of-range → fallback.

## Recipes / batch

- The Colour step serialises as `{stage: color, option: {method: "photometric"}}` (the session gains are **not** written to the recipe — a fixed white balance would be wrong for a batch of different targets).
- On batch/recipe replay, `ColorStep.apply()` sees `method: photometric` with no gains → **re-runs SPCC per image** (solve + Gaia + fit), so each target is calibrated independently; per-image fallback to sky balance if offline/unsolvable.
- Backward compatibility: existing recipes with the old Colour option (no `method`) are treated as `method: sky` — behaviour unchanged.

## Testing

- **`core/spcc.py` (bulk of the tests, pure):** synthetic star field — inject a known per-channel colour cast into stars whose "true" BP−RP values are known; assert `photometric_gains` recovers gains that remove the cast (corrected ratios ≈ solar-neutral at BP−RP 0.82). Cross-match correctness (right star paired, out-of-tolerance dropped). Sigma-clip rejects injected outliers. `< min_stars` → returns None. Saturated stars excluded.
- **`tools/gaia.py`:** `query_field` with a canned CSV via the injected `fetch` → parses the expected `GaiaStar` rows; a fetch that raises → `GaiaError`; ADQL contains the right centre/radius. No live network.
- **`core/color.py`:** `apply_color` with `{method: photometric, gains}` applies those gains; unknown/old option → sky path.
- **UI (`tests/ui`)** with qtbot + mocks: selecting Photometric + apply with a mocked solve + mocked Gaia commits a photometric Colour step; each failure branch falls back to sky balance with the right status. No real network/ASTAP in CI.

## Open questions / risks

1. **Gaia TAP endpoint stability / rate limits** — confirm the sync CSV endpoint + query shape against the live service during implementation; keep a short timeout and a clean fallback. (ESA occasionally changes hostnames; the fetcher is injectable so this is contained.)
2. **Cross-match tolerance & aperture size** — the px tolerance and flux aperture may need tuning on real Seestar data during validation (undersampled stars, field rotation at edges).
3. **Solar reference (0.82)** — a reasonable G2V convention; may fine-tune after real-data validation (some prefer a slightly different white point).
4. **Batch network dependency** — re-running SPCC per batch image needs internet + a solve each; acceptable with fallback, but note it in the batch help/report so it isn't surprising.
