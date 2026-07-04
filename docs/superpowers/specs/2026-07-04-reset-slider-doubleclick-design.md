# Reset Sliders on Double-Click — Design

**Date:** 2026-07-04
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — design pre-specified in TODO; built autonomously under standing authorization.

## Motivation

After dragging sliders around, users can't tell what the default was or restore it. The
Lightroom / PixInsight convention is **double-click a slider to reset it to its default** — no
extra UI clutter, works per-slider. Apply that across the app's sliders.

## Decisions

- Add a small `ResetSlider(QSlider)` that stores its default and resets on double-click, with a
  "Double-click to reset" tooltip.
- Swap every ad-hoc horizontal `QSlider` in `ui/step_panels.py` and `ui/palette_dialog.py` for it.
- **Range is set before value** in the constructor (a default outside the Qt default 0–99 range —
  e.g. gamma's 100 in a 10–300 range — would otherwise be clamped). This is the one real trap.
- Reset restores the widget's stored construction default. For the Stretch slider that default is
  a fixed 50 (the "Auto" target); the Target dropdown continues to set the slider on change, but
  double-click resets to 50. (Matches the TODO's "stretch 50"; not tied to the current target —
  intentional, keeps the widget self-contained.)

## Defaults (verified against current code, not the stale TODO)

| Slider | File | Range | Default |
|---|---|---|---|
| Stretch aggressiveness | step_panels | 0–100 | 50 |
| Levels black | step_panels | 0–100 | 0 |
| Levels gamma | step_panels | 10–300 | 100 |
| Levels white | step_panels | 0–100 | 100 |
| Saturation | step_panels | 0–100 | **50** (TODO said 40 — stale) |
| Palette black | palette_dialog | 0–100 | 0 |
| Palette mid | palette_dialog | 0–100 | 50 |
| Palette white | palette_dialog | 0–100 | 100 |

## Architecture / changes

### `ui/reset_slider.py` (new)
```python
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSlider


class ResetSlider(QSlider):
    """Horizontal slider that resets to its construction default on double-click."""

    def __init__(self, default: int, *, minimum: int = 0, maximum: int = 100,
                 orientation: Qt.Orientation = Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setRange(minimum, maximum)   # range BEFORE value so default isn't clamped
        self.setValue(default)
        self._default = default
        self.setToolTip("Double-click to reset")

    def mouseDoubleClickEvent(self, event) -> None:
        self.setValue(self._default)      # emits valueChanged so live previews update
        event.accept()
```

### `ui/step_panels.py`
- Replace the 5 `QSlider(...)`/`setRange`/`setValue` blocks with `ResetSlider(...)`:
  - stretch: `ResetSlider(50)`
  - levels black `ResetSlider(0)`, gamma `ResetSlider(100, minimum=10, maximum=300)`, white `ResetSlider(100)`
  - saturation: `ResetSlider(50)` (keep the existing `setTickPosition`/`setTickInterval(50)` calls)
- Keep everything else (signal wiring, `w.*_slider` attributes, target-dropdown `setValue`). Drop
  the now-unused `QSlider` import only if nothing else uses it (the tick enums are accessed via
  `QSlider.TickPosition` — keep the import).

### `ui/palette_dialog.py`
- Change the `_slider()` factory to `_slider(self, default: int) -> ResetSlider: return ResetSlider(default)`.
- `black = self._slider(0)`, `mid = self._slider(50)`, `white = self._slider(100)`; remove the
  now-redundant post-construction `black.setValue(0)` / `white.setValue(100)` lines. The signal
  connections still happen after construction, so no premature `_on_slider` fire.

## Data flow

Unchanged. Reset emits `valueChanged`, so the palette preview (connected to `_on_slider`) updates
on reset; the stretch/saturation/levels sliders are read on Apply, so their reset simply changes
the displayed value.

## Error handling

None new — pure UI. Double-click on a slider already at its default is a no-op.

## Testing

- **`tests/ui/test_reset_slider.py` (new):**
  - `ResetSlider(50)` starts at 50; `setValue(30)`; `qtbot.mouseDClick(slider, Qt.LeftButton)` → 50.
  - `ResetSlider(100, minimum=10, maximum=300)` starts at **100** (proves range-before-value: not clamped to 99).
  - tooltip contains "reset".
- **`tests/ui/test_step_panels.py`:** stretch / saturation / levels sliders are `ResetSlider`
  instances with `_default` 50 / 50 / (0,100,100); a double-click after moving resets one of them.
- **`tests/ui/test_palette_dialog.py`:** black/mid/white are `ResetSlider` with defaults 0/50/100;
  double-click on a moved slider restores default and updates the curve (preview state).
- Full suite stays green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`).

## Verification (by eye)

Drag any slider (Stretch, Levels, Saturation, Palette) → double-click → snaps back to default;
hover shows the "Double-click to reset" tooltip.
