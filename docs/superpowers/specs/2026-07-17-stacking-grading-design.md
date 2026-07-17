# Stacking frame selection: transparent grading redesign

**Date:** 2026-07-17
**Status:** Approved
**Scope:** `nocturne/stacking/grade.py`, `nocturne/ui/stack_dialog.py`, `nocturne/stacking/stacker.py`

## Problem

The current grader rejects a frame when any of three metrics (star count, FWHM,
background) falls outside `median ± 3×raw-MAD` of the session. This is wrong in
three compounding ways, measured on a real 186-sub NGC 7000 session:

1. **3×raw-MAD ≈ 2 sigma** (MAD ≈ 0.6745σ for Gaussian data), so each gate is
   ~1.5× tighter than the "3-sigma" it pretends to be. Tighter, the more
   consistent the session is.
2. **Three OR'd one-tailed ~2σ tests compound** to reject several percent of
   perfectly good frames even on ideal data.
3. **Background drifts within a session** (twilight, moonrise, LP). A
   median+k gate on a drifting series systematically rejects a whole block of
   the night. On the NGC 7000 set, ~45 of 60 rejections were the twilight block
   (23:58–00:25, background 1375→1193 ADU decaying smoothly) — frames with more
   sky glow but intact signal.

Result: Nocturne rejected 60/186 where Siril rejected 9. Siril's 9 were
registration failures — its default script applies **no quality filter at all**;
transient junk is handled per-pixel by sigma clipping. PixInsight's WBPP goes
further: it rejects nothing by default and *weights* frames by quality.
Rejecting a usable frame throws away integration time for nothing.

The UI compounds the problem: verdicts are silent (a checkbox flips off with raw
numbers and no reason), so the user can neither understand nor confidently
override them.

## Design

### 1. Selection engine: measure/judge split (`stacking/grade.py`)

Separate the expensive measurement from the cheap judgement so strictness
changes re-judge instantly without re-reading files.

- `measure_frames(paths, on_progress)` → `list[FrameMeasure]` — per frame:
  star count, FWHM, background (sep, unchanged math), plus `EXPTIME` from the
  header. Run once per folder.
- `judge(measures, strictness)` → verdicts applied onto the frames. Rules:
  - **Reject "Very few stars — likely clouds or trailing"**: star count
    < 50% of session median. Absolute collapse test, not statistical, so mild
    dips (twilight) never trip it.
  - **Reject "Stars softer than the rest of the session"**: FWHM above an
    **iterative one-tailed median + k×SD** gate (Siril's formula: median and
    plain standard deviation, remove values above `median + k×SD`, recompute,
    repeat until stable; excluded values don't pollute the statistics).
  - **Warn, never reject: "Brighter sky (twilight, moon or light pollution) —
    kept"**: background above the same style of gate. Informational only.
- Strictness: Relaxed / Normal / Strict → k = 4 / 3 / 2 (true sigma units).
  Default Normal. k scales the FWHM gate and the background warning gate only;
  the 50% cloud-collapse gate is fixed regardless of strictness.
- Each verdict carries: kept/rejected flag, machine reason code, human reason
  string, measured value, and the threshold that produced it — the UI never
  re-derives why.
- Existing `score` retained for best-first ordering at stack time.

Expected on the NGC 7000 benchmark at Normal: ~180 of 186 kept (vs 126 today);
the genuinely bad frames (FWHM 3.54 tracking hiccup, 479-star frame) still go.

### 2. Dialog UX (`ui/stack_dialog.py`)

- **Verdict column** appended to the table: kept → "OK" or the amber sky
  warning; rejected → the plain-language reason. Rejected rows dimmed; warning
  rows amber.
- **Row select → autostretched preview** in a pane beside the table: async
  load, debayered luminance, display autostretch, downscaled to ~512 px,
  cached per path. Lets the user eyeball borderline frames before overriding.
- **Strictness dropdown** beside the integration method. Changing it re-judges
  from cached measures immediately. Override tracking: the dialog records the
  set of rows whose checkbox the user has toggled by hand; re-judging updates
  the checkboxes of untouched rows only (verdict text updates everywhere).
- **Status line in user language**: "Keeping 177 of 186 frames — 59 of 62
  minutes of light." (from per-frame `EXPTIME`; falls back to frame counts if
  headers lack it).
- **Registration failures surfaced**: frames that fail to align during the
  stack are reported by filename in the completion status, not just a count.

### 3. Informative master filename (`stacking/stacker.py` + dialog)

Default output filename: `<Object>_<count>x<exp>s_<minutes>min.fits`
(e.g. `NGC7000_177x20.0s_59min.fits`), built from the sanitized FITS `OBJECT`
header and the final selection at the moment Stack is pressed. A user-edited
output path is never overwritten. Degrades gracefully: no OBJECT →
`master_177x20.0s_59min.fits`; no EXPTIME → omit exposure/minutes; worst case
`master.fits` (today's behaviour).

### 4. Error handling

- sep failure on a frame (corrupt/truncated) → verdict "Couldn't measure —
  excluded"; row still listed and manually includable.
- Fewer than 5 frames → no statistics; keep everything, say so in the status.
- Missing headers → fallbacks per section 3; integration time falls back to
  frame count phrasing.

### 5. Testing

- **Unit (judge)**: iterative k-sigma matches hand-computed cases; tight
  distributions reject ~nothing (the property the old code fails); cloud
  collapse gate; background warns but never rejects; strictness mapping;
  override preservation across re-judge; measurement-failure verdict.
- **Unit (filename)**: object sanitization ("NGC 7000" → "NGC7000"), missing
  OBJECT/EXPTIME fallbacks, user-edited path untouched.
- **UI (qtbot)**: verdict column text; strictness change re-judges without
  calling the (injectable) measurer again; preview requested on row select;
  status-line phrasing; registration-failure names in completion status.
- **Validation**: rerun the grading diagnostic on the NGC 7000 dataset;
  confirm kept/rejected matches predictions; visually inspect previews of all
  rejected frames.

## Out of scope (deliberate)

- **Quality weighting during integration** (PixInsight philosophy) — next
  iteration of the stacking deep-dive; the stored per-frame measures feed it.
- **Memory runaway during stacking** (~396 GB observed 2026-07-17) — tracked in
  `TODO.md`, to be profiled on this same dataset.
- Registration/integration math changes.

## References

- Diagnostic + policy comparison on NGC 7000 (2026-07-17): current policy 60
  rejected; 3-sigma(SD) gates 10; FWHM-only 1; best-90% 19; Siril 9.
- Siril k-sigma filtering: `generic_compute_accepted_value_with_rejection()`
  in `src/core/sequence_filtering.c` (median + k×SD, iterative, one-tailed);
  default `OSC_Preprocessing.ssf` stacks with **no** `-filter-*`.
- PixInsight ImageWeighting / SubframeSelector: weight-don't-cull; approval
  expressions in MAD-sigma units at k≈2–2.5 per single metric.
- DeepSkyStacker "best 80%": the rank-based design rejected (pun intended).
