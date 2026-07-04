# "Reset Image" — Start Over Button — Design

**Date:** 2026-07-04
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — user-requested; built autonomously under standing authorization.

## Motivation

Common workflow: the user edits all the way to the end, isn't happy, and today has to re-open the
same file from disk to start fresh. Add a **"Reset" button that restarts editing on the
already-loaded image** (no file re-pick), behind a confirmation so it can't be hit by accident.

## Decisions

- A **toolbar "Reset" action** (with an icon) placed in the Edit/compare group next to Undo/Redo.
- Clicking it shows a **confirm dialog** ("Discard all edits and start over?", default No); only on
  Yes does it reset.
- Reset **re-initialises the project from the loaded base image** — a true "start over": fresh
  `Project`, all history/redo cleared, back on the Import stage. No disk re-read.
- The action is **enabled only when an image is loaded** (like Undo/Redo).

## Architecture / changes

### `ui/main_window.py`
- In `open_image(base, label)`, stash the source so reset can rebuild without a file dialog:
  ```python
  self._source_base = base
  self._source_label = label
  ```
  (Set them at the top of `open_image`, before building the Project.)
- Add the toolbar action in the Edit/compare group (after Redo):
  ```python
  self._reset_act = tb.addAction(load_icon("reset"), "Reset", self._reset_image)
  ```
- New handler:
  ```python
  def _reset_image(self) -> None:
      if self.project is None:
          return
      resp = QMessageBox.question(
          self, f"{APP_NAME} — Reset",
          "Discard all edits and start over from the loaded image?",
          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
          QMessageBox.StandardButton.No,
      )
      if resp != QMessageBox.StandardButton.Yes:
          return
      self.open_image(self._source_base, self._source_label)  # fresh Project, history cleared
  ```
- In `_refresh`, gate the action like Undo/Redo:
  ```python
  self._reset_act.setEnabled(self.project is not None)
  ```
- `QMessageBox` and `APP_NAME` are already imported/used (Help dialog).

### `assets/icons/reset.svg` (new) + `ui/icons.py`
- Add a `reset.svg` (rotate-counterclockwise glyph) matching the existing icon style
  (`viewBox="0 0 24 24"`, `stroke="#fff"`, `stroke-width="2"`, round caps/joins):
  ```xml
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 4 3 10 9 10"/><path d="M5.5 15a8 8 0 1 0 1.9-8.3L3 10"/></svg>
  ```
- Add `"reset"` to `ICON_NAMES` in `ui/icons.py` (the existing parametrized icon test then covers
  it automatically).

## Data flow

Reset button → `_reset_image` → confirm → `open_image(_source_base, _source_label)` → new
`Project(base, cache_dir)`, log "Opened …", go to Import stage, rebuild panel, refresh. Identical
end state to a fresh open of the same file, minus the disk read.

## Error handling

- Guarded on `project is None` (returns; also disabled in the toolbar until load).
- Reset re-uses the in-memory base (`AstroImage`), so it cannot fail on a missing/renamed file.
- Default dialog button is No, so an accidental Enter/Escape does not wipe work.

## Testing

- **`tests/ui/test_icons.py`:** already parametrized over `ICON_NAMES` — adding `"reset"` makes it
  assert `reset.svg` exists and is valid XML. (No new test needed; verify it passes.)
- **`tests/ui/test_main_window.py`:**
  - `open_fits` sets `_source_base`/`_source_label`.
  - `_reset_act` is disabled before load, enabled after `open_fits`.
  - Reset confirmed (monkeypatch `QMessageBox.question` → `Yes`): after editing (e.g. a Stretch),
    `_reset_image()` clears history — `project.entries()` empty, current stage is `load`, and
    `project.current().data` matches the original base shape/values.
  - Reset declined (monkeypatch → `No`): the edit survives (`entries()` still has "Stretch").
- Full suite green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`).

## Verification (by eye)

Open an image, apply several steps, click **Reset**, confirm → back to the freshly-imported image
on the Import stage; decline → nothing changes. Button greyed out before any image is loaded.
