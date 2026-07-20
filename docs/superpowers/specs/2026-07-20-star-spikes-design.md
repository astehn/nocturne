# Diffraction Star Spikes — Design

**Status:** approved (2026-07-20)
**Group:** B (Enhancements), item 3 of 4
**Author:** Nocturne pipeline-audit initiative

## Problem

Refractor-based smart telescopes like the ZWO Seestar produce **no diffraction
spikes** — the four-point (or six-point) star flares that reflector/spider-vane
scopes give, and that many people associate with a "proper" astrophoto. Nocturne
has no way to add that aesthetic flourish.

## Goal

Add a **Star Spikes** step that draws tasteful, colour-matched diffraction
spikes on the brightest stars, with sliders for length, how many stars, and
rotation angle — live-previewed, and gentle by default so it never looks fake.

Non-goal: physically accurate diffraction modelling; this is a cosmetic overlay.

## Placement

A new pipeline stage inserted **after Star Reduction, before Enhancements**:

```
… Local Contrast → Star Reduction → [Star Spikes] → Enhancements → Export
```

Rationale: spikes are a finishing flourish and should be drawn last, on the
final star field — so if the user shrank the stars first, the spikes sit on the
reduced stars rather than on stars that then get shrunk. It operates in display
space, joins `POST_STRETCH_IDS`, and is recipe-serializable.

## Architecture

One pure-numpy core module (no new dependency — `sep` is already used by the
stacking grader):

**`nocturne/core/star_spikes.py`**

```python
def detect_stars(data: np.ndarray) -> list[Star]
def add_spikes(img: AstroImage, stars: list[Star],
               length: float, count: int, angle: float) -> AstroImage
```

- `detect_stars` runs `sep.extract` on the display-space luminance and returns a
  list of stars (centroid, flux, sampled colour), **brightest first**. It is the
  moderately expensive part and is **cached once on entering the step** — exactly
  as Star Reduction caches its StarX split — so the three sliders then re-render
  instantly from the cached list.
- `add_spikes` is a pure render from a star list + the three parameters.

`Star` is a small record: `(x: float, y: float, flux: float, color: tuple[float,
float, float])`. A lightweight tuple or dataclass; the module owns its shape.

## Algorithm

### Detection (`detect_stars`, cached on entry)
On the display-space luminance `L = mean(RGB)` (or `L = data` for greyscale):
- `bkg = sep.Background(L); objects = sep.extract(L - bkg, thresh, err=bkg.globalrms)`
  (the same call shape the grader uses in `stacking/grade.py`).
- Sort `objects` by `flux` descending; keep the top **100** (an upper bound; the
  Number-of-stars slider selects how many actually get drawn).
- For each kept object, sample the source image's RGB at the rounded centroid →
  the star's **colour**. Greyscale → colour is `(1, 1, 1)`.
- Return `list[Star]`, brightest first. Empty list if `sep` finds nothing.

### Rendering (`add_spikes(img, stars, length, count, angle)`), all numpy
- If `length == 0` or `count == 0` or `stars` is empty → exact no-op (return a
  copy of the input).
- Take the brightest `count` stars (`stars[:count]`). Normalise fluxes to
  `[0,1]` against the brightest → `w` per star.
- `max_len = 0.08 * min(H, W)`; each star's arm length `arm = length * max_len *
  (0.4 + 0.6 * w)` (brighter stars get longer spikes).
- Build a float RGB **spike layer** (zeros). For each star, for each of 4 arm
  directions at angles `angle, angle+90, angle+180, angle+270` (degrees):
  - March `t` from `0` to `arm`; at each step the arm point is `center + t *
    (cos, sin)`. Splat a **Gaussian-thickness** profile (sigma ≈ 1 px) across the
    arm, with intensity `w * (1 - t/arm)` (linear falloff, zero at the tip),
    accumulated into the layer scaled by the star's `color`.
- **Screen-blend** onto the image: `out = 1 - (1 - img) * (1 - clip(layer,0,1))`
  (adds light without harsh clipping — the same screen op used by
  `star_reduction` and the narrowband palette), then clip `[0,1]`.
- `is_linear` and `metadata` preserved; output `float32`. Greyscale → spikes
  drawn on the single channel (white).

### Parameters and gating
- **Length** `[0,1]` (0 = off, the default). Scales arm length and, via the
  falloff, overall prominence.
- **Number of stars** integer `0–50` (default **6**). Selects the top-N brightest.
- **Rotation angle** degrees `0–90` (default **0**). Because a 4-point cross is
  90°-symmetric, `0–90` covers every distinct orientation (e.g. 45° = diagonal X).

Default Length 0 means the step is a no-op until engaged; when engaged it starts
gentle (few stars, short arms).

## UI & data flow

**Panel** (`nocturne/ui/step_panels.py`, `kind == "star_spikes"`) — mirrors the
Star Reduction panel (which also gates on a cached detection):
- A description line + a **status label** (`spikes_status`): "Detecting stars…"
  until the cache is ready, then cleared.
- **Length** slider `ResetSlider(0)` + readout `length_val` (`value/100`).
- **Number of stars** slider `ResetSlider(6, 0–50)` + readout `stars_val` (int).
- **Rotation** slider `ResetSlider(0, 0–90)` + readout `angle_val` (`{deg}°`).
- **Apply Star Spikes** button (`apply_btn`).
- Sliders + Apply start **disabled**; main_window enables them once detection
  caches.
- Slider `valueChanged` → `on_spikes_change(length, count, angle)`; Apply →
  `on_spikes_apply(length, count, angle)`.

**Data flow** (`nocturne/ui/main_window.py`) — mirrors Star Reduction's cached
async split:
- On entering the step, `_setup_star_spikes()` kicks off `detect_stars(
  _spikes_base().data)` off-thread via `_run_busy` (synchronous when
  `_async_enabled` is False, i.e. in tests), stores `self._spikes_stars`, and
  enables the panel controls.
- `_spikes_base()` = `project.state_at(_leading_kept(entries, preceding))` where
  `preceding` = geometry + the processing steps up to `star_spikes` — the same
  pre-step base the commit uses (WYSIWYG).
- `_on_spikes_change(length, count, angle)` stashes the values and starts a 90 ms
  single-shot timer; `_render_spikes_preview` renders `add_spikes(_spikes_base(),
  self._spikes_stars, length, count, angle)` through the shared `_show_preview`.
- **Commit**: Apply routes through the generic `apply_current` path with option
  `(length, count, angle)`. `StarSpikesStep.apply` is **self-contained** — it
  calls `detect_stars` then `add_spikes` — so recipe replay and batch need no
  cached state. The live preview uses the cache only for speed; the committed
  result is identical to the preview.
- `_rebuild_panel`: on entering `star_spikes`, reset `_spikes_pending = None`,
  wire the callbacks, and call `_setup_star_spikes()`.

**Recipe**: option is `(length, count, angle)`; serialize as `[length, count,
angle]`, deserialize back to a tuple — its own branch (not the float branch).

**Log label**: add `"star_spikes"` to the `_log_step` cases so the raw parameter
tuple isn't shown as a label (use a short formatted label or empty, consistent
with the other multi-parameter steps like `levels`/`curves`).

## Testing

**`tests/core/test_star_spikes.py`**
- `detect_stars` on a synthetic image with one bright dot returns that dot's
  centroid (within ~1 px), brightest-first, with a sampled colour; empty image →
  empty list.
- `add_spikes` with `length == 0` or `count == 0` → exact no-op (`np.allclose`).
- A single bright star with `length > 0`: pixels **along the 4 arms** through the
  centre are brightened; a background pixel far off any arm is unchanged.
- Brighter star → longer arm than a fainter star (measure lit extent).
- `angle = 45` puts lit pixels on the diagonal (not purely horizontal/vertical).
- The star's colour tints its spikes (spike pixels carry the star's hue).
- Output within `[0,1]`, `float32`; `is_linear`/`metadata` preserved.
- Greyscale (2-D) input → valid 2-D result with white spikes.
- `count` greater than the number of stars is handled (no index error).

**`tests/ui/test_step_panels.py`**
- The `star_spikes` panel exposes `length_slider`, `stars_slider`,
  `angle_slider`, their readouts, `spikes_status`, and `apply_btn`; sliders start
  disabled; `on_spikes_change` fires with `(length, count, angle)`.

**`tests/ui/test_main_window.py`**
- Entering the step caches stars and enables the controls (synchronous with
  `_async_enabled = False`).
- `_render_spikes_preview` renders without committing (no new history entry) and
  feeds the histogram.
- Apply commits a Star Spikes step; `StarSpikesStep.apply` (self-contained
  detect+render) produces a finite in-range result.

## Real-data validation (final task)

Drive the three sliders on a real star field: confirm detection lands on the
bright stars, spikes look intentional (not fake) and colour-matched, brighter
stars get bolder spikes, rotation behaves, and the live preview equals the
committed result. Present before/after for sign-off. Do not merge until
confirmed. Tune the auto constants (`max_len` fraction, falloff, thickness,
default count) here if needed.

## Out of scope (future)

- 6-point / configurable vane count (only 4-point + rotation for now).
- Per-star manual selection or exclusion.
- Physically accurate diffraction PSF.
