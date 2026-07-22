# Nocturne — Backlog

Working notes for what's next. Core pipeline + UX are functional on `main`.

## Investigate
- [x] **Stars come back softer after a StarX split + screen recombine — RESOLVED 2026-07-22.** Root
      cause: `remove_stars` ran `sxt --stars` WITHOUT `--unscreen` (stars = original−starless, meant
      for ADDITIVE recombine) but every caller SCREEN-recombines → dimmed/puffed stars even at zero
      reduction. Fix: `remove_stars` now defaults `unscreen=True`, so `1-(1-starless)*(1-stars)` is
      exact. Proven objectively (Star Reduction at 0.00 = perfect no-op, stars sharp) + audited: single
      split path, all recombines are screen, no additive recombine. Fixes all four split-based steps +
      previews + the starless/stars export (now exports unscreened, Screen-recombine-ready stars).

## GraXpert AI denoise + engine choice (branch `graxpert-denoise`, awaiting user validation 2026-07-21)
Wired GraXpert AI denoise into the Noise Reduction step as a choosable engine. Verified GraXpert
3.0.2 CLI (`-cmd denoising -strength`). `NoiseSharpenStep(rc, gx)` resolves: chosen engine → other
installed → TV. Global default (RC-Astro) in Settings + per-image "Engine" dropdown in the Noise
panel (shown only when both installed). Recipe captures `{engine, level}`. Whole-branch review
READY WITH FIXES → the one recommended fix (coerce unknown level) is landed; 616 green.
- [ ] **VALIDATE + calibrate (blocks merge).** Judge GraXpert denoise quality vs NoiseXTerminator vs
      the TV fallback on real Seestar data (NGC 7000), and **tune `_GX_LEVELS`** in
      `nocturne/steps/noise_sharpen.py` (currently light 0.5 / medium 0.7 / strong 0.9) so the presets
      feel right. Confirm the Engine dropdown + global default behave.
- [ ] **Recorded option captures the CHOSEN engine, not the RESOLVED one (by design).** If you author
      on a GraXpert-only machine while the setting is "rcastro" (default), the recipe records
      `engine: rcastro` even though the local preview used GraXpert (fallback). Replaying elsewhere then
      uses rcastro. Consequence of the spec's "record chosen, resolve at apply-time" model — noted for
      awareness; revisit only if it bites.
- [ ] Small: no direct unit test for the main_window both-installed dropdown gating (low risk; panel
      side is tested). `_noise_apply_option` name is narrower than its scope (serves all process stages).
- [x] **Heads-up that GraXpert is slow — DONE (commit below).** Speed confirmed INHERENT to the newer
      GraXpert denoise models — user reproduced the same multi-minute times in Siril (2026-07-22); not a
      Nocturne setting (CoreML accelerates only ~78/2527 model nodes on Mac, rest is CPU). Busy status
      now shows "Denoising with GraXpert — this can take a few minutes…" when GraXpert is the running
      engine (`main_window._busy_label_for`).
- [ ] Update the Noise Reduction help topic to mention the two AI engines + free fallback + the Engine
      selector (note GraXpert = free but slower, RC-Astro NoiseX = fast).

## Free star split (MERGED to main 2026-07-22)
Free sep-based `(starless, stars)` split (`core/starless.py`) ungates Star Reduction, Remove Green
Fringe, and the Nebula boost without RC-Astro. Screen-recombine-exact. User-validated on NGC 7000
(RC-Astro cleared): Star Reduction + Nebula boost "work beautifully"; Green Fringe reduces green and
shifts the residual to a natural blue. Merged (637 tests). Follow-ups:
- [x] **VALIDATE + Green Fringe fix — DONE 2026-07-22.** Green Fringe "did nothing" on the free path:
      the split can't isolate a broad chromatic halo (a smooth halo is absorbed into the median
      background → stays in starless, which the stars-layer de-green never touches; measured ~76%
      retained, and a wider mask changed it by ~0). Fixed by de-greening the image IN PLACE inside a
      feathered star-neighbourhood mask (`remove_green_fringe_masked` + public `star_mask`), free path
      only; RC-Astro keeps the clean stars-layer de-green. 2.6× more fringe removed on the broad-halo
      case. Help + panel copy for all 3 steps updated (no longer claim "Needs RC-Astro").
- [ ] **`sep` star detection is fragile to a lone hot pixel** — a single bright outlier made
      `sep.extract` return zero detections, collapsing the whole free mask to empty (Green Fringe /
      Star Reduction / Nebula boost then silently no-op). Pre-existing free-split behaviour; denoise +
      background run before these steps, so unlikely in the normal pipeline. Harden `_star_mask`
      against outliers (e.g. clip/`np.percentile` cap the luminance before `sep`, or median-prefilter).
- [ ] **Export "Starless + Stars" still RC-Astro-gated** — the free split could power that export too
      (`step_panels.py:559-570`, `main_window.py:1295`). Out of scope this cycle; extend later.
- [ ] Optional tuning: `split_stars` constants (`_THRESH`, `_RFAC`, `_RMIN/_RMAX`, `_FEATHER`,
      `_BG_STEP/_BG_MED`) — acceptable as-is, revisit only if real data shows misses/over-fill.
- [ ] Cosmetics: redundant `np.ascontiguousarray` in `core/starless.py`; redundant Star-Reduction
      ungated test pair.

## Narrowband tool (MERGED to main 2026-07-21) — follow-ups
Guided **Narrowband…** colour tool (NBN engine: MTF median-lift of OIII→Ha per Blanshan/Cranfield V8;
HOO / Pseudo-SHO / Pseudo-bicolor; StarX-or-whole-image; params-serialised recipe step). HOO
user-validated on NGC 7000. Non-blocking follow-ups:
- [ ] **Palette work — validate & tune Pseudo-SHO and Pseudo-bicolor on real data.** Only **HOO** was
      validated. The two pseudo palettes' channel math was deliberately left tunable (spec: "exact
      channel math for the pseudo palettes may be tuned during real-data validation"). Current routing
      (`core/narrowband.py` `_combine`): Pseudo-SHO = (Ha, Ha, OIII) → gold/teal; Pseudo-bicolor =
      (Ha, OIII, Ha) → magenta/green. TO DO: run both on real Seestar HOO frames, judge whether the
      gold-teal and magenta-green looks are pleasing/distinct, and tune the channel mix, SCNR scope,
      hue, and per-palette default sliders as needed. Also consider whether the **default OIII boost**
      should sit above ×1.00 (user liked ~×1.3 in testing) and whether more palettes are wanted.
- [x] **"Brightness" slider inert at the default — FIXED (commit 1de0462).** Moved `brightness` to
      apply on the FINAL image (after the lightness step) so the slider is live in both modes; also
      defaulted **Preserve lightness OFF** (brighter combine is the better default) and added numeric
      slider readouts (OIII boost / Brightness as ×N). User: "much better".
- [ ] **`PALETTES` duplicated** — a list in `ui/narrowband_dialog.py` and a tuple in
      `core/narrowband.py`. Import the core tuple to keep one source of truth (a parity test guards drift).
- [ ] **Preview is a downscaled approximation of Apply.** `nebula_mask` percentiles and
      `preserve_lightness` are resolution-sensitive, so the live (downscaled starless) preview is close
      but not pixel-identical to the full-res Apply. Standard preview behaviour; note it against the
      project's strict preview==export principle.
- [ ] **Dedicated toolbar icon** (currently reuses the `haoiii` icon).
- [ ] **Free star-mask fallback** (narrowband without RC-Astro StarX) and **continuum subtraction**
      (`OIII − k·Ha`, to clean Ha bleed-through from OIII) — future sub-projects (spec "Out of scope").

## Future features — Enhancements / finishing (from research 2026-07-20)
Ranked; all pure-numpy/scikit-image, no paid deps. Sources in the audit ledger.
- [x] **HDR core / highlight recovery (HIGH — top pick; done 2026-07-20).** Shipped the "Recover
      Core" step (after Stretch): single-scale local HDR under a feathered highlight mask
      (`core/hdr.py` `recover_core`), one Strength slider with live preview + live histogram.
      Validated on real data (recovers usable core detail on M31). Fully-clipped-to-white cores stay
      white by design (nothing to recover) — accepted, help text says so. Future upgrade path:
      multiscale (à-trous/Gaussian-pyramid) HDR on the same mask/luminance plumbing.
- [x] **Curves — S-curve / tone curve (HIGH; done 2026-07-20).** Shipped the "Curves" step (after
      Levels): a draggable `CurveEditor` widget (monotone-cubic / Fritsch–Carlson LUT on luminance,
      hue-preserved) with pinned corners, a faint histogram backdrop, Reset + background-aware
      "Add contrast" preset, and live preview + live histogram. User-validated ("works as it should,
      very useful"); may fine-tune the Add-contrast preset strength after more use.
      Deferred polish (from final review): (a) wrap `build_lut`'s arithmetic in `np.errstate` to clear
      the sticky FP flag at the source (root-cause complement to the `sharpen` NaN guard already
      shipped); (b) `CurveEditor.mousePressEvent` add-then-regrab narrow edge case when a click's x is
      within the 0.02 min-gap of an existing point (cosmetic). Future: per-channel R/G/B curves.
- [x] **Diffraction / star spikes (MED, high wow; done 2026-07-20).** Shipped as a **toolbar tool**
      (like Ha/OIII) rather than a pipeline step — it's a purely artistic choice, so it lives outside
      the faithful-processing flow. `core/star_spikes.py` (sep detection + tapered needle + core-bloom
      render), `ui/star_spikes_dialog.py` (live-preview dialog: Length / Number-of-stars / Rotation),
      records a `_PrecomputedStep`; refuses on a linear image. Deferred: a dedicated toolbar icon
      (reuses the Ha/OIII icon for now); make dialog-open star detection non-blocking if sluggish on
      full-res.
- [x] **Remove Green Fringe (done 2026-07-20; user-requested).** New finishing step after Saturation:
      splits stars from background (StarXTerminator), de-greens ONLY the stars layer via green-excess
      suppression, screen-recombines — nebula/background colour untouched. Strength slider, live
      preview, RC-Astro-gated (disabled + message when absent), Star-Reduction architecture. Chosen
      over a global green-excess pass (which over-corrected the nebula → magenta shift). Deferred: a
      non-RC-Astro fallback (brightness-weighted or sep-mask) for users without StarXTerminator.
- [x] **Masked "nebula-only" saturation (MED-HIGH; done 2026-07-21).** Added a **Nebula boost** slider
      to the Saturation step: StarX-split star separation (stars untouched) + a sky-anchored nebula
      mask on the starless layer (`core/saturation.py` `nebula_saturate`), boosting only nebulosity
      (faint included) while sky stays neutral. Lazy cached split, RC-Astro-gated; the global
      Saturation slider still works for everyone. User-validated ("worked perfectly"). Also fixed a
      long-standing quirk: fully-left Saturation now mutes to greyscale (explicit 0 = grey; only an
      unset option is native). Deferred polish: clear the "Separating stars…" status if a StarX split
      *fails* — a shared bug across Saturation / Remove Green Fringe / Star Reduction, worth one pass;
      a non-RC-Astro fallback for the Nebula boost.
- [ ] **Secondary (lower priority):** "Clarity" large-radius luminance unsharp (overlaps CLAHE —
      only if differentiated); colour-temperature tweak (careful — fights the colour calibration);
      Dark Structure Enhancement (expert-niche for undersampled Seestar data); aesthetic vignette.
      Skip: dehaze (redundant with background removal + contrast).

## UX affordances
- [x] **Spacebar before/after toggle (requested 2026-07-20; done 2026-07-21).** Space toggles a
      full-image before↔after swap (image + histogram), with a status hint; app-wide event filter so
      it works regardless of focus (skipped in text fields / while a modal dialog is up); auto-resets
      on navigation/apply. Chose **press-to-toggle** (not hold-to-peek). **Step-scoped (fixed
      2026-07-21):** *before* = the current step's entry image (`_preview_base(stage_id)`), *after* =
      whatever's on the canvas now (`_displayed` — the live preview mid-drag, else the committed
      result), so Space shows only THIS step's effect and never reveals an earlier step's change
      (original bug: noise reappearing while on Local Contrast). Non-pipeline stages fall back to
      `before_after()`. Works on all 13 pipeline steps + before a step is applied.

## Now — core refinements
- [x] **Total integration wrong for new ZWO-firmware masters (reported 2026-07-17; RESOLVED 2026-07-19).** After
      ZWO's firmware + app update (~2026-07-10), the Import step shows e.g.
      "Total integration 60h 05m (104 × 2080s)" for an NGC 281 master. The numbers expose the
      cause: 2080 = 104 × 20, so the new firmware appears to write `EXPTIME` as the
      **cumulative total** integration of the stack (2080s) instead of the per-sub exposure
      (20s); our `fits_io.format_metadata` still multiplies frames × EXPTIME → 104 × 2080s
      ≈ 60h. Real value for that stack: 2080s ≈ 34m40s. (Second data point confirms:
      "46h 00m (91 × 1820s)", 1820 = 91 × 20.) TO FIX (needs a real new-firmware master +
      raw sub to inspect): dump full headers (`astropy.io.fits` — EXPTIME, STACKCNT/NSUBS,
      any new per-sub-exposure keyword ZWO may have added); then make the integration
      calculation robust to both firmware generations — plausible heuristic: if
      EXPTIME/frames yields a sane per-sub value (5–60s) and EXPTIME alone is implausibly
      long for one sub, treat EXPTIME as the total. Also check whether raw SUBS from the new
      firmware still carry per-sub EXPTIME (old-firmware subs did — affects our own stacker's
      minutes-of-light math + master filename if not). CONFIRMED (2026-07-17, code read):
      `import_summary` multiplies exp × frames unconditionally (`fits_io.py:80-82`), and OUR
      stacker writes EXPTIME = TOTAL (+NSUBS/STACKCNT) — the same convention ZWO switched to —
      so re-opening a Nocturne master mis-displays the same way (e.g. 182 × 3640s ≈ 184h).
      ZWO's change exposed a latent assumption, not just a ZWO quirk. Fix must handle: old-ZWO
      (per-sub EXPTIME), new-ZWO (total EXPTIME), and Nocturne masters (total EXPTIME +
      STACKCNT present — can key on our own NSUBS/STACKCNT headers for a reliable signal).
      RESOLVED 2026-07-19 (Import audit): `fits_io.resolve_integration` prefers `LIVETIME`; else
      uses the EXPTIME/STACKCNT ∈ 0.5–600s ratio test to tell total-vs-per-sub apart — handles
      old-ZWO (per-sub), new-ZWO (total), and Nocturne masters (total). Validated on real files
      (NGC 281 → 27m, NGC 7000 → 61m). Camera specs now also read from the header.
- [ ] **Stacking memory runaway (~396 GB) (reported 2026-07-17).** After stacking a 186-sub session
      (NGC 7000), macOS reported "system has run out of application memory" with Nocturne at
      ~396 GB (Force Quit dialog — likely runaway allocation/virtual memory during or after
      the stack, not a slow leak). Investigate as the non-functional half of the stacking
      deep-dive: profile grade → register → integrate on the real dataset; suspects include
      registered-frame accumulation (registration output kept in memory rather than streamed),
      per-frame float64 copies, and the master + history caches piling on top. Reproduce with
      Activity Monitor / `memory_profiler` before fixing.
- [ ] **Free deconvolution better than unsharp-mask — NEAR-TERM (RL decided 2026-07-22).** Update:
      `sharpen` was fixed today (broken skimage `unsharp_mask` → manual gaussian high-pass →
      positive-only, no dark rings). But real-data testing confirmed the ceiling: **unsharp only
      BRIGHTENS star cores, it does not TIGHTEN them** (FWHM unchanged). The "tightening" the user
      liked earlier was actually the dark-ring artifact carving the halo (fake tightening); removing
      the rings (positive-only) removed the apparent tightening. User chose to KEEP the honest
      positive-only sharpen for now (option A) and set expectations in the help + presentation.
      THE REAL FIX (this item): a proper **Richardson–Lucy PSF deconvolution** — estimate a PSF from
      the image's stars (`sep` available), RL iterate with regularization + a star/background mask to
      curb noise and ringing. That's the only free path that genuinely tightens without artifacts.
      IDEA: study
      the deconvolution algorithms in **Siril** (Richardson–Lucy / Wiener / split-Bregman, with a
      star-derived PSF) and **PixInsight** (classic Deconvolution: RL + PSF + regularization /
      deringing) and implement an open numpy version that beats unsharp mask — e.g. RL with a PSF
      estimated from the image's stars (`sep` already available), plus regularization + a
      star/background mask to curb noise and ringing. ALSO evaluate free redistributable AI
      options (Seti Astro "Cosmic Clarity" sharpen/deconv is free with an ONNX path) as a better
      fallback. GOAL: the non-RC-Astro result should be clearly better than today's unsharp mask.
      SECONDARY (same audit): consider separate star vs non-stellar strength (BlurX exposes both;
      undersampled Seestar data often wants more star-tightening than non-stellar); add a
      "zoom to 100% to see the effect" nudge; and signal the free path as "basic sharpening".
- [ ] **Free noise reduction better than TV — wire GraXpert AI denoise (parked 2026-07-20, from
      Noise Reduction audit).** Without RC-Astro/NoiseXTerminator, `core/noise.reduce_noise` falls
      back to skimage `denoise_tv_chambolle` (TV) — the classic watercolour/plastic smearer that
      flattens faint nebulosity and softens stars. But **GraXpert (already installed for Background)
      has an AI *denoise* mode**, and Nocturne already has the wrapper `GraXpert.denoise` — just
      unwired. FIX: chain the Noise Reduction fallback **RC-Astro → GraXpert AI denoise (free,
      already configured) → TV last-resort**; pass a `graxpert` instance into `NoiseSharpenStep`.
      CAVEAT: verify the GraXpert *denoise* CLI flag — the existing wrapper passes `-smoothing` but
      denoise likely needs `-strength`; test against real GraXpert. Same "better free path for
      non-RC-Astro novices" theme as the free-deconvolution item above.
- [x] **M5** Background "off" skips (no history entry / no done-mark).
- [x] **L1** "Tools configured" indicator (GraXpert / RC-Astro) in the toolbar.
- [x] **L2** Clear the error/status line when navigating between steps.

## Tweaks (small, from real-data use)
- [x] **Undo takes you to the affected step (reported 2026-07-19; DONE 2026-07-22, commit a28d89b).**
      Undo/redo now capture the step at the top of the applied stack and navigate the stepper to its
      stage (`_stage_for_step_name` + `_navigate_to_step`): geometry → Crop, Enhancements taps →
      Enhancements, Remove Green → Color; toolbar tools (Narrowband/Star Spikes) have no stepper stage
      → stay put. Reverting a post-stretch step always leaves Stretch applied, so the auto-stretch
      commit never fires on the jump (redo stack intact). 638 tests.
- [ ] **Saturation "expert mode" — per-channel R/G/B saturation (suggested 2026-07-19).** The
      re-centred saturation slider (0 grey / 0.5 native / 1 strong) works well as-is; add an
      optional **expert mode** exposing per-channel R/G/B chroma control for users who want finer
      colour shaping (scale each channel's `data - lum` residual independently). Consider during
      the Step 8 (Saturation) audit as an advanced toggle/panel, alongside the live-preview + numeric
      readout that step will inherit. User has no complaints about the current default behaviour.
- [x] **Configurable base / default open directory (reported 2026-07-20; done 2026-07-20).** Added a
      **Default folder** setting (`Settings.base_dir`, persisted in `settings.json`) + a `start_dir()`
      helper (returns the base if it exists, else the OS default). Every file/folder picker across
      Open FITS, Save Recipe, Export, Stack, Ha/OIII, and Batch now starts there. Set it once in
      Settings. Last-used-folder memory was considered and deliberately left out (a fixed base is
      simpler/predictable) — noted as a possible future enhancement.
- [x] **Live histogram during slider preview (reported 2026-07-20; done 2026-07-20).** Factored a
      shared `_show_preview()` helper (image + histogram in sync) and routed Levels / Saturation /
      Local Contrast / Star Reduction / Stretch previews through it, so the histogram now tracks every
      slider live. Also retrofit the Stretch aggressiveness slider with a debounced non-committing
      live preview + numeric readout (group A). Merged to main.
- [ ] **Coalesce duplicate in-flight preview loads in the stack dialog.** Rapid ↑/↓ row
      navigation dispatches one full-res load per visited row with no dedup/cancel — harmless
      today (each just runs a full-res unlinked stretch) but wasteful on fast repeated
      navigation. Also note for later: possible display-only smoothing for single-sub RGB shot
      noise at fit zoom (cosmetic, low priority).
- [x] **Palette workflow reworked into one-press "Colourise" (fixes both palette bugs).** DONE. Replaced the modal-only palette with a one-press **Colourise** button on the Stretch step (StarX cached → auto Foraxx → stars screened back), recorded as a "Colourise" history step at the **stretch position** so later steps preserve it (fixes the "palette discarded by later steps / reset on Color" bug — you also skip the broadband Color step for narrowband, per the new tip). The old "Apply drops stars" bug is gone: the one-press path composes the cached stars back, and "Advanced…" opens the slider dialog seeded with those layers. Whole-branch review caught + fixed a data-loss bug (Advanced truncated history on open → cancel wiped work); now non-destructive (`Project.state_at`; truncate only on record). 348 tests.
- [x] **~~FOLLOW-UP: Recipes/batch don't capture Colourise~~ — SUPERSEDED (2026-07-21).** The old
      one-press "Colourise" lived only on the never-merged `narrowband-core` branch; it was replaced on
      `main` by the guided **Narrowband tool**, which IS a params-serialised recipe step
      (`NarrowbandStep` + factory + recipe serialize/deserialize) captured by recipes/batch. The
      recipe-capture gap this item described no longer exists.
- [x] **Crop rotate/flip decoupled.** Rotate/Flip are immediate undoable buttons; Apply Crop
      crops only; flipping no longer re-crops; processing steps preserve geometry (crop/rotate/
      flip each their own history step).
- [x] **Recipes capture rotate/flip.** DONE. Rotate/Flip H/Flip V now map to first-class recipe steps (`rotate`/`flip_h`/`flip_v`) replayed through the same `CropStep` engine (`recipe.py` `_NAME_TO_STAGE` + `deserialize_option`; `factory.make_step`; `batch.py` unchanged). Replay proven byte-identical to live; whole-branch review clean; 327 tests.
- [x] **"Reset image" button — start the whole process over.** DONE. Toolbar Reset action (disabled until loaded) → confirm dialog (default No) → `open_image(_source_base, _source_label)` (fresh Project, history cleared, back on Import; no disk re-read, base stays pristine). New `reset.svg` icon. Whole-branch review clean; 330 tests.
- [ ] **Crop preview framing stretch (deferred).** When cropping a raw/linear image the
      preview can be too dark to frame, even though it already auto-stretches. Add an optional
      stronger "framing stretch" toggle in the crop view (display-only, doesn't touch data).
      Deferred until real-data samples confirm whether the existing display auto-stretch is
      failing (bug) or just too gentle (needs a stronger toggle).
      RELATED (done 2026-07-19, merged f23da41): the **colour-cast** side of crop-framing is now
      handled by the "Unlink stretch (neutralize tint)" checkbox in the Crop panel — a
      display-only per-channel stretch that evens out a blue/green LP cast (PixInsight STF-unlink
      style, off by default). It also lifts each channel to the background target, so it brightens
      a dark frame somewhat; this deferred item is now only the *pure-brightness* case (a neutral
      but under-exposed linear frame). Re-evaluate whether that still needs its own toggle.
- [x] **Reset sliders to default.** DONE — double-click any slider resets to its default (`ResetSlider`, tooltip 'Double-click to reset'); applied across stretch/levels/saturation/palette. Whole-branch review clean; 324 tests.
- [x] **Saturation remap.** Current slider is additive-only: 0 = native saturation (never
      desaturates) and the top end is too weak — you must crank it to see effect, and low
      settings still look fully saturated. Remap so low = desaturate (factor < 1), mid =
      neutral, high = stronger boost; steepen the curve. (`core/saturation.saturate` +
      panel default/labels.) Shipped: centre-neutral slider (0=grey, 50=native, 100=strong,
      boost tapered toward highlights); default 50; S_MAX=2.5 (tunable).
- [x] **"Remove Green" as its own button.** DONE (merged 004181e). The checkbox is gone;
      Apply Color = neutralize+white-balance only. Green removal is a dedicated "Remove Green"
      button applying SCNR as its own undoable step (`RemoveGreenStep`, positioned after Color
      in `PROCESSING_ORDER`), recipe-able. Whole-branch review clean; 316 tests.

## Soon
- [x] **Comprehensive in-app Help.** DONE. Replaced the stale `help_html()` blob with a
      single content module (`ui/help_content.py`, 21 concept-teaching topics) feeding both a
      bottom-anchored per-step explainer and a browsable Help window (`ui/help_dialog.py`,
      sidebar TOC + content pane). 393 tests.
- [x] **Export options at the final Save step + remove the Destination step.** In the final
      "Save"/Export step, let the user choose to save either (a) the whole image, or (b) a
      **separated pair** — a starless (background/nebula) image + a stars-only image — so they
      can keep editing the two layers in other software. The star-split capability already
      exists (StarX via `tools/rcastro.remove_stars` → starless + stars; the "Two TIFFs:
      starless + stars" option currently lives only in the *external* destination panel,
      `EXTERNAL_FORMATS` in `step_panels.py` + `main_window.export_external`). Move that option
      into the normal in-app Export step (`export` kind), gated on RC-Astro like today. Once
      export covers the split, the **Destination step becomes redundant → remove it**: drop the
      `destination` stage, the `external`/`in_app` branch (`path_stages`, `set_destination`,
      `_EXTERNAL_TAIL`/`_IN_APP_TAIL`, `export_external`) and always run the single in-app flow.
      Simpler mental model for the user (one linear path; the "how do I want to finish?" choice
      moves to the moment of saving). Own design + build cycle (touches pipeline, step_panels,
      main_window, and their tests). Shipped: single Export step with a 'Starless + Stars (two TIFFs)' 4th format (RC-Astro-gated); Destination step + external branch removed; one linear flow.
- [ ] **(note) Export is post-stretch (non-linear).** The starless/stars (and whole-image)
      export saves stretched data. Fine for most users, but a pro continuing in PixInsight/Siril
      would often want *linear* starless data. Future option: offer a "linear" export that saves
      the pre-stretch state (would need history to expose the last linear step, or re-run the
      pipeline to the stretch boundary). Low priority — noted so it isn't forgotten.
- [ ] **L3** Project save / reopen (currently work is lost on close).
- [~] **T1** Tune Background / Noise / Sharpen strength mappings + free fallbacks on real
      stacks. NOISE done (2026-07-17): NoiseX presets recalibrated light/medium/strong
      0.4/0.7/0.9 → 0.75/0.90/0.95 (medium now = PixInsight's default 0.90; the old medium
      0.7 was the under-denoising the user saw). Free TV fallback left unchanged (decoupled,
      not benchmarked). Validated on NGC 7000 via recipe replay. STILL OPEN: Background &
      Sharpen strength mappings; free TV-fallback calibration (own mini-audit).
      Deferred (own deep-dive): dual-track starless architecture for stretch/detail (NOT
      noise — proven equivalent).
- [ ] **T2** Confirm the Stretch aggressiveness slider range feels right on real data.

## Processing features — quick wins (OSC essentials)
- [x] **Green-cast removal (SCNR)** — toggle in the Color step.
- [x] **Histogram display + Levels** — live histogram widget + a Levels step (black/gamma/
      white). (Full interactive curve editor still deferred.)
- [x] **Star reduction** — Star Reduction step (StarX split → shrink/dim → recombine).

## Processing features — second tier
- [ ] **(idea, researched 2026-07-17) Bundle our own AI denoising?** Goal: reduce the
      "install GraXpert first" onboarding hurdle. Research findings: SCUNet (Apache-2,
      weights ~72MB, redistributable) is trained on natural images only — community tests
      show this class erases faint stars on astro data → DO NOT bundle. AstroNoiseNet (MIT,
      astro-native, by GraXpert's own author Steffen Hirtle) ships NO pretrained weights and
      is the dormant prototype of GraXpert's AI denoise. GraXpert's production ONNX weights:
      no published license, credentialed S3 — even Siril shells out to the binary rather than
      bundle (the sanctioned pattern = our current CLI approach). NEXT ACTIONS if pursued:
      (1) email Hirtle asking whether GraXpert models may be run in-process via onnxruntime
      (~10-40MB dep; removes install hurdle, no quality risk); (2) track Seti Astro Cosmic
      Clarity (active, astro-trained, weight license unstated — ask first); (3) long-term
      differentiator: train AstroNoiseNet ourselves on tester-contributed Seestar data
      (months-scale). Runtime if ever bundling: onnxruntime + download-weights-on-first-use,
      never full PyTorch (~doubles the 314MB bundle).
- [ ] **(idea, parked) Port Colourise/Foraxx to a Siril `sirilpy` plugin.** Cross-platform
      (Win/Mac/Linux), no code-signing/notarization, taps Siril's user base. Low-friction
      because `core/palette.py` is pure numpy and sirilpy is get-numpy → set-numpy (Siril
      1.4+ Python API). Trade-off: gives up the guided UX (that stays the app). Only if the
      packaging/reach situation ever warrants it.
- [x] **Local contrast / structure boost** — Local Contrast step (CLAHE on luminance).
- [x] **Before/after split divider** — draggable divider in the preview.
- [x] **Per-target-type stretch presets** — Auto/Nebula/Galaxy/Cluster dropdown.

## Feature ideas
- [x] **Recipes + batch processing.** Save a session as a `.json` recipe (Save Recipe) and
      apply it to a folder of stacked FITS via the Batch dialog (auto-crops each image's
      border, exports TIFF/PNG/FITS). `recipe.py` + `batch.py` + `steps/factory.py`.
- [x] **Stacking (preprocessing).** Separate "Stack…" tool: point at a folder of individual
      Seestar light subs, grade + auto-reject bad frames, register (astroalign, handles
      alt-az field rotation), integrate (average / sigma-clip), save a 32-bit master FITS and
      load it into the editor. `stacking/` package + `ui/stack_dialog.py`.
- [x] **Narrowband palette (HOO / pseudo-SHO), starless workflow.** Interactive "Palette…"
      on the current image: StarX removes stars (once), the starless nebula is coloured with
      live controls, white stars are screened back, and Apply records a "Palette" history
      step. Falls back to whole-image without RC-Astro. `core/palette.py` + `ui/palette_dialog.py`.
      - v3: per-channel Black/Mid/White curves (R/G/B channel tabs) replace the global
        balance/saturation sliders, so the SHO look is sculpted per channel, not globally
        re-tinted. Palette radio + SCNR + Reset retained.
      - v4 (real colour, fixes red-monochrome): proper narrowband combine — per-channel
        background-subtract, normalize OIII to Ha (median+MAD), **stretch Ha & OIII
        independently** (the actual monochrome fix), blend (**Foraxx dynamic** default / HOO /
        pseudo-SHO), max-mask SCNR, hue rotation, saturation; white stars screened back
        (now stretched too). Output is `is_linear=False`. Curves/R-G-B tabs removed →
        controls: Palette + Ha stretch + OIII stretch + Hue + Saturation + SCNR + Reset.
        Runs on the **linear master** (hint shown if not). Whole-branch review caught a
        compose `is_linear` mislabel + a vacuous guard (both fixed/verified); 333 tests.
        NB for the user: from a bright northern-summer LP sky OIII is faint, so teal starts
        subtle — darker skies + more OIII time raise the ceiling.
- [x] **Ha/OIII duo-band extraction (lights-only).** Separate "Ha/OIII…" tool: grade raw subs,
      split each CFA sub into Ha (red sites) and OIII (green+blue) planes, register once on Ha
      and reuse the transform for OIII, stack each channel separately, MAD-renorm OIII to Ha,
      and produce a combined RGB master (Ha→R, OIII→G+B) for the editor/Palette.
      `stacking/haoiii.py` + `ui/haoiii_dialog.py`. Inspired by Siril's ExtractHaOIII, no calibration.

## Packaging / distribution (later, after refinement)
- App name chosen: **Nocturne** (display name set; About/Help added). Not affiliated w/ ZWO.
- [x] Rename the internal package `seestar_processor` → `nocturne`. DONE — all imports/tests
      renamed; `pyproject` name → `nocturne`; settings dir → `~/.nocturne` with one-time
      auto-migration of a legacy `~/.seestar_processor/settings.json`
      (`settings.resolve_settings_path`).
- [x] ~~**Splash screen** on launch~~ — tried it, but the app starts in <1s so it was just a
      sub-second flash. Removed by decision; window appears immediately.
- [x] App **icon**. DONE — simplified dock-legible icon (`nocturne/assets/nocturne_icon.svg`),
      `.icns` via `packaging/make_icons.py`; window icon wired in `__main__`.
- [ ] Trim heavy deps before bundling: replace `colour-demosaicing` (rare mono-Bayer path)
      with a small bilinear debayer; replace `scikit-image` (unsharp / TV-denoise fallbacks)
      with small scipy/numpy versions. ~halves the ~314MB bundle. (optional)
- [x] Standalone **macOS** app build. DONE — `packaging/nocturne.spec` + `nocturne_app.py`
      launcher → `dist/Nocturne.app` (verified running on a second Mac). Build note: matplotlib
      is a build-only dep (astropy hook imports wcsaxes); excluded from the bundle.
- [ ] macOS code-sign + notarize (Apple Developer ID) so others can open without warnings.
- [ ] **Windows** build — can't cross-compile from macOS (PyInstaller bundles the host).
      Path: GitHub Actions `windows-latest` runner + a `.ico` + cross-platform spec. Coupled to
      the GitHub-publish step. Deferred by decision (no Windows tester yet).

## GitHub publish (when ready to go public)
- [x] README drafted (`README.md` + `docs/img/` hero - [ ] README (screenshots, "requires GraXpert (free), RC-Astro optional", install steps). icon; features, requirements, install/build,
      quick-start, credits). TODO: add UI screenshots; finalise LICENSE reference.
- [x] LICENSE — GPLv3 (`LICENSE`); referenced in README + pyproject classifier.
- [ ] GitHub Releases with built artifacts; optional GitHub Actions to build all platforms.

## Visual polish — later tiers (Tier 1 shipped)
- [x] **Tier 2 — canvas & panels (hero shot):** radial-gradient canvas backdrop; framed image
      with soft shadow; floating zoom pill (– 100% +); empty-state screen (logo + "Open or Stack
      to begin"); card-style right panel with per-step description strips; histogram styling
      (filled RGB + faint grid). Shipped: gradient canvas, image shadow, zoom pill, welcome
      screen, filled histogram, card panels.
- [ ] **Tier 3 — branding & finish:** app icon + "Nocturne" wordmark; splash screen (with
      packaging); labelled before/after divider handle; spinner busy-overlay.
- [x] **Toolbar tool-status chip — color only the checkmark, not the label.** DONE. Currently the
      whole "GraXpert ✓" / "RC-Astro ✓" is green (red on failure), which is louder than needed.
      Make the tool *name* the normal interface text colour and colour only the ✓/✗ mark
      (green = works, red = doesn't). One spot: `main_window.py:_update_tools_label` `chip()` —
      split the span so `name` uses the default text colour and just `mark` carries the
      green/red colour. Cosmetic; low urgency.

## Done (recent)
- Stacking frame selection redesigned (2026-07-17, spec `docs/superpowers/specs/2026-07-17-stacking-grading-design.md`):
  Siril-style iterative k-sigma judge replaces 3×raw-MAD gates (NGC 7000: 182/186 kept vs 126 before;
  Siril 177). Plain-language verdict column + row tinting, strictness knob (Relaxed/Normal/Strict)
  with instant re-judge preserving manual overrides, autostretched per-frame preview pane, human
  status line ("Keeping 182 of 187 frames — 61 of 62 minutes of light"), descriptive master filename
  (`NGC7000_182x20s_61min.fits`), unaligned frames named in the completion report, previous masters
  in the folder auto-excluded ("Already-stacked image — excluded"). Bright sky warns but never rejects.
- Processing log: collapsible bottom panel, append-only, timestamped, with an RMS Δ%
  change metric per step (proves subtle steps actually ran).
- Adaptive Stretch (slider) — fixed the black-image problem.
- Robustness: safe file open, guarded exports, `.app` bundle resolution (errno 13).
- Crop polish: aspect-snap, 8 handles, dropped redundant margin, re-fit after crop.
