# Ha/OIII Extraction (Duo-band Stacking) — Design

**Date:** 2026-07-03
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — ready for implementation planning

## Motivation

The Seestar S30 Pro's built-in Ha+OIII dual-band filter puts real narrowband signal in
emission-nebula captures. Our current narrowband path debayers each sub to RGB, stacks to one
RGB master, then the Palette tool extracts Ha=R / OIII=(G+B)/2 from that finished master.
Siril's `OSC_Extract_HaOIII.ssf` does it better: it splits the raw **CFA** data into separate
Ha and OIII channels *before* debayering, stacks each channel independently, and combines
them. This spec builds a **lights-only** version of that technique — no darks/flats/bias,
matching Nocturne's philosophy — as a dedicated tool that produces a combined master for the
editor + Palette tool.

## Why it beats the current path

- **CFA-level extraction** avoids demosaic interpolation smearing Ha and OIII into each other.
- **Ha and OIII are stacked separately** — each gets its own rejection and SNR (OIII, being
  faint, benefits most).
- **MAD/median renormalization** matches OIII's background and noise scale to Ha so the
  combination is clean, not muddy.

## Calibration dropped (lights-only)

The Siril script's bias/flat/dark half is separable and omitted here:
- **Dark/bias** (hot pixels, thermal, read noise) → the Seestar handles darks on-device, and
  **sigma-clip rejection during stacking** removes hot pixels / cosmic rays / trails.
- **Flat** (vignetting, dust motes) → impractical on a sealed scope; GraXpert background
  extraction mitigates the residual gradient afterward.
Honest caveat: without a flat, dust motes/vignetting remain; without a dark, slightly more
thermal noise. Acceptable for duo-band emission targets and consistent with the app.

## Decisions (from brainstorming)

- **Output:** one combined RGB master — `R = Ha`, `G = OIII'`, `B = OIII'` — so it loads into
  the editor and the existing Palette tool recovers Ha=R / OIII=(G+B)/2.
- **Placement:** a separate **"Ha/OIII Extract…"** toolbar tool + dialog (not a mode of Stack).
- **Grading:** include the same scored frame table + auto-reject as the Stack tool (reuse
  `grade.grade_frames`).

## Architecture

```
seestar_processor/
  stacking/haoiii.py    # Qt-free: extract_cfa_planes, renorm_oiii, run_haoiii_extract
  ui/haoiii_dialog.py   # dialog: folder -> grade table -> extract -> combined master
  ui/main_window.py     # "Ha/OIII Extract…" toolbar action + guarded open
```

Reuses (unchanged): `stacking/frames.discover_subs`, `stacking/grade` (FrameStats,
grade_frames), `stacking/register` (find_transform, warp_to, RegistrationError),
`stacking/integrate` (average_integrate, sigma_clip_integrate), `stacking/coverage`
(full_coverage_bounds, coverage_map), `core/export.save_fits`, `core/image.AstroImage`,
`core/instrument`/`core/fits_io._bayer_pattern` (GRBG from header), `ui/worker`,
`MainWindow.open_image`.

## The duo-band pipeline

Each raw sub is one mono **CFA (GRBG)** frame (2D). The GRBG 2×2 tile is:

```
G R
B G
```

**Per-sub extraction** (`extract_cfa_planes(cfa, pattern) -> (ha, oiii)`), full-res via
upscaling the half-res planes:
- **Ha** = the red sites (`cfa[0::2, 1::2]` for GRBG) — Hα (656nm) only passes red.
- **OIII** = (green + blue) / 2, where green = mean of the two green sites
  (`cfa[0::2,0::2]`, `cfa[1::2,1::2]`) and blue = `cfa[1::2,0::2]` — OIII (~500nm) passes
  green+blue.
- Each half-res plane is bilinearly upscaled back to the sub's full (H, W).
- Bayer site offsets are derived from the pattern string so non-GRBG patterns also work.

**Shared-transform simplification (the key win):** Ha and OIII from the same sub share the
exact same coordinate frame (same exposure/pointing), so we register once on Ha and reuse the
transform for OIII — no independent OIII registration, no cross-registration of the two
masters (both end up in the Ha reference frame, already aligned).

**Orchestration** (`run_haoiii_extract(opts, *, on_progress=None) -> HaOIIIResult`):
1. Validate ≥3 included frames; the reference = best included sub; its Ha plane is the
   registration reference (`ref_ha_lum`).
2. **Phase A (register):** for each included sub, load raw CFA, extract Ha/OIII,
   `find_transform(ha, ref_ha_lum)` → cache `Tᵢ`; drop on unreadable / dimension mismatch /
   registration failure (collected in `rejected`). Progress label "registering".
3. **Phase B (stack), streaming, two accumulators:** stream Ha planes warped by `Tᵢ` →
   `sigma_clip_integrate`/`average_integrate` → Ha master; likewise OIII planes warped by the
   **same** `Tᵢ` → OIII master. Progress "stacking Ha" / "stacking OIII".
4. **Renorm:** `renorm_oiii(ha, oiii)` → `a = mad(ha)/mad(oiii)`,
   `oiii' = a*(oiii - median(oiii)) + median(ha)`, clipped ≥0.
5. **Coverage crop** (reuse `full_coverage_bounds` on the cached transforms), then pack
   `RGB = stack([ha, oiii', oiii'], axis=2)`, normalize once by peak, `AstroImage(is_linear=
   True)`, sum EXPTIME into metadata + FITS header, `save_fits`.
6. Return `HaOIIIResult(image, used, rejected, frame_count, integration_seconds, output_path)`.

Frames are loaded **raw** (`load_sub(path, normalize=False)`) so Ha/OIII share one photometric
scale; the master is normalized once at the end (same rule as the RGB stacker).

## Data model / API

```python
@dataclass
class HaOIIIOptions:
    method: str          # "sigma_clip" | "average"
    kappa: float
    include: list        # sub paths, best-first; include[0] is the reference
    output_path: str

@dataclass
class HaOIIIResult:
    image: AstroImage
    used: list
    rejected: list       # (path, reason)
    frame_count: int
    integration_seconds: float
    output_path: str

def extract_cfa_planes(cfa: np.ndarray, pattern: str) -> tuple[np.ndarray, np.ndarray]:
    """(ha, oiii) full-res float32 from a 2D CFA frame. Ha=red sites; OIII=(green+blue)/2;
    half-res planes bilinearly upscaled. Raises ValueError if cfa is not 2D."""

def renorm_oiii(ha: np.ndarray, oiii: np.ndarray) -> np.ndarray:
    """Linear-fit OIII to Ha: a=mad(ha)/mad(oiii); a*(oiii-median(oiii))+median(ha)."""

def run_haoiii_extract(opts, *, on_progress=None) -> HaOIIIResult: ...
```

## UI — dialog

Toolbar **"Ha/OIII Extract…"** (guarded import, like `_open_stack`). Dialog mirrors
`StackDialog`: folder picker → async grading fills a scored frame table (worst pre-unchecked,
overridable) → integration radios (Sigma-clipped default / Average) + κ selector → output path
(defaults `<folder>/HaOIII_master.fits`) → **Extract** runs `run_haoiii_extract` async with a
progress line (grading / registering / stacking Ha / stacking OIII). On completion: save the
combined master, load it into the editor via `on_master`, close. Injectable `_grade_runner`
and `_extract_runner` for tests.

## Error handling

Clear message, never crash:
- < 3 usable frames → "not enough frames".
- Star-sparse reference / < 3 registered → "not enough frames could be registered".
- **Input not raw CFA** (a sub loads as 3-channel/already-debayered) → reject that sub with
  "needs raw (un-debayered) subs"; if none are raw CFA, error out.
- Unreadable sub / dimension mismatch / registration failure → rejected with reason, noted.
- No RC-Astro/GraXpert needed (this tool uses neither).

## Testing

Synthetic, headless, fast:
- `extract_cfa_planes`: a synthetic GRBG frame with known R/G/B site values → `ha` == red
  sites, `oiii` == (green+blue)/2, both upscaled to full (H, W); raises on a 3D input.
- Shared transform: a sub's Ha and OIII planes warped by the same matrix stay pixel-aligned.
- `renorm_oiii`: an OIII plane with a known scale+offset is matched to Ha's median and MAD.
- `run_haoiii_extract`: temp folder of synthetic **CFA** subs (small shifts) → combined RGB
  master, correct shape, `is_linear=True`, R≈Ha and G==B (OIII), rejection metadata populated;
  a non-CFA (3D) sub in the folder is rejected, not crashed.
- `haoiii_dialog`: injected fake grade + extract runners → table fills, Extract runs, progress
  fires, `on_master` handoff called; < 3 selected → status message.

## Verification (end to end, real data)

1. Point the tool at the real Pelican (IC 5070) raw subs folder → grade → Extract.
2. Combined master loads in the editor; run Palette (per-channel curves) → compare the
   duo-band-extracted result against the current debayer-then-extract master (expect cleaner
   OIII / better channel separation).
3. Confirm the saved `HaOIII_master.fits` header records sub count + integration time.
