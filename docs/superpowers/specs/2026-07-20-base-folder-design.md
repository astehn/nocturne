# Configurable Base Open Folder — Design

**Status:** approved (2026-07-20)
**Group:** D (UX)
**Author:** Nocturne pipeline-audit initiative

## Problem

Every file/folder picker in Nocturne (Open FITS, Save Recipe, Export, and the
Stack / Ha-OIII / Batch folder pickers) passes an empty start directory, so they
cold-start at the OS default every time. Users who keep their astro data in one
folder must re-navigate there on every open — a persistent annoyance.

## Goal

Add a single configurable **Base folder** setting. Every picker starts there
(gracefully falling back to the OS default when it is unset or no longer exists).
Set it once in Settings; everything opens there.

Non-goal: remembering the last-used subfolder (explicitly chosen against — a
fixed, predictable base is simpler).

## Architecture

**Setting** (`nocturne/settings.py`):
- Add `base_dir: str = ""` to the `Settings` dataclass.
- `load_settings` reads `data.get("base_dir", "")`; `save_settings` writes it
  (the current `save_settings` serialises the dataclass, so confirm `base_dir`
  is included).

**Helper** (`nocturne/settings.py`):
```python
def start_dir(base_dir: str) -> str:
    """The directory a file picker should open in: the configured base folder if
    it is a real existing directory, else '' (OS default)."""
    base_dir = (base_dir or "").strip()
    return base_dir if base_dir and os.path.isdir(base_dir) else ""
```
Every picker resolves its start directory through this, so a blank or
deleted base folder never breaks a dialog.

**Settings dialog** (`nocturne/ui/settings_dialog.py`):
- Add a **"Default folder"** form row: a `QLineEdit` prefilled with
  `settings.base_dir` + a **Browse…** button that runs
  `QFileDialog.getExistingDirectory` and sets the field.
- `result_settings()` includes `base_dir=self._dir.text().strip()`.

**Pickers** — replace the empty start-directory argument with
`start_dir(<settings>.base_dir)` in every `QFileDialog.get*` call:
- `nocturne/ui/main_window.py`: Save Recipe (`getSaveFileName`), Open FITS
  (`getOpenFileName`), Export starless folder (`getExistingDirectory`), Export
  save (`getSaveFileName`). Uses `self.settings.base_dir`.
- `nocturne/ui/haoiii_dialog.py`: folder of raw subs (`getExistingDirectory`),
  master FITS (`getSaveFileName`). Uses `self._settings.base_dir`.
- `nocturne/ui/stack_dialog.py`: folder of subs (`getExistingDirectory`), master
  FITS (`getSaveFileName`). Uses `self._settings.base_dir`.
- `nocturne/ui/batch_dialog.py`: recipe (`getOpenFileName`), input folder,
  output folder (`getExistingDirectory`). Uses `self._settings.base_dir`.

All three dialogs already receive `settings` in their constructor and store it,
so they can reach `base_dir` without signature changes. (Confirm each stores it
as `self._settings`; if a dialog doesn't, add the assignment.)

The `getExistingDirectory` signature is `(parent, caption, dir)`;
`getOpenFileName`/`getSaveFileName` are `(parent, caption, dir, filter)`. The
resolved start dir goes in the `dir` position — the same position currently
holding `""`.

## Testing

**`tests/test_settings.py`** (or the existing settings test module)
- `start_dir(existing_dir)` returns that dir; `start_dir("")` returns `""`;
  `start_dir("/no/such/path")` returns `""`.
- `Settings` round-trips `base_dir` through `save_settings` / `load_settings`
  (write then read a `Settings(base_dir=tmp)`), and `load_settings` on a file
  without the key defaults `base_dir` to `""`.

**`tests/ui/test_settings_dialog.py`**
- The dialog prefills the "Default folder" field from `settings.base_dir` and
  `result_settings()` returns the edited value.

**`tests/ui/test_main_window.py`**
- With `settings.base_dir` set to an existing dir, `_choose_fits` passes that dir
  to `QFileDialog.getOpenFileName` (monkeypatch `getOpenFileName` to capture the
  `dir` argument; assert it equals the base dir). With `base_dir=""`, the
  captured `dir` is `""`.

## Out of scope (future)

- Last-used-folder memory (deliberately excluded).
- Per-picker distinct base folders (one base for everything).
