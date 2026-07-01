# Palette v3 — Per-Channel Curves — Design

**Date:** 2026-07-01
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — ready for implementation planning
**Evolves:** `2026-07-01-palette-v2-starless-design.md` (keeps the starless StarX workflow;
replaces the tweak controls).

## Motivation

Palette v2's tweak controls were the wrong tool: the **Ha/OIII balance** slider and the
**saturation** slider each multiply whole channels uniformly, so they just re-tint the entire
image. That is not how a SHO/Hubble palette is dialed in. Real palette work uses **per-channel
curves** — moving the dark, mid, and bright parts of R, G, and B *independently* to place the
gold and teal where you want them. This spec replaces the two global sliders with per-channel
Black/Mid/White curves.

## Decisions (from brainstorming)

- **Per-channel curves** (Black / Mid / White for each of R, G, B) — a per-channel *levels*
  operation, reusing `core/levels.apply_levels` math.
- **Pipeline: combine → sculpt → finish.** Palette radio (HOO / pseudo-SHO) is the starting
  combination; curves sculpt; SCNR + neutral-white stars finish.
- **Drop** the Ha/OIII balance and saturation sliders entirely (replaced by curves).
- **Neutral by default:** all curves start at black 0 / mid 0.5 / white 1 → opening the
  dialog shows the plain palette combination; every visible change is user-made.
- **UI:** channel tabs (R/G/B) + three sliders (Black/Mid/White) for the selected channel,
  plus a **Reset** button. Palette radio and SCNR toggle stay. Live downscaled preview.
- Everything else from v2 is unchanged: StarX-once (cached), Apply→undoable history, no-RC-
  Astro whole-image fallback.

## Scope

**In scope**
- `core/palette.py`: new `ChannelCurve`, revised `PaletteParams` (palette + per-channel
  curves + scnr), new `apply_channel_curve`, revised `render_nebula`.
- `ui/palette_dialog.py`: replace balance/saturation sliders with channel tabs + Black/Mid/
  White sliders + Reset.

**Out of scope (deferred)**
- A draggable curve-editor widget or per-channel histogram behind the sliders (three sliders
  per channel is enough; the live preview is the feedback).
- Additional palettes; star size/brightness controls; saturation as a separate control
  (per-channel white points cover intensity).

## Data model / core API

```python
from dataclasses import dataclass, field

@dataclass
class ChannelCurve:
    black: float = 0.0    # 0..1 input black point
    mid:   float = 0.5    # 0..1 slider; 0.5 = neutral gamma
    white: float = 1.0    # 0..1 input white point

@dataclass
class PaletteParams:
    palette: str = "HOO"                       # "HOO" | "pseudo_SHO"
    r: ChannelCurve = field(default_factory=ChannelCurve)
    g: ChannelCurve = field(default_factory=ChannelCurve)
    b: ChannelCurve = field(default_factory=ChannelCurve)
    scnr: bool = True

def apply_channel_curve(channel: np.ndarray, curve: ChannelCurve) -> np.ndarray:
    """Levels on a single 2D channel: remap [black, white]->[0,1], then midtone
    gamma. Reuses the core/levels math. Returns float32 in [0,1]."""

def render_nebula(starless: AstroImage, params: PaletteParams) -> AstroImage:
    """Extract Ha/OIII -> palette-combine (HOO or pseudo_SHO) -> apply each
    channel's curve -> optional SCNR. Returns the coloured starless nebula."""
```

**Mid → gamma mapping:** `gamma = 10 ** ((curve.mid - 0.5) * 2)` (so `mid=0.5`→1.0 neutral,
`mid=1`→10 brighter mids, `mid=0`→0.1 darker). Per-channel apply:
`out = ((clip(x,0,1) - black) / max(white-black, 1e-4)) ** (1/gamma)`, clipped to [0,1] —
identical to `apply_levels` but on one channel. A fully-neutral curve (0, 0.5, 1) is a no-op.

**Palette combine** (unchanged from v2): HOO = `(ha, oiii, oiii)`; pseudo-SHO =
`(ha, 0.5*ha+0.5*oiii, oiii)`. Then curves are applied to R, G, B respectively. SCNR
(`green = min(green, (red+blue)/2)`) runs last if enabled.

**Removed from v2:** `PaletteParams.balance`, `PaletteParams.saturation`, and the
`_saturate_rgb` helper (per-channel white points cover intensity). `neutralize_stars`,
`screen`, `compose` are unchanged.

## UI — dialog (v2 layout, new control panel)

Interactive dialog on the current image (unchanged shell): live downscaled preview on the
left; controls on the right:
- **Palette** radio: HOO / Pseudo-SHO.
- **Channel** tabs/radio: R / G / B — selects which channel the sliders edit.
- **Black / Mid / White** sliders (0..100 → 0..1) for the selected channel. Switching the
  channel tab repopulates the three sliders from that channel's stored `ChannelCurve`; moving
  a slider writes to the active channel's curve and re-renders the downscaled preview.
- **Green suppression (SCNR)** toggle.
- **Reset** button: set all three channels back to neutral (0, 0.5, 1).
- **Apply** / **Close**.

StarX-once caching, Apply→`on_apply` history record, and the no-RC-Astro whole-image fallback
are all inherited from v2 unchanged. Test seams (`_async`, `_starx_enabled`, `_starx_runner`)
unchanged.

Dialog attributes for tests: `palette` radios (`hoo_radio`, `sho_radio`), channel selector
(`r_radio`, `g_radio`, `b_radio`), sliders (`black_slider`, `mid_slider`, `white_slider`),
`scnr_check`, `reset_btn`, `preview`, plus the per-channel store `_curves` (dict "R"/"G"/"B"
→ ChannelCurve) and `_active_channel`.

## Error handling

Inherited from v2, unchanged: no image → status; not colour → status; RC-Astro not configured
→ whole-image fallback + note; StarX failure → status, no crash. Curve math is total on valid
input; `white` clamped above `black`.

## Testing

Synthetic, headless, fast:
- `apply_channel_curve`: black-point lift darkens low values; white-point pull brightens;
  `mid<0.5` darkens midtones and `mid>0.5` brightens; neutral curve (0,0.5,1) is a no-op.
- mid→gamma: `mid=0.5` → gamma 1.0 (identity).
- `render_nebula` all-neutral curves == plain palette combination.
- `render_nebula` per-channel independence: pulling R's white down lowers red mean while
  green/blue means are unchanged (the exact thing that was broken in v2).
- `palette_dialog`: switching channel tab repopulates the three sliders from the stored curve;
  moving a slider updates only the active channel and re-renders; **Reset** returns all curves
  to neutral; Apply records the history step; no-RC-Astro fallback still renders.

## Verification (end to end, real data)

1. Finish a Pelican (IC 5070) image in the editor → **Palette…** → StarX removes stars once.
2. Start from HOO/pseudo-SHO, then sculpt per channel: e.g. lift R black + push R white for
   gold Ha; pull B white to cool the background; use G mid to taste.
3. Confirm each channel moves independently (no global re-tint), stars stay white, SCNR
   cleans residual green. Reset recovers the plain combination.
4. Apply → undoable "Palette" step → export.
