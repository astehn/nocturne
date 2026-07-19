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
| 2 | Crop | UX | ⬜ | unlink ✅ shipped; brightness-framing parked |
| 3 | Background | UX + algo | ⬜ | GraXpert strengths |
| 4 | Color | algo-deep | ⬜ | OSC neutralize/WB correctness; green cast |
| 5 | Deconvolution | algo-deep | ⬜ | — |
| 6 | Stretch | algo + UX | ⬜ | slider→target mapping; preview fidelity ✅ |
| 7 | Levels | UX | ⬜ | — |
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
