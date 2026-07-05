# Linear Deconvolution Step — Design

**Date:** 2026-07-05
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — building under standing authorization.

## Motivation

BlurXTerminator (BXT) is used today only inside "Noise & Sharpen", **post-stretch** and nebula-only
(`sharpen_stars=0.0`). But BXT is a **deconvolution** tool: it corrects the point-spread function and
works best on **linear** data, run early — tightening stars and recovering fine detail before the
stretch. AstroWizard runs BXT on linear (its Step 6, before Stretch). Add a proper **linear
Deconvolution step** before Stretch, and split sharpening out of "Noise & Sharpen" so BXT runs
exactly once, in the right place.

## Decisions (from discussion)

- **New "Deconvolution" step**, linear, positioned **Background → Color → Deconvolution → Stretch**.
  Runs BXT on the linear image sharpening **stars and nebula**; presets Light / Medium / Strong,
  default Medium. Because it's before the Stretch position, it also precedes **Colourise**, so the
  narrowband flow is deconvolved too.
- **"Noise & Sharpen" → "Noise Reduction"** (denoise only): the sharpen moves out, so BXT runs once.
- **Free fallback** without RC-Astro: the existing unsharp-mask `core/deconvolution.sharpen`
  (labelled honestly as a sharpen, not true deconvolution). It is NOT gated-disabled — the step
  always works, better with RC-Astro.
- **Deferred:** a real Lucy-Richardson free fallback; recipe capture; per-target auto strength.

## Architecture / changes

### `steps/deconvolution_step.py` (new)
```python
class DeconvolutionStep(Step):
    name = "Deconvolution"
    _LEVELS = {"light": (0.3, 0.3), "medium": (0.5, 0.5), "strong": (0.7, 0.7)}  # (stars, nonstellar)
    def __init__(self, rcastro=None):
        self._rc = rcastro
        self._runner = run_cli
    def options(self): return ["light", "medium", "strong"]
    def default_option(self): return "medium"
    def apply(self, img, option):
        ss, sn = self._LEVELS[option]
        if self._rc is not None:
            return self._rc.deconvolve(img, sharpen_stars=ss, sharpen_nonstellar=sn,
                                       runner=self._runner)
        return sharpen(img, sn)          # free unsharp-mask fallback
```
(Deconvolution runs on **linear** data, so `sharpen_stars > 0` is safe/desirable — tighter stars.)

### `steps/factory.py`
```python
    if stage_id == "deconvolution":
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        step = DeconvolutionStep(rc)
        step._runner = rc_runner
        return step
```

### `ui/pipeline.py`
- Add `Stage("deconvolution", "Deconvolution", "process")` to `_CORE` **after `color`, before
  `stretch`**.
- `STEP_NAME["deconvolution"] = "Deconvolution"`.
- Insert `"deconvolution"` into `PROCESSING_ORDER` after `"remove_green"`, before `"stretch"`:
  `[background, color, remove_green, deconvolution, stretch, levels, ...]`.
- Because deconvolution precedes the stretch position, `_colourise`/`apply_current` preserve it
  automatically (it's included in `_stretch_preceding()` and every post-stretch step's `preceding`).

### `steps/noise_sharpen.py` → denoise-only ("Noise Reduction")
Drop the BXT `deconvolve`/free `sharpen` calls; keep NoiseXTerminator denoise (free `reduce_noise`
fallback):
```python
class NoiseSharpenStep(Step):          # id stays "noise_sharpen"; behaviour now denoise-only
    name = "Noise Reduction"
    _LEVELS = {"light": 0.4, "medium": 0.7, "strong": 0.9}   # denoise strengths
    def apply(self, img, option):
        dn = self._LEVELS[option]
        if self._rc is not None:
            return self._rc.denoise(img, dn, runner=self._runner)
        return reduce_noise(img, dn)
```
- `STEP_NAME["noise_sharpen"] = "Noise Reduction"`; the `_IN_APP_TAIL` stage label → "Noise
  Reduction". (Stage id kept `"noise_sharpen"` to avoid churn.)

### `ui/step_panels.py`
- `_PROCESS_OPTIONS["deconvolution"] = ["light", "medium", "strong"]`.
- `_DESCRIPTIONS["deconvolution"] = "Sharpens stars and recovers fine detail (deconvolution) on the
  linear image, before stretch. Best with RC-Astro; free fallback otherwise."`
- Update `_DESCRIPTIONS["noise_sharpen"] = "Reduces grain (noise reduction)."`.

## Data flow

Linear master → Background → Color → **Deconvolution** (BXT linear / free sharpen) → Stretch or
Colourise → … → **Noise Reduction** (denoise) → Local Contrast → Star Reduction → Export. One BXT
pass, on linear, early; denoise stays post-stretch and cosmetic.

## Error handling

- No RC-Astro → free unsharp fallback (step still works, not disabled).
- RC-Astro CLI error → surfaces via the existing async apply err path (like other process steps).
- `option` always one of light/medium/strong (panel-constrained).

## Testing

- **steps** (`tests/steps/`):
  - `DeconvolutionStep().apply(img, "medium")` with no RC-Astro changes the image (free sharpen path).
  - With a fake RC-Astro runner, `apply` calls `deconvolve` with `sharpen_stars > 0` (records the
    args, mirroring the existing rcastro test pattern).
  - `make_step("deconvolution", settings)` returns a `DeconvolutionStep`.
  - `NoiseSharpenStep().apply(...)` now denoises only — with a fake RC-Astro it calls `denoise` and
    NOT `deconvolve` (assert the product sequence is just `["nxt"]`, updating the existing
    `test_new_steps` product-order assertion).
- **pipeline** (`tests/ui/test_pipeline.py`): `PROCESSING_ORDER` has `"deconvolution"` between
  `"remove_green"` and `"stretch"`; `STEP_NAME["deconvolution"] == "Deconvolution"`;
  `STEP_NAME["noise_sharpen"] == "Noise Reduction"`; a `deconvolution` Stage exists in the core path
  before the `stretch` stage.
- **step_panels** (`tests/ui/test_step_panels.py`): a `deconvolution` process panel offers
  light/medium/strong and emits the chosen option; the noise panel description no longer says
  "sharpen".
- **main_window** (`tests/ui/test_main_window.py`): update `test_default_in_app_path_navigation`'s
  expected stage sequence to include `"deconvolution"` after `"color"`; a deconvolution apply records
  a "Deconvolution" step and is preserved after a later step (e.g. Stretch).
- Full suite green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`).

## Verification (by eye)

On a linear master: Background → **Deconvolution (Medium)** → stars visibly tighter and fine nebula
detail sharper → Stretch/Colourise looks crisper. "Noise Reduction" later only denoises (no
double-sharpen). Without RC-Astro, Deconvolution still applies a free sharpen.
