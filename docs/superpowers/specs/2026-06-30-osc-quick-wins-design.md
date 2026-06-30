# OSC Quick Wins — Design (SCNR, Histogram+Levels, Star Reduction)

## Context
Three high-value, OSC-essential features from the backlog. Engine and flow are reused; two
new post-stretch steps are added to the in-app branch.

## Decisions (approved 2026-06-30)
- **SCNR (green removal):** a toggle inside the **Color** step (linear, with neutralization
  / white balance). Default on.
- **Histogram + Levels:** a live **histogram** widget (display) + a **Levels** step
  (black / gamma / white). Full curve editor deferred.
- **Star reduction:** a post-stretch **step**, gated on StarX.
- New in-app tail order: **Stretch → Levels → Saturation → Noise & Sharpen → Star Reduction
  → Export**. External path unchanged.

## 1. SCNR (green removal)
- `core/color.py`: `ColorSettings` gains `remove_green: bool = False`. In `apply_color`,
  when color + `remove_green`: `green = minimum(green, (red + blue) / 2)` (average-neutral
  SCNR), applied after neutralization/white balance.
- `ui/step_panels.py` "auto"/color panel: add a "Remove green cast" checkbox (default
  checked); Apply emits `ColorSettings(neutralize_background=True, white_balance=True,
  remove_green=<checkbox>)`. Expose `w.remove_green_check`.
- `main_window._log_step`: color label is "" (option is a settings object, not shown).

## 2. Histogram + Levels
- `core/histogram.py`: `histogram(img, bins=256) -> dict` → `{"r":counts,"g":counts,
  "b":counts}` for color, or `{"l":counts}` for mono; counts are int arrays length `bins`
  over [0,1].
- `ui/histogram_view.py`: `HistogramView(QWidget)` with `set_image(AstroImage)` that draws
  the channel curves (paintEvent). Placed at the top of the right column; updated from
  `project.current()` in `_refresh`.
- `core/levels.py`: `apply_levels(img, black, gamma, white) -> AstroImage`. With
  `0 <= black < white <= 1`, `gamma > 0`:
  `out = clip((data - black) / (white - black), 0, 1) ** (1 / gamma)`. Preserves is_linear.
- `steps/levels.py: LevelsStep` (`name="Levels"`), `apply(img, (black,gamma,white))`.
- Levels panel: three sliders (black 0–100→0–1, gamma 10–300→0.1–3.0, white 0–100→0–1)
  + Apply → `on_apply((black, gamma, white))`. Expose the three sliders + apply_btn.

## 3. Star reduction
- `core/star_reduction.py`: `reduce_stars(starless, stars, amount) -> AstroImage`.
  Shrink the stars layer with `scipy.ndimage.grey_erosion` (footprint size scales with
  amount), attenuate (`stars * (1 - 0.4*amount)`), then screen-recombine with starless:
  `1 - (1 - starless) * (1 - reduced)`. amount in [0,1].
- `steps/star_reduction.py: StarReductionStep(rcastro)`; options light/medium/strong →
  amount {0.3, 0.6, 0.9}; `apply(img, option)`: `starless, stars = rc.remove_stars(img,
  runner=self._runner)`; return `reduce_stars(starless, stars, amount)`. Requires StarX
  (no free fallback) — gated.
- Panel: kind "process" (light/medium/strong combo), gated on `rcastro_valid`; reuse the
  process-panel disabled-note pattern (note: "Needs RC-Astro").

## Pipeline (`ui/pipeline.py`)
- In-app tail becomes: `saturation` (unchanged) plus new `levels` (after stretch) and
  `star_reduction` (after noise_sharpen). Full in-app order:
  load, destination, crop, background, color, stretch, **levels**, saturation,
  noise_sharpen, **star_reduction**, export.
- `STEP_NAME`: add `levels → "Levels"`, `star_reduction → "Star Reduction"`.
- `PROCESSING_ORDER`: `[crop, background, color, stretch, levels, saturation,
  noise_sharpen, star_reduction]`.

## main_window wiring
- `_step_for`: `levels → LevelsStep()`; `star_reduction → StarReductionStep(rc or None)`
  with `_runner = self._rc_runner` (gated; if rc None the panel's Apply is disabled).
- Levels panel kind is its own (`"levels"`); its Apply uses `on_apply((b,g,w))` → `apply_current`.
- `_rebuild_panel`: star_reduction `apply_enabled = loaded and rcastro_valid`.
- HistogramView updated in `_refresh` from the displayed image.

## Testing
- `core`: SCNR reduces green excess; `apply_levels` darkens/raises black point and gamma
  brightens; `reduce_stars` lowers the star layer's bright-pixel mean and keeps shape;
  `histogram` returns right-length per-channel counts summing to pixel count.
- `ui`: Color panel emits `remove_green`; `HistogramView.set_image` runs; Levels panel
  emits `(b,g,w)`; Star Reduction panel gated without StarX; pipeline in-app order includes
  levels + star_reduction; main_window `_step_for` returns the new step types; applying
  Levels stays on step.

## Out of scope
Full interactive curve editor; star reduction without StarX (no good free fallback).
