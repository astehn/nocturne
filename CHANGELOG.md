# Changelog

All notable changes to Nocturne. This project uses [semantic versioning](https://semver.org/); while pre-1.0, minor versions add features.

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
