# Narrowband Palette (HOO / pseudo-SHO) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone "Palette…" tool that remaps a stacked duo-band Seestar master into an HOO or pseudo-SHO narrowband palette and writes a new file.

**Architecture:** A Qt-free `core/palette.py` (extract Ha/OIII, build the palettes) + a `load_master` loader in `core/fits_io.py` + a file-in/file-out `ui/palette_dialog.py`, mirroring the existing `batch.py` / `ui/batch_dialog.py` pattern. Fully decoupled from the editing flow.

**Tech Stack:** Python 3.11+, numpy, astropy, tifffile, PySide6.

## Global Constraints

- Package is `seestar_processor` (do NOT rename).
- Always use the venv: `.venv/bin/python` and `.venv/bin/pytest` (system python is 3.9 and fails).
- UI tests run headless: prefix with `QT_QPA_PLATFORM=offscreen`.
- `core/` stays Qt-free.
- The pseudo-SHO palette must be labeled **pseudo** in UI/copy — the Seestar has no SII; it is an artistic Ha+OIII remap, not real SHO.
- Channel extraction: `Ha = red channel`, `OIII = (green + blue) / 2`, clipped to [0,1].
- Feature stays isolated/removable: `core/palette.py` + `load_master` + `ui/palette_dialog.py` + one toolbar action.
- Commit after each task. Do not start on `main` — create the `narrowband-palette` branch first.

---

## File Structure

- `seestar_processor/core/palette.py` — `PALETTES`, `extract_channels`, `hoo`, `pseudo_sho`, `apply_palette` (Qt-free numpy).
- `seestar_processor/core/fits_io.py` — add `load_master(path)` (FITS via existing `load_fits`, 16-bit TIFF via tifffile).
- `seestar_processor/ui/palette_dialog.py` — the Palette dialog.
- `seestar_processor/ui/main_window.py` — "Palette…" toolbar action + `_open_palette`.
- Tests: `tests/core/test_palette.py`, `tests/core/test_load_master.py`, `tests/ui/test_palette_dialog.py`.

---

## Task 0: Branch setup

- [ ] **Step 1: Create the feature branch**

```bash
cd /Volumes/Work/Code/Editor
git checkout -b narrowband-palette
git status   # expect: On branch narrowband-palette, clean
```

---

## Task 1: `core/palette.py` — channel extraction + palettes

**Files:**
- Create: `seestar_processor/core/palette.py`
- Test: `tests/core/test_palette.py`

**Interfaces:**
- Consumes: `core.image.AstroImage` (`.data` HxWx3 float32, `.is_color`, `.is_linear`, `.metadata`).
- Produces:
  - `PALETTES = ("HOO", "pseudo_SHO")`
  - `extract_channels(img: AstroImage) -> tuple[np.ndarray, np.ndarray]` — `(ha, oiii)` 2D float32 in [0,1]; raises `ValueError` if not colour.
  - `hoo(img) -> AstroImage`, `pseudo_sho(img) -> AstroImage`
  - `apply_palette(img: AstroImage, name: str) -> AstroImage` — dispatch; `ValueError` on unknown name.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_palette.py`:

```python
import numpy as np
import pytest
from seestar_processor.core.image import AstroImage
from seestar_processor.core.palette import (
    PALETTES, extract_channels, hoo, pseudo_sho, apply_palette,
)


def _img(pixels):
    # pixels: list of (r,g,b) -> a 1 x N x 3 colour image
    return AstroImage(np.array([pixels], dtype=np.float32), is_linear=False)


def test_extract_channels_ha_red_oiii_greenblue():
    img = _img([(0.8, 0.2, 0.4)])
    ha, oiii = extract_channels(img)
    assert np.allclose(ha, 0.8)
    assert np.allclose(oiii, 0.3)          # (0.2 + 0.4) / 2


def test_extract_channels_rejects_mono():
    mono = AstroImage(np.zeros((4, 4), np.float32))
    with pytest.raises(ValueError):
        extract_channels(mono)


def test_hoo_ha_pixel_red_and_oiii_pixel_teal():
    out = hoo(_img([(0.9, 0.1, 0.1), (0.1, 0.9, 0.9)])).data
    ha_px, oiii_px = out[0, 0], out[0, 1]
    assert ha_px[0] > ha_px[1] and ha_px[0] > ha_px[2]        # red-dominant
    assert np.isclose(oiii_px[1], oiii_px[2]) and oiii_px[1] > oiii_px[0]  # teal


def test_pseudo_sho_ha_gold_oiii_teal():
    out = pseudo_sho(_img([(0.9, 0.1, 0.1), (0.1, 0.9, 0.9)])).data
    ha_px, oiii_px = out[0, 0], out[0, 1]
    # Ha region -> gold: R and G both above B
    assert ha_px[0] > ha_px[2] and ha_px[1] > ha_px[2]
    # OIII region -> teal: B above R
    assert oiii_px[2] > oiii_px[0]


def test_apply_palette_dispatch_and_unknown():
    img = _img([(0.5, 0.5, 0.5)])
    assert apply_palette(img, "HOO").data.shape == img.data.shape
    assert set(PALETTES) == {"HOO", "pseudo_SHO"}
    with pytest.raises(ValueError):
        apply_palette(img, "SHO")
```

- [ ] **Step 2: Run it, expect failure**

Run: `.venv/bin/pytest tests/core/test_palette.py -q`
Expected: FAIL (module `seestar_processor.core.palette` not found).

- [ ] **Step 3: Implement**

Create `seestar_processor/core/palette.py`:

```python
from __future__ import annotations

import numpy as np

from .image import AstroImage

PALETTES = ("HOO", "pseudo_SHO")


def extract_channels(img: AstroImage) -> tuple:
    """Return (ha, oiii) as 2D float32 in [0,1]. Ha = red channel; OIII =
    mean of green and blue. Raises ValueError for a non-colour image."""
    if not img.is_color:
        raise ValueError("palette needs a colour (RGB) master")
    data = np.clip(img.data, 0.0, 1.0)
    ha = data[..., 0].astype(np.float32)
    oiii = ((data[..., 1] + data[..., 2]) / 2.0).astype(np.float32)
    return ha, oiii


def _image_like(channels: tuple, like: AstroImage) -> AstroImage:
    rgb = np.clip(np.stack(channels, axis=2), 0.0, 1.0).astype(np.float32)
    return AstroImage(rgb, is_linear=like.is_linear, metadata=dict(like.metadata))


def hoo(img: AstroImage) -> AstroImage:
    """R=Ha, G=OIII, B=OIII — the honest native duo-band palette."""
    ha, oiii = extract_channels(img)
    return _image_like((ha, oiii, oiii), img)


def pseudo_sho(img: AstroImage) -> AstroImage:
    """Foraxx-inspired gold/teal remap from Ha+OIII only. Not real SHO
    (no SII). Ha -> gold (R+G), OIII -> teal (G+B)."""
    ha, oiii = extract_channels(img)
    r = ha
    g = np.clip(0.5 * ha + 0.5 * oiii, 0.0, 1.0)
    b = oiii
    return _image_like((r, g, b), img)


_PALETTE_FNS = {"HOO": hoo, "pseudo_SHO": pseudo_sho}


def apply_palette(img: AstroImage, name: str) -> AstroImage:
    if name not in _PALETTE_FNS:
        raise ValueError(f"unknown palette: {name}")
    return _PALETTE_FNS[name](img)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `.venv/bin/pytest tests/core/test_palette.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/core/palette.py tests/core/test_palette.py
git commit -m "feat: narrowband palette core (HOO + pseudo-SHO from Ha/OIII)"
```

---

## Task 2: `load_master` — read a FITS/TIFF master back to AstroImage

**Files:**
- Modify: `seestar_processor/core/fits_io.py`
- Test: `tests/core/test_load_master.py`

**Interfaces:**
- Consumes: existing `load_fits`, `core.export.save_tiff`/`save_fits` (tests), `AstroImage`, `tifffile`.
- Produces: `load_master(path: str) -> AstroImage` — FITS via `load_fits`; `.tif/.tiff` via tifffile (normalized to [0,1]); `ValueError` on unsupported extension.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_load_master.py`:

```python
import numpy as np
import pytest
from seestar_processor.core.image import AstroImage
from seestar_processor.core.export import save_tiff, save_fits
from seestar_processor.core.fits_io import load_master


def _color():
    return AstroImage((np.random.rand(6, 8, 3)).astype(np.float32), is_linear=True)


def test_load_master_tiff_roundtrip(tmp_path):
    p = tmp_path / "m.tiff"
    save_tiff(_color(), str(p))
    img = load_master(str(p))
    assert img.data.shape == (6, 8, 3)
    assert img.data.max() <= 1.0 + 1e-6


def test_load_master_fits_roundtrip(tmp_path):
    p = tmp_path / "m.fits"
    save_fits(_color(), str(p))
    img = load_master(str(p))
    assert img.data.shape == (6, 8, 3)


def test_load_master_unsupported_extension(tmp_path):
    p = tmp_path / "m.jpg"
    p.write_text("x")
    with pytest.raises(ValueError):
        load_master(str(p))
```

- [ ] **Step 2: Run it, expect failure**

Run: `.venv/bin/pytest tests/core/test_load_master.py -q`
Expected: FAIL (`cannot import name 'load_master'`).

- [ ] **Step 3: Implement**

In `seestar_processor/core/fits_io.py`, add `import os` and `import tifffile` at the top with the other imports, then append this function at the end of the file:

```python
def load_master(path: str) -> AstroImage:
    """Load a processed master back to a linear AstroImage. Supports the formats
    the app writes: FITS (via load_fits) and 16-bit TIFF (via tifffile)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".fits", ".fit", ".fts"):
        return load_fits(path)
    if ext in (".tif", ".tiff"):
        arr = np.asarray(tifffile.imread(path)).astype(np.float32)
        peak = float(arr.max())
        if peak > 0:
            arr = arr / peak
        h, w = arr.shape[:2]
        return AstroImage(np.clip(arr, 0.0, 1.0), is_linear=True,
                          metadata={"width": w, "height": h})
    raise ValueError(f"unsupported input format: {ext}")
```

- [ ] **Step 4: Run tests, expect pass**

Run: `.venv/bin/pytest tests/core/test_load_master.py tests/ -k "fits or export" -q`
Expected: PASS (existing fits_io/export tests unaffected).

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/core/fits_io.py tests/core/test_load_master.py
git commit -m "feat: load_master reads FITS/TIFF masters back to AstroImage"
```

---

## Task 3: `ui/palette_dialog.py` + toolbar "Palette…" action

**Files:**
- Create: `seestar_processor/ui/palette_dialog.py`
- Modify: `seestar_processor/ui/main_window.py` (toolbar action + `_open_palette`)
- Test: `tests/ui/test_palette_dialog.py`

**Interfaces:**
- Consumes: `core.palette.apply_palette`, `core.fits_io.load_master`, `core.export.save_tiff/save_png/save_fits`, `MainWindow.open_image`.
- Produces:
  - `class PaletteDialog(QDialog)` with `__init__(self, settings, parent=None, on_master=None)`, injectable `_palette_runner = apply_palette` and `_loader = load_master`, method `run()`.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_palette_dialog.py`:

```python
import numpy as np
import pytest

pytest.importorskip("PySide6")
from seestar_processor.settings import Settings  # noqa: E402
from seestar_processor.core.image import AstroImage  # noqa: E402
from seestar_processor.ui.palette_dialog import PaletteDialog  # noqa: E402


def test_palette_dialog_applies_writes_and_hands_off(qtbot, tmp_path):
    (tmp_path / "in.fits").write_text("placeholder")  # loader is faked below
    handed, captured = {}, {}
    dlg = PaletteDialog(Settings(), on_master=lambda img: handed.setdefault("img", img))
    qtbot.addWidget(dlg)
    dlg._loader = lambda path: AstroImage(
        np.random.rand(4, 5, 3).astype(np.float32), is_linear=False)

    def fake_runner(img, name):
        captured["name"] = name
        return img

    dlg._palette_runner = fake_runner
    dlg.input_edit.setText(str(tmp_path / "in.fits"))
    out = tmp_path / "out.tiff"
    dlg.output_edit.setText(str(out))
    dlg.hoo_radio.setChecked(True)
    dlg.open_check.setChecked(True)
    dlg.run()
    assert captured["name"] == "HOO"
    assert out.exists()                 # file written via save_tiff
    assert "img" in handed              # editor handoff called


def test_pseudo_sho_selected_passes_pseudo_name(qtbot, tmp_path):
    (tmp_path / "in.fits").write_text("x")
    captured = {}
    dlg = PaletteDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._loader = lambda path: AstroImage(np.zeros((4, 5, 3), np.float32))
    dlg._palette_runner = lambda img, name: captured.setdefault("name", name) or img
    dlg.input_edit.setText(str(tmp_path / "in.fits"))
    dlg.output_edit.setText(str(tmp_path / "out.tiff"))
    dlg.sho_radio.setChecked(True)
    dlg.run()
    assert captured["name"] == "pseudo_SHO"


def test_palette_dialog_requires_paths(qtbot):
    dlg = PaletteDialog(Settings())
    qtbot.addWidget(dlg)
    dlg.run()
    assert "pick" in dlg.status.text().lower()
```

- [ ] **Step 2: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_palette_dialog.py -q`
Expected: FAIL (module `seestar_processor.ui.palette_dialog` not found).

- [ ] **Step 3: Implement the dialog**

Create `seestar_processor/ui/palette_dialog.py`:

```python
from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from ..core.export import save_fits, save_png, save_tiff
from ..core.fits_io import load_master
from ..core.palette import apply_palette

_EXPORTERS = {
    ".tiff": save_tiff, ".tif": save_tiff, ".png": save_png,
    ".fits": save_fits, ".fit": save_fits, ".fts": save_fits,
}


def _picker_row(edit: QLineEdit, on_browse) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(edit)
    btn = QPushButton("Browse…")
    btn.clicked.connect(on_browse)
    lay.addWidget(btn)
    return row


class PaletteDialog(QDialog):
    def __init__(self, settings, parent=None, on_master=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Narrowband palette")
        self.setMinimumWidth(500)
        self._settings = settings
        self._on_master = on_master
        self._palette_runner = apply_palette   # injectable for tests
        self._loader = load_master             # injectable for tests

        self.input_edit = QLineEdit()
        self.output_edit = QLineEdit()
        self.hoo_radio = QRadioButton("HOO — honest duo-band (Ha/OIII)")
        self.sho_radio = QRadioButton("Pseudo-SHO — SHO look from Ha+OIII only (no real SII)")
        self.hoo_radio.setChecked(True)
        self.open_check = QCheckBox("Open result in the editor")
        self.open_check.setChecked(True)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.hoo_radio.toggled.connect(self._suggest_output)

        form = QFormLayout()
        form.addRow("Master image", _picker_row(self.input_edit, self._browse_input))
        palettes = QVBoxLayout()
        palettes.addWidget(self.hoo_radio)
        palettes.addWidget(self.sho_radio)
        pal_wrap = QWidget()
        pal_wrap.setLayout(palettes)
        form.addRow("Palette", pal_wrap)
        form.addRow("Output", _picker_row(self.output_edit, self._browse_output))
        form.addRow("", self.open_check)

        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self.run)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(apply_btn)
        buttons.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.status)
        root.addLayout(buttons)

    # --- browse ---
    def _browse_input(self) -> None:
        path = QFileDialog.getOpenFileName(
            self, "Master image", "", "Masters (*.fits *.fit *.fts *.tif *.tiff)")[0]
        if path:
            self.input_edit.setText(path)
            self._suggest_output()

    def _browse_output(self) -> None:
        path = QFileDialog.getSaveFileName(
            self, "Output", "", "Image (*.tiff *.fits *.png)")[0]
        if path:
            self.output_edit.setText(path)

    def _suggest_output(self) -> None:
        inp = self.input_edit.text().strip()
        if not inp:
            return
        stem, ext = os.path.splitext(inp)
        if ext.lower() not in _EXPORTERS:
            ext = ".tiff"
        tag = "HOO" if self.hoo_radio.isChecked() else "SHO"
        self.output_edit.setText(f"{stem}_{tag}{ext}")

    # --- run (synchronous — palette math is fast) ---
    def run(self) -> None:
        inp = self.input_edit.text().strip()
        out = self.output_edit.text().strip()
        if not inp or not out:
            self.status.setText("Pick an input master and an output path.")
            return
        name = "HOO" if self.hoo_radio.isChecked() else "pseudo_SHO"
        exporter = _EXPORTERS.get(os.path.splitext(out)[1].lower())
        if exporter is None:
            self.status.setText("Unsupported output format (use .tiff, .fits or .png).")
            return
        try:
            result = self._palette_runner(self._loader(inp), name)
            exporter(result, out)
        except Exception as exc:
            self.status.setText(f"Failed: {exc}")
            return
        self.status.setText(f"Wrote {os.path.basename(out)}.")
        if self.open_check.isChecked() and self._on_master is not None:
            self._on_master(result)
        self.accept()
```

- [ ] **Step 4: Wire the toolbar action**

In `seestar_processor/ui/main_window.py`, add the toolbar action next to "Stack…" (after the `tb.addAction("Stack…", self._open_stack)` line):

```python
        tb.addAction("Palette…", self._open_palette)
```

And add the method next to `_open_stack`:

```python
    def _open_palette(self) -> None:
        from .palette_dialog import PaletteDialog
        PaletteDialog(self.settings, self,
                      on_master=lambda img: self.open_image(img, "palette")).exec()
```

- [ ] **Step 5: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_palette_dialog.py tests/ui/test_main_window.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add seestar_processor/ui/palette_dialog.py seestar_processor/ui/main_window.py tests/ui/test_palette_dialog.py
git commit -m "feat: Palette dialog + toolbar action (HOO / pseudo-SHO, file in/out)"
```

---

## Task 4: Full-suite check + backlog update

**Files:**
- Modify: `TODO.md`

- [ ] **Step 1: Run the whole suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all tests pass (existing 228 + new palette tests).

- [ ] **Step 2: Headless end-to-end smoke**

```bash
.venv/bin/python -c "
import numpy as np, tempfile, os
from seestar_processor.core.image import AstroImage
from seestar_processor.core.export import save_tiff
from seestar_processor.core.fits_io import load_master
from seestar_processor.core.palette import apply_palette
d = tempfile.mkdtemp()
save_tiff(AstroImage((np.random.rand(20, 20, 3)).astype('float32')), os.path.join(d, 'm.tiff'))
for name in ('HOO', 'pseudo_SHO'):
    out = apply_palette(load_master(os.path.join(d, 'm.tiff')), name)
    print(name, out.data.shape, round(float(out.data.max()), 3))
"
```
Expected: prints `HOO (20, 20, 3) ...` and `pseudo_SHO (20, 20, 3) ...` with maxima ≤ 1.0.

- [ ] **Step 3: Update the backlog**

In `TODO.md`, replace the open SHO bullet with a done entry:

```markdown
- [x] **Narrowband palette (HOO / pseudo-SHO).** Standalone "Palette…" tool: read a
      stacked duo-band master (FITS/TIFF), extract Ha (=R) and OIII (=G+B), remap to HOO or
      pseudo-SHO, write a file and optionally load it into the editor. `core/palette.py` +
      `ui/palette_dialog.py`. Pseudo-SHO is honestly labeled (no SII on a duo-band OSC).
```

- [ ] **Step 4: Commit**

```bash
git add TODO.md
git commit -m "docs: mark narrowband palette done in backlog"
```

---

## Definition of Done

- All tasks committed on `narrowband-palette`; full suite green.
- "Palette…" appears on the toolbar; picking a master + palette writes a remapped file and
  (optionally) loads it into the editor.
- Feature is isolated: removing `core/palette.py`, `load_master`, `ui/palette_dialog.py`,
  and the toolbar action leaves the rest working.
- After merge: validate HOO and pseudo-SHO **by eye on the real Pelican (IC 5070) master**,
  tuning the pseudo-SHO coefficients if needed.
- Finish with **superpowers:finishing-a-development-branch**.
