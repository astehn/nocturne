# Mosaic panels: match colour, not only brightness

**Written 2026-09-04. To run unattended while Andreas is out.**

Say **"execute the mosaic colour plan"** and this document is the whole brief.

---

## The problem, in one paragraph

`mosaic.match_offsets` collapses each panel's overlap to **luminance** and solves
for **one scalar per panel**, applied equally to R, G and B. So panel
*brightness* is matched across every overlap by weighted least squares — and
panel *colour* is not matched at all. Across a 39-pointing session running
several hours, sky colour changes, and each panel keeps its own tint. On
Andreas' M 31 mosaic that shows as a patchwork of rectangular tiles, invisible
at normal saturation and unmistakable at ×3.

```python
# nocturne/stacking/mosaic.py, inside match_offsets
li, lj = li.mean(axis=-1), lj.mean(axis=-1)      # <- RGB collapsed to luminance
d = float(np.median(lj) - np.median(li))         # <- one scalar for all channels
```

**More data would not fix this.** It is systematic, not noise. That matters
because the weather is poor and no more mosaic data is coming.

## What to build

Solve the offsets **per channel**: three independent least-squares solves
instead of one on the mean. The graph-Laplacian machinery is already correct
and well documented — area-weighted, every overlap solved at once rather than
chained, each connected component anchored on its first panel. **Keep all of
it**; only the quantity being solved for changes.

Files:

- `nocturne/stacking/mosaic.py`
  - `match_offsets(layers, valids, on_progress=None)` — return a per-panel
    **sequence of three** offsets for colour input, and keep returning a scalar
    for mono. The overlap medians must be taken per channel.
  - `combine_panels(...)` — `data + off` must broadcast a 3-vector across the
    channel axis. It currently adds a float.
  - `run_mosaic` — no change expected; it just passes `offsets` through.
- Tests: `tests/stacking/test_mosaic.py`

Keep the anchoring behaviour: a panel overlapping nothing keeps its own level,
in every channel. Inventing an offset there moves real signal.

## Acceptance

1. **Mono still works.** A single-channel mosaic must behave exactly as now.
2. **A synthetic colour tilt is removed.** Build panels that overlap and differ
   by a known per-channel constant; after matching, the overlaps must agree in
   all three channels, not just in luminance. This is the test that would have
   failed before the change.
3. **The existing offset tests still pass** — the least-squares behaviour, the
   four-panel-ring case, and the anchor rule are all already covered.
4. **The real mosaic improves**, measured (see below), not judged by eye.

## How to verify on real data — the fast test first

**Do NOT start with the drizzle run.** The tiling is an offset problem, not a
drizzle one, so it reproduces in an ordinary mosaic that costs minutes instead
of hours.

```
Folder:  /Volumes/Work/Astro/M 31_mosaic_sub          # 392 subs, 39 pointings
ASTAP:   /Applications/ASTAP.app                      # resolved internally
```

Run **the same mosaic twice** — once on `main` as it stands, once with the
change — with `method="sigma_clip"` (NOT drizzle), `autocrop=True`, writing into
a temp dir. Then measure both with the baseline script below and compare.

A 3-panel/18-sub mosaic took 18.8 s on 2026-09-02, so 39 panels is expected in
the tens of minutes. **Time the first one and report it** — if it runs past
~45 minutes, stop and say so rather than pressing on.

Only if the fast test shows a real improvement is the full drizzle re-run worth
it, and that one is ~2 hours.

### The measurement

`docs/mosaic-colour/baseline.json` holds the current numbers, measured from
Andreas' finished starless export:

| | value |
|---|---|
| brightness spread across background patches | 8.373% |
| colour-ratio spread, mean of R/G/B | 2.376% |
| per channel | R 1.588% · G 2.764% · B 2.775% |

**The colour-ratio spread is the number that must fall.** Brightness spread
should stay roughly where it is — it includes the real sky gradient and the
galaxy's outer halo, so driving it to zero would mean subtracting signal.

The exact measurement is the `tiling_metrics` function used to produce that
file: resize by 1/16, take 24 background patches from the LEFT 40% (away from
the galaxy), and report the spread of each channel's ratio to the patch mean.
Re-implement it identically or the comparison is meaningless.

Also produce a ×3-saturation preview of each result, as
`docs/mosaic-colour/before-starless-saturated.jpg` was produced — that is the
image that made the problem obvious, and it is how Andreas will judge it.

## Report back with

- the two measurements side by side, and the % change in colour spread;
- the two saturated previews;
- wall-clock time for the mosaic run;
- whether the full drizzle re-run looks worth doing.

**Do not release anything.** The change lands as a commit on main; Andreas
tests before it ships.

## Hard constraints

- **Never modify anything under `/Volumes/Work/Astro` or on the Seestar.**
  Those are the only copies of these nights. Read the subs, write masters to a
  temp directory.
- Full suite green before committing: `.venv/bin/python -m pytest tests/ -q`
  (~2248 tests, ~2 minutes).
- Mutation-test the new guards — break each, watch it fail, restore, clearing
  `__pycache__` between runs.
- This touches image data and the stacking pipeline, so per `CLAUDE.md` it gets
  the full treatment: adversarial review at the end, not just tests.

## If it does not work

Say so plainly and stop. A negative result recorded is worth more than a change
kept because it was built — the `_weights` broadcast optimisation on 2026-09-04
was reverted for exactly that reason, and the note in `TODO.md` now stops anyone
re-trying it.

Plausible ways this disappoints, none of them reasons to force it:

- The residual after matching is dominated by something else — a per-panel
  gradient rather than a constant, which a single offset per channel cannot fix
  whatever colour space it works in.
- The overlaps are too small on the perimeter panels to measure a reliable
  median, so the outermost tiles stay mismatched.
- Colour differences are multiplicative (transparency) rather than additive
  (sky glow), in which case a *scale* per channel is the right model and an
  offset is not. If the measurement says this, report it — that is a design
  finding, not a failure.
