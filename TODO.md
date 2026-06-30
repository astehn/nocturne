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

## Feature ideas
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
- [ ] Trim heavy deps before bundling: replace `colour-demosaicing` (rare mono-Bayer path)
      with a small bilinear debayer; replace `scikit-image` (unsharp / TV-denoise fallbacks)
      with small scipy/numpy versions. ~halves bundle size.
- [ ] Standalone app build (PyInstaller for a quick `.app`, or Briefcase for installers).
- [ ] macOS code-sign + notarize (Apple Developer ID) so others can open without warnings.
- [ ] App icon + name polish.

## GitHub publish (when ready to go public)
- [ ] README (screenshots, "requires GraXpert (free), RC-Astro optional", install steps).
- [ ] LICENSE (MIT or GPL).
- [ ] GitHub Releases with built artifacts; optional GitHub Actions to build all platforms.

## Done (recent)
- Adaptive Stretch (slider) — fixed the black-image problem.
- Robustness: safe file open, guarded exports, `.app` bundle resolution (errno 13).
- Crop polish: aspect-snap, 8 handles, dropped redundant margin, re-fit after crop.
