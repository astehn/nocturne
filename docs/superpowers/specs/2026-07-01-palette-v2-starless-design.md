# Palette v2 — Starless Narrowband Workflow — Design

**Date:** 2026-07-01
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — ready for implementation planning
**Supersedes:** the file-in/out palette dialog from `2026-07-01-narrowband-palette-design.md`
(the `core/palette.py` extract/HOO/pseudo-SHO core is kept and extended).

## Motivation

The v1 palette tool did a crude **whole-image** channel remap. That maps the stars too, so
they become ugly colored blobs over the false-color nebula — the main reason v1 results
look unpleasant. The professional narrowband workflow separates stars first: remove stars →
color the *starless* nebula (with tweaks) → screen neutral stars back. This spec rebuilds
the palette feature around that workflow, interactively, so results are actually pleasing.

## Decisions (from brainstorming)

- **Interactive, on the current editor image** (not file-in/out). Live preview + sliders;
  **Apply** records the result in the editor's history (undoable).
- **Star separation via StarXTerminator** (`RCAstro.remove_stars`, already built, returns
  `(starless, stars)`). Run **once** on open, cache the layers.
- **Controls:** palette (HOO / pseudo-SHO), nebula **saturation**, **Ha/OIII balance**,
  **green suppression (SCNR)**. No star brightness/size control.
- **Stars neutralized to white** before screening back.
- **Graceful fallback:** if RC-Astro isn't configured, apply the palette to the whole image
  (v1 behavior) with a note — the feature still works without StarX.

## Scope

**In scope**
- Rebuild `ui/palette_dialog.py` as an interactive dialog on the current image.
- Extend `core/palette.py`: `PaletteParams`, `render_nebula`, `neutralize_stars`, `screen`,
  `compose`.
- MainWindow: "Palette…" opens the new dialog on the current image; a helper records the
  Apply result in project history.

**Out of scope (deferred)**
- Star brightness/size controls; per-star color tinting.
- Automatic emission-target detection.
- File-in/out batch palette (v1's mode is dropped; `load_master` is retained as a utility
  but no longer used by the palette dialog).
- v1's "subtract background first" checkbox is dropped: v2 operates on an already-finished
  (background-processed, stretched) editor image, so a background pedestal isn't present.
  `subtract_background` stays in `core/palette.py` (harmless/retained) but the dialog no
  longer calls it.

## Architecture

```
seestar_processor/
  core/palette.py       # v1 (extract_channels, hoo, pseudo_sho, apply_palette,
                        #     subtract_background) + NEW: PaletteParams, render_nebula,
                        #     neutralize_stars, screen, compose            (Qt-free)
  ui/palette_dialog.py  # rebuilt: preview + sliders; StarX once; Apply -> history
  ui/main_window.py     # "Palette…" -> dialog on current image; record_palette_result()
  tools/rcastro.py      # RCAstro.remove_stars (existing, unchanged)
```

Core stays Qt-free and unit-testable. The dialog reuses `ui/worker.run_async` + `BusyOverlay`
(StarX is slow) and `ui/preview.to_qimage` (input is already stretched → render directly).

## Data model / core API

```python
# core/palette.py
@dataclass
class PaletteParams:
    palette: str = "HOO"      # "HOO" | "pseudo_SHO"
    balance: float = 0.5      # 0=OIII emphasis .. 0.5 neutral .. 1=Ha emphasis
    saturation: float = 0.5   # 0=greyscale .. 0.5 as-mapped .. 1=strong
    scnr: bool = True         # green suppression on the nebula

def render_nebula(starless: AstroImage, params: PaletteParams) -> AstroImage:
    """Extract Ha/OIII from the starless nebula, apply Ha/OIII balance, map to the
    chosen palette, apply saturation, and (optionally) SCNR. Returns a colored
    starless nebula."""

def neutralize_stars(stars: AstroImage) -> AstroImage:
    """Replace the stars layer's colour with its luminance -> white stars."""

def screen(base: np.ndarray, top: np.ndarray) -> np.ndarray:
    """Screen blend: 1 - (1-base)*(1-top)."""

def compose(starless: AstroImage, stars: AstroImage, params: PaletteParams) -> AstroImage:
    """render_nebula(starless) then screen neutralize_stars(stars) back on top."""
```

**Control formulas (initial, tuned on real data):**
- **Ha/OIII balance** `b∈[0,1]`: weight `ha *= 2b`, `oiii *= 2(1-b)` (clamped), so `b=0.5`
  is neutral, `b>0.5` favors Ha, `b<0.5` favors OIII; renormalize to keep range.
- **Palette:** HOO = `(ha, oiii, oiii)`; pseudo-SHO = `(ha, 0.5*ha+0.5*oiii, oiii)`.
- **Saturation** `s∈[0,1]`: `out = lum + k(s)*(rgb - lum)` where `lum` is per-pixel
  luminance and `k(0.5)=1` (as-mapped), `k(0)=0` (grey), `k(1)≈2` (strong). Reuse the
  spirit of `core/saturation.py`.
- **SCNR:** `green = min(green, (red+blue)/2)` (reuse `core/color.py` remove_green).
- **Neutralize stars:** `lum = mean(RGB)`; output `(lum, lum, lum)`.
- **Screen:** `1 - (1-nebula)*(1-stars)`, clipped [0,1].

Exact `k(s)` and balance coefficients are the documented starting point; refined by eye on
the real Pelican (IC 5070) master.

## StarX integration & caching

On dialog open (with a colour image present and RC-Astro configured):
- Run `RCAstro.remove_stars(image)` once via `run_async` (BusyOverlay "Removing stars…").
- Cache `starless` and `neutralize_stars(stars)`.
- All slider re-renders use the cached layers — StarX never re-runs for tweaks.

If RC-Astro is **not** configured: skip StarX; treat the whole image as the "starless"
input (no stars layer to screen back) and show a note. Slider tweaks still work.

## UI — dialog

Toolbar **"Palette…"** opens the dialog on the current editor image. Layout: a **preview**
pane (downscaled live render) + controls — palette radios (HOO / pseudo-SHO), an **Ha↔OIII**
slider, a **Saturation** slider, a **Green (SCNR)** toggle — plus **Apply** / **Close** and
a status line. Slider/radio changes re-render the downscaled preview immediately; full-res is
computed only on Apply. **Apply** calls back into MainWindow to record the full-res result in
project history as a "Palette" step, then closes. Injectable seams for tests: `_starx_runner`
(defaults to `RCAstro.remove_stars` via settings) and direct `core.palette` calls.

## Error handling

Each surfaces a clear message; none crash:
- No image loaded → "Open or stack an image first" (dialog does not open / shows note).
- Not a colour image → "needs a colour image".
- RC-Astro not configured → whole-image fallback + note.
- StarX subprocess failure → surfaced status, no crash; dialog stays open.

## Testing

Synthetic, headless, fast — no real RC-Astro needed (StarX is injected):
- `neutralize_stars`: a coloured star pixel → grey (R=G=B=luminance).
- `screen`: matches `1-(1-a)(1-b)`; screening stars onto a nebula brightens only star sites.
- `render_nebula`: saturation=0 → greyscale; higher saturation widens channel spread; SCNR
  lowers green; balance>0.5 raises Ha (red) vs balance<0.5 raising OIII (teal); palette
  dispatch (HOO vs pseudo-SHO) differs as expected.
- `compose`: starless→palette→white-stars-back returns a valid AstroImage, stars present,
  nebula coloured.
- `palette_dialog`: injected fake StarX runner (synthetic starless+stars) → preview renders;
  a slider change re-renders; **Apply** invokes the history-record callback; the
  no-RC-Astro path uses the whole-image fallback.

## Verification (end to end, real data)

1. Process a Pelican (IC 5070) master to a finished stretched image in the editor.
2. **Palette…** → StarX removes stars (once) → preview shows the starless nebula in HOO with
   white stars screened back.
3. Tweak Ha/OIII balance, saturation, SCNR → preview updates live; dial in a pleasing look.
4. Switch to Pseudo-SHO → gold/teal look; confirm stars stay white, not magenta blobs.
5. **Apply** → result lands in history (undoable); export as usual.
