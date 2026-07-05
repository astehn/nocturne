# Colourise Stars — The Photoshop Way + User Control — Design

**Date:** 2026-07-05
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — direction + refinement from the user; validated end-to-end on the user's real
NGC 7000 file with real StarX (full star field recovered) before writing this spec.

## Motivation

One-press Colourise produces a beautiful colourised nebula, but the screened-back stars were
heavily reduced (3–4 → still thinned after several brightness fixes). Root cause, measured on real
data: we run StarX on the **linear** master (needed for the per-channel colour), where it detects
fewer/fainter stars, and re-stretching that faint layer can't recover them. Photoshop and
AstroWizard ("Dual Band to Hubble Mix", one click) get full stars because they work in **stretched
space** — StarX sees bright, complete stars and the screen-back is exact.

**Validated fix (real data):** extract the stars from a **display-stretched** copy of the image
(StarX on stretched), then screen those over the linear-colourised nebula. On the user's file this
brings back the full star field (`/tmp/v_composite_default.png`), matching the source density.

## Decisions (from discussion)

- **Extract stars the Photoshop/AstroWizard way** — StarX on the display-stretched image — so we
  capture the full, bright star field. The **colour engine is unchanged** (linear starless →
  per-channel stretch → Foraxx).
- **Blend stars in as-is** (screen), no brightness "magic" by default.
- **User controls the stars before applying:** a **"Star brightness" slider with live preview** in
  Advanced…; Apply commits exactly what was previewed. One-press uses the as-is default.
- Star dimming/reduction stays in the separate **Star Reduction** step.

## Architecture / changes

### `ui/main_window.py` — `_colourise_starx(base)` gets the stars from the stretched image
Run StarX twice (cached together): once on the **linear** base for the colour-starless, once on the
**display-stretched** base for the bright stars.
```python
    def _colourise_starx(self, base):
        sig = self._base_sig(base)
        if self._colourise_layers is not None and self._colourise_layers[0] == sig:
            return self._colourise_layers[1], self._colourise_layers[2]
        if rcastro_valid(self.settings):
            starless, _ = self._remove_stars(base)                          # linear -> colour starless
            stretched = AstroImage(autostretch(base), is_linear=False)      # display stretch
            _, stars = self._remove_stars(stretched)                        # bright, complete stars
        else:
            starless, stars = base, None                                    # whole-image fallback
        self._colourise_layers = (sig, starless, stars)
        return starless, stars
```
`autostretch` is imported from `..core.autostretch`. Two StarX passes cost ~a few seconds on first
press (cached afterwards, and reused by Advanced) — acceptable and matches the tool's existing
async busy overlay.

### `core/palette.py` — `compose` screens the (already-stretched) stars as-is, with a user factor
The `stars` handed to `compose` are now display-stretched (bright). Screen them as-is; a
`star_brightness` factor lets the user push brighter/dimmer. **`restore_stars` is removed** (no
re-brightening magic), along with its now-unused `_stretch_params`/`_apply_params`/`_TARGET_BG`
imports.
```python
@dataclass
class PaletteParams:
    ...
    scnr: bool = True
    star_brightness: float = 1.0   # screened stars as-is at 1.0; >1 brighter, <1 dimmer


def compose(starless, stars, params):
    nebula = render_nebula(starless, params)
    s = np.clip(stars.data, 0.0, 1.0)
    if params.star_brightness != 1.0:
        s = np.power(s, 1.0 / params.star_brightness)   # gamma: higher param = brighter stars
    out = screen(nebula.data, s.astype(np.float32))
    return AstroImage(out, is_linear=False, metadata=dict(starless.metadata))
```
(The one-press path in `_colourise` still calls `compose(starless, stars, PaletteParams())` when
`stars is not None`, else `render_nebula`.)

### `ui/palette_dialog.py` — "Star brightness" slider with live preview
Add a `star_slider` (`ResetSlider`, default maps to `star_brightness = 1.0`) below the existing
controls; on change it re-composites and updates the preview (existing preview machinery). `_params()`
includes `star_brightness = star_slider.value() / <scale>` (mapped so mid = 1.0, right = brighter).
The dialog is seeded with `(starless, stretched_stars)` exactly as today — no seeding change beyond
`stars` now being the stretched layer.

## Data flow

`_colourise` → `_colourise_starx` (StarX linear → starless; StarX on display-stretch → bright stars,
cached) → `compose(starless, stars, PaletteParams())` → `render_nebula(starless)` (colour, unchanged)
→ screen the bright stars (as-is, or user `star_brightness`) → record "Colourise". Advanced… opens
the dialog seeded with the same layers, adds the live star-brightness slider.

## Error handling

- No RC-Astro → whole-image fallback (`stars is None` → `render_nebula`), unchanged.
- `star_brightness == 1.0` → stars screened exactly as StarX-on-stretched produced them (no-op path).
- StarX async errors handled by the existing `_colourise` err path; two passes run inside the same
  `work()` so a failure surfaces once.

## Testing

- **core** (`tests/core/test_palette.py`):
  - `compose` screens the given (pre-stretched) stars **as-is** at `star_brightness=1.0` — a bright
    star pixel in the stars layer appears bright in the composite (screen math), and the star layer
    is used unmodified (no re-stretch): assert composite ≥ nebula at a star pixel and that
    `star_brightness=1.0` leaves the stars' relative values unchanged before screen.
  - `star_brightness > 1.0` brightens the screened stars vs `1.0`; `< 1.0` dims them.
  - `restore_stars` is gone (`assert not hasattr(palette, "restore_stars")`); `PaletteParams` has
    `star_brightness == 1.0` and no `star_brightness`-less regressions; `is_linear is False` kept.
- **main_window** (`tests/ui/test_main_window.py`): `_colourise_starx` runs StarX on BOTH the linear
  base and a stretched copy when RC-Astro is present (inject a fake `_remove_stars` that records its
  input's `is_linear`; assert it's called for a linear AND a non-linear image); whole-image fallback
  unchanged; the cache still yields one extraction per base.
- **step_panels / palette_dialog** (`tests/ui/test_palette_dialog.py`): the dialog exposes a
  `star_slider`; moving it changes the composed preview; `_params().star_brightness` reflects it.
- **Real-data check (manual, before merge):** re-run the validation script on the user's file and
  confirm the composite shows the full star field (already done for this spec).
- Full suite green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`).

## Out of scope (fast-follow)

- Single-StarX-pass optimisation (invert the display stretch to recover the linear starless) — a
  possible speed-up; the validated 2-pass approach ships first.
- Recipe/batch capture of Colourise (already logged).

## Verification (by eye)

Colourise a dualband master → the full star field returns over the colourised nebula (matching the
source), one press. Advanced… → the Star brightness slider dials the stars up/down with a live
preview; Apply commits exactly that.
