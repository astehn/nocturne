# Seestar Processor — Backlog

Working notes for what's next. Core pipeline + UX are functional on `main`.

## Now — core refinements
- [x] **M5** Background "off" skips (no history entry / no done-mark).
- [x] **L1** "Tools configured" indicator (GraXpert / RC-Astro) in the toolbar.
- [x] **L2** Clear the error/status line when navigating between steps.

## Soon
- [ ] **L3** Project save / reopen (currently work is lost on close).
- [ ] **T1** Tune Background / Noise / Sharpen strength mappings + free fallbacks on real
      stacks (needs real-data testing).
- [ ] **T2** Confirm the Stretch aggressiveness slider range feels right on real data.

## Processing features — quick wins (OSC essentials)
- [x] **Green-cast removal (SCNR)** — toggle in the Color step.
- [x] **Histogram display + Levels** — live histogram widget + a Levels step (black/gamma/
      white). (Full interactive curve editor still deferred.)
- [x] **Star reduction** — Star Reduction step (StarX split → shrink/dim → recombine).

## Processing features — second tier
- [ ] **Multi-session combine** — register + integrate several nights' stacked FITS of the
      same target. Powerful for serious users; bigger build (alignment/integration).
- [x] **Masked / lightness-aware saturation** — boost fades toward highlights/stars.
- [x] **Local contrast / structure boost** — Local Contrast step (CLAHE on luminance).
- [x] **Before/after split divider** — draggable divider in the preview.
- [x] **Per-target-type stretch presets** — Auto/Nebula/Galaxy/Cluster dropdown.

## Feature ideas
- [ ] **Recipes + batch processing (the founding-vision feature).** Save a sequence of step
      settings as a reusable recipe and apply it unattended to a whole folder of stacked
      FITS, exporting each. This is what turns the app from a manual editor into "does my
      repetitive work for me" — the original motivation. (Added per assistant's top
      recommendation; remove if not wanted.)
- [ ] **SHO / Hubble-palette editing for the duo-band OSC data.**
      The S30 Pro has a built-in Ha/OIII duo-band filter, so emission-nebula captures hold
      narrowband signal: Ha → red channel, OIII → green+blue. Automate the extraction +
      palette remap that's manual/fiddly in PixInsight:
      - Extract Ha (= R) and OIII (= G+B blend).
      - Palette presets: Natural (RGB), HOO (bicolor), SHO-style (Foraxx/dynamic, Ha+OIII).
      - Ideally process the *starless* nebula in-palette and re-add RGB stars (reuse StarX).
      - Caveat: true SHO needs mono + SII; from OSC duo-band this is a convincing
        *pseudo*-SHO (Ha+OIII only) — label it honestly. Only meaningful for duo-band
        emission-nebula shots (detect via FITS `FILTER` header or a user toggle).
      - Own design + build cycle.

## Packaging / distribution (later, after refinement)
- App name chosen: **Nocturne** (display name set; About/Help added). Not affiliated w/ ZWO.
- [ ] Rename the internal package `seestar_processor` → `nocturne` (touches all imports/tests;
      do at packaging time to avoid mid-iteration churn). Settings dir `~/.seestar_processor`
      → `~/.nocturne` too.
- [ ] **Splash screen** on launch (with a real logo).
- [ ] App **icon**.
- [ ] Trim heavy deps before bundling: replace `colour-demosaicing` (rare mono-Bayer path)
      with a small bilinear debayer; replace `scikit-image` (unsharp / TV-denoise fallbacks)
      with small scipy/numpy versions. ~halves bundle size.
- [ ] Standalone app build (PyInstaller for a quick `.app`, or Briefcase for installers).
- [ ] macOS code-sign + notarize (Apple Developer ID) so others can open without warnings.

## GitHub publish (when ready to go public)
- [ ] README (screenshots, "requires GraXpert (free), RC-Astro optional", install steps).
- [ ] LICENSE (MIT or GPL).
- [ ] GitHub Releases with built artifacts; optional GitHub Actions to build all platforms.

## Done (recent)
- Processing log: collapsible bottom panel, append-only, timestamped, with an RMS Δ%
  change metric per step (proves subtle steps actually ran).
- Adaptive Stretch (slider) — fixed the black-image problem.
- Robustness: safe file open, guarded exports, `.app` bundle resolution (errno 13).
- Crop polish: aspect-snap, 8 handles, dropped redundant margin, re-fit after crop.
