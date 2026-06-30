# Recipes + Batch — Design

## Context
The founding goal: the processing steps are the same every time. Let the user tune once on a
real image, save that as a **recipe**, and apply it to a whole folder of stacked FITS
unattended. Reuses the existing step engine.

## Decisions (approved 2026-06-30)
- **Recipe creation:** record the current session (a "Save Recipe" action), not a separate editor.
- **Crop in batch:** auto-detect each image's border per image; the recipe stores only
  aspect/rotate/flip (not the manual pixel box).
- **Export format:** chosen at batch time (not stored in the recipe). Recipe = processing steps only.

## Components

### `core/recipe.py`
- `Recipe` dataclass: `steps: list[dict]`, each `{"stage": <stage_id>, "option": <json-safe>}`.
- `serialize_option(stage_id, option) -> json-safe` / `deserialize_option(stage_id, value) -> option`:
  - background / noise_sharpen / local_contrast / star_reduction → str (unchanged).
  - stretch / saturation → float.
  - levels → list `[black, gamma, white]` (tuple round-trips via list).
  - color (`ColorSettings`) → `{"neutralize_background","white_balance","remove_green"}`.
  - crop (`CropParams`) → `{"aspect","rotate","flip_h","flip_v"}` (pixel `bounds` dropped).
- `recipe_from_entries(entries) -> Recipe`: map each `(step_name, option)` via the reverse of
  `STEP_NAME` to a stage id, serialize the option; skip names not in the processing set.
- `save_recipe(recipe, path)` / `load_recipe(path) -> Recipe` (JSON, version field `{"version":1,"steps":[...]}`).

### `steps/factory.py`
- `make_step(stage_id, settings, *, bg_runner=run_cli, rc_runner=run_cli) -> Step`:
  the construction currently in `main_window._step_for` (crop/background/color/stretch/levels/
  saturation/noise_sharpen/local_contrast/star_reduction), using `resolve_binary` + GraXpert/
  RCAstro from `settings`. `main_window._step_for` delegates to it.

### `batch.py`
- `apply_recipe(base, recipe, settings, *, bg_runner=run_cli, rc_runner=run_cli) -> AstroImage`:
  for each step: build via `make_step`; deserialize the option; for `crop`, set
  `bounds = detect_content_bounds(current)` on the `CropParams` before applying; apply in order.
- `run_batch(recipe, input_paths, output_dir, fmt, settings, *, on_progress=None,
  bg_runner=run_cli, rc_runner=run_cli) -> list[dict]`: for each path: `load_fits` →
  `apply_recipe` → export (`save_tiff`/`save_png`/`save_fits` by `fmt`) to
  `output_dir/<stem>.<ext>`; catch per-file exceptions → record `{"path","ok","message"}`;
  call `on_progress(i, n, path)`. Continues past failures.

### UI
- `main_window`: toolbar **"Save Recipe…"** (enabled when a project is loaded) → `recipe_from_entries(self.project.entries())` → `QFileDialog.getSaveFileName(*.json)` → `save_recipe`.
- `ui/batch_dialog.py: BatchDialog` — fields: recipe file (Browse), input folder (Browse), output
  folder (Browse), format combo (TIFF/PNG/FITS), a progress bar + status, Run/Close. Run executes
  `run_batch` on the worker thread (reuse `ui/worker.run_async`), updating the progress bar via the
  `on_progress` callback (marshalled to the UI thread) and showing a final ✓/✗ count. Injectable
  `_batch_runner` (default `run_batch`) for tests.
- `main_window`: toolbar **"Batch…"** opens `BatchDialog(self.settings)`.

## Data flow
Save: session `entries()` → `recipe_from_entries` → JSON file.
Batch: JSON → `load_recipe` → for each FITS, `apply_recipe(load_fits(path), recipe, settings)` →
export. GraXpert/RC-Astro come from `settings` (same as the live app); the RC-Astro vertical-flip
correction already lives in the adapter, so batch output is correctly oriented.

## Testing
- `recipe`: each option type round-trips through serialize/deserialize; `recipe_from_entries`
  drops crop bounds but keeps aspect/rotate/flip and skips non-processing names; `save/load` round-trip.
- `factory`: `make_step` returns the correct types for every stage id.
- `batch`: `apply_recipe` runs an in-app recipe (stretch + saturation + levels) on a base image and
  changes it; crop step uses detected bounds. `run_batch` over two synthetic FITS writes two output
  files for the chosen format and records a failure (e.g., a non-FITS file) without aborting; tool
  steps use injected fake runners.
- `ui`: Save Recipe writes a file `load_recipe` can read back; `BatchDialog` constructs and, with a
  fake `_batch_runner`, runs and reports a summary.

## Out of scope
Editing a saved recipe in a GUI; parallel batch; per-image overrides; recipe versioning beyond v1.
