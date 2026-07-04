# Saturation Remap — Design

**Date:** 2026-07-04
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — ready for implementation planning

## Motivation

The Saturation step is **additive-only**: `factor = 1 + amount·(1 − lum)`, so `amount = 0` is
native saturation (never desaturates) and even maxed the effect is gentle. From real-data use:
"you must crank it to see effect, low settings still look fully saturated, and you can't mute
colour." Fix: re-centre the slider so the **middle is native**, the left **desaturates** (down
to greyscale), and the right **boosts harder** than today.

## Decisions (from discussion)

- **Slider curve:** `0 = greyscale · 50 = native (no change) · 100 = strong`. Symmetric,
  centre-neutral.
- **Star protection:** keep the lightness-aware taper on the **boost** side (the extra above
  native fades toward highlights, so bright stars stay natural while the nebula gets colour).
- **Default:** slider at **50** (native).

## The remap (core/saturation.py)

Slider value `t ∈ [0, 1]` (panel sends `slider.value()/100`) → chroma multiplier `s`, applied
as `out = lum + (data − lum) · s_px`, clipped to [0,1]:

- **Desaturate side (`t ≤ 0.5`):** `s = 2·t` → `t=0 → 0` (greyscale), `t=0.5 → 1` (native).
  Applied **uniformly** (`s_px = s`) — pulling a pixel toward grey evenly, including stars.
- **Boost side (`t > 0.5`):** `s = 1 + (2·t − 1)·(S_MAX − 1)` → `t=0.5 → 1`, `t=1 → S_MAX`.
  **Star protection:** taper the extra above native by luminance —
  `s_px = 1 + (s − 1)·(1 − lum)` — full boost in shadows, ~native at highlights.

`S_MAX = 2.5` (documented starting point; stronger than today's implicit ~2). Tunable by eye on
real data. `lum = data.mean(axis=2, keepdims=True)`.

New signature keeps `saturate(img: AstroImage, amount: float) -> AstroImage`, but **`amount`
now means the slider position where 0.5 = native** (was `0 = native`). Behaviour:
- Mono / non-colour image → returned unchanged (any amount).
- `amount == 0.5` → true no-op (native).
- Remove the old `if amount <= 0: return copy` guard (0 now means greyscale, not no-op).

Reference implementation:

```python
def saturate(img: AstroImage, amount: float) -> AstroImage:
    """Re-centred saturation: amount 0=greyscale, 0.5=native, 1=strong boost.
    The boost above native tapers toward highlights so bright stars keep natural
    colour; desaturation is uniform. Mono is returned unchanged."""
    if not img.is_color:
        return img.copy()
    S_MAX = 2.5
    t = float(amount)
    data = img.data
    lum = data.mean(axis=2, keepdims=True)
    if t <= 0.5:
        s_px = 2.0 * t                       # 0 -> grey, 0.5 -> native; uniform
    else:
        s = 1.0 + (2.0 * t - 1.0) * (S_MAX - 1.0)
        s_px = 1.0 + (s - 1.0) * (1.0 - lum)  # taper the boost toward highlights
    out = np.clip(lum + (data - lum) * s_px, 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear,
                      metadata=dict(img.metadata))
```

(When `t <= 0.5`, `s_px` is a scalar; NumPy broadcasts it against `(data - lum)`. When
`t > 0.5`, `s_px` has shape `(H, W, 1)` and broadcasts per pixel.)

## Panel (ui/step_panels.py, saturation branch)

- Slider default **40 → 50**.
- Label: `"Saturation"` → **`"Saturation (mute ← native → boost)"`**; description
  `"Boost colour intensity."` → **`"Drag left to mute colour, right to boost. Centre = no change."`**
- Add a centre tick: `slider.setTickPosition(QSlider.TickPosition.TicksBelow)` and
  `slider.setTickInterval(50)` so "neutral" is visually marked.
- The apply wiring is unchanged: `on_apply(slider.value() / 100.0)`.

## Compatibility

The `saturate` parameter's meaning changes (0.5 = native instead of 0). A **recipe** saved with
the old model stores a saturation float that will now be reinterpreted (e.g. an old `0.4` boost
reads as slight desaturation). No migration — the app is pre-release and recipes are the user's
own; documented so it isn't a surprise. `recipe.py` (de)serialization is unaffected (saturation
stays a float).

## Error handling

Pure numeric op on [0,1] data; no new failure modes. `amount` outside [0,1] is not produced by
the slider; values clip naturally (t>1 would just cap at S_MAX-ish via the formula; t<0 → grey).

## Testing (tests/core/test_saturation.py + panel test)

Use a small known coloured image (e.g. a dark pixel `(0.4, 0.1, 0.1)` and a bright pixel
`(0.9, 0.6, 0.6)`), `chroma = max(rgb) - min(rgb)` as the saturation proxy:
- `saturate(img, 0.5)` returns the data **unchanged** (native no-op) within tolerance.
- `saturate(img, 0.0)` → **greyscale**: each pixel R=G=B (chroma ≈ 0).
- `saturate(img, 0.25)` → **partial desaturation**: chroma reduced vs native but > 0.
- `saturate(img, 1.0)` → **boost**: the dark pixel's chroma exceeds its native chroma; and the
  taper holds — the bright pixel's chroma increases **less** than the dark pixel's (relative to
  each one's native), i.e. highlights are protected.
- **Monotonic** for the fixed dark coloured pixel: chroma(0) < chroma(0.25) < chroma(0.5) <
  chroma(0.75) < chroma(1.0).
- Mono image (2D) unchanged for `amount` in {0, 0.5, 1}.
- Panel: building the saturation panel yields `sat_slider.value() == 50`.

## Verification (by eye, after merge)

Open a colour image → Saturation: slider starts centred (native). Drag left → colour mutes to
grey; drag right → nebula colour deepens while stars stay natural. Tune `S_MAX` if the top feels
weak or garish.
