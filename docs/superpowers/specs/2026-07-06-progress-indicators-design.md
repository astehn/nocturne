# Progress Indicators — Design

**Date:** 2026-07-06
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — building under standing authorization.

## Motivation

The app runs slow work (GraXpert / RC-Astro CLI calls, the two-pass Colourise StarX,
export) with little or no visible feedback. On a fast machine it feels instant; on a slow
machine an operation can take several seconds during which the window looks **hung**. The
user asked for progress indication that is **clear but non-intrusive** — the current image
must stay visible, and fast operations must not flash distracting UI.

Two concrete defects compound the problem:

1. **Export runs on the UI thread** (`export_final`), so the "Starless + Stars" path
   (a StarX pass + two TIFF writes) genuinely freezes the whole window with zero feedback.
2. **`_busy` is not cleared in a `finally`** — if the `done` callback body throws after
   busy is set, the app stays busy (overlay up, buttons disabled) **forever**, looking
   permanently hung.

## Decisions (from discussion)

- **Ambient, not modal.** Replace the image-dimming `BusyOverlay` with a **thin (3px)
  animated indeterminate bar** anchored to the top edge of the image canvas. The image is
  never dimmed or blocked.
- **Threshold-gated visuals.** Nothing appears for the first **~400 ms** of an operation.
  The `_busy` re-entry gate flips immediately (double-clicks still blocked); only the
  *visuals* (bar, busy-cursor, busy label) are delayed, so sub-threshold work shows nothing
  and never flashes.
- **Per-operation label.** A dedicated grey busy label near the Back/Next buttons shows
  what is running ("Applying Stretch…", "Colourising…", "Exporting…") with a gently
  animated ellipsis. Kept **separate** from the red error `_status` label.
- **App busy-cursor** while an operation is visibly running (set once, restored once).
- **Indeterminate only** on the main window. The slow main-window ops are single CLI /
  numpy calls with no parseable progress. The **stacking / batch / Ha-OIII dialogs already
  have real `i/n` progress bars and are out of scope** (unchanged).
- **Fold in the two real fixes**: move `export_final` off the UI thread, and make busy
  clearing `finally`-safe — both via one small consolidation helper (`_run_busy`).
- **Deferred (fast-follow):** parsing GraXpert / RC-Astro stdout for a *real* percentage
  (would upgrade specific ops to determinate); unifying the dialogs' bars with `BusyBar`.

## Architecture / changes

### `ui/busy_bar.py` (new) — `BusyBar(QWidget)`

Replaces `BusyOverlay`. A thin animated indeterminate progress bar shown as an overlay
child of a target widget (the image view), anchored to the target's **top edge**, full
width, **3 px** tall. Never dims or covers the image body.

```python
BUSY_BAR_HEIGHT = 3           # px
_ANIM_INTERVAL_MS = 33        # ~30 fps repaint

class BusyBar(QWidget):
    """Thin animated indeterminate progress bar overlaid on a target's top edge."""

    def __init__(self, parent=None) -> None: ...
    #   - transparent for mouse events (WA_TransparentForMouseEvents) so it never
    #     blocks clicks on the canvas underneath
    #   - owns a QTimer (_ANIM_INTERVAL_MS) that advances an animation phase and
    #     calls update(); the timer runs only while visible

    def show_over(self, widget: QWidget) -> None:
        """Reparent to widget, position as a top strip (width = widget.width,
        height = BUSY_BAR_HEIGHT), install a resize filter on widget so the bar
        follows resizes, start the animation timer, show + raise."""

    def hide_bar(self) -> None:
        """Stop the animation timer, remove the resize filter, hide."""

    def eventFilter(self, obj, event) -> bool:
        """On the target's Resize event, reposition the bar to the new top strip."""

    def paintEvent(self, event) -> None:
        """Paint a moving highlight sweep across a faint track using the current
        animation phase — the indeterminate 'alive' motion."""
```

Notes:
- Indeterminate only (no `set_fraction`) — YAGNI for the main window.
- The animation timer must be **stopped when hidden** so headless tests and idle windows
  do not spin a repaint timer.

### `ui/main_window.py`

**New busy label.** Add a dedicated grey busy label in the right panel near the nav
buttons, separate from the red `_status` (error) label:

```python
self._busy_label = QLabel("")
self._busy_label.setStyleSheet("color: #9aa0a6;")   # neutral grey, not error-red
# placed in the right panel near the Back/Next row
```

**New busy state.** In `__init__`, replace `self._busy_overlay = BusyOverlay()` with:

```python
self._busy_bar = BusyBar()
self._busy_shown = False                 # whether the delayed visuals are currently up
self._cursor_active = False              # whether an override cursor is currently set
self._busy_timer = QTimer(self)          # single-shot; arms the delayed visuals
self._busy_timer.setSingleShot(True)
self._busy_timer.timeout.connect(self._show_busy_visuals)
self._busy_label_text = ""               # base label text (ellipsis animation appends)
self._ellipsis_timer = QTimer(self)      # cycles the label's trailing dots while visible
self._ellipsis_timer.timeout.connect(self._tick_ellipsis)
```

**Threshold-gated `_set_busy`.** Rewrite to flip the gate immediately but delay the
visuals:

```python
BUSY_DELAY_MS = 400

def _set_busy(self, busy: bool, label: str = "Working…") -> None:
    self._busy = busy
    if busy:
        self._busy_label_text = label
        self._busy_timer.start(BUSY_DELAY_MS)     # visuals appear only if op outlasts it
    else:
        self._busy_timer.stop()
        self._hide_busy_visuals()                 # no-op if visuals never showed
    self._back_btn.setDisabled(busy)              # gating stays immediate (prevents
    self._next_btn.setDisabled(busy)              # double-clicks even sub-threshold)
    if hasattr(self._panel, "apply_btn"):
        self._panel.apply_btn.setDisabled(busy)

def _show_busy_visuals(self) -> None:
    self._busy_bar.show_over(self.image_view)
    self._busy_label.setText(self._busy_label_text)
    if not self._cursor_active:
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        self._cursor_active = True
    self._busy_shown = True

def _hide_busy_visuals(self) -> None:
    if self._busy_shown:
        self._busy_bar.hide_bar()
        self._busy_label.setText("")
    if self._cursor_active:
        QApplication.restoreOverrideCursor()
        self._cursor_active = False
    self._busy_shown = False
```

The busy label's animated ellipsis is driven by a **separate small `QTimer` owned by
`MainWindow`** (interval ~400 ms), started in `_show_busy_visuals` and stopped in
`_hide_busy_visuals`. On each tick it cycles the label text between `text`, `text.`,
`text..`, `text...`. This keeps `BusyBar` fully decoupled from the label. Keep it simple —
it is a nicety on top of the bar's motion, not the primary cue.

**Finally-safe consolidation helper.** Add `_run_busy`, centralising the
set-busy → run_async → done/err dance so busy is **always** cleared:

```python
def _run_busy(self, work, on_result, label: str, err_prefix: str) -> None:
    self._set_busy(True, label)

    def done(result):
        try:
            on_result(result)
        finally:
            self._set_busy(False)          # cleared even if on_result raises

    def err(exc):
        try:
            self._status.setText(f"{err_prefix}: {exc}")
        finally:
            self._set_busy(False)

    if self._async_enabled:
        run_async(self._pool, work, done, err)
    else:
        try:
            result = work()
        except Exception as exc:            # mirror the async error path
            err(exc)
        else:
            done(result)                    # on_result throw propagates after finally
```

**Migrate the three slow paths onto `_run_busy`:**

- `apply_current` — `work` = `step.apply(base, option)`; `on_result` = record step, log,
  refresh; `label` = `f"Applying {STEP_NAME[stage_id]}…"`; `err_prefix` = `"Failed"`.
- `_colourise` — `work` = the StarX/compose closure; `on_result` = `jump_back(idx)` +
  run_step + log + refresh; `label` = `"Colourising…"`; `err_prefix` = `"Colourise failed"`.
- `export_final` — after the `QFileDialog` selection (which stays synchronous on the UI
  thread), run the **write** through `_run_busy`: `work` = the StarX+TIFF / single-file
  save; `on_result` = append the "Exported …" log entry; `label` = `"Exporting…"`;
  `err_prefix` = `"Export failed"`. This moves export off the UI thread. The now-redundant
  `_guarded` is retired (export was its only caller).

### Removals

- Delete `BusyOverlay` from `ui/worker.py` (replaced by `BusyBar`).
- Delete `_guarded` from `main_window.py` (no callers after the export migration).

## Data flow

User triggers a slow op → `_run_busy(work, on_result, label, err_prefix)` → `_set_busy(True)`
flips the gate + arms the 400 ms timer → `run_async` runs `work` on a worker thread → if the
op outlasts 400 ms the timer fires and the bar + busy-cursor + grey label appear → worker
finishes → `done`/`err` runs `on_result` (or sets the error) and **always** clears busy in a
`finally`, hiding the visuals and restoring the cursor. Fast ops complete before the timer
fires and show nothing.

## Error handling

- Any exception in `work`, or in the `on_result` body, still clears busy (the `finally` in
  `done`/`err`, plus the sync-path structure). This is the fix for the stuck-forever bug.
- The busy-cursor override is balanced by `_cursor_active`: set at most once per visible op,
  restored at most once — no unbalanced `restoreOverrideCursor` stack.
- Export failures surface via `err_prefix="Export failed"` in the red `_status` label
  (same user-visible behaviour as the retired `_guarded`, now off the UI thread).
- `BusyBar` is mouse-transparent, so it never intercepts clicks on the canvas.

## Testing

Preserve the existing test seams: the `_async_enabled=False` synchronous path, the
injectable `_bg_runner` / `_rc_runner`, and the dialogs' `on_progress` contract (untouched).

- **busy_bar** (`tests/ui/test_busy_bar.py`, new):
  - `BusyBar().show_over(w)` reparents to `w`, sizes to a `BUSY_BAR_HEIGHT`-tall top strip,
    starts its animation timer (`isActive()` True), and is visible.
  - `hide_bar()` stops the timer (`isActive()` False) and hides.
  - The bar has `WA_TransparentForMouseEvents` set (never blocks canvas clicks).
- **worker** (`tests/ui/test_worker.py`): update the `BusyOverlay` test to `BusyBar`
  (construct + `show_over` + `hide_bar`); `run_async` tests unchanged.
- **main_window** (`tests/ui/test_main_window.py`):
  - `_set_busy(True, "X…")` sets `_busy` True and disables Back/Next immediately, but does
    **not** show visuals synchronously (`_busy_shown` False before the timer fires);
    `_set_busy(False)` clears `_busy`, stops the timer, and re-enables the buttons.
  - Directly invoking `_show_busy_visuals()` shows the bar, sets the busy label text, and
    sets `_cursor_active`; `_hide_busy_visuals()` restores all three.
  - **Finally-safe regression test:** with `_async_enabled=False`, call `_run_busy` with an
    `on_result` that raises; assert `_busy` ends False (busy cleared despite the throw) and
    the exception propagates.
  - `apply_current` / `_colourise` still record their step, log, and refresh with
    `_async_enabled=False` (existing assertions hold after the migration).
  - **Export becomes async:** update the existing export tests to set
    `win._async_enabled = False` so the write runs inline; assert files are written and the
    "Exported …" log entry appears (behaviour preserved, now via `_run_busy`).
  - The busy-cursor override is balanced (no leftover override after an op:
    `QApplication.overrideCursor()` is None once the op completes).
- Full suite green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`).

## Verification (by eye)

On a slower machine (or with an artificially slow runner): apply Stretch → after ~0.4 s a
thin bar sweeps across the top of the image, the cursor shows busy, and "Applying Stretch…"
appears near the buttons; the image stays fully visible; all clear the instant it finishes.
Colourise shows "Colourising…". Export (Starless + Stars) no longer freezes the window — the
bar runs and the UI stays responsive. A fast step apply shows nothing (no flash). Forcing an
error mid-op leaves the app responsive (not stuck busy).
