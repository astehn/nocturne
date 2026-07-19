# Import step — audit fixes (Design)

**Date:** 2026-07-19 · **Status:** Approved (audit + design Q&A)
**Source:** `docs/audit/PIPELINE_AUDIT.md` → Step 1 (Import).

Fix the correctness + trust issues found auditing the Import step. Display/parse
only — no change to pixel data or the processing pipeline.

## Scope (agreed)

**Fix now:** D1 (integration time), D2 (camera info from file + profile FL),
U2 (target fallback), U1 (linear-preview reassurance), U4 (empty-metadata
fallback). **Deferred (logged in tracker):** D3 (stacker provenance → Stack
audit #14), U5 (stack discoverability), U7 (naming drift).

## Ground truth (3 real headers)

| Source | EXPTIME | STACKCNT | LIVETIME | true total |
|---|---|---|---|---|
| Nocturne master | 1620 = total | 81 | — | 27m |
| Nocturne/stripped | 3640 = total | 182 | — | 61m |
| native ZWO/Siril | 20 = per-sub | 161 | 3220 = total | 54m |

`EXPTIME` is per-sub in native files, total in Nocturne masters. `LIVETIME`
(standard) = total in native files. `FOCALLEN=160`, `XPIXSZ=2.9` in native files.

## D1 — Integration resolution

New pure helper `resolve_integration(meta) -> Integration | None` with fields
`total_s | None`, `per_sub_s | None`, `frames | None`. Rule:

```
live, exp, frames = meta.livetime, meta.exposure, meta.frames   # floats/None
if live and live > 0:
    total = live
    per_sub = exp if (exp and _plausible_sub(exp)) else (live/frames if frames else None)
elif exp and frames:
    cand = exp / frames
    if _plausible_sub(cand):   # EXPTIME already the TOTAL (Nocturne masters)
        total, per_sub = exp, cand
    else:                      # EXPTIME is per-sub (native, no LIVETIME)
        total, per_sub = exp * frames, exp
elif exp:                      # single sub, no count
    total, per_sub = None, exp
else:
    return None
```

`_plausible_sub(x) = 0.5 <= x <= 600`. Assumption (comment it): rule-2's ratio
test only ever sees Nocturne `EXPTIME=total` masters, because native files carry
`LIVETIME` and are caught by rule 1 — so the test is safe there.

Display: total present → `Total integration: {format_integration(total)}
({frames} × {per_sub:g}s)` (drop the parenthetical if frames/per_sub unknown);
else per_sub only → `Exposure: {per_sub:g}s`; else omit.

## D2 — Camera & scope from the file

`import_summary` reads focal length ← `FOCALLEN`, pixel size ← `XPIXSZ`, gain ←
`GAIN` from `meta` when present, falling back to the instrument profile per
field. **Image scale is computed** from the effective focal length + pixel size
(`206.265 * pix / focal`). Sensor name + f-ratio stay from the profile (Seestar
audience). Correct the profile: `focal_length_mm 150 → 160`, `aperture_mm 30 →
32` (keeps f/5, matches the device header; new scale ≈ 3.7″/px).

## U2 — Target fallback

`import_summary(meta, instrument=..., filename=None)`. Target = `meta.target`
else a cleaned stem of `filename` (strip extension + trailing
`_NNNxNNs…`-style capture suffixes into something readable, best-effort). Thread
`self._source_label` from `MainWindow` into the call.

## U1 — Linear-preview reassurance

Static `_desc_label` in the Import panel (`step_panels.py` import branch), below
the metadata: e.g. *"Teal cast and a flat histogram are normal here — this is
your un-stretched data. Colour and contrast come in the next steps."*

## U4 — Empty-metadata fallback

When no capture fields resolve, still render the **"Your stack"** section with a
graceful line (*"Couldn't read capture details from this file's header."*) plus
whatever is known (dimensions), instead of dropping the whole block.

## Testing

- `resolve_integration`: the 3 conventions above + edges (exp-only, none,
  livetime+no-exp). Assert total_s / per_sub_s.
- `import_summary`: integration string for a Nocturne-master meta (EXPTIME=1620,
  frames=81 → "27m 00s (81 × 20s)"); camera-from-file (FOCALLEN=160 → "~3.7″");
  target-from-filename fallback; empty-metadata fallback line present.
- `instrument`: focal 160, scale ≈ 3.7, f/5 (update existing asserts).
- Update existing `test_import_summary_full_and_sparse` token `4.0″` → `3.7″`.

## Out of scope

D3 stacker provenance, U5 stack discoverability, U6 deep hierarchy rework, U7
naming drift — logged in the tracker for their own step/tool.
