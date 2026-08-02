# Changelog

All notable changes to Nocturne. This project uses [semantic versioning](https://semver.org/); while pre-1.0, minor versions add features.

## [0.10.0] — 2026-08-02

Trim without losing your edit, a distraction-free view, and labels that stop colliding.

### Added
- Trim — cut the edges off a finished image without losing the edit. Ragged stacking borders and smeared corners are often invisible in the linear data you cropped at the start and only appear once you have stretched, at which point going back to the Crop step would discard every step you had done since. Trim adds a final step instead of reaching back, so the whole edit survives and undo still works. Available once the image is stretched.
- Press F for the image and nothing else — toolbar, step list, panels and the log all step aside so you can judge noise, star shapes and faint detail without the interface competing for attention. Escape returns, and your zoom and position are kept.
- Names for objects that had none. The deep-sky catalogues added recently arrived as bare designations, so the Elephant's Trunk appeared as "vdB 142". Eighteen of the best-known now carry the names people actually use — which also means a frame is more often identified as the thing you pointed at rather than as the largest catalogued region that happens to overlap it.

### Changed
- The in-app help now covers Trim, the full-screen view, the objects-in-field list, the Density control, Re-solve, the clipping line's "on import" reading, and Share's caption and output controls. It also says plainly that plate solving needs ASTAP's star database — a separate download from ASTAP itself, and much the most common reason a solve fails.

### Fixed
- Annotation labels could print on top of one another on a crowded field, rendering "LDN 1109" and "LDN 1110" as a single unreadable smear. Labels stay a fixed size on screen while their spacing was being worked out in image pixels, so at anything below 100% zoom they were larger than the space reserved for them. They now re-place themselves as you zoom. Burned exports were never affected.

## [0.9.0] — 2026-08-01

Plate solving that works beyond the Seestar — and several things that were quietly wrong.

### Added
- Plate solving no longer gives up when its assumed image scale turns out to be wrong. When a file carries no optical details in its header — which most stacked masters do not — Nocturne assumes the Seestar's image scale, which is right for a Seestar and badly wrong for anything else. If a solve fails with that assumption, it now drops the hint and tries again without one, so frames from other instruments can solve where they previously failed. The result card says when that happened, which is also the clearest available signal that a frame did not come from a Seestar.

### Fixed
- The same object could be named three different ways in the same window. The overlay labelled the Andromeda Galaxy "M 31" while the object list beside it and the solved-target line both called it "NGC 224". Every surface now uses the name people actually use.
- Dialogs that show an image — Share, Upscale Crop, Star Spikes — opened with the picture shrunk into the middle of the window, and only corrected themselves once you changed something. The view now re-fits when the window is resized, while leaving a zoom you chose deliberately alone.
- Sharing an annotated image drew the caption band on top of the annotations, swallowing the coordinate-grid labels and cutting object labels in half. With annotations burned in, the caption now sits below the picture by default, where it cannot cover anything — and you can still move it back onto the image if you prefer.

## [0.8.0] — 2026-08-01

Share grows up — and a colour fix that was quietly costing you accuracy.

### Added
- The Share caption is yours. Nocturne still writes a first draft from the image's own data — target, integration, frame count — but it is now an ordinary text field you can rewrite, trim, or replace with something the metadata never knew. Put it on the image or below it (below extends the canvas, so nothing you photographed is covered), left, centred or right, at three sizes, in any colour, with a slider for how dark the band behind it is. The styling is remembered between shares; the text starts fresh for each image.
- Share now lets you choose the output: 1080, 2048 or 4096 px, or full size, as JPEG or PNG. PNG is the better choice when the image carries annotations or a caption, since labels and text are hard edges and JPEG softens exactly those. Exports only ever scale down, and the status line reports the pixel size actually produced.
- The objects the plate solve found now appear beside the image by themselves, and follow the Annotations button rather than needing a separate control. Click a row to jump the view to that object; close it with its own ✕ if you would rather see the whole picture.
- Plate Solve is greyed out until ASTAP is configured, and says what to install rather than waiting for you to press it and then complaining.

### Changed
- The clipping warning now judges what your editing session actually caused, while still reporting the true total. An image that arrives already crushed — a re-imported export, or an upscaled copy — used to show amber from the first Stretch with nothing you could do about it, which is precisely the cry-wolf failure the warning was built to avoid. It now reads, for example, "0.9% shadows clipped (0.9% shadows on import)" and stays calm until you add to it.
- Share's aspect buttons show which one is selected. Previously nothing indicated the current choice, so the only way to know what you would get was to read the shape of the preview.
- Cropping, rotating or flipping a solved image now tells you the plate solve no longer lines up and its annotations have been hidden, instead of removing them in silence.

### Fixed
- Photometric colour (SPCC) silently fell back to sky balance on any master whose header carried no optical details — which is most stacked masters exported from another tool. The plate-solve tool already handled this by falling back to the Seestar's known image scale, but the colour step did not, so it solved blind, failed, and quietly used the lesser method. On a test capture this took it from no solution at all to 1,718 matched stars.
- A shared image ignored the plate-solved target. If your file's header never named what you photographed but Nocturne identified it, the caption left the target out entirely — while the info strip and the provenance report both showed it.
- Opening a new image left the previous image's annotation pill and object list on screen, describing a field you were no longer looking at.
- The plate-solve screenshot on this site and in the project README dated from before the annotation-mirroring fix, so both were illustrating the bug rather than the feature. Replaced with a current capture.

## [0.7.1] — 2026-08-01

Two correctness fixes — a bad pixel no longer blanks a channel, and a background step can't land on the wrong image.

### Fixed
- A single bad pixel could turn a whole colour channel black on screen. Frames registered with rotation (alt-az field rotation) often carry NaN "no data" in the corners, and one such pixel was enough to blank an entire channel of the display. Three faults compounded: importing a file containing NaN skipped normalisation entirely, leaving values far outside the range every later step assumes; the display stretch derived its parameters from a statistic that one bad sample destroys; and export cast those pixels differently from the canvas, so a saved file could disagree with what you were shown. Non-finite pixels are now treated the same way everywhere — as no data, drawn black — and the good pixels around them are unaffected.
- Opening or closing an image while a step was still running could corrupt it or crash. Closing a project mid-step raised an error; opening a different image mid-step silently applied the previous image's result to the new one and recorded it in the wrong history. Saving while opening another image could also write the new project to the old file. A result now only ever lands on the image it was computed for, and Open Project no longer silently does nothing while a step is running.

## [0.7.0] — 2026-07-31

Plate solving you can steer — an object list, a Cancel button that works, and annotations on Share.

### Added
- Objects in field — everything the solve found, as a list beside the image: deep-sky objects in the overlay's own significance order, named stars below with their magnitude. Click a row to jump the view to it. The list shows the whole field, including objects Density leaves off the image, so the ones hardest to spot are the ones easiest to reach.
- Share can carry your annotations. A checkbox switches the preview between the clean and the annotated frame, so a labelled image gets the social reframing and caption band too — previously the only way to publish a labelled image was a PNG export, which skips both. The checkbox is hidden entirely when there is no solution.
- Plate solving falls back to the instrument profile for the field-of-view hint when a file carries no optics. A stacked master exported from another tool routinely has neither FOCALLEN nor XPIXSZ, which left ASTAP solving a few-degree field blind and usually failing. The result card says when the scale was assumed rather than read, since on data from another instrument that assumption is wrong.

### Fixed
- Cancel during a plate solve did nothing. The button set the flag and the interface reported "Cancelling…" while ASTAP carried on to completion. It now genuinely stops the solver, and a solve still grinding after three minutes gives up with a diagnostic rather than holding on indefinitely.
- A pointing hint taken from a bare RA header card was parsed as hours when it was in degrees, making the search centre meaningless. Latent — those files carry pointing elsewhere too, so the bad value was never actually passed — but a file without that fallback would have been handed nonsense.
- The changelog on this site listed releases by headline alone, so you could not tell which version you were running. Every entry now names its version, and the newest is marked Latest.

## [0.6.0] — 2026-07-31

Plate solving grows up — and a fix that has been mislabelling your images since 0.3.0.

### Added
- Object circles are drawn at each object's real size on the sky instead of a fixed dot, so a large nebula's ring shows how far it extends — past the frame edge if the object is bigger than your field. A dashed ring means the catalogue records no size.
- A Plate Solve tool panel with a checkbox per layer (objects, named stars, RA/Dec grid, compass, scale bar), a Density control for how crowded the labels get, and a result card showing the field centre, size, scale, orientation, solver and elapsed time.
- Colour by type: violet Messier objects, white dark nebulae, cyan planetary nebulae, orange galaxies, yellow named stars.
- An RA/Dec coordinate grid, drawn as true curved lines with edge labels.
- Far more to find in your frames. The deep-sky catalogue grew from 13,962 NGC/IC objects to 15,890 by adding Sharpless HII regions, Lynds and Barnard dark nebulae and van den Bergh reflection nebulae — so the dark lane inside the North America Nebula is now labelled LDN 935. Named stars grew from 371 to 2,831 by adding Bayer and Flamsteed designations.
- An Annotations button on the image toggles the overlay without closing the tool, so you can keep the labels up while you carry on editing.

### Changed
- The Plate Solve toolbar button now opens the tool rather than solving immediately — solving starts when you press Solve, so a several-second run never begins by surprise.
- Labels are placed to avoid overlapping each other, in order of significance, with a leader line when a label has to sit away from its object.
- Labels are larger and carry a proper dark halo, so they stay readable over bright nebulosity as well as dark sky.
- Annotations are clipped to the image, and a solution is cleared when you crop, rotate or flip, since it belongs to the framing it was made for.
- The result card reports no confidence score and no mirrored/not-mirrored flag. Neither can be established reliably from what the solver returns, and a wrong claim on the panel that exists to tell you the solve is trustworthy is worse than a missing one.

### Fixed
- Every annotation was mirrored vertically. Object labels, stars, the grid and the compass have all been placed on the wrong side of the image since plate solving shipped in 0.3.0 — most visible on named stars, where a label sat in empty sky while the star was elsewhere in the frame. Large nebula circles disguised it because they landed roughly over their nebula either way.
- Photometric colour (SPCC) matched Gaia stars against the same mirrored positions, so its matches were coincidental rather than real. It now matches around 1,500 stars on a typical frame.
- Annotated PNG exports silently dropped named stars — the exported image no longer matches what the overlay showed.
- Sharpless objects were labelled with designations that do not exist (Sh 2117 instead of Sh 2-117), and drew a second ring and label over objects already catalogued, including on the North America and Orion nebulae.
- The identified target could be a huge diffuse complex that merely overlaps the frame rather than the object you photographed.

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
