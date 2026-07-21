# GraXpert AI Denoise + Engine Choice — Design

**Status:** design approved by the user 2026-07-21 (both global default + per-image override;
RC-Astro is the default when both are installed). GraXpert denoise CLI verified empirically
against the user's GraXpert 3.0.2. Spec awaiting user review before the implementation plan.

## Problem & goal

Without RC-Astro **NoiseXTerminator** (paid; the user's trial is expiring), Nocturne's
Noise Reduction step falls back to skimage TV denoising — a crude "watercolour" smear that
flattens faint nebulosity. But **GraXpert (already installed for Background extraction) has a
free AI denoiser**, and Nocturne already has a `GraXpert.denoise` wrapper — just unwired and
using the wrong CLI flag.

Goal: **wire GraXpert AI denoise into the Noise Reduction step as a first-class engine**, with
user choice of engine (global default + per-image override) and graceful fallback:
- Both NoiseXTerminator and GraXpert installed → user chooses (default: RC-Astro).
- Only one installed → use that one.
- Neither installed → the TV fallback (unchanged).

## Verified facts (GraXpert 3.0.2, tested against the real binary)

- `-cmd denoising` selects a **separate "GraXpert Denoising" argparse** that does NOT accept
  `-smoothing` (that flag is background-extraction only, and denoising errors on it).
- The denoise strength flag is **`-strength` (`--denoise_strength`), 0–1**. Full invocation:
  `graxpert -cli -cmd denoising <in.fits> -output <out> -strength <s>`.
- Strength is graduated and monotonic: on a σ=0.106 noisy test frame, `-strength 0.3` → σ 0.090
  (mean|Δ| 0.017), `-strength 0.9` → σ 0.071 (mean|Δ| 0.052). So light/medium/strong presets are
  meaningful.
- GraXpert appends its own extension to `-output` (e.g. `out` → `out.fits`); the existing
  wrapper's `_find_output` (scans the temp dir for the non-input image) already handles this.

## Starting point (what exists)

- `nocturne/steps/noise_sharpen.py` `NoiseSharpenStep(rcastro)`: `apply` → `rc.denoise(...)` if
  RC-Astro present, else `reduce_noise` (TV). Presets `_NXT_LEVELS = {light:0.75, medium:0.90,
  strong:0.95}`, `_TV_LEVELS = {light:0.4, medium:0.7, strong:0.9}`.
- `nocturne/tools/graxpert.py` `GraXpert.denoise(img, strength)` calls the shared `_run` which
  hardcodes `-smoothing` — **wrong for denoising** (must be `-strength`).
- `nocturne/settings.py`: `graxpert_path`, `rcastro_path`; `graxpert_valid(s)`, `rcastro_valid(s)`.
- `nocturne/steps/factory.py` `noise_sharpen`: builds `rc` only (GraXpert not passed).
- `nocturne/ui/step_panels.py`: Noise panel uses generic light/medium/strong preset buttons
  (`_PRESET_STEPS["noise_sharpen"]`).
- `nocturne/recipe.py`: `noise_sharpen` option serialised as a bare string (the level).

## Architecture

### 1. Fix `GraXpert.denoise` (tools/graxpert.py)

Denoise must pass `-strength`, not `-smoothing`. Split the CLI so background-extraction keeps
`-smoothing` and denoising uses `-strength` (e.g. `_run` takes the strength flag name, or denoise
builds its own args). Keep the `_find_output` handling. Do not force `-gpu`; let GraXpert default.

### 2. Engine resolution (steps/noise_sharpen.py)

`NoiseSharpenStep(rcastro, graxpert)` — both tool handles, either may be `None` (not installed).

Preset strengths:
- NoiseX `_NXT_LEVELS = {light:0.75, medium:0.90, strong:0.95}` (unchanged).
- **GraXpert `_GX_LEVELS = {light:0.5, medium:0.7, strong:0.9}`** (starting point — calibrate on
  real data during validation).
- TV `_TV_LEVELS = {light:0.4, medium:0.7, strong:0.9}` (unchanged).

`apply(img, option)` parses `option` → `(engine, level)` where `engine ∈ {"rcastro","graxpert",
None}` and `level ∈ {light,medium,strong}`. Resolve with fallback, then dispatch:

```
order = ["graxpert","rcastro"] if engine == "graxpert"
        else ["rcastro","graxpert"]        # rcastro chosen, OR None/legacy: prefer RC-Astro
for e in order:
    if e == "rcastro" and self._rc:  return self._rc.denoise(img, _NXT_LEVELS[level], runner=...)
    if e == "graxpert" and self._gx: return self._gx.denoise(img, _GX_LEVELS[level], runner=...)
return reduce_noise(img, _TV_LEVELS[level])   # neither installed
```

This yields exactly the required behaviour: both→chosen (RC-Astro default), one→that one,
neither→TV — and if a recipe's chosen engine is absent on the replay machine, it falls back to
the other installed engine before TV.

### 3. Settings — global default engine

Add `Settings.denoise_engine: str = "rcastro"` (persisted in settings.json, read defensively).
The Settings dialog gains a **"Preferred denoise engine"** dropdown: **RC-Astro** / **GraXpert**.
Used when both are installed and the panel override is "Default".

### 4. Noise panel — per-image override

When **both** engines are installed, the Noise Reduction panel shows an **"Engine"** dropdown:
**Default** (follow the Settings preference) / **RC-Astro** / **GraXpert**. Hidden when fewer than
two are installed (nothing to choose). The current selection feeds the applied option.

### 5. Live-apply wiring (main_window)

When the user applies Noise Reduction, resolve the concrete engine = the panel override if it is
a concrete engine, else `settings.denoise_engine`; record the option as `(engine, level)` so it is
reproducible. (The step still degrades gracefully if that engine is later unavailable.)

### 6. Recipe / batch capture

`noise_sharpen` option becomes `{"engine": "rcastro"|"graxpert", "level": "light|medium|strong"}`.
`serialize_option`/`deserialize_option` handle the dict; a **legacy bare string** ("medium") still
deserialises (engine `None` → auto-resolve, preferring RC-Astro). Factory builds both tools:
`gx = GraXpert(resolve_binary(settings.graxpert_path)) if graxpert_valid(settings) else None`,
`rc = RCAstro(...) if rcastro_valid(settings) else None`, `NoiseSharpenStep(rc, gx)`. Batch replays
via factory; a GraXpert recipe on an RC-Astro-only machine falls back to NoiseX.

## Error handling

- Neither engine installed → TV fallback (no error, existing behaviour).
- Chosen engine's binary present but the run fails → surfaces as the step's normal error path
  (unchanged from how RC-Astro failures surface today); the tool is not silently swapped mid-run.
- Legacy recipe (bare-string option) → engine `None` → auto-resolve.

## Testing

- **Wrapper (`tests/`):** `GraXpert.denoise` builds `-cmd denoising … -strength <s>` (a fake runner
  captures argv and asserts `-strength` present, `-smoothing` absent); background-extraction still
  builds `-smoothing`.
- **Engine resolution (`tests/steps/`):** the full matrix — both installed + engine="rcastro" →
  NoiseX; both + "graxpert" → GraXpert; both + None (legacy) → RC-Astro; only GraXpert + engine=
  "rcastro" → falls back to GraXpert; only RC-Astro + "graxpert" → falls back to NoiseX; neither →
  TV. Use fake tool objects that record which was called.
- **Recipe:** `{"engine","level"}` round-trips serialize→deserialize→apply; a legacy bare string
  deserialises to auto-engine; not reported by `uncaptured_step_names` (already captured).
- **Settings:** `denoise_engine` persists and defaults to "rcastro".
- **UI:** the Engine dropdown appears only when both installed; its selection reaches the applied
  option. Follow existing panel-test patterns.
- Keep the full suite green.

## Validation (before merge)

User validates on real Seestar data (NGC 7000): GraXpert AI denoise vs NoiseXTerminator vs the TV
fallback — judge quality and **calibrate `_GX_LEVELS`** (light/medium/strong) so the presets feel
right. Confirm the engine dropdown + global default behave as expected.

## Out of scope (future)

- Chaining GraXpert denoise into other steps.
- A separate GraXpert "denoise + sharpen" combined mode.
- GPU-toggle exposure (`-gpu`) — leave GraXpert's default.

## Build process

Subagent-driven, TDD: wrapper fix → engine resolution + presets → settings field + dialog → panel
dropdown + main_window wiring → recipe/factory → whole-branch review → user validation → merge.
