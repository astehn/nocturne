# Changelog

All notable changes to Nocturne. This project uses [semantic versioning](https://semver.org/); while pre-1.0, minor versions add features.

## [0.5.0] — 2026-07-31

Know exactly what you're looking at — pixel readout, clipping warnings, and a precise cursor.

### Added
- Hover pixel readout — a floating pill reports the pixel under your cursor: R/G/B (or V for mono) plus L luminance. Before Stretch it shows four decimals and tags the reading "linear", because the preview is auto-stretched while the value underneath is not.
- Clipping warning — from Stretch onward, a live summary under the histogram shows how much of the image is blown or crushed, naming the worst channel, and turns amber past a threshold calibrated on real Seestar stacks. Tick Show clipping to paint the affected pixels on the canvas (blue shadows, red highlights) live, even mid-slider-drag.
- Crosshair cursor over the image, so you can tell precisely which pixel a reading belongs to — the normal cursor everywhere else, and the grab hand while panning.
- Batch processing gained a Cancel button, and each failed file is now named with the reason it failed instead of a bare success count.

### Changed
- The Levels-only clipping checkbox is retired — clipping feedback is now global and works on every step from Stretch on, including Curves.
- Share and Upscale now ask you to Stretch first rather than silently producing a near-black result from linear data.
- Histogram redraws about 4x faster (126 ms to 36 ms on an 8 MP frame), so live previews are smoother.
- The in-app update link now uses HTTPS.

### Fixed
- Nocturne failed to start when run from a source checkout — a toolbar icon was missing from the repository, so launching from a fresh clone raised an error. The downloadable app was unaffected.
- Auto Enhance now gates on a crop and respects the crop you chose.
- Remove Green's live preview goes through the same canvas path as every other step, so what you see matches what applies.

## [0.4.2] — 2026-07-26

Five new one-tap Enhancements, plus recipe/batch capture and an in-app update check.

### Added
- Five new Enhancements taps — Star Colour (recover stars' natural colour via a star/starless split), Vibrance (oversaturation-resistant colour pop), Boost Gold (warm hue boost for dust and star fields), Dark Structure (definition in dust lanes and dark nebulae), and Soft Glow (dreamy Orton-style bloom).
- Enhancements taps are now captured in Recipes and replayed in Batch, so finishing survives folder processing.
- In-app "Update available" indicator — a fail-silent GitHub check on launch (no telemetry).

### Changed
- Refreshed in-app help, README, and testers' guide to cover the newer tools (Auto Enhance, Plate Solve, Share, Upscale Crop, Saved Projects, Provenance, Photometric/SPCC colour, ASTAP).

### Fixed
- The crop overlay now stays within the image — resizing or moving the box clamps to the bounds.

## [0.4.1] — 2026-07-25

Plate-solving fixed in the app build

### Fixed
- Plate Solve now works in the downloaded app — a packaging issue had it failing to solve or annotate (it had always worked when run from source).
- macOS "Get Info" now reports the correct app version.
- A plate-solve that can't complete now explains why, instead of showing a generic message.

## [0.4.0] — 2026-07-25

Saved projects, one-tap Auto Enhance, and shareable exports

### Added
- Saved Projects — save your whole editing session as a .nocturne file and reopen it exactly, pixel for pixel.
- Auto Enhance — one adaptive tap that detects dual-band vs broadband data and processes accordingly.
- Share — reframe and caption an image for social, then export or copy to the clipboard.
- Upscale Crop — a 2× layered upscale of any crop, exported or opened as a copy.
- Provenance report — a readable record of every step applied to an image, from the Project menu (Save or Copy).
- Cancel, live progress and failure diagnostics for long operations (stacking, grading, Auto Enhance, external tools).
- A histogram info strip (resolution · integration · target), Close Project, recent projects, and refreshed toolbar icons.

### Changed
- Auto Enhance reworked to always use photometric colour with a gentler stretch.
- The right panel no longer shifts as status messages update, and the message panels clear when a new image is opened.

### Fixed
- Readable FITS import details, a Close button on every dialog, and the Star Spikes preview now opens fitted to the image.

## [0.3.0] — 2026-07-23

The big feature build-out since the initial public release.

### Added
- **Plate Solve & Annotate** — solve any frame with ASTAP to identify the target and overlay deep-sky object labels, named stars, a compass and a scale bar. Annotations burn into PNG exports and the WCS is written into exported FITS.
- **Photometric colour calibration (SPCC)** — Gaia-based white balance in the Colour step, with an automatic fall-back to sky balance.
- **Guided Narrowband tool** — map Ha/OIII into finished palettes with a live preview, on the stars-removed image or the whole frame.
- **Curves** (a smooth monotone-cubic editor) and **HDR core recovery** for bright galaxy and nebula cores.
- **Star Spikes** — artistic diffraction spikes.
- **Denoise engine choice** — RC-Astro NoiseXTerminator, GraXpert, or a built-in method.
- **Frame grading in stacking** — a per-sub verdict, a strictness control, quality-ranked integration and a plain-language summary of what was kept.
- Free star separation, so Star Reduction, Remove Green Fringe and the nebula saturation boost work without RC-Astro.
- Remove Green Fringe, a masked nebula saturation boost, a default working folder, and spacebar before/after peek.

### Changed
- **Interface overhaul** — feedback is split into a timestamped log, a copyable output area, and a prominent warning area beside the buttons; Back/Next are pinned so they never shift; the detailed step-help is now a collapsible panel that remembers your choice; successes are no longer shown in alarm red.
- Every pipeline step audited and refined for beginners: accurate import integration time, a reworked Crop, per-channel Stretch, and live-preview Levels / Saturation / Local Contrast / Star Reduction.
- Robust background-neutralization replaces grey-world white balance in the Colour step (preserves real nebula colour).

### Fixed
- Numerous correctness and stability fixes across import, stacking, colour and the star-split pipeline.

## [0.2.0]

Prior baseline: the guided, non-destructive pipeline (live preview + full undo), built-in stacking, one-press Colourise, Ha/OIII extraction, real narrowband palettes, recipes & batch, and the native macOS app.
