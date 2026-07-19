# Nocturne Pipeline Audit

A step-by-step deep-dive through every processing step, in pipeline order, to
optimize / refine / harden each one before moving to the next. Two lenses per
step — **UX** (a UX-expert review agent, fed screenshots + panel code + help
text + behaviour) and **Domain** (astrophotography correctness: algorithm,
defaults, prior art). Heuristic audit first; deep research only where the audit
flags a real concern. Every agreed fix goes through the normal flow
(design → plan → subagent → tests → merge) and is logged here.

**Method:** independent audit — Claude forms its own findings before the user
shares theirs, so convergence is a real signal.

## Roadmap

| # | Step | Depth | Status | Known issue folded in |
|---|------|-------|--------|-----------------------|
| 1 | Import | UX + correctness | ✅ fixed | integration-time / EXPTIME miscalc |
| 2 | Crop | UX | ✅ fixed | unlink ✅ shipped; brightness-framing parked |
| 3 | Background | UX + algo | ✅ fixed | GraXpert strengths |
| 4 | Color | algo-deep | ✅ fixed | grey-world → robust background-neutralization |
| 5 | Deconvolution | algo-deep | ✅ reviewed | free unsharp-mask fallback → parked in TODO |
| 6 | Stretch | algo + UX | ✅ fixed | linked→unlinked (red-clip); WYSIWYG preview==export |
| 7 | Levels | UX | 🛠 fixing | live preview + auto + clipping + numeric + label |
| 8 | Saturation | UX | ⬜ | recently remapped — verify |
| 9 | Noise Reduction | algo-deep | ⬜ | — |
| 10 | Local Contrast | algo + UX | ⬜ | — |
| 11 | Star Reduction | algo + UX | ⬜ | retune (paused) |
| 12 | Enhancements | UX | ⬜ | boost buttons; narrowband adjacent |
| 13 | Export | UX + correctness | ⬜ | — |
| 14 | Stack (adjacent tool) | correctness | ⬜ | ~396 GB memory runaway |

Legend: ⬜ not started · 🔎 auditing · 🛠 fixing · ✅ done

## Per-step template

Each step's entry captures:
1. **What it does** — code path + algorithm, in one paragraph.
2. **Domain findings** — correctness, defaults, ranges, prior-art gaps.
3. **UX findings** — clarity, labels, feedback, discoverability, friction.
4. **Verdict** — leave as-is / minor polish / structural fix.
5. **Actions** — prioritized, each linked to its spec/plan/commit when done.

---

## Step 4 — Color  ✅

**Finding (algo-deep, deep-research backed):** grey-world white balance assumes the
whole frame averages to neutral grey — false for an emission nebula. On a
red-dominant NGC 7000 frame it computed R×0.61 / B×1.53 (measured), desaturating
real Hα and casting the sky the complementary colour; SCNR then turned the
grey-world green-boost into a blue sky. **Fix (merged 85c6441):** replaced with
robust background-neutralization — sample an empty-sky luminance band (10–40th
pct), match each channel's background level via green-anchored multiplicative
gains. Sky neutral, nebula colour preserved. `white_balance` setting removed
(recipe deserialize tolerates old keys); help copy corrected. Deferred: star-based
WB advanced toggle. _Status: ✅ complete._

## Step 6 — Stretch  ✅

**Finding (the "unnatural red" the user couldn't reproduce in PI/Siril):**
`linked_stretch` subtracted ONE common luminance-derived black point from all
channels, clipping the lowest (red) to zero on any non-neutral background (proven
on the real file: raw→linked red→0; background-neutralize→linked neutral). It was
used for both preview AND commit, so previews mispredicted the export — a
[[wysiwyg-preview-principle]] violation. On real NGC 7000 the user judged the
per-channel **unlinked** look right (linked reads over-the-top). **Fix (merged
1fc0a17):** `autostretch` (preview) and `apply_stretch` (commit) both use the
per-channel unlinked stretch — neutral background, no channel clipped, preview ==
export. Retired the now-redundant Crop "Neutral preview" toggle. User: "best image
edited with Nocturne so far, end to end." _Status: ✅ complete._

---

## Step 3 — Background  🛠

**Code:** `nocturne/steps/background.py` (off/light=0.3/strong=0.7,
`default_option()="light"`), `nocturne/tools/graxpert.py` (CLI invocation),
`nocturne/ui/step_panels.py` (process-kind panel), `nocturne/ui/main_window.py`
(`apply_current` → `_run_busy`).

### Findings (audit — domain + UX)
- **BG1 [High] Default strength is "off" — a no-op.** The process combo shows
  the first item ("off"), ignoring `default_option()="light"` and the help. Trust
  the flow → Apply does nothing. Background-specific (other process steps list
  their default first). *(Both lenses — headline.)*
- **BG2 [Med] "off" conflates skip with strength**; enabled even without GraXpert
  so a beginner can "complete" the step doing nothing. Largely mitigated by BG1.
- **BG3 [Med] Blind choice; result hard to judge** — nothing points to Before/After.
- **BG4 [Med] "gradient" is unexplained jargon.**
- **BG5 [Low] Settings link missing** on the (already-inline) gate note.
- **BG6/7/8 [Low]** no "applied ✓" state; "Apply Background" verb; no GraXpert cancel.

### Verified already-handled (corrects the UX agent)
- **Progress feedback EXISTS**: `apply_current` → `_run_busy(…, "Applying
  Background…")` shows the BusyBar + animated label. The agent's "no progress"
  High finding is moot (residual: no cancel — Low).
- The **gate note is already inline** (`_GATE_NOTE` shown under the control when
  GraXpert is unset), not only in help prose.

### User's list: none (considered Background good) — endorsed the fixes.

### Scope → fix now: BG1 (preselect default), BG4 (gradient explainer), BG3
(Before/After cue). Deferred: BG2, BG5, BG6/7/8.

### Verdict: **targeted fix** (one correctness default + beginner-clarity copy).

### Resolution (merged to main 2026-07-19, 199d71c, suite 489 pass)
- **BG1**: process panels now preselect `default_option()` — Background lands on
  **light**, not off (systemic across all process steps).
- **BG4/BG3**: Background panel explains "gradient" in plain language + points to
  Before/After. Deferred: BG2, BG5, BG6/7/8 (logged above).

_Status: ✅ complete._

---

## Step 2 — Crop  ✅

**Code:** `nocturne/ui/image_view.py` (overlay: `_Body`, `_Handle`,
`set_crop_overlay`, `cropBoxChanged`), `nocturne/ui/step_panels.py` (crop panel),
`nocturne/ui/main_window.py` (`_setup_crop_overlay`, `_apply_crop`,
`_on_crop_change`), `nocturne/core/crop.py` (`apply_crop_params`,
`detect_content_bounds`/`auto_crop`, `ASPECTS`).

### Findings (audit — domain + UX)
- **C1 [High] Crop box nearly invisible; no exterior dimming.** Dashed teal
  outline + faint *inside* fill (alpha 40), no darkening of the removed area. On
  a dark sky at the near-full-frame default the box is imperceptible and its
  inside-tint is misread as a colour cast. *(Both audit lenses independently.)*
- **C2 [Med] No live selection readout** (W×H / resulting size).
- **C3 [Med] Auto-trim is implicit.** `detect_content_bounds` *does* set the
  initial box on entry (verified — corrects the UX agent's "not wired" claim),
  but it runs silently with no affordance/feedback.
- **C4 [Med] Apply-Crop vs instant Rotate/Flip under-signalled**; Rotate 90° has
  no direction cue.
- **C5 [Low] "Unlink stretch (neutralize tint)" label is jargon.**
- **C6 [Low] No composition/framing grid** despite "frame your target".

### User's own list (independent)
1. Overlay colour makes the (full-frame default) image look tinted → **= C1**.
2. **Don't show the crop box until the user clicks the image.** *(new)*
3. **Hide the overlay again after cropping**, until the next click. *(new)*
4. Offer composition guides (rule of thirds, center cross) → **= C6**, concrete.

### Agreed design → spec `docs/superpowers/specs/2026-07-19-crop-rework-design.md`
Overlay **hidden by default**; a click on the image shows it **at detected
content edges**; **hidden again after Apply**. When shown: **dim the exterior**
(drop the inside tint), **selectable guides** (None / Rule of thirds / Center
cross), **live W×H readout**. Polish: Rotate/Flip grouped as instant + direction
cue; checkbox relabel. Engine unchanged (display-only).

### Verdict: **structural fix** (interaction-model rework of the overlay).

### Resolution (merged to main 2026-07-19, 7 commits, suite 486 pass)
- Overlay **hidden by default**; click summons it **at content edges**; **hides
  after Apply** (C1/C3 + user 2/3).
- **Exterior dimming** + inside-tint removed (C1/user 1); **guides** None/Thirds/
  Center (C6/user 4); **live W×H readout** (C2).
- **Dismiss**: click-outside / Esc, **confirm-only-if-modified** (user follow-up).
- Polish: Rotate `↻` + instant note (C4); checkbox → "Neutral preview (for
  framing)" (C5); intro copy → click-to-place.
- Deferred: rule-of-thirds *snapping*, diagonal/golden guides.

_Status: ✅ complete._

---

## Step 1 — Import  🔎

**Code:** `nocturne/core/fits_io.py` (`load_fits`, `_parse_metadata`,
`import_summary`, `format_integration`), `nocturne/ui/step_panels.py` (import
panel: "Open FITS…" + metadata readout), `nocturne/core/instrument.py`
(`SEESTAR_S30_PRO` profile).

**Ground-truth headers (3 real files):**

| File (source) | EXPTIME | STACKCNT | LIVETIME | true total |
|---|---|---|---|---|
| NGC 281 `master.fits` (**Nocturne stacker**) | 1620 = total | 81 | — | 27 min |
| NGC 7000 `182x20s` (Nocturne/stripped) | 3640 = total | 182 | — | 61 min |
| NGC 7000 `161x20sec` (**native, Siril-stacked**) | 20 = per-sub | 161 | 3220 = total | 54 min |

`EXPTIME` = *per-sub* in native ZWO/Siril files but *total* in Nocturne's own
masters. Native files also carry standard `LIVETIME` (= total) + rich metadata
(`OBJECT`, `GAIN`, `CCD-TEMP`, `DATE-OBS`, `FILTER`, `FOCALLEN=160`, `XPIXSZ=2.9`)
that Nocturne's stacker discards.

### Domain findings
- **D1 [Critical] Integration-time miscalc.** `import_summary` does
  `EXPTIME × frames` unconditionally — right for native (per-sub) files,
  catastrophically wrong for Nocturne masters (total), e.g. shows 184h 01m for a
  61-min stack. The `(N × Xs)` derivation also prints the wrong per-sub.
- **D2 [High] "Camera & scope" is hardcoded, never read from the file.** Always
  prints IMX585 / 2.9µm / **150mm** / f5 regardless of the FITS. Real header says
  `FOCALLEN=160` (→ ~3.7″/px, not the shown ~4.0″), and any non-S30-Pro file is
  silently mislabeled. Profile FL (150) also disagrees with the device (160).
- **D3 [Med] Nocturne's own stacker strips provenance.** Writes only
  `NSUBS`/`STACKCNT`/`EXPTIME`(as total) — losing OBJECT/DATE/GAIN/temp/FOCALLEN
  and using a non-standard EXPTIME. Root of both the sparse readout and the
  EXPTIME ambiguity. (Bridges to the Stack tool, audit #14.)

### UX findings (independent agent)
- **U1 [High] First impression reads as "broken."** Strong teal canvas + a
  near-empty histogram, with nothing explaining it's a display-only stretch of
  still-linear data. Reassurance is buried behind "Full help."
- **U2 [High] No target name = no orientation anchor.** OBJECT absent from the
  readout though the filename shows it; surface target (fallback to filename).
- **U3 [High] Hardcoded camera block looks "measured"** → trust hazard (= D2).
- **U4 [Med] Empty-metadata edge drops the whole "Your stack" block** — no
  confirmation the file was even read.
- **U5 [Med] Stacking from subs is undiscoverable** at Import (only the generic
  toolbar Stack icon; no pointer).
- **U6 [Med] Weak hierarchy + dead space** — data vs boilerplate equal weight;
  large empty gap that could hold the linear-preview explanation.
- **U7 [Low] Naming drift** — Import / "Getting started" / `load`.
- **U8 [Low] Integration is the hero number** — amplifies the (currently wrong)
  value; keep the derivation once D1 is fixed.

### Verdict: **structural fix** (one critical data bug + a systemic
"read from the file, don't hardcode or discard" theme).

### Proposed actions (prioritized — scope TBD with user)
1. Fix integration time: prefer `LIVETIME`; else disambiguate EXPTIME by the
   `EXPTIME/STACKCNT ∈ plausible-sub-range` ratio test; show correct total + per-sub.
2. Read "Camera & scope" from the header when present (FOCALLEN/XPIXSZ/GAIN…),
   fall back to profile only for missing fields; correct profile FL to 160.
3. Surface Target (OBJECT → filename fallback).
4. Stacker: propagate provenance + write standard `EXPTIME`(per-sub)+`LIVETIME`(total).
5. Reassure on the linear preview (teal + empty histogram is normal).
6. Empty-metadata edge: always show "Your stack" with a graceful fallback line.
7. Polish: hierarchy/dead-space, Stack discoverability, naming drift.

### Resolution (branch `import-audit-fixes`, 2026-07-19)

**Shipped** (validated end-to-end on the 3 real headers; full suite 472 pass):
- **D1** `resolve_integration` — LIVETIME-first + ratio-test disambiguation.
  NGC 281 now reads **27m 00s (81 × 20s)**, native NGC 7000 **53m 40s (161 × 20s)**
  (was 184h / ~36h). (`7b4fa8f`)
- **D2** camera & scope read from header (FOCALLEN/XPIXSZ/GAIN) with profile
  fallback; profile FL 150→160 / aperture 30→32; image scale now computed
  (~3.7″/px). (`0eef0ad`)
- **U2** target OBJECT→filename fallback. **U4** graceful empty-metadata line.
  **U1** linear-preview reassurance note in the panel. (`0eef0ad`, `0bbeaa7`)
- Polish: sensor temp rounded to 1 decimal. (`e60cfad`)

**Deferred (logged):** D3 stacker provenance → Stack audit (#14); U5 stack
discoverability; U6 deeper hierarchy rework; U7 naming drift. Minor:
`_target_from_filename` cuts at the first `_<digits>`, so an underscore-separated
catalog name (`NGC_7000_…`) with no `OBJECT` header would yield `NGC` — rare
cosmetic fallback, revisit if it bites.

_Status: Import fixes complete on branch; awaiting user visual check + merge._
