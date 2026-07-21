# Narrowband Colour Tool (NarrowbandNormalization) — Design

**Status:** design approved by the user 2026-07-21 (workflow = single guided tool;
stars = StarX-when-present else whole-image; palettes = HOO + two labelled pseudo-SHO
looks). Spec awaiting user review before the implementation plan.
**Group:** Narrowband (its own multi-increment cycle)

## Problem & goal

Nocturne's audience shoots **ZWO Seestar dual-band OSC** data: two real signals,
**Ha** (H-alpha) and **OIII** (oxygen), with OIII usually weak under light-polluted
skies. A naive channel map (Ha→R, OIII→G&B) plus SCNR yields the classic
orange/red cast, because Ha's overall level swamps OIII. The goal is a **guided
Narrowband tool that produces natural SHO/HOO-style colour as good as PixInsight's
NarrowbandNormalization**, on this dual-band data, usable by novices.

The load-bearing idea (verified against Bill Blanshan & Mike Cranfield's public
"Normalize V8" PixelMath and a GPL-3.0 numpy port — see *Provenance*): **before
combining, statistically lift the weak channel (OIII) up to the strong reference
channel (Ha) with a midtones-transfer-function (MTF) median match.** This is the
step naive combines skip, and it is what turns a flat orange frame into one with
real teal/blue oxygen.

## Provenance & licensing

- PixInsight **NarrowbandNormalization** is a closed compiled C++ module (Mike
  Cranfield), but it is a faithful port of Blanshan & Cranfield's **public
  "Normalize HOS data — V8" PixelMath**, which we have verbatim and algebraically
  confirmed.
- A **GPL-3.0** numpy reimplementation exists in Franklin Marek's SetiAstroSuite
  (`setiastro/setiastrosuitepro`, `src/setiastro/saspro/imageops/narrowband_normalization.py`).
  GPL-3.0 is compatible with Nocturne (GPLv3), so we may read, cross-check against,
  and (with attribution) adapt it. We build our own clean implementation and credit
  the source.
- **Attribution:** the narrowband combine/normalization concept and SHO/HOS/HSO/HOO
  formulas are by **Bill Blanshan and Mike Cranfield**; the numpy reference is
  **SetiAstroSuite (GPL-3.0), Franklin Marek**. Credit both in the code header and
  in the in-app Help topic.

## Starting point (what exists)

- **On `main`:** the only narrowband-adjacent code is the raw-CFA extractor
  `nocturne/stacking/haoiii.py` + `ui/haoiii_dialog.py`, which produces the linear
  RGB master that feeds the tool: **R = Ha, G = B = OIII** (peak-normalised). There
  is no palette / narrowband / Colourise code on `main`.
- **`narrowband-core` branch:** a **stale, divergent** branch (125 commits behind
  `main`, missing Curves / Star Spikes / HDR / Nebula Saturation / spacebar, etc.).
  It carries a **~90 % faithful NBN engine** `core/narrowband.py` plus a two-engine
  mess (old Foraxx `palette.py` + one-press Colourise + Advanced dialog). We **do
  not merge** this branch. We **salvage** `core/narrowband.py` and adapt
  `ui/narrowband_dialog.py` from it as reference, building clean on `main`; the old
  Foraxx engine and the Colourise/Advanced entry points are dropped.

## Data domain

The tool runs on the **current, stretched (display-space, `is_linear=False`)
image**, as a **finishing step** — exactly what NBN expects. It operates on the
**starless nebula** (stars removed, then screened back). Median-matching is only
meaningful on stretched histograms (on linear data medians are ~0 and the match is
unstable), so the tool must run after Stretch.

## Architecture

### 1. Engine — `nocturne/core/narrowband.py` (salvage + correct)

Bring the branch's engine over and correct it against V8. The core normalization,
per channel `c`:

```
M  = min(c) + blackpoint * (median(c) - min(c))          # black reference
E0 = adev(c) / 1.2533 + mean(c) - M                       # robust signal above M
A  = E0 / (1 - M)                                          # ratio statistic (per channel)
```

`adev` = **average absolute deviation from the median** (PixInsight semantics),
NOT from the mean. To match V8 fidelity this must use the median.

Normalize the secondary (OIII) up to the reference (Ha):

```
E1 = ( A_sec*(1 - A_ref) / (A_sec - 2*A_sec*A_ref + A_ref) ) / OIIIBoost   # MTF midtone
E2 = clip( (sec - M_sec) / (1 - M_sec), 0, 1 )            # rescale [M_sec,1] -> [0,1]
E3 = 1 - (1 - mtf(E1, E2)) * (1 - min(sec, M_sec))        # ~(~mtf * ~sub): fold shadows back
```

**Bug to fix (verified against V8):** `A_ref` must use the **reference channel's own**
black point — `A_ref = E0_ref / (1 - M_ref)` — not the secondary's `(1 - M_sec)`.
The branch code reuses `M_sec` for both, which skews the match whenever the two
channels' backgrounds differ (i.e. always). Each channel uses its own `M`.

Degenerate guards (faint/empty channel, near-equal levels, tiny denominator) fall
back to identity — no NaN. Keep the existing guards.

**SCNR green/magenta clamp (restore — the branch engine dropped it):** after routing
channels, clamp green toward the red/blue average, as V8 does:

```
G = min( (R + B) / 2, G )          # when SCNR on (default on)
```

This suppresses the residual green cast / magenta tint on the nebula. Stars are
handled by separation (below), so this clamp is nebula-only.

**Finishing tone stages** (keep; already match V8 — verify during implementation):
- `highlight_reduction(x, amount)`  → `mtf(1 - 0.5/amount, x)*x + x*(1-x)`  (E11)
- `brightness(x, amount)`           → `mtf(0.5/amount, x)`                    (E12)
- `highlight_recover(x, amount)`    → `x / amount`                            (E13)

All are identity at `amount = 1.0`.

**Palettes** (`_combine`), with SII synthesised from Ha on dual-band. Ship exactly
three distinct looks — drop HSO (it is identical to SHO once SII = Ha):

| Palette label        | R      | G                         | B      | Look                    |
|----------------------|--------|---------------------------|--------|-------------------------|
| **HOO (natural)**    | Ha     | dynamic Ha/OIII blend     | OIII   | red-gold neb, teal O    |
| **Pseudo-SHO (gold)**| Ha     | Ha                        | OIII   | gold nebula, teal/blue  |
| **Pseudo-bicolor**   | Ha     | OIII                      | Ha     | magenta neb, green O    |

- HOO's green is the **Blanshan/Foraxx dynamic blend** `synthetic_green(ha, oiii,
  blend_amount)`: `w = (ha*oiii)^(1-ha*oiii)`, `dynamic = w*ha + (1-w)*oiii`, mixed
  toward OIII by `(1 - blend_amount)`. (Kept — richer than V8's linear HOO blend.)
- Pseudo-SHO / Pseudo-bicolor route the (normalized) channels directly. Exact
  channel math for the pseudo palettes may be tuned during real-data validation.
- The SCNR clamp applies after routing, for every palette.

**Lightness (Preserve toggle, default on):** keep the **original stretched image's
CIE-L\*** and take only colour (a\*, b\*) from the recolour — holds the tonal
structure (dark sky, bright nebula) while remapping hue. (NBN Mode-1 LAB behaviour.)

**Protect background (slider, default ~0.4):** a soft luminance smoothstep mask that
confines the recolour to the nebula and leaves the darkest sky its natural colour.
Nocturne addition on top of NBN; keep it.

`render(img, params)` is the single engine entry point: extract Ha/OIII → normalize
OIII→Ha → route to palette → SCNR clamp → tone stages → saturation → optional
preserve-lightness → optional protect-background blend. Output `is_linear=False`.

`NarrowbandParams`: `palette, blackpoint(=1.0), oiii_boost(=1.0), blend_amount(=0.6),
highlight_reduction(=1.0), brightness(=1.0), highlight_recover(=1.0), saturation(=0.5),
lightness_preserve(=True), protect_background(=0.4)`.

### 2. Guided tool — `nocturne/ui/narrowband_dialog.py`

A single **"Narrowband…"** toolbar tool (peer of Ha/OIII, Star Spikes), operating on
the current stretched image. Adapt the branch dialog into current `main`'s UI.

- **Star handling:** on open, if `rcastro_valid(settings)`, run StarX **async**
  (`RCAstro.remove_stars` → starless + stars), status "Removing stars… (one-time,
  then tweak live)"; else fall back to the **whole image** with a visible note that
  star colour may look off without StarXTerminator. Cache the split.
- **Controls (live, debounced ~90 ms preview):** Palette (HOO / Pseudo-SHO /
  Pseudo-bicolor), **OIII Boost** (the key Seestar knob), Green blend, Protect
  background, Saturation, Brightness, and a **Preserve lightness** checkbox. Reset
  button; double-click resets a slider (`ResetSlider`).
- **Preview:** the starless nebula recoloured (stars omitted from the live preview
  for speed, as the branch does). **Apply** renders full-res, screens the real stars
  back (`screen(nebula, stars)` = `1-(1-neb)*(1-stars)`), and records the step.
- Uses the shared preview plumbing where practical; RC-Astro gating consistent with
  the other split-based tools.

### 3. First-class, recipe-captured step (closes the Colourise recipe gap)

Make Narrowband a **parameter-serialisable step**, not a baked `_PrecomputedStep`,
so recipes and batch replay it:

- New `nocturne/steps/narrowband_step.py` `NarrowbandStep(rcastro)`: `apply(img,
  option)` parses `option` → `NarrowbandParams`, runs the same StarX-split (or
  whole-image) + `render` + screen-stars-back that the dialog does, so **live
  Apply == recipe replay** (WYSIWYG).
- Stable stage id **`narrowband`**, added to `STEP_NAME` and `PROCESSING_ORDER` as a
  **post-stretch finishing step** (position pinned in the plan — after the tone/colour
  finishing steps, near `star_reduction`).
- `factory.make_step("narrowband", …)` returns a `NarrowbandStep`; `recipe.py`
  serialises/deserialises the params (a dict/tuple option) via `_NAME_TO_STAGE` and
  `deserialize_option`; `batch.py` replays it. Replay re-runs StarX at batch time
  (or whole-image fallback if RC-Astro absent).
- The dialog records the step with its params (jump/record consistent with how other
  finishing steps commit); history log shows `Narrowband (HOO, OIII +N)` or similar.

## Error handling

- **Mono image:** `render` raises `ValueError` ("Narrowband needs a colour image");
  the tool shows a clear message and does nothing.
- **RC-Astro absent:** whole-image fallback with a visible note (chosen behaviour).
- **StarX split fails:** clear the "Removing stars…" status and fall back to
  whole-image with a message (this also fixes the shared "status never clears on
  split failure" bug for this tool).
- **Degenerate channels** (flat / empty / near-equal levels): normalization falls
  back to identity — no NaN, no crash.

## Testing

- **Core (`tests/core/test_narrowband.py`):** `channel_level` M/E0 on known arrays;
  `normalize_to_reference` lifts a weak channel's median toward the reference and
  uses each channel's own `M` (regression test pinning the A_ref fix — construct Ha
  and OIII with **different** backgrounds and assert the matched median is correct,
  which fails with the old shared-`M` code); OIIIBoost>1 pushes past parity; SCNR
  clamp reduces green; degenerate inputs → identity (no NaN); each palette routes
  channels as specified; tone stages identity at amount 1.0; `preserve_lightness`
  keeps L\*; `protect_background` leaves dark sky unchanged.
- **Step (`tests/steps/`):** `NarrowbandStep.apply` with a params option changes a
  colour image; round-trips through recipe serialize→deserialize→apply **identically**
  to a live render (WYSIWYG); mono → ValueError; whole-image path when rcastro is None.
- **Recipe/batch:** a saved recipe containing `narrowband` is **not** dropped by
  `uncaptured_step_names`; `factory.make_step("narrowband", opt)` builds the step;
  batch replay produces the coloured output.
- **Dialog (`tests/ui/`):** builds and detects layers; sliders re-render the preview;
  OIII-boost slider visibly lifts OIII; Apply calls back with an AstroImage and the
  stars are screened back.
- Keep the full suite green; no regression to the haoiii extractor.

## Validation (before merge)

User validates on real Seestar HOO data (NGC 7000, Pacman) via the live tool and via
a recipe replay, confirming: OIII boost brings out teal, background stays neutral,
stars are correctly coloured (with RC-Astro), and the pseudo-SHO looks are distinct
and pleasing.

## Out of scope (future)

- A **free star-mask fallback** (sep-based) so starless quality is available without
  RC-Astro — its own sub-project.
- **Continuum subtraction** (`OIII − k·Ha`) to remove Ha bleed-through from OIII —
  a promising Seestar refinement, evaluated later.
- Per-channel manual curves; additional palettes beyond the three.
- Anything touching the `haoiii.py` extractor itself.

## Build & review process

Subagent-driven, TDD, per Nocturne's standing practice: engine (corrected + tested)
→ guided tool → first-class recipe-captured step → whole-branch review → user
real-data validation → merge. Fresh branch off `main`; `narrowband-core` is a
read-only salvage reference, never merged.
