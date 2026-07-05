# "Colourise" — One-Press Dualband Colour — Design

**Date:** 2026-07-05
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved (design + key decisions) — building under standing authorization.

## Motivation

New users (and the app's Seestar audience) want their red dualband (Ha+OIII) masters turned into a
finished colour image in **one press**, like AstroWizard's "Dual Band to Hubble Mix" — no sliders.
Nocturne already has the engine (Foraxx dynamic blend + independent per-channel stretch + StarX
star handling), but only behind a modal slider dialog that also has two bugs: (1) the palette
result is discarded when the user continues the pipeline (esp. the broadband Color step), and
(2) Apply can drop the stars. This design adds a one-press **Colourise** operation that fixes both
structurally and keeps the manual sliders as an "Advanced…" option.

## Decisions (from discussion)

- **One-press, fully automatic** (stars handled invisibly; StarX cached so re-presses are fast).
- **Keep the manual sliders as "Advanced…"** — one-press is primary; Advanced opens the existing
  dialog seeded from the auto result.
- **Colourise lives at the Stretch step** as a second button beside "Apply Stretch" (the "reveal"
  step). It operates on the **linear** image (required for the independent per-channel stretch that
  makes real colour) and occupies the **stretch position** in history.
- **Broadband vs narrowband fork:** Apply Stretch = broadband/natural; Colourise = dualband colour.
- Add a **Color-step tip** telling narrowband users to skip broadband colour-balance (it muddies
  the palette), mirroring AstroWizard.
- **Deferred:** colour pops (Red/OIII/Blue Pop), Darker/Lighter Sky, explicit Remove/Replace Stars,
  Gentle/Strong presets, and **recipe/batch capture of Colourise** (see Out of Scope).

## Architecture / changes

### Core — `core/palette.py` (already built; reused)
`compose(starless, stars, PaletteParams())` already does the full combine (bg-subtract → normalize
→ independent stretch → Foraxx → SCNR → hue/sat → screen tight stars). One press uses the **default
`PaletteParams()`** — no new core math. StarX star removal stays in the tool layer
(`RCAstro.remove_stars`).

### `ui/main_window.py`
- **`_colourise()` handler** (new), analogous to `apply_current` for the stretch stage but running
  the colourise pipeline:
  1. Guard `project`/`_busy`.
  2. Truncate to the stretch position: `preceding = set(GEOMETRY_NAMES) | {STEP_NAME[sid] for sid
     in PROCESSING_ORDER[:index("stretch")]}` → `jump_back(_leading_kept(...))` (same predecessors
     as Apply Stretch — Colourise *replaces* the reveal step).
  3. `base = project.current()` (linear).
  4. **StarX (cached):** if the cache holds `(starless, stars)` for this base signature, reuse;
     else run `RCAstro.remove_stars(base)` **async** (busy overlay — StarX takes seconds) and cache.
     If RC-Astro is unavailable, fall back to whole-image (`starless = base`, `stars = None`).
  5. `result = compose(starless, stars, PaletteParams())` (or `render_nebula` if `stars is None`).
  6. `run_step(_PrecomputedStep("Colourise", result), "")`; log "Colourise (dualband → colour)";
     refresh.
- **History preservation (fixes bug 1):** in `apply_current`, after building `preceding`, if it
  contains `STEP_NAME["stretch"]` (i.e. we're on a post-stretch stage), also add `"Colourise"`.
  A Colourise entry then sits at the stretch position and is preserved by every later step exactly
  like a Stretch entry — later steps build on it instead of discarding it.
- **`_done_ids`:** mark the `stretch` stage done if `"Colourise"` OR `"Stretch"` is present.
- **Star cache:** `self._colourise_layers = None` holding `(sig, starless, stars)`; `sig` is a cheap
  signature of `base` (shape + mean/std) so it invalidates when earlier steps change the input.
  Reused by `_colourise()` and by Advanced.
- **Remove the toolbar "Palette…" action** (`load_icon("palette")` / `_open_palette`); the palette
  is now reached from the Stretch panel (Colourise + Advanced…). `_record_palette` is repurposed to
  the stretch-position recording used by Advanced.
- **Advanced…** opens `PaletteDialog` **seeded with the cached `(starless, stars)`** (skips a second
  StarX run) and default `PaletteParams()`; its Apply records at the stretch position as
  `"Colourise"` via the same path. This also resolves bug 2 (Apply screens stars) by routing
  through the fixed `compose`; if any drop remains, root-cause via systematic-debugging.

### `ui/step_panels.py` (stretch branch) + `ui/pipeline.py`
- Stretch panel gains a **"Colourise"** primary button → `on_colourise()`, and a small
  **"Advanced…"** button → `on_palette_advanced()`, alongside the existing Apply Stretch + slider.
- Add `on_colourise` / `on_palette_advanced` params to `build_panel`; wire them in `_rebuild_panel`.
- Color panel (`kind == "auto"`) gains a tip line: "Dualband / narrowband? Skip this — colour is
  applied later by Colourise."
- No change to `PROCESSING_ORDER`/`STEP_NAME` (Colourise is preserved via the name-set rule above,
  not a new pipeline id — keeps recipes unaffected; see Out of Scope).

## Data flow

Stretch step → **Colourise** → truncate to stretch predecessors → StarX (cached) on the linear
base → `compose(default params)` → record `"Colourise"` at the stretch position → later steps
(Levels/Saturation/…) preserve it. Advanced… → same, but through the seeded slider dialog.

## Error handling

- `project is None` / `_busy` guarded.
- RC-Astro unavailable → whole-image fallback (`render_nebula`), with the existing "StarX not
  configured" status note; still produces colour (just with stars processed) — no crash.
- StarX async error → status message; no partial history entry recorded.
- Colourise on an already-stretched state is impossible in practice (it truncates to the pre-stretch
  linear predecessors first), so it never double-stretches.

## Out of scope (explicit — immediate follow-ups)

- **Recipe / batch capture of Colourise.** Because Colourise is not a `PROCESSING_ORDER`/`STEP_NAME`
  id, `recipe_from_entries` skips it — a saved recipe currently omits the colourise step (batch
  output would be un-colourised). This is safe (no crash) but a real gap given recipes are a
  differentiator. Logged as the very next follow-up (needs a `ColouriseStep` + factory + StarX in
  batch). Documented so it isn't a silent surprise.
- Colour pops, Darker/Lighter Sky, explicit Remove/Replace Stars, stretch presets.

## Testing

- **main_window** (`tests/ui/test_main_window.py`):
  - `_colourise()` records a `"Colourise"` entry and produces a colour, stretched
    (`is_linear is False`) image (inject a fake StarX runner returning `(starless, stars)` so no
    RC-Astro binary is needed, mirroring `test_palette_dialog`'s `_fake_starx`).
  - **Preservation (bug 1):** after Colourise, applying a later step (e.g. Saturation) keeps the
    `"Colourise"` entry and builds on it (entries contain "Colourise" and "Saturation", in order).
  - Colourise truncates a prior Apply-Stretch at the reveal position (no double reveal).
  - RC-Astro-absent path: `_colourise()` still yields a stretched colour image (whole-image
    fallback, no crash).
  - `_done_ids` marks `stretch` done after Colourise.
- **step_panels** (`tests/ui/test_step_panels.py`): the stretch panel exposes a `colourise_btn`
  and an `advanced_btn`; clicking them invokes the injected callbacks; Apply Stretch still works.
  The Color panel shows the narrowband tip.
- **star cache:** a second `_colourise()` (or Advanced open) with an unchanged base does not re-run
  the StarX runner (assert the injected runner is called once).
- Full suite green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`).

## Verification (by eye)

Load a linear dualband master → (skip Color) → Stretch step → press **Colourise** → one press gives
a gold/teal colour image with tight stars. Continue to Levels/Saturation → the colour is preserved
(not reset). Advanced… → the slider dialog opens on the same result for fine-tuning.
