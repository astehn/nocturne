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
| 1 | Import | UX + correctness | 🔎 auditing | integration-time / EXPTIME miscalc |
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

_Findings pending artifacts + independent audit._
