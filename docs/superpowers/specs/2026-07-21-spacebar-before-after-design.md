# Spacebar Before/After Peek — Design

**Status:** approved by delegation (2026-07-21 — user authorised end-to-end autonomous
implementation and merge; design decisions below are the controller's, on record for review)
**Group:** D (UX)

## Problem

There's no quick way to see what the current/most-recent step did. The existing
"Before/After" toolbar button opens a *split-view* comparison (draggable divider),
which is heavier than the instant full-image "toggle the last edit" peek most photo
editors bind to the spacebar.

## Goal

Pressing **Space** toggles the main image between the **before** and **after** of the
most recently applied step — a full-image swap (image + histogram), with a small status
hint. Press again to toggle back. That is the only thing Space does.

## Decisions (made autonomously; flag on review if you'd prefer otherwise)

- **What "before/after" means (revised 2026-07-21 after real-data feedback):** the
  peek is **scoped to the current step**. *Before* = the current step's **entry image**
  (`_preview_base(stage_id)` — the same pre-step base a commit operates on, so it's
  WYSIWYG). *After* = whatever is currently on the canvas (`self._displayed`), i.e. the
  live preview if the slider is being dragged, else the committed result. So Space shows
  **only this step's effect**, whether or not the step has been applied yet — and never
  reveals an earlier step's change (the original bug: sitting on Local Contrast, Space
  brought back the noise removed two steps earlier, because it showed the last *applied*
  step's before/after). For non-processing stages (import/crop/export/enhancements) it
  falls back to `project.before_after()`.
- **Toggle, not hold:** Space flips before↔after on each press (not hold-to-peek). Simpler,
  and doesn't depend on key-release/auto-repeat quirks.
- **Full-image swap** (not the split-view): swaps both `image_view` and `histogram_view`
  to the before, and back to the after. The existing split-view Before/After toolbar
  button is left unchanged.
- **Space is intercepted app-wide** via an event filter on the QApplication, but only when
  the main window is active and the focused widget is **not** a text input (`QLineEdit` /
  `QPlainTextEdit` / `QTextEdit`), so typing spaces still works. Auto-repeat and modified
  Space are ignored.
- **Auto-reset:** any `_refresh()` (navigation, apply, undo/redo, reset) clears the peek
  state and restores the current image — so a peek never "sticks" across steps.

## Architecture

`nocturne/ui/main_window.py`:
- State `self._peek_active = False` in `__init__`; install the event filter:
  `QApplication.instance().installEventFilter(self)`.
- `eventFilter(self, obj, event)`: on `KeyPress`, `Key_Space`, no modifiers, not auto-repeat,
  `self.isActiveWindow()`, and focus not a text input → call `_toggle_peek()`, return `True`
  (consume). Otherwise defer to `super().eventFilter`.
- `_toggle_peek(self)`: no-op if `self.project is None`. Flip `_peek_active`; get
  `before, after = self.project.before_after()`; pick `before` if peeking else `after`;
  `self.image_view.set_image(to_qimage(img))`; `self.histogram_view.set_image(img)`;
  set `self._status` to "Before — press Space to compare" when peeking, else clear it.
- `_refresh(self)`: set `self._peek_active = False` at the top (it already repaints
  `image_view`/`histogram_view` from `project.current()`), so the peek resets whenever the
  view is rebuilt.

No new dependency; `to_qimage` and `before_after()` already exist.

## Testing

**`tests/ui/test_main_window.py`**
- `_toggle_peek` with a project + at least one applied step: first call sets the image_view
  to the "before" and `_peek_active` True; second call restores the "after" and
  `_peek_active` False. (Assert via `win.image_view` having an image / `_peek_active`, and a
  spy on `histogram_view.set_image` capturing the before then after image.)
- `_toggle_peek` with `project is None` is a no-op (no crash, `_peek_active` stays False).
- After `_toggle_peek()` (peek on), calling `_refresh()` resets `_peek_active` to False.
- The event filter is installed (smoke): `QApplication.instance()` has the window as an
  event filter — or, if reliable headless, `qtbot.keyClick(win, Qt.Key_Space)` toggles
  `_peek_active` when no text widget is focused.

## Out of scope

- Hold-to-peek (momentary) variant.
- Changing the existing split-view Before/After toolbar button.
