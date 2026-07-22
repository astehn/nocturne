# Plate Solve & Annotate — Design Spec

**Status:** Draft for review · 2026-07-22
**Depends on:** ASTAP (external, user-installed) · OpenNGC catalogue (bundled)
**Unlocks later (separate specs):** Photometric colour calibration (SPCC) · Mosaic stitching

## Goal

Add offline **plate-solving** to Nocturne as an optional external tool, plus its two first novice payoffs:

1. **Target auto-identification** — "you shot NGC 7000 · North America Nebula", shown in the Import panel.
2. **Annotation overlay** — deep-sky object labels (M/NGC/IC + common names), a compass (N/E), and an angular scale bar drawn over the image, optionally burned into the export.

Plate-solving is the *infrastructure*; these two payoffs are the shippable v1. It also produces a WCS that a later SPCC-colour spec and a later mosaic spec will build on.

## Scope

**In scope (v1):**
- ASTAP detect-and-shell-out, configured in Settings exactly like RC-Astro / GraXpert (path + Test + status chip).
- Solve the **currently displayed image** on demand; cache the result; feed the target name into the Import panel.
- Annotation overlay in the viewer (DSO labels + compass + scale bar), toggleable.
- Optional "Burn annotations into export" for raster formats; write solved WCS keywords into exported **FITS**.
- Capture RA/DEC hints from the source FITS header to speed the solve.

**Explicitly out of scope (later specs / not now):**
- Photometric colour calibration (SPCC) — needs Gaia photometry; separate spec.
- Mosaic / panel stitching — needs multi-panel WCS reproject; separate spec.
- Constellation lines and named-star labels — annotation v2.
- Transforming a WCS *through* Crop/Rotate/Flip — we **re-solve the current image** instead (see Decision 3).
- Any online solver (nova.astrometry.net) — ASTAP-only, per decision. If ASTAP is absent, the feature is simply unavailable (like RC-Astro steps today).
- A pure-Python/bundled solver.

## User experience

**Setup (once):** Settings → **ASTAP (optional)** path field + Browse + Test, mirroring the GraXpert/RC-Astro rows. A toolbar status chip shows `ASTAP ✓/✗`. The user installs ASTAP and its ~100 MB **D05** database themselves (matches the S30 Pro's ~4°×2.24° field); Nocturne never distributes either.

**Solve + identify:** A toolbar **Plate Solve…** action (grouped with Stack / Ha·OIII / Narrowband). Activating it:
- If ASTAP isn't configured → status-bar hint "Set the ASTAP path in Settings to plate-solve." (no error).
- Else solves the current displayed image asynchronously (busy status "Plate-solving…"), caches the WCS, and:
  - populates the Import panel's **Target** line with the identified object(s),
  - turns on the **annotation overlay**.
- Re-activating toggles the overlay off/on. If the image state changed since the last solve (crop/rotate/flip/step), the cache is invalid and the next activation re-solves.

**Annotation overlay:** DSO labels positioned on their objects, a compass rose (N/E from the WCS), and a scale bar (arcmin). Constant on-screen size regardless of zoom/pan.

**Export:** the Export panel gains a **Burn annotations** checkbox (enabled only once solved). Annotation is a *presentation* artifact, not data, so burn-in produces an **8-bit rendered image** (PNG) — the display image plus the overlay rasterised via `QImage`. The 16-bit TIFF and FITS **data** exports are never burned (they stay pixel-faithful); FITS instead gets the solved **WCS keywords written into its header** (via the existing `save_fits(header=...)` path) whenever a solve exists, independent of the checkbox. So: checkbox → annotated PNG; FITS → WCS in header; TIFF/Starless untouched.

## Architecture & components

New modules, following existing patterns (file refs are the templates to copy):

### Core (pure, testable — no Qt)
- **`nocturne/tools/astap.py`** — the ASTAP wrapper, templated on `tools/rcastro.py` + `tools/base.py`.
  - `class ASTAP: __init__(self, binary_path)`.
  - `solve(self, img: AstroImage, *, fov_deg: float | None = None, ra_hours: float | None = None, dec_deg: float | None = None, runner=run_cli) -> SolveResult`.
  - Writes a temp FITS (`write_temp_fits`), runs ASTAP, parses the `.wcs` sidecar into an `astropy.wcs.WCS`, cleans up the temp dir in `finally`.
  - `SolveResult` dataclass: `wcs` (astropy WCS), `center` (SkyCoord), `fov_deg` (solved), `pixscale_arcsec` (from CD matrix), `solved: bool`.
  - **ASTAP CLI contract:** `astap -f <in.fits> [-fov <height_deg>] [-r <radius_deg>] [-ra <hours>] [-spd <dec+90>] -wcs -o <base>`. Success → exit 0 + `<base>.wcs` (FITS keywords CRVAL1/2, CRPIX1/2, CD1_1…); no solution → exit 1; error → exit 2. The wrapper must inspect the **exit code** (ASTAP returns nonzero on no-solution, so `run_cli`'s raise-on-nonzero must be caught and the `ToolError.returncode` mapped to solved=False vs error). It also reads the `.ini` `PLTSOLVD` flag as a cross-check.
  - **Y-axis convention:** ASTAP FITS is bottom-row-first; Nocturne display arrays are top-row-first (see `_read_corrected` in `rcastro.py`). The parsed WCS must be flipped on the Y axis to match Nocturne's top-down pixel coordinates before it's used for overlay positioning.
- **`nocturne/core/catalog.py`** — bundled DSO catalogue access.
  - Loads a trimmed **OpenNGC** table shipped at `nocturne/data/openngc.csv` (name, common name, RA, Dec, major axis, type).
  - `objects_in_field(wcs, shape) -> list[CatalogObject]` — projects catalogue RA/Dec through the WCS, keeps those landing inside the image with their pixel (x, y) and on-screen size.
  - `identify_target(objects, shape) -> str` — pick the most prominent object near frame centre (largest angular size / closest to centre) for the "Target" line; may return the top 1–2.
- **`nocturne/core/annotate.py`** — geometry for the overlay (pure math, no Qt).
  - `compass(wcs, shape) -> (north_angle, east_angle)` — screen angles of N/E from the WCS CD matrix.
  - `scale_bar(pixscale_arcsec, shape) -> (length_px, label)` — a "nice" round angular length (e.g. 10′, 30′) and its pixel length.

### UI (Qt)
- **`nocturne/ui/annotation_overlay.py`** — a `QGraphicsItemGroup` (or a managed set of items) added to `ImageView._scene`.
  - Label/compass/scale-bar items positioned in **scene = display-pixel coords** (WCS→pixel gives these directly), flagged `ItemIgnoresTransformations` so they stay constant size under zoom/pan — same technique as the crop handles.
  - `ImageView` gains `set_annotations(overlay | None)` and a teardown, mirroring `set_crop_overlay` / `set_compare` (image_view.py:353–359). Z-value above the image, below crop handles.
- **Settings** (`ui/settings_dialog.py`): add `self._astap` line-edit, `_astap_result` label, an `addRow("ASTAP (optional)", _path_row(...))`, and `_test_astap`. (See Decision 5 on the Test action.)
- **`settings.py`**: add `astap_path: str = ""` to `Settings`; add `astap_path=data.get("astap_path", "")` in `load_settings` and `astap_path=self._astap.text().strip()` in the dialog's `result_settings` (both are non-generic and drop unknown fields otherwise); add `astap_valid(s)` mirroring `rcastro_valid`.
- **`main_window.py`**:
  - toolbar action + `_open_plate_solve` handler (async solve via the `run_async`/`QThreadPool` pattern from `narrowband_dialog.py`, with a busy/status label).
  - cache `self._solve = (sig, SolveResult, objects)` keyed by a display-image signature (reuse the `_sr_sig` fingerprint approach); invalidate when the signature changes.
  - store the solved name in `metadata["target_solved"]` (a **distinct** key — never overwrite the header/filename `"target"`); `import_summary` adds a separate **"Target (solved)"** line when the key is present. `_rebuild_panel` already calls `import_summary`, so the line appears on the next panel rebuild.
  - status chip in `_update_tools_label`.
- **Export** (`ui/step_panels.py` + `main_window.export_final`): `w.burn_annotations` checkbox in the export branch (enabled only when a valid solve exists). When set with PNG selected, render the display image + overlay to a `QImage` and save it (8-bit). For FITS, pass the solved WCS keys to `save_fits(header=...)` regardless of the checkbox. TIFF-16 and Starless+Stars ignore burn-in.

### Data / packaging
- **OpenNGC** trimmed CSV bundled under `nocturne/data/` (a few MB). License **CC BY-SA 4.0** — bundle with attribution in About/Help/NOTICE. This is *not* the Gaia-derived solver DB, so it's freely bundle-able.
- Capture **RA/DEC** in `core/fits_io.py::_parse_metadata` (add `OBJCTRA`/`OBJCTDEC`/`RA`/`DEC` to the mapping) to seed the solve. Falls back to blind solve if absent.
- **PyInstaller** (`packaging/nocturne.spec`): add `hiddenimports += collect_submodules("astropy.wcs") + collect_submodules("astropy.coordinates")`; add `nocturne/data/openngc.csv` to `datas`. Verify against `dist/Nocturne.app` that no matplotlib pull-in is introduced (the spec already excludes matplotlib and warns about astropy's wcsaxes hook).

## Data flow

```
Import FITS ──► metadata (incl. RA/DEC hint if present)
                     │
   [Plate Solve…] ──►│  write current display image → temp FITS
                     ▼
             ASTAP solve (-fov est, -ra/-spd hint) ──► .wcs sidecar
                     │  parse → astropy WCS (Y-flip to top-down)
                     ▼
          catalog.objects_in_field(wcs, shape) ──► [labels @ (x,y), sizes]
                     │                                    │
        identify_target ──► Import "Target" line     annotate.compass / scale_bar
                                                          │
                                        AnnotationOverlay on ImageView (toggle)
                                                          │
                                  Export: burn raster  /  save_fits(header=wcs)
```

**FOV estimate for the solve:** plate scale = `206.265 × pixel_size_µm / focal_length_mm` arcsec/px (both are already in `metadata`); vertical FOV = `pixscale × current_height / 3600` deg. Pass as `-fov`; ASTAP still refines. If focal/pixel metadata is missing, omit `-fov` (blind on scale).

## Key technical decisions

1. **ASTAP-only, detect-and-shell-out.** No bundled/online solver. Zero distribution and zero licensing burden (the Gaia-derived D05 DB is CC BY-NC 3.0 IGO — never touched by us because the user's own ASTAP fetches it). Identical trust model to RC-Astro.
2. **Solve the display-space image, not the linear master.** The overlay must match what's on screen (WYSIWYG). ASTAP centroids stars regardless of stretch, so a stretched image solves fine; and solving the current frame means the WCS is automatically correct for the current crop/rotate/flip.
3. **Re-solve on change; do not transform the WCS through geometry.** No WCS-vs-geometry composition code exists, and building it is error-prone. Cache the solve against a display-image signature; a changed signature (any geometry or step edit) invalidates it and the next Annotate re-solves. Solves are seconds and cached, so this is cheap and always correct. The *target name* is geometry-invariant, so it survives crop/rotate as-is once known.
4. **Overlay lives in scene(=pixel) coords with `ItemIgnoresTransformations`.** Zoom/pan come free from `QGraphicsView`; labels stay legible at constant size. Same mechanism as crop handles.
5. **Settings "Test" for ASTAP.** ASTAP has no clean exit-0 `--version`/`--help` probe. v1 Test = validate the binary resolves and is executable (`astap_valid`); optionally attempt a lightweight invocation if a reliable exit-0 arg is found during implementation. Do **not** run a full solve for the Test. (Implementation task should confirm ASTAP's actual probe behaviour.)
6. **Seed with header RA/DEC when present.** Seestar masters usually carry pointing; passing `-ra/-spd` turns a blind solve into a near-instant local one. Blind fallback otherwise.

## Error handling & edge cases

- **ASTAP not configured / not found:** feature unavailable; status-bar hint, no error dialog. Toolbar chip shows `ASTAP ✗`.
- **Solve fails (exit 1 / `PLTSOLVD=F`):** status message "Couldn't plate-solve this image — try after Stretch, or check the field isn't mostly empty." No overlay, no crash. (Solving works best once stars are visible; suggest running it on a stretched image.)
- **Solve error (exit 2 / missing DB):** status message pointing at ASTAP's database install ("ASTAP has no star database for this field — install D05 in ASTAP.").
- **Solved but no catalogue objects in field:** still draw compass + scale bar + set nothing for Target ("Solved — no catalogued DSO in frame").
- **Mono image / linear image:** solving is allowed (stars present); annotation is colour-agnostic. No `is_color` gate. (Unlike Narrowband, no colour requirement.)
- **Overlay after the image changes:** signature mismatch → overlay auto-clears and the Target line reverts to header/filename until re-solved.
- **Export burn-in when not solved:** checkbox disabled until a valid solve exists for the current image.

## Testing strategy

- **`tools/astap.py`:** inject a fake `runner` (as RC-Astro tests do) that writes a canned `.wcs` sidecar; assert the wrapper parses CRVAL/CRPIX/CD into a WCS, applies the Y-flip, and maps exit codes 0/1/2 → solved/no-solution/error. Test temp-dir cleanup.
- **`core/catalog.py`:** with a synthetic WCS over a known field, assert `objects_in_field` keeps in-field objects with correct pixel positions and drops out-of-field ones; `identify_target` picks the central/largest object. Use a tiny fixture catalogue.
- **`core/annotate.py`:** `compass` returns correct N/E angles for a known CD matrix (incl. a flipped/rotated one); `scale_bar` picks a sane round length and correct pixel length for a given pixscale.
- **`core/fits_io.py`:** `_parse_metadata` captures RA/DEC from `OBJCTRA/OBJCTDEC`.
- **UI (`tests/ui`)** with the qtbot harness: toolbar action gated on `astap_valid`; solve populates the Target line and shows the overlay; changing the image clears the overlay; export checkbox enabling. Mock the solve (no real ASTAP in CI).
- **Packaging:** manual check that `dist/Nocturne.app` imports `astropy.wcs`/`coordinates` and finds `openngc.csv`.

## Dependencies & footprint

- **User-side:** ASTAP (free, MPL-2.0) + D05 database (~101 MB download / ~137 MB installed) — user-installed, matches the S30 Pro FOV. Not bundled.
- **Nocturne-side:** OpenNGC CSV (~few MB, CC BY-SA 4.0, bundled with attribution). `astropy.wcs`/`coordinates` already available via the existing `astropy>=6.0` dep. No new pip dependency.

## Open questions / risks

1. **ASTAP Test probe** (Decision 5) — confirm during implementation whether ASTAP exposes a clean exit-0 probe; otherwise Test = existence check.
2. **PyInstaller astropy.wcs pull-in** — must be verified in the frozen bundle (risk noted in the spec header); `astropy.wcs` isn't currently exercised so the hook may miss it.
3. **OpenNGC trim** — decide the size/columns of the shipped subset (all NGC/IC/Messier vs a brightness cut). Start with the full OpenNGC (still only a few MB) to avoid missing a user's target.
4. **`.wcs` parse robustness** — ASTAP's `.wcs` is FITS-like ASCII; parse via `astropy.io.fits.Header.fromtextfile` / `WCS(header)`. Confirm the exact sidecar format against a real ASTAP run during implementation.
```
