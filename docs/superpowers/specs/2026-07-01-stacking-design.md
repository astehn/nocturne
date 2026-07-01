# Stacking (Preprocessing) — Design

**Date:** 2026-07-01
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — ready for implementation planning

## Motivation

Nocturne exists to make the repetitive, scientific parts of astrophotography
post-processing simple for **smart-telescope users** (ZWO Seestar S30 Pro), so they can
get good results without PixInsight/Siril. Today the app starts from a *stacked* FITS —
which means users must stack their subs in another program first. This is the one major
gap in the "do the whole job in one simple app" story.

Advanced Seestar users can enable a mode that **saves every individual sub-frame** as its
own `.fit` file. This feature stacks that folder of light subs into a single clean master
FITS that flows straight into the existing editing pipeline — giving quality the on-device
live stack can't: **pixel rejection** (kills satellite trails, planes, hot pixels) and
**bad-frame rejection** (clouds, wind, poor tracking).

Stacking is a **separate function**, launched from the toolbar like Batch — **not** part of
the main one-step-at-a-time editing flow.

## Scope

**In scope**
- Input: a folder of individual **light** sub-frames (`.fit`/`.fits`/`.fts`), raw Bayer
  (OSC) or already-color — detected/handled by the existing `core/fits_io` loader.
- Per-frame **grading** (star count, FWHM, background) with a transparent checklist and
  auto-suggested rejects.
- **Registration** handling both translation and **rotation** (the Seestar is an alt-az
  mount, so the field rotates across a session).
- **Integration** with pixel rejection: Average and Sigma-clipped methods.
- Output: one **linear 32-bit master FITS**, saved to disk **and** loaded into the editor
  session (Import step).

**Explicitly out of scope (deferred)**
- Calibration frames (darks/flats/bias). Seestar handles darks internally and flats are
  impractical on a sealed scope; lights-only matches the "keep it simple" philosophy.
  A calibration layer can be added later without disturbing this design.
- Drizzle / CFA-drizzle, comet stacking, mosaic assembly.
- Multi-night registration (the existing "Multi-session combine" backlog item is the
  higher-level cousin of this; this feature is the more fundamental raw-sub stacker).

## Engine choice

**`astroalign` + `sep`, with streaming numpy integration.** (Chosen over a
scikit-image-only aligner and over shelling out to Siril.)

- **`astroalign`** (MIT, pip) registers by matching triangles of stars and computes a full
  **similarity transform (rotation + translation + scale)** — the only viable option for
  the alt-az field rotation. Translation-only methods (phase correlation) would smear stars
  into arcs.
- **`sep`** (pulled in by astroalign) detects stars, doing double duty: it powers both
  registration and grading, so no separate star-detection machinery is needed.
- Self-contained: both are pip wheels on macOS — **no external application** for the user
  to install/configure, unlike a Siril-CLI approach. This preserves the app's beginner-
  friendly, self-contained premise.
- New dependencies: `astroalign`, `sep` (added to `pyproject.toml`).

## Architecture

New **Qt-free `stacking/` core package** + one **UI dialog**, mirroring the existing
`batch.py` (core) / `ui/batch_dialog.py` (UI) pattern.

```
seestar_processor/
  stacking/
    __init__.py
    frames.py      # discover subs in a folder; lazy per-frame load (never all at once)
    grade.py       # FrameStats via sep: star_count, fwhm, background -> score + outlier flag
    register.py    # astroalign wrapper: transform sub->reference, apply per RGB channel
    integrate.py   # streaming integrator: Average + Sigma-clipped, O(1 frame) memory
    stacker.py     # run_stack(folder, opts, *, on_progress) -> StackResult  (batch.py analog)
  ui/
    stack_dialog.py  # "Stack..." toolbar button + dialog     (batch_dialog.py analog)
```

Boundaries:
- **Core is Qt-free and unit-testable** (like `core/`, `batch.py`).
- `stacker.run_stack` is headless; the dialog drives it through the existing
  `ui/worker.run_async` + progress-signal seam (same as `BatchDialog`), with an injectable
  `_stack_runner` for tests.
- Reuses `core/fits_io` (load + debayer), `core/export.save_fits`, `core/image.AstroImage`,
  `ui/worker`.

## Data model

```python
@dataclass
class FrameStats:
    path: str
    star_count: int
    fwhm: float           # median, pixels
    background: float     # median sky level, normalized
    score: float          # composite 0..1, higher = better
    included: bool        # default suggestion; user-overridable in the UI

@dataclass
class StackOptions:
    method: str           # "average" | "sigma_clip"
    kappa: float          # sigma-clip threshold (e.g. Low 3.0 / Med 2.5 / High 2.0)
    include: list[str]    # explicit list of sub paths to integrate (post-user-edit)
    output_path: str

@dataclass
class StackResult:
    image: AstroImage     # linear 32-bit RGB master
    used: list[str]       # subs actually integrated
    rejected: list[tuple[str, str]]  # (path, reason) — graded-out, reg-failed, unreadable
    frame_count: int
    integration_seconds: float       # sum of EXPTIME across used subs
    output_path: str
```

## Pipeline / data flow

1. **Discover** (`frames.py`) — glob `*.fit/*.fits/*.fts`; expose lazy per-frame loading
   (load + debayer one sub at a time via `core/fits_io`). Never hold all frames in RAM.
2. **Grade** (`grade.py`) — for each sub, derive luminance, run `sep` for background + star
   catalog; compute `star_count`, median `fwhm`, `background`; composite `score`. Flag
   statistical outliers (far-below-median stars, far-above-median FWHM/background) as
   `included=False` by default. Returns `list[FrameStats]` sorted worst→best.
3. **Reference selection** — the highest-scoring included sub becomes the registration
   reference. If even the best sub has too few stars to align, error out clearly.
4. **Register** (`register.py`) — for each included sub, `astroalign.find_transform(sub_lum,
   ref_lum)` → similarity transform; apply to each RGB channel (warp). The transform matrix
   is cached in memory (tiny) for reuse in integration pass 2. A sub whose transform can't
   be found is auto-rejected with a reason.
5. **Integrate** (`integrate.py`) — **streaming, O(one frame + accumulators) memory**,
   frame count unbounded:
   - **Average**: one pass — running sum + count.
   - **Sigma-clipped**: two passes. Pass 1 warps each frame (caching its transform) and
     accumulates per-pixel mean + variance (Welford). Pass 2 re-warps using the **cached
     transform** (no re-detection), rejects pixels beyond κ·σ of the pass-1 mean, and
     accumulates the clipped mean. Extra cost is one warp/frame, not double registration.
6. **Output** — wrap master as `AstroImage(is_linear=True)`; sum `EXPTIME` headers →
   `integration_seconds`; `save_fits` to `output_path` with a header noting sub count and
   integration time; return `StackResult`. The UI then loads `result.image` into the
   editor session (Import step).

## UI — Stack dialog

Toolbar **"Stack..."** button beside "Batch...". Dialog (dark theme, injectable
`_stack_runner`, progress marshaled via a Qt signal exactly like `BatchDialog`):

- **Folder of subs** picker. On select → grading runs in the background (`run_async`) and
  fills a **frame table**: filename, star count, FWHM, background, score, and an
  include **checkbox**. Sorted worst→best; worst outliers pre-unchecked; user can override
  any checkbox.
- **Integration**: Average / Sigma-clipped radio, with a κ selector (Low/Med/High) for
  sigma-clip.
- **Output** path (defaults to `<folder>/master.fits`).
- **Stack** button → runs `run_stack` async with a live progress line
  (`grading / registering / integrating i/N`). On completion: save master, load it into the
  editor session, close the dialog.

## Error handling & edge cases

Each surfaces a clear message; none crash the app:
- Fewer than ~3 usable frames → "not enough frames to stack."
- Best frame too star-sparse to be a reference → "not enough stars to align."
- Corrupt/unreadable sub → skipped, added to `rejected` with reason.
- Dimension mismatch (a sub from a different target/binning in the folder) → rejected.
- Per-frame registration failure → auto-rejected, reason noted.
- `astroalign`/`sep` import guarded → if somehow missing, the feature is disabled with a
  message and the app still launches (same spirit as RC-Astro gating).

## Testing

All synthetic, headless, fast — no real data required:
- **grade**: a low-star / high-background frame scores low and is flagged.
- **register**: build a star field, make a shifted **and rotated** copy, assert astroalign
  recovers the transform within tolerance (proves alt-az field-rotation handling).
- **integrate**: streaming average equals naive numpy mean; sigma-clip rejects an injected
  hot pixel / satellite streak that a plain average would retain.
- **stacker**: end-to-end `run_stack` on a temp folder of synthetic FITS subs → master of
  correct shape, `is_linear=True`, with rejection metadata populated.
- **stack_dialog**: injected fake `_stack_runner` (mirrors the batch-dialog test) verifies
  wiring, progress updates, and the save + load-into-editor handoff.

## Verification (end to end, real data)

1. Enable "save every frame" on the Seestar; capture a target → folder of `.fit` subs.
2. Nocturne → **Stack...** → pick the folder → grading fills the table; a cloud/trailed sub
   shows a low score and is pre-unchecked.
3. Stack (Sigma-clipped) → master loads into the editor; satellite trails present in the
   live stack are gone; background is cleaner than a plain average.
4. Confirm the saved `master.fits` header records sub count and total integration time.
5. Process the master through the normal flow (crop → background → color → stretch → ...).
