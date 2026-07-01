# Narrowband Palette (HOO / pseudo-SHO) — Design

**Date:** 2026-07-01
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — ready for implementation planning

## Motivation

The ZWO Seestar S30 Pro has a built-in **dual-band filter (Ha + OIII)**, so emission-nebula
captures hold real narrowband signal: **Ha** on the red Bayer pixels, **OIII** on the
green/blue pixels. Remapping that into a false-colour "Hubble" palette is a popular but
fiddly manual job in PixInsight/Siril. This feature automates it as a **standalone tool**,
kept out of the basic one-step editing flow.

## Honesty constraint (defining the scope)

True **SHO** (the classic Hubble palette) maps SII→R, Ha→G, OIII→B — it needs three
narrowband channels from a mono camera with separate filters. The Seestar is **Ha + OIII
only; there is no SII signal**. So this tool offers:

- **HOO** — the honest native duo-band palette: Ha→Red, OIII→Green+Blue.
- **Pseudo-SHO** — a Foraxx-inspired artistic remap that produces the gold-and-teal SHO
  *look* from just Ha and OIII. Labeled **pseudo** everywhere; it is not real SHO.

## Scope

**In scope**
- Standalone **file-in / file-out** tool (decoupled from the editor, like Batch).
- Input: a stacked/processed master — **FITS** or **16-bit TIFF** — still holding OSC
  duo-band structure (Ha in red, OIII in green/blue).
- Two palettes: **HOO** and **pseudo-SHO**.
- Output: write a new file; optionally load the result into the editor for fine-tuning.

**Out of scope (deferred)**
- Natural/bicolor boost and single-channel mono extraction (not chosen).
- Live/interactive preview, per-channel tuning knobs, star-colour correction.
- Auto-detection of "is this an emission nebula" (the user picks when to use it).
- Batch application across a folder (single file per run).

## Architecture

New Qt-free core module + a small input loader + one UI dialog, mirroring the existing
`batch.py` (core) / `ui/batch_dialog.py` (UI) pattern.

```
seestar_processor/
  core/palette.py       # extract_channels, hoo, pseudo_sho, apply_palette  (Qt-free)
  core/fits_io.py       # add load_master(path): FITS (existing load_fits) + 16-bit TIFF
  ui/palette_dialog.py  # "Palette..." dialog: file in -> pick palette -> write file
  ui/main_window.py     # "Palette..." toolbar action + guarded open (like _open_stack)
```

- `core/palette.py` is pure numpy, Qt-free, unit-testable.
- The palette apply runs **synchronously** (fast on 8 MP); a status line, no progress bar.
- Reuses `core/export.save_tiff/save_fits/save_png`, `core/image.AstroImage`,
  `MainWindow.open_image` (the editor handoff added for stacking).

## Data model / API

```python
# core/palette.py
PALETTES = ("HOO", "pseudo_SHO")

def extract_channels(img: AstroImage) -> tuple[np.ndarray, np.ndarray]:
    """Return (ha, oiii) as 2D float32 in [0,1]. ha = red channel;
    oiii = (green + blue) / 2. Raises ValueError if img is not colour (RGB)."""

def hoo(img: AstroImage) -> AstroImage:
    """R=Ha, G=OIII, B=OIII. is_linear preserved from input."""

def pseudo_sho(img: AstroImage) -> AstroImage:
    """Foraxx-inspired gold/teal remap from Ha+OIII (labeled pseudo)."""

def apply_palette(img: AstroImage, name: str) -> AstroImage:
    """Dispatch by name ('HOO' | 'pseudo_SHO'); ValueError on unknown name."""
```

**Channel extraction:** `ha = R`, `oiii = (G + B) / 2`, both clipped to [0,1].

**HOO:** `stack(ha, oiii, oiii)` → red Ha + teal OIII.

**Pseudo-SHO (initial formula, tuned on real data):** push Ha toward gold, OIII toward
teal, with a dynamic green so Ha-strong areas don't wash out:
```
R = ha
G = clip(0.5*ha + 0.5*oiii, 0, 1)      # gold where Ha dominates, teal where OIII does
B = oiii
```
This is the documented starting point; the exact coefficients/nonlinearity are refined by
eye against real Pelican (IC 5070) data during implementation — synthetic tests lock the
*intent* (Ha→gold, OIII→teal), not exact pixel values.

```python
# ui/palette_dialog.py
class PaletteDialog(QDialog):
    def __init__(self, settings, parent=None, on_master=None) -> None: ...
    _palette_runner = apply_palette   # injectable for tests
    _loader = load_master             # injectable for tests
    def run(self) -> None: ...        # read input -> apply -> write -> optional handoff
```

## Input loader

Add `load_master(path) -> AstroImage` to `core/fits_io.py`:
- `.fits/.fit/.fts` → existing `load_fits`.
- `.tif/.tiff` → `tifffile.imread`, cast float32, normalize by max to [0,1], wrap
  `AstroImage(is_linear=True)`. 16-bit and 8-bit both supported.
- Other extensions → `ValueError("unsupported input format")`.

## UI — Palette dialog

Toolbar **"Palette..."** button beside "Stack..."/"Batch...". Dialog (dark theme, injectable
`_palette_runner` and `_loader`):
- **Master image** file picker (FITS/TIFF).
- **Palette**: `(•) HOO  ( ) Pseudo-SHO`, with a one-line honest caption under each.
- **Output** path — auto-fills to `<stem>_HOO.<ext>` / `<stem>_SHO.<ext>` when the palette
  or input changes; format follows the output extension (TIFF/FITS/PNG via existing exporters).
- **[x] Open result in the editor** checkbox.
- **Apply** → `load_master(input)` → `apply_palette(img, name)` → write via the matching
  exporter → if checked, `on_master(result)` handoff → close. Runs synchronously with a
  status line.

Toolbar wiring uses a **guarded import** (`_open_palette`), same spirit as `_open_stack`.

## Error handling

Each surfaces a clear message; none crash:
- Input not colour/RGB (mono or single-channel) → "needs a colour master".
- Unreadable/corrupt file → surfaced status, no crash.
- Unsupported input/output format → clear message.
- Empty input/output path → prompt to pick.

## Testing

Synthetic, headless, fast:
- `extract_channels`: `oiii == (G+B)/2` on a known RGB array; raises on a mono image.
- `hoo`: a Ha-strong/OIII-weak pixel → red-dominant (R > G,B); an OIII-strong pixel → teal
  (G ≈ B, both > R).
- `pseudo_sho`: a Ha-dominant region → gold (R and G raised vs B); an OIII region → teal.
- `apply_palette`: dispatches to the right palette; `ValueError` on unknown name.
- `load_master`: round-trip a saved 16-bit TIFF and a FITS back to `AstroImage` (shape,
  [0,1] range); `ValueError` on an unsupported extension.
- `palette_dialog`: injected fake `_palette_runner`/`_loader` (mirrors batch/stack dialog
  tests) → file-in → Apply → output written → `on_master` handoff called.

## Verification (end to end, real data)

1. Stack/process a Pelican (IC 5070) master (duo-band emission target).
2. Palette... → pick the master → **HOO** → Apply → result loads in the editor: expect a
   clean teal/red emission-nebula rendering.
3. Re-run → **Pseudo-SHO** → expect the gold-and-teal SHO look; tune the formula by eye
   until it reads Hubble-ish without artefacts.
4. Confirm output files are written and reopen correctly.
