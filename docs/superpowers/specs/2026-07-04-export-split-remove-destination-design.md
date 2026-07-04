# Export Split + Remove Destination Step — Design

**Date:** 2026-07-04
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — ready for implementation planning

## Motivation

The app currently forks at a **Destination** step (right after Import) into two paths:
- **external** — skips the editing tail; exports a single TIFF *or* a starless+stars split.
- **in_app** — the full editing flow, ending in an Export (TIFF/PNG/FITS).

This fork adds branching complexity and an upfront "how do I want to finish?" decision that
really belongs at the moment of saving. The starless+stars split (useful for continuing in
other software) is locked behind the external branch. This change **folds the split into the
normal Export step** and **removes the Destination step entirely**, giving one linear flow and
a simpler mental model.

## Decisions (from discussion)

- **One dropdown** at Export: `TIFF (16-bit) · PNG · FITS · Starless + Stars (two TIFFs)`.
  The split entry is **greyed out when RC-Astro isn't configured** (with a one-line note).
- **One linear path** — the Destination fork is deleted; all editing steps are shown in order.
  Every step is optional (Next past it without applying), so "just do the basics and export"
  is still possible; the early-exit was not a distinct capability, just skipped steps.
- **Keep the "Export" label** (stepper + panel).

## Scope

**In scope**
- Remove the `destination` stage and the `external` branch from the pipeline.
- Delete the `export_external` panel/handler; move the starless+stars split into the unified
  Export panel + `export_final`.
- Update all affected tests to the collapsed flow.

**Out of scope** — no new export formats; no change to the editing steps themselves; the split
still writes two TIFFs (`starless.tif` + `stars.tif`) to a chosen folder, exactly as today.

## Architecture / changes

### `ui/pipeline.py`
- Remove `Stage("destination", "Destination", "destination")` from `_CORE`.
- Delete `_EXTERNAL_TAIL`.
- `path_stages()` takes **no argument** and returns `list(_CORE) + list(_IN_APP_TAIL)`.
- `core_stages()` stays (now without the destination stage). `next_enabled`/`prev_enabled`
  unchanged. `STEP_NAME`/`PROCESSING_ORDER` unchanged (they never included destination/export).

### `ui/step_panels.py`
- Delete the `elif stage.kind == "destination":` branch and the
  `elif stage.kind == "export_external":` branch.
- Remove `EXTERNAL_FORMATS`; extend export formats to include the split:
  `EXPORT_FORMATS = ["TIFF (16-bit)", "PNG", "FITS", "Starless + Stars (two TIFFs)"]`.
- `build_panel(..., split_enabled: bool = False)` — new kwarg. In the `export` branch: build the
  dropdown from `EXPORT_FORMATS`; if `not split_enabled`, disable the last item (index 3) and
  add `_desc_label("Starless + stars split needs RC-Astro (set its path in Settings).")`.
- Remove the `on_destination` and `on_export_external` params from `build_panel`.

### `ui/main_window.py`
- Remove `self.destination`, `set_destination`, and `export_external`.
- In `__init__`: `self._stages = path_stages()` (no destination arg).
- `_rebuild_panel`/`build_panel` call: drop `on_destination`/`on_export_external`; pass
  `split_enabled=rcastro_valid(self.settings)` for the export stage.
- `export_final(fmt)` absorbs the split branch:
  - If `fmt == "Starless + Stars (two TIFFs)"`: re-check `rcastro_valid` (defensive — the option
    is greyed otherwise; if invalid, set a status message and return); ask for a folder
    (`getExistingDirectory`); run `RCAstro(resolve_binary(...)).remove_stars(img, runner=
    self._rc_runner)` → `save_tiff(starless, folder/starless.tif)` + `save_tiff(stars,
    folder/stars.tif)`, wrapped in `self._guarded(...)`.
  - Else: the existing single-file TIFF/PNG/FITS save (unchanged).
- The `RCAstro`/`resolve_binary`/`rcastro_valid` imports (currently used by `export_external`)
  are retained for `export_final`.

## Data flow (Export)

Export panel dropdown → `on_export(fmt)` → `main_window.export_final(fmt)` → either the
single-file save (TIFF/PNG/FITS) or the StarX split (two TIFFs to a folder). No branch state,
no destination — the format string alone selects the behaviour.

## Error handling

- Split chosen without RC-Astro: option is greyed; `export_final` also re-checks and returns
  with a status message (never crashes).
- StarX subprocess failure / file-write error: surfaced via the existing `_guarded` wrapper.
- Cancelled folder/file picker: aborts cleanly (no write, no status error).

## Testing

- **pipeline** (`tests/ui/test_pipeline.py`): `path_stages()` returns the single linear id
  sequence `["load","crop","background","color","stretch","levels","saturation",
  "noise_sharpen","local_contrast","star_reduction","export"]` — asserting **no `destination`**
  and **no `export_external`**; `core_stages()` no longer contains `destination`.
- **step_panels** (`tests/ui/test_step_panels.py`): the `export` panel's `fmt_box` has 4 items;
  the last item is **disabled when `split_enabled=False`**, **enabled when True**; building a
  panel for a removed kind is not exercised (those kinds are gone).
- **main_window** (`tests/ui/test_main_window.py`):
  - `export_final("Starless + Stars (two TIFFs)")` with an injected fake `_rc_runner` and a
    monkeypatched `getExistingDirectory` writes `starless.tif` + `stars.tif`.
  - `export_final("PNG")` (monkeypatched `getSaveFileName`) writes one `.png`.
  - After `open_fits`, `go_next` from `load` lands on `crop` (no `destination` between).
  - `MainWindow` has no `set_destination` / `export_external` attributes.
  - Update `test_default_in_app_path_navigation` to drop the `destination` entry; remove
    `test_external_destination_changes_tail` and `test_export_external_panel_split_gated`.

## Verification (by eye, after merge)

Open an image → step Import → Crop (no Destination) → … → Export: the dropdown lists all four
options. With RC-Astro configured, "Starless + Stars" is selectable and writes two TIFFs to a
chosen folder; without it, the entry is greyed with the note. Whole-image TIFF/PNG/FITS export
unchanged.
