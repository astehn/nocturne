# Processing Log — Design

## Context

Some steps (especially Noise & Sharpen, Color) change the image so subtly that the user
can't tell anything happened. Both Siril (log console) and PixInsight (process history /
console) confirm actions textually. Add a **processing log** that records each action with
a timestamp, its settings, and a **quantitative change metric** so even invisible changes
are proven and quantified.

## Decisions (approved 2026-06-30)
- **Content per entry:** step + settings + a change metric (RMS Δ as % of full scale).
- **Placement:** a collapsible panel across the bottom of the window, toggled by a "Log"
  button in the toolbar. Default visible (it's meant to be glanceable).
- **Behavior:** append-only activity log with timestamps — records every action including
  undone ones (an "Undo"/"Redo" line is logged), an honest session record.

## Components
- **`core/metrics.py`** — `rms_delta(before: AstroImage, after: AstroImage) -> float | None`.
  Root-mean-square of `(after - before)` over all pixels, as a fraction of full scale
  (0–1 data → already a fraction; report ×100 as %). Returns `None` when the shapes differ
  (e.g. after a crop), since a pixelwise delta is undefined. Pure, no Qt.
- **`ui/log_panel.py`**
  - `format_log_entry(name: str, option, delta: float | None, dims: tuple[int,int] | None = None) -> str`
    builds the body (no timestamp): e.g. `"Noise & Sharpen (medium)  —  Δ 0.8%"`,
    `"Crop  —  → 1920×1080"`, `"Color  —  Δ 0.0%"`. `option` of None/"" omits the parens.
  - `LogPanel(QWidget)` — a read-only `QPlainTextEdit`; `append_entry(text)` prepends an
    `HH:MM:SS` timestamp, appends a line, and auto-scrolls to the bottom. `clear_log()`.
- **`ui/main_window.py`**
  - Restructure the central widget: wrap the existing stepper|image|controls row in a
    `QVBoxLayout` and add `self.log_panel` beneath it.
  - Toolbar **"Log"** toggle action (checkable, default checked) → show/hide the panel.
  - Emit log entries: on **open** (`"Opened <name> — <W>×<H>"`), on each **applied step**
    (name + option + `rms_delta(base, result)`; for crop, dims of the result), on **export**
    (`"Exported <filename>"`), and on **undo/redo** (`"Undo"` / `"Redo"`).
  - The apply flow already has `base` (pre-step) and `result` (post-step), so the delta is
    computed there. Background "off" logs `"Background (off) — skipped"`.

## Data flow
`apply_current.done(result)` → `delta = rms_delta(base, result)` →
`self.log_panel.append_entry(format_log_entry(name, option, delta, dims))`. Timestamp is
added inside `append_entry` (runtime `datetime.now()`), kept out of `format_log_entry` so
the formatter is deterministically testable.

## Testing
- `rms_delta`: identical images → 0.0; a scaled/changed image → > 0; different shapes → None.
- `format_log_entry`: step+delta string; crop (dims, no delta); None/empty option omits parens; zero delta renders `Δ 0.0%`.
- `LogPanel.append_entry` adds a line containing the message (timestamp not asserted); `clear_log` empties it.
- `main_window` (pytest-qt): applying a step appends an entry containing the step name and `Δ`; opening logs an "Opened" entry; the Log toggle shows/hides the panel.

## Out of scope
Saving the log to disk; per-entry revert (that's undo/redo + future project save).
