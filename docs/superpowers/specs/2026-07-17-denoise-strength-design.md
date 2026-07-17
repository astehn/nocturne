# Denoise preset recalibration

**Date:** 2026-07-17
**Status:** Approved
**Scope:** `nocturne/steps/noise_sharpen.py` (+ its test)

## Problem

Nocturne's Noise Reduction "medium" preset visibly under-denoises real Seestar
stacks — a benchmark (NGC 7000 master, RC-Astro green) showed heavy residual
chroma mottle vs a clean PixInsight NoiseXTerminator result at its default
(Denoise 0.90, no separation). Audit + a strength sweep on the same master
found the cause is simply that our preset strengths are too low, and that the
single `_LEVELS` map feeds the same number to both the NoiseX (`nxt`) path and
the free TV-denoise fallback, coupling them.

Evidence (high-pass pixel noise ×1000, and sep star count, on the stretched
master):

| NoiseX strength | noise R/G/B | stars |
|---|---|---|
| none | 79/65/85 | 1904 |
| 0.75 | 38/30/33 | 4514 |
| 0.90 | 34/27/27 | 5212 |
| 0.95 | 33/26/26 | 5366 |

Noise reduction has a knee at ~0.90 (= PixInsight's default); star count rises
with strength (no erosion — cleaner background reveals faint stars); crops show
no plastic/over-smoothed look through 0.95.

## Design

### Recalibrate NoiseX strengths, decouple the fallback

In `nocturne/steps/noise_sharpen.py`, replace the single `_LEVELS` map with two:

```python
_NXT_LEVELS = {"light": 0.75, "medium": 0.90, "strong": 0.95}  # RC-Astro NoiseXTerminator --denoise
_TV_LEVELS = {"light": 0.4, "medium": 0.7, "strong": 0.9}       # free TV fallback (unchanged)
```

`apply()` selects the map by path:

```python
def apply(self, img, option):
    if self._rc is not None:
        return self._rc.denoise(img, _NXT_LEVELS[option], runner=self._runner)
    return reduce_noise(img, _TV_LEVELS[option])
```

- **NoiseX path** gets the new, evidence-based strengths.
- **Free TV path** keeps its exact current numbers (0.4/0.7/0.9) — no blind
  retune of a path we have not benchmarked; free-tier users see no change.
- No CLI flag changes — plain `--denoise` (matches the PI default that produced
  the good benchmark).

### What does not change

- `RCAstro.denoise` and `reduce_noise` signatures — untouched.
- Recipes/batch: the option is serialized as the label (`"medium"`), not the
  number, so existing recipes automatically pick up the stronger NoiseX
  strength with no migration.
- Pipeline position (post-stretch): the audit showed linear-vs-stretched and
  full-vs-starless make no meaningful noise difference on this data — strength
  is the only lever, so ordering stays as-is.

## Testing

- Unit (`tests/steps/test_noise_sharpen.py` or existing location): with an
  injected RC-Astro stub, `apply(img, "medium")` calls `denoise` with `0.90`
  (and light→0.75, strong→0.95); with `rcastro=None`, `apply(img, "medium")`
  routes to `reduce_noise` with `0.7` (fallback unchanged).
- Validation: replay the user's `~/Desktop/Noise.json` recipe (color → stretch
  0.5 → noise medium) on the NGC 7000 master with the new presets; confirm the
  denoised output visually matches the PixInsight-quality reference and that the
  star count does not drop vs the undenoised base (proven in the sweep).

## Out of scope (deliberate)

- Pipeline reordering / dual-track starless architecture (separate future
  deep-dive; justified by star-bloat control + detail, not noise).
- Retuning the free TV fallback (no benchmark showing it is broken).
- Extra NoiseX controls (intensity/color/frequency separation) — PI's good
  result used none; keeps the one-control-per-step philosophy.
