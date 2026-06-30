# Seestar Processor — UX Polish Pass Design

## Context

After running the spec-aligned flow on real images, the user reported concrete UX gaps.
This pass addresses them. The pipeline order, engine (GraXpert/RC-Astro adapters, stretch,
history, export), and destination branch are unchanged — this is interaction polish plus a
rebuilt Crop step.

## Findings → changes (all approved 2026-06-30)

### 1. Crop rebuild (Step 3) — interactive box + more controls
- Auto-detect of the stacking border **seeds** an interactive crop rectangle drawn on the
  preview (drag to move; corner/edge handles to resize). The overlay updates live so the
  user sees exactly what will be removed before applying.
- Controls (this step intentionally exceeds "one control" — user override):
  - **Aspect ratio**: Original / 1:1 / 16:9 / 4:5 / 3:2 (constrains the box).
  - **Rotate 90°** and **Flip H / Flip V**.
  - **Margin** slider: shrink the box inward from the detected edge.
- `CropStep` applies a settings object: crop `bounds` (top,bottom,left,right in image
  pixels), `aspect`, `rotate` (0/90/180/270 cw), `flip_h`, `flip_v`. Order: rotate → flip
  → crop to bounds. The box is expressed in pre-rotate image coordinates for predictability.

### 2. Destination (Step 2) — descriptive buttons
- Replace the radio buttons with two large buttons, each with a one-sentence description:
  - **Continue in external software** — "Runs the core steps, exports a 16-bit TIFF for
    Photoshop/PixInsight, then stops."
  - **Finish here** — "Takes the image all the way to a share-ready file in the app."
- Clicking a button sets the destination (same `set_destination` behavior) and advances.

### 3. Background (Step 4) — explainer + correct gating
- Add a one-line description: "Removes light-pollution gradients so the sky background is
  even."
- Gating fix: **"off" is always appliable** (no tool needed). **light / strong** are
  enabled only when the GraXpert path is valid; when disabled, show inline text:
  "Needs GraXpert — set its path in Settings."

### 4. Color visibility (Step 5)
- Root cause: the display autostretch stretches **each channel independently**, which
  re-neutralizes color for display and hides the calibration. Fix: the preview uses a
  **linked stretch** — compute the midtones transfer from luminance and apply the *same*
  transfer to all channels — so background-neutralization and white-balance are visible.
- `autostretch(img)` gains linked behavior for color images (single transfer from the
  luminance channel's statistics applied to R, G, B). Mono unchanged.

### 5. Settings — verify paths, required vs optional
- Each path row gets a **Test** button that runs the binary (`graxpert -v`;
  `rc-astro --no-banner --help`) via subprocess and shows ✓ + detected version on success
  or ✗ + the error on failure.
- Labels: **GraXpert (required)** and **RC-Astro (optional)**, with a short note that
  RC-Astro unlocks BlurX/NoiseX/StarX and the starless+stars export.

### 6. Progress + no double-fire
- Step processing runs on a **background worker thread** (QThreadPool/QRunnable) so the UI
  stays responsive. While a step runs: a **"Working…" busy overlay** covers the preview and
  Apply/Back/Next are disabled; on completion the result renders and controls re-enable.
- A second Apply while busy is ignored (guard flag), eliminating button-smashing.

### 7. Stay on step after Apply
- Applying a processing step updates the preview **in place** and does NOT auto-advance.
  The user toggles Before/After to compare, then clicks **Next** to move on.

## Architecture / units

- `ui/image_view.py` — add an optional **crop-overlay mode**: `set_crop_box(bounds)`,
  `crop_box() -> bounds`, draggable `QGraphicsRectItem` with handles, optional
  aspect-ratio lock; emits `cropBoxChanged`. Zoom/pan still work when overlay is off.
- `core/crop.py` — `CropParams` dataclass (bounds, aspect, rotate, flip_h, flip_v) +
  `apply_crop_params(img, params)`. Keep `detect_content_bounds`/`auto_crop`.
- `steps/crop_auto.py` → `steps/crop.py` `CropStep` applying `CropParams`.
- `core/autostretch.py` — linked stretch for color.
- `ui/step_panels.py` — destination buttons; background explainer + gating text; crop
  panel (aspect/rotate/flip/margin) wired to the overlay; (saturation/export unchanged).
- `ui/settings_dialog.py` — Test buttons + required/optional labels; needs a tester
  helper `tools/probe.py` (`probe_binary(path, args) -> (ok, message)`).
- `ui/worker.py` — `run_async(fn, on_done, on_error)` wrapping QThreadPool; `ui/busy.py`
  or an overlay widget for the "Working…" state.
- `ui/main_window.py` — async apply (worker + busy overlay + guard), no auto-advance,
  crop overlay wiring, linked-preview rendering.

## Testing

- `core`: `apply_crop_params` (bounds/rotate/flip order, aspect), linked `autostretch`
  preserves color ratios (a color cast survives the stretch, unlike per-channel).
- `tools/probe`: success/failure parsing with a fake runner.
- `steps`: `CropStep` applies params; background "off" no-op vs light/strong.
- `ui` (pytest-qt): destination buttons emit the choice; settings Test shows ✓/✗;
  ImageView crop box round-trips bounds; MainWindow does NOT advance after Apply; Apply is
  blocked while a (fake, slow) worker is busy; background Apply enabled for "off" without
  GraXpert. Background-thread tests use a synchronous fake runner / `qtbot.waitUntil`.

## Out of scope
Pipeline reordering, new processing steps, project save/reopen.
