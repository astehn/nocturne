# Remove Green Fringe — Design (revised: star-layer targeted)

**Status:** approved (2026-07-20; revised after real-data validation)
**Group:** B (Enhancements), corrective finishing tool
**Author:** Nocturne pipeline-audit initiative

## Problem

OSC/refractor data (including the Seestar) commonly shows a green colour fringe
or halo around stars — a chromatic-aberration / debayering artifact. Stars are
never truly green, so the fringe is always an artifact worth removing.

A first design applied a **global** green-excess suppression (reduce green
wherever `G > (R+B)/2`). Real-data testing showed this over-corrects: it
re-removes the broad, faint green in the *background and nebula* (which the early
Color-step Remove Green already handled), tipping the whole image toward magenta.
The fix must touch **only the stars**, leaving the background and nebula colour
untouched.

## Goal

Add a **Remove Green Fringe** finishing step that splits the image into starless
+ stars layers (StarXTerminator), suppresses green *only on the stars layer*, and
recombines — so the background and nebula are literally never modified. Strength
slider, live preview, gated on RC-Astro like Star Reduction.

## Placement

A new pipeline stage **after Saturation, before Noise Reduction** (unchanged):

```
… Levels → Curves → Saturation → [Remove Green Fringe] → Noise Reduction → Local Contrast → Star Reduction → …
```

It operates in display space, joins `POST_STRETCH_IDS`, and is recipe-serializable
as a float strength.

## Architecture & Algorithm

This mirrors the **Star Reduction** architecture: a slow StarXTerminator split runs
once on entering the step (off-thread, cached), and the strength slider then
previews an instant recombination.

**Core** (`nocturne/core/color.py`):

```python
def remove_green_fringe(starless: AstroImage, stars: AstroImage,
                        strength: float) -> AstroImage
```

- `strength` clamped `[0,1]`.
- De-green the **stars layer only** via green-excess suppression: on
  `stars.data`, `avg_rb = (R+B)/2`; `excess = max(G - avg_rb, 0)`;
  `G_new = G - strength * excess` (red/blue untouched).
- **Recombine by screen** with the untouched starless background:
  `out = 1 - (1 - starless) * (1 - degreened_stars)` — the same screen op Star
  Reduction uses. Because `starless` is passed through unchanged, the background
  and nebula colour are preserved exactly.
- `strength == 0` → `out == 1 - (1-starless)*(1-stars)` (the original recombined
  image; an exact no-op relative to the split input). Output clipped `[0,1]`
  float32; `is_linear`/`metadata` taken from `starless`.
- The per-pixel green-excess op is factored into a small helper
  `_suppress_green_excess(data: np.ndarray, strength: float) -> np.ndarray` so
  it can be unit-tested directly and reused.

**Step** (`nocturne/steps/green_fringe.py`) — mirrors `StarReductionStep`:

```python
class GreenFringeStep(Step):
    def __init__(self, rcastro: RCAstro) -> None: ...
    def apply(self, img, option):
        starless, stars = self._rc.remove_stars(img, runner=self._runner)
        strength = float(option) if option not in (None, "") else 0.0
        return remove_green_fringe(starless, stars, strength)
```

Self-contained (splits internally) so recipe replay / batch work. The factory
constructs `GreenFringeStep(RCAstro(resolve_binary(settings.rcastro_path)))`,
exactly like `StarReductionStep`.

## UI & data flow (mirrors Star Reduction)

**Panel** (`nocturne/ui/step_panels.py`, `kind == "green_fringe"`):
- A description line + a **status label** (`fringe_status`) — set to "Separating
  stars…", "Needs RC-Astro — set its path in Settings.", or cleared.
- A **Strength** slider `ResetSlider(0)` + numeric readout (`fringe_val`).
- An **Apply Remove Green Fringe** button.
- Slider + Apply start **disabled**; enabled once the split has cached.
- Slider `valueChanged` → `on_fringe_change(strength)`; Apply →
  `on_fringe_apply(strength)` (a custom commit that reuses the cached split — NOT
  the generic `apply_current`, exactly like Star Reduction's `on_sr_apply`).

**main_window** (`nocturne/ui/main_window.py`) — mirrors `_setup_star_reduction`
/ `_on_sr_split` / `_render_sr_preview` / `_apply_star_reduction`:
- `_fringe_layers` cache `(sig, starless, stars)`, `_fringe_pending`,
  `_fringe_ready`, `_fringe_timer` (90 ms).
- `_fringe_base()` = `state_at(_leading_kept(entries, preceding-up-to-green_fringe))`
  — the same pre-step base the split and commit share (WYSIWYG).
- `_setup_green_fringe()` on entering the stage: if `not rcastro_valid(settings)`
  → disable controls + "Needs RC-Astro…" message and stop. Else reuse a cached
  split for the same base sig, or run `self._remove_stars(base)` off-thread
  (`_run_busy`, synchronous in tests) and cache it, disabling controls with
  "Separating stars…" meanwhile.
- `_on_fringe_split(sig, layers)` caches the split and enables the controls
  (guarded by `current_stage_id() == "green_fringe"`).
- `_on_fringe_change(strength)` stashes + starts the timer when ready;
  `_render_fringe_preview()` renders `remove_green_fringe(starless, stars,
  strength)` from the cache through the shared `_show_preview` (image + histogram).
- `_apply_green_fringe(strength)` commits `remove_green_fringe(...)` from the
  cached split via `run_step(_PrecomputedStep("Remove Green Fringe", result),
  float(strength))`, logs, and refreshes — no StarX rerun.
- `_rebuild_panel` on entering `green_fringe` resets `_fringe_pending`, wires
  `on_fringe_change`/`on_fringe_apply`, and calls `_setup_green_fringe()`.

The `_sr_sig` fingerprint helper is reused for the cache key.

**Recipe** — the option is a float strength; the existing float
serialize/deserialize branch already covers `green_fringe`.

## Testing

**`tests/core/test_green_fringe.py`**
- `_suppress_green_excess`: green-excess reduced, red/blue untouched, neutral/red
  pixel untouched, `strength=0` no-op.
- `remove_green_fringe(starless, stars, 0)` equals the plain screen recombine
  `1-(1-starless)*(1-stars)` (exact no-op).
- `remove_green_fringe` with `strength>0` reduces green in the star regions while
  a background (starless) region with `stars==0` is unchanged in the output.
- Output `[0,1]` float32; `is_linear`/`metadata` from starless.

**`tests/steps/test_factory.py`**
- `make_step("green_fringe", settings)` returns a `GreenFringeStep`;
  `GreenFringeStep(fake_rc).apply(img, s)` splits via the injected rc and calls
  `remove_green_fringe` (use a fake rc whose `remove_stars` returns synthetic
  starless/stars).

**`tests/ui/test_step_panels.py`**
- The `green_fringe` panel exposes `fringe_status`, `fringe_slider`, `fringe_val`,
  `apply_btn`; slider + Apply start disabled; `on_fringe_change` and
  `on_fringe_apply` fire with the scaled strength.

**`tests/ui/test_main_window.py`**
- Entering `green_fringe` with RC-Astro **invalid** disables the slider/Apply and
  shows the "Needs RC-Astro" message.
- With a monkeypatched `_remove_stars` returning synthetic layers and
  `rcastro_valid` true, entering the stage caches the split and enables controls
  (synchronous with `_async_enabled = False`); `_render_fringe_preview` renders
  without committing; `_apply_green_fringe` records a "Remove Green Fringe" step.

## Real-data validation (final task)

Drive Strength on a real green-fringe image: confirm the green fringe/halo on
stars fades while the background and nebula colour are unchanged (no magenta
shift), and the live preview equals the committed result. Present before/after
for sign-off. Do not merge until confirmed.

## Out of scope (future)

- A non-RC-Astro fallback (brightness-weighted or sep-mask) for users without
  StarXTerminator — deferred; the step is simply gated off when RC-Astro is absent.
