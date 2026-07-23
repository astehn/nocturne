# GUI Overhaul: Message Areas, Flush Nav, Collapsible Help — Design

**Date:** 2026-07-23
**Status:** Design (awaiting user review)
**Backup:** git tag `pre-gui-overhaul-2026-07-23` @ `eb9fb1f`; dir snapshot `/Volumes/Work/Code/Editor_backup_pre-gui-overhaul_2026-07-23`

## Goal

Reorganise where Nocturne shows feedback so that: the Back/Next buttons stop
moving, status/output text becomes copyable, blocking warnings stay prominent
and near the action, and the always-on wall of help text stops making the app
read like a tutorial for users who already know the steps.

## Motivation / current state

Feedback is spread across three surfaces, two of them stacked *below* the nav
buttons in the right pane (`nocturne/ui/main_window.py`):

- `_status` — red `QLabel`, right pane, **under** Back/Next (`:238`). Word-wraps,
  so its height changes with message length → **the buttons physically move**.
  Used for everything: successes ("Saved recipe…", "142 stars matched"),
  progress ("Plate-solving…"), and blocking guidance ("Stretch the image
  first…"). All uniformly alarm-red, even successes.
- `_busy_label` — grey `QLabel`, right pane, under `_status` (`:242`). Animated
  ellipsis progress.
- `log_panel` — full-width `QPlainTextEdit` at the window bottom (`:247`, capped
  140px). Timestamped step history. Already selectable/copyable, but visually
  underused (spans full width, rarely fills it).

Separately, the detailed help block `_explainer` (`:213`, a scrollable
`QLabel` capped at 240px, filled by `_update_explainer` from
`help_content.topic()`) is **always visible**. It is the most novice-friendly
element in the app on first use, and pure clutter by the tenth.

## Design

### 1. Three message channels, split by intent

Feedback is routed to one of three areas by *what the message is for*:

| Channel | Where | Widget | Content |
|---|---|---|---|
| **Log** | bottom bar, left | existing `log_panel` (`QPlainTextEdit`) | timestamped step history (Δ%), auto-appended. Unchanged. |
| **Output** | bottom bar, centre | **new**: read-only *selectable* text field | routine results & progress: "142 stars matched · gains…", "Saved recipe…", "Plate-solving…", "Separating stars…". Copyable. Shows the latest output line(s). |
| **Warning** | right pane, just above the nav buttons | **new**: `QLabel`, red/amber, word-wrap | blocking guidance & errors: "Stretch the image first…", "Set the ASTAP path…", "Could not open file…", "…unavailable — install…". Near the action, cleared on step change. |

The bottom bar becomes a horizontal split: **log (left) | output (centre)**,
sized to content (log wider for history, output wide enough for a line of
result text) — not a 50/50 split of a mostly-empty strip.

**Routing API.** Replace scattered `self._status.setText(...)` with three
intent-named methods on `MainWindow`, so every call site self-documents which
channel it means:

```python
def _show_output(self, text: str) -> None    # bottom-centre output field (selectable)
def _show_warning(self, text: str) -> None    # right-pane warning label (red/amber)
def _clear_warning(self) -> None              # empties the warning label (grow-upward collapses)
```

`_show_output` also mirrors the line into the log where appropriate is **out of
scope** — output and log stay independent (user's explicit ask).

**Colour semantics.** Warning = red for errors, amber for advisories (both are
"you must act / be aware"). Output = neutral/subtle (successes stop being red).
This falls out of the split for free.

### 2. Nav buttons pinned flush, warnings grow upward

The right-pane column already has `addStretch(1)` *above* the explainer (`:209`).
Reorder so the nav row (`Back`/`Next`) is the **last** widget in the column,
with the warning label immediately above it:

```
[histogram] [panel] --stretch(1)-- [collapsible help] [warning label] [nav row]
```

Because the stretch sits above the cluster, the nav row stays pinned to the
pane bottom, and when the warning label gains text it **expands upward** into
the stretch space — the buttons never move. `_status` and `_busy_label` are
removed from below the nav (that stacking is the whole bug).

Back/Next therefore sit flush at the bottom-right, always in the exact same
place regardless of message state.

### 3. Collapsible, global, sticky, persisted help

The detailed `_explainer` block becomes a **collapsible section** with a
clickable header ("How this works ▸" collapsed / "▾" expanded). The per-step
one-liner (`_desc_label` in `step_panels.py`, e.g. "Final targeted tweaks — tap
to stack, Undo to peel back.") stays **always visible** — it is one line and
pure orientation, not a tutorial wall.

Critical property: the expanded/collapsed state is a **single global
preference**, persisted, sticky across steps and sessions:

- New field `Settings.help_expanded: bool = True` (default expanded — the app is
  still novice-first, so a first-run user is guided out of the box).
- Toggling the header flips `settings.help_expanded` and calls `save_settings`
  immediately.
- The state applies to **every** step. Collapse once → stays collapsed on all
  steps and on next launch, until the user reopens it.

This is what actually cures the "annoying over and over" problem: per-step or
per-session state would force an experienced user to re-collapse repeatedly,
which is worse than the wall of text. Per-step granularity (keep one step's
help open, others shut) is a deliberate **non-goal** for v1.

When expanded: header + `<b>summary</b> + body` + "Full help →" link (opens the
existing `HelpDialog` for the topic). When collapsed: just the header row; the
freed vertical space lets the right pane breathe / gives tools room.

### Message routing classification (the `_status` call sites)

**→ Warning** (blocking guidance / errors, right pane):
`main_window.py` :340 (stacking unavailable), :349 (Ha/OIII unavailable),
:358 (Star Spikes needs stretch), :377 (Narrowband needs stretch), :381
(Narrowband needs colour), :426 (set ASTAP path), :441 (couldn't plate-solve),
:591 (could not open file), :647 (Levels needs stretch), :716 (error prefix),
:1451 (split needs RC-Astro), and the `_FREE_STAR_NOTE` notices (:999, :1140,
:1264).

**→ Output** (results / progress, bottom-centre):
:331 (saved recipe), :433 (plate-solving…), :673 (`step.last_message`, e.g.
"142 stars matched"), :1009/:1157/:1281 (separating stars…), and the star-split
result lines (:1020, :1149, :1186, :1273, :1296) — each confirmed at plan time.

**Special:** :1417 "Before — press Space to compare" is a transient *mode*
indicator; keep it as a lightweight cue (output channel or a dedicated peek
label — decided at plan time). `""`-clears currently on `_status` map to
`_clear_warning()` on step change (:568) and before export (:1448).

### `_busy_label` (animated progress)

`_busy_label` (`:242`, ellipsis animation) is transient progress, not something
to copy later. It stays a transient indicator but moves out from under the nav
(it currently contributes to button jump). Placement — inside the output area
vs. a small inline cue — is settled at plan time; it must not push the nav row.

## Data / settings changes

- `nocturne/settings.py`: add `help_expanded: bool = True` to `Settings`; read it
  in `load_settings` (`data.get("help_expanded", True)`); `save_settings`
  serialises it automatically via `asdict`.

## Testing

- **Settings round-trip:** `help_expanded` defaults True, survives
  save→load, and load of an old settings.json without the key defaults True.
- **Routing:** unit tests (qtbot) that `_show_warning` sets the warning label and
  `_show_output` sets the output field, and that a step change clears the warning
  but not the log.
- **Nav stays put:** with the warning label empty vs. filled with a long
  wrapping message, the nav row's `y()` is unchanged (the regression this whole
  overhaul exists to kill).
- **Help toggle:** toggling the header flips `settings.help_expanded`, persists,
  and the same state is shown when navigating to a different step.
- Existing `test_main_window.py` assertions that reference `_status` are updated
  to the new methods/widgets.

## Non-goals (v1)

- Per-step help expand/collapse memory (global only).
- Merging output into the log (they stay separate).
- Reworking `help_content` topics themselves or the `HelpDialog`.
- Changing the toolbar "Log" button behaviour beyond what the split requires.

## Open questions for the plan phase

1. Output widget type: read-only `QPlainTextEdit` (multi-line, matches log) vs.
   a selectable single-line field. Leaning multi-line read-only for symmetry
   with the log and easy copy.
2. Exact home for `_busy_label` / the peek indicator.
3. Whether "Full help →" also appears when collapsed (probably no — collapsed
   means minimal).
