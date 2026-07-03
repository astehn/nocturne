# Ha/OIII Extraction (Duo-band Stacking) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lights-only "Ha/OIII Extract…" tool that splits raw CFA subs into Ha and OIII planes, stacks each channel separately (sharing the Ha registration), renormalizes OIII to Ha, and produces a combined RGB master for the editor/Palette.

**Architecture:** A Qt-free `stacking/haoiii.py` (CFA plane extraction, MAD renorm, extract orchestrator) + a `ui/haoiii_dialog.py` mirroring the Stack dialog. Reuses the existing register/integrate/coverage/grade modules and the editor handoff.

**Tech Stack:** Python 3.11+, numpy, astropy, scikit-image, astroalign, PySide6.

## Global Constraints

- Package is `seestar_processor` (do NOT rename). Use the venv (`.venv/bin/python`, `.venv/bin/pytest`); system python is 3.9 and fails.
- UI tests run headless: prefix with `QT_QPA_PLATFORM=offscreen`.
- `stacking/` core stays Qt-free.
- CFA input is raw 2D mono; a 3D/debayered sub must be rejected with "needs raw (un-debayered) subs".
- Bayer pattern from each file's `BAYERPAT` header via `core.fits_io._bayer_pattern` (Seestar = GRBG), instrument default fallback.
- Frames loaded raw (no per-frame normalization); the combined master is normalized once at the end.
- Output combined master: `R = Ha`, `G = OIII'`, `B = OIII'` (so Palette recovers Ha=R, OIII=(G+B)/2).
- OIII renorm (from the Siril script): `a = mad(Ha)/mad(OIII)`, `OIII' = a*(OIII - median(OIII)) + median(Ha)`.
- Commit after each task. Create the `haoiii-extract` branch first (do not start on `main`).

---

## File Structure

- `seestar_processor/stacking/haoiii.py` — `load_cfa`, `_site_offsets`, `extract_cfa_planes`, `renorm_oiii`, `HaOIIIOptions`, `HaOIIIResult`, `run_haoiii_extract`.
- `seestar_processor/ui/haoiii_dialog.py` — the dialog.
- `seestar_processor/ui/main_window.py` — toolbar action + `_open_haoiii`.
- `tests/stacking/synthetic.py` — add `write_cfa_fits` helper.
- Tests: `tests/stacking/test_haoiii.py`, `tests/ui/test_haoiii_dialog.py`.

---

## Task 0: Branch setup

- [ ] **Step 1: Create the feature branch**

```bash
cd /Volumes/Work/Code/Editor
git checkout -b haoiii-extract
git status   # expect: On branch haoiii-extract, clean
```

---

## Task 1: `haoiii.py` — CFA extraction + renorm (pure functions)

**Files:**
- Create: `seestar_processor/stacking/haoiii.py`
- Modify: `tests/stacking/synthetic.py` (add `write_cfa_fits`)
- Test: `tests/stacking/test_haoiii.py`

**Interfaces:**
- Consumes: `core.fits_io._bayer_pattern`, `skimage.transform.resize`, `astropy.io.fits`.
- Produces:
  - `load_cfa(path) -> tuple[np.ndarray, str, float]` — (2D float32 CFA, pattern, exptime); raises `ValueError` on non-2D.
  - `_site_offsets(pattern) -> dict` — color → list of (row, col) in the 2×2 tile.
  - `extract_cfa_planes(cfa, pattern) -> tuple[np.ndarray, np.ndarray]` — (ha, oiii) full-res float32.
  - `renorm_oiii(ha, oiii) -> np.ndarray`.

- [ ] **Step 1: Add the synthetic CFA writer**

In `tests/stacking/synthetic.py`, add:

```python
def write_cfa_fits(path, base, exptime=10.0):
    """Write a 2D GRBG mono CFA FITS from a full-res `base` (H, W) star field.
    GRBG tile: G R / B R? no -> G R (row0), B G (row1). Strong signal on the RED
    sites so extracted Ha carries the stars; weaker green/blue."""
    import numpy as np
    from astropy.io import fits
    h, w = base.shape
    cfa = np.zeros((h, w), np.float32)
    cfa[0::2, 1::2] = base[0::2, 1::2]          # R (Ha)
    cfa[0::2, 0::2] = base[0::2, 0::2] * 0.3    # G
    cfa[1::2, 1::2] = base[1::2, 1::2] * 0.3    # G
    cfa[1::2, 0::2] = base[1::2, 0::2] * 0.2    # B
    hdu = fits.PrimaryHDU((cfa * 1000).astype(np.uint16))
    hdu.header["BAYERPAT"] = "GRBG"
    hdu.header["EXPTIME"] = exptime
    hdu.writeto(str(path), overwrite=True)
```

- [ ] **Step 2: Write the failing test**

Create `tests/stacking/test_haoiii.py`:

```python
import numpy as np
import pytest
from astropy.io import fits
from seestar_processor.stacking.haoiii import (
    load_cfa, extract_cfa_planes, renorm_oiii, _site_offsets,
)
from tests.stacking.synthetic import make_star_field, write_cfa_fits


def test_site_offsets_grbg():
    off = _site_offsets("GRBG")   # G R / B G
    assert off["R"] == [(0, 1)]
    assert off["B"] == [(1, 0)]
    assert sorted(off["G"]) == [(0, 0), (1, 1)]


def test_extract_cfa_planes_known_values():
    # constant sites: R=0.8, G=0.4, B=0.2 on an 8x8 GRBG frame
    cfa = np.zeros((8, 8), np.float32)
    cfa[0::2, 1::2] = 0.8   # R
    cfa[0::2, 0::2] = 0.4   # G
    cfa[1::2, 1::2] = 0.4   # G
    cfa[1::2, 0::2] = 0.2   # B
    ha, oiii = extract_cfa_planes(cfa, "GRBG")
    assert ha.shape == (8, 8) and oiii.shape == (8, 8)
    assert np.allclose(ha, 0.8, atol=1e-4)              # Ha = red
    assert np.allclose(oiii, 0.3, atol=1e-4)            # OIII = (G+B)/2 = 0.3


def test_extract_cfa_planes_rejects_3d():
    with pytest.raises(ValueError):
        extract_cfa_planes(np.zeros((4, 4, 3), np.float32), "GRBG")


def test_load_cfa_reads_2d_and_pattern(tmp_path):
    p = tmp_path / "s.fit"
    write_cfa_fits(p, make_star_field(shape=(40, 40), n_stars=20, seed=1))
    cfa, pattern, exp = load_cfa(str(p))
    assert cfa.ndim == 2 and pattern == "GRBG" and exp == 10.0


def test_load_cfa_rejects_3d(tmp_path):
    p = tmp_path / "color.fits"
    fits.PrimaryHDU(np.zeros((3, 8, 8), np.float32)).writeto(str(p))
    with pytest.raises(ValueError):
        load_cfa(str(p))


def test_renorm_oiii_matches_median_and_mad():
    ha = np.array([1.0, 2.0, 3.0, 4.0], np.float32)
    oiii = ha * 0.5 + 10.0                    # scaled + offset copy
    out = renorm_oiii(ha, oiii)
    assert np.isclose(np.median(out), np.median(ha), atol=1e-4)
    def mad(x): return np.median(np.abs(x - np.median(x)))
    assert np.isclose(mad(out), mad(ha), atol=1e-4)
```

- [ ] **Step 3: Run it, expect failure**

Run: `.venv/bin/pytest tests/stacking/test_haoiii.py -q`
Expected: FAIL (module `seestar_processor.stacking.haoiii` not found).

- [ ] **Step 4: Implement**

Create `seestar_processor/stacking/haoiii.py`:

```python
from __future__ import annotations

import numpy as np
from astropy.io import fits
from skimage.transform import resize

from ..core.fits_io import _bayer_pattern


def load_cfa(path: str) -> tuple:
    """Load a raw 2D CFA sub: (cfa float32, pattern, exptime). Raises ValueError
    for a 3D/already-debayered file."""
    with fits.open(path) as hdul:
        data = np.asarray(hdul[0].data)
        header = hdul[0].header
    if data.ndim != 2:
        raise ValueError("Ha/OIII extraction needs raw (un-debayered) subs")
    exp = float(header.get("EXPTIME", 0.0) or 0.0)
    return data.astype(np.float32), _bayer_pattern(header), exp


def _site_offsets(pattern: str) -> dict:
    """Map each colour to its (row, col) offsets within the 2x2 CFA tile."""
    offsets: dict = {"R": [], "G": [], "B": []}
    for i, ch in enumerate(pattern.upper()):
        offsets[ch].append((i // 2, i % 2))
    return offsets


def _plane(cfa: np.ndarray, sites: list) -> np.ndarray:
    """Mean of the half-res sub-planes at the given (row, col) site offsets."""
    parts = [cfa[r::2, c::2] for r, c in sites]
    return np.mean(parts, axis=0).astype(np.float32)


def extract_cfa_planes(cfa: np.ndarray, pattern: str) -> tuple:
    """(ha, oiii) full-res float32. Ha = red sites; OIII = (green + blue)/2.
    Half-res planes are bilinearly upscaled to the CFA's full (H, W)."""
    if cfa.ndim != 2:
        raise ValueError("extract_cfa_planes needs a 2D CFA frame")
    off = _site_offsets(pattern)
    red = _plane(cfa, off["R"])
    green = _plane(cfa, off["G"])
    blue = _plane(cfa, off["B"])
    oiii_half = (green + blue) / 2.0
    shape = cfa.shape
    ha = resize(red, shape, order=1, preserve_range=True, anti_aliasing=False).astype(np.float32)
    oiii = resize(oiii_half, shape, order=1, preserve_range=True,
                  anti_aliasing=False).astype(np.float32)
    return ha, oiii


def _mad(x: np.ndarray) -> float:
    return float(np.median(np.abs(x - np.median(x))))


def renorm_oiii(ha: np.ndarray, oiii: np.ndarray) -> np.ndarray:
    """Linear-fit OIII to Ha (Siril ExtractHaOIII): match median and MAD."""
    mad_o = _mad(oiii)
    a = (_mad(ha) / mad_o) if mad_o > 1e-9 else 1.0
    out = a * (oiii - np.median(oiii)) + np.median(ha)
    return np.clip(out, 0.0, None).astype(np.float32)
```

- [ ] **Step 5: Run tests, expect pass**

Run: `.venv/bin/pytest tests/stacking/test_haoiii.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add seestar_processor/stacking/haoiii.py tests/stacking/synthetic.py tests/stacking/test_haoiii.py
git commit -m "feat: CFA Ha/OIII plane extraction + MAD renorm"
```

---

## Task 2: `haoiii.py` — the extract orchestrator

**Files:**
- Modify: `seestar_processor/stacking/haoiii.py`
- Test: `tests/stacking/test_haoiii.py`

**Interfaces:**
- Consumes: `load_cfa`, `extract_cfa_planes`, `renorm_oiii` (Task 1); `register.find_transform/warp_to/RegistrationError`; `integrate.average_integrate/sigma_clip_integrate`; `coverage.coverage_map/full_coverage_bounds`; `core.export.save_fits`; `AstroImage`.
- Produces:
  - `@dataclass HaOIIIOptions(method, kappa, include, output_path)` — include best-first, `include[0]` is the reference.
  - `@dataclass HaOIIIResult(image, used, rejected, frame_count, integration_seconds, output_path)`
  - `run_haoiii_extract(opts, *, on_progress=None) -> HaOIIIResult`.

- [ ] **Step 1: Write the failing test**

Add to `tests/stacking/test_haoiii.py`:

```python
def _cfa_subs(tmp_path, n=4, seed=2):
    from skimage.transform import SimilarityTransform, warp
    base = make_star_field(shape=(120, 120), n_stars=60, seed=seed)
    paths = []
    for i in range(n):
        t = SimilarityTransform(translation=(i * 0.5, -i * 0.5))
        f = warp(base, t.inverse, order=1, preserve_range=True).astype(np.float32)
        p = tmp_path / f"s{i}.fit"
        write_cfa_fits(p, f, exptime=10.0)
        paths.append(str(p))
    return paths


def test_run_haoiii_extract_produces_combined_master(tmp_path):
    from seestar_processor.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    import os
    paths = _cfa_subs(tmp_path)
    out = tmp_path / "HaOIII_master.fits"
    result = run_haoiii_extract(HaOIIIOptions("average", 2.5, paths, str(out)))
    assert result.image.is_linear and result.image.data.ndim == 3
    assert result.frame_count == 4
    assert result.integration_seconds == 40.0
    # OIII packed into G and B -> those channels are identical
    g, b = result.image.data[..., 1], result.image.data[..., 2]
    assert np.allclose(g, b, atol=1e-6)
    assert os.path.exists(result.output_path)


def test_run_haoiii_extract_rejects_non_cfa(tmp_path):
    from seestar_processor.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _cfa_subs(tmp_path)
    bad = tmp_path / "color.fits"
    fits.PrimaryHDU(np.zeros((3, 120, 120), np.float32)).writeto(str(bad))
    result = run_haoiii_extract(
        HaOIIIOptions("average", 2.5, paths + [str(bad)], str(tmp_path / "m.fits")))
    assert any(str(bad) == p for p, _ in result.rejected)
    assert result.frame_count == 4


def test_run_haoiii_extract_too_few(tmp_path):
    from seestar_processor.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _cfa_subs(tmp_path, n=2)
    with pytest.raises(ValueError):
        run_haoiii_extract(HaOIIIOptions("average", 2.5, paths, str(tmp_path / "m.fits")))
```

- [ ] **Step 2: Run it, expect failure**

Run: `.venv/bin/pytest tests/stacking/test_haoiii.py -q`
Expected: FAIL (`cannot import name 'HaOIIIOptions'`).

- [ ] **Step 3: Implement**

Append to `seestar_processor/stacking/haoiii.py` (add the imports at the top with the others):

```python
from dataclasses import dataclass

from ..core.export import save_fits
from ..core.image import AstroImage
from .coverage import coverage_map, full_coverage_bounds
from .integrate import average_integrate, sigma_clip_integrate
from .register import RegistrationError, find_transform, warp_to


@dataclass
class HaOIIIOptions:
    method: str          # "sigma_clip" | "average"
    kappa: float
    include: list        # sub paths, best-first; include[0] is the reference
    output_path: str


@dataclass
class HaOIIIResult:
    image: AstroImage
    used: list
    rejected: list
    frame_count: int
    integration_seconds: float
    output_path: str


def run_haoiii_extract(opts: HaOIIIOptions, *, on_progress=None) -> HaOIIIResult:
    paths = list(opts.include)
    if len(paths) < 3:
        raise ValueError("need at least 3 frames to extract")

    ref_path = paths[0]
    ref_cfa, ref_pat, ref_exp = load_cfa(ref_path)
    ref_ha, _ = extract_cfa_planes(ref_cfa, ref_pat)
    ref_shape = ref_cfa.shape

    transforms = {ref_path: np.eye(3)}
    exposures = {ref_path: ref_exp}
    used = [ref_path]
    rejected: list = []
    n = len(paths)

    # Phase A: register each remaining sub on its Ha plane.
    for i, path in enumerate(paths[1:], start=1):
        try:
            cfa, pat, exp = load_cfa(path)
        except Exception as exc:  # noqa: BLE001
            rejected.append((path, f"unreadable or not raw CFA: {exc}"))
            continue
        if cfa.shape != ref_shape:
            rejected.append((path, "dimension mismatch"))
            continue
        try:
            ha, _ = extract_cfa_planes(cfa, pat)
            matrix = find_transform(ha, ref_ha)
        except RegistrationError as exc:
            rejected.append((path, f"registration failed: {exc}"))
            continue
        transforms[path] = matrix
        exposures[path] = exp
        used.append(path)
        if on_progress is not None:
            on_progress(i, n, "registering")

    if len(used) < 3:
        raise ValueError("not enough frames could be registered (need at least 3)")

    total = len(used)

    def _channel_frames(which: str, label: str):
        def gen():
            for i, path in enumerate(used, start=1):
                cfa, pat, _ = load_cfa(path)
                ha, oiii = extract_cfa_planes(cfa, pat)
                plane = ha if which == "ha" else oiii
                if on_progress is not None:
                    on_progress(i, total, label)
                yield warp_to(plane, transforms[path])
        return gen

    ha_frames = _channel_frames("ha", "stacking Ha")
    oiii_frames = _channel_frames("oiii", "stacking OIII")
    if opts.method == "sigma_clip":
        ha_master = sigma_clip_integrate(ha_frames, opts.kappa)
        oiii_master = sigma_clip_integrate(oiii_frames, opts.kappa)
    else:
        ha_master = average_integrate(ha_frames())
        oiii_master = average_integrate(oiii_frames())

    # Coverage crop (Ha transforms), then renorm OIII to Ha and pack RGB.
    coverage = coverage_map([transforms[p] for p in used], ref_shape)
    top, bottom, left, right = full_coverage_bounds(coverage, len(used))
    ha_master = ha_master[top:bottom, left:right]
    oiii_master = oiii_master[top:bottom, left:right]
    oiii_master = renorm_oiii(ha_master, oiii_master)

    rgb = np.stack([ha_master, oiii_master, oiii_master], axis=2).astype(np.float32)
    peak = float(rgb.max())
    if peak > 0:
        rgb = rgb / peak
    integ = sum(exposures[p] for p in used)
    ch, cw = rgb.shape[:2]
    image = AstroImage(
        np.clip(rgb, 0.0, 1.0).astype(np.float32),
        is_linear=True,
        metadata={"frames": len(used), "exposure": integ, "width": cw, "height": ch},
    )
    save_fits(image, opts.output_path,
              header={"NSUBS": len(used), "STACKCNT": len(used), "EXPTIME": integ})
    return HaOIIIResult(image, used, rejected, len(used), integ, opts.output_path)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `.venv/bin/pytest tests/stacking/test_haoiii.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/stacking/haoiii.py tests/stacking/test_haoiii.py
git commit -m "feat: Ha/OIII extract orchestrator (shared-transform, separate stacks, renorm)"
```

---

## Task 3: `ui/haoiii_dialog.py` + toolbar + suite + backlog

**Files:**
- Create: `seestar_processor/ui/haoiii_dialog.py`
- Modify: `seestar_processor/ui/main_window.py` (toolbar action + `_open_haoiii`)
- Modify: `TODO.md`
- Test: `tests/ui/test_haoiii_dialog.py`

**Interfaces:**
- Consumes: `stacking.frames.discover_subs`, `stacking.grade.grade_frames`/`FrameStats`, `stacking.haoiii.run_haoiii_extract`/`HaOIIIOptions`, `ui.worker.run_async`, `MainWindow.open_image`.
- Produces: `class HaOIIIDialog(QDialog)` with `__init__(self, settings, parent=None, on_master=None)`, injectable `_grade_runner = grade_frames` and `_extract_runner = run_haoiii_extract`, `KAPPA` dict, `grade()`, `run()`; dialog attrs `folder_edit`, `output_edit`, `table`, `avg_radio`, `sigma_radio`, `kappa_box`, `progress`, `status`, `_stats`, `_busy`, `_stack_btn` (Extract button).

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_haoiii_dialog.py`:

```python
import pytest

pytest.importorskip("PySide6")
from seestar_processor.settings import Settings  # noqa: E402
from seestar_processor.stacking.grade import FrameStats  # noqa: E402
from seestar_processor.ui.haoiii_dialog import HaOIIIDialog  # noqa: E402


def _stats(path, score, included=True):
    return FrameStats(path, 100, 3.0, 0.02, score, included)


def test_grading_fills_table(qtbot, tmp_path):
    (tmp_path / "a.fit").write_text("x")
    (tmp_path / "b.fit").write_text("x")
    dlg = HaOIIIDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None: [
        _stats(str(tmp_path / "a.fit"), 0.4, included=False),
        _stats(str(tmp_path / "b.fit"), 0.9, included=True),
    ]
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 2, timeout=2000)


def test_extract_hands_off_master(qtbot, tmp_path):
    for name in ("low.fit", "mid.fit", "high.fit"):
        (tmp_path / name).write_text("x")
    low, mid, high = (str(tmp_path / n) for n in ("low.fit", "mid.fit", "high.fit"))
    captured, got = {}, {}
    dlg = HaOIIIDialog(Settings(), on_master=lambda img: got.setdefault("img", img))
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None: [
        _stats(low, 0.4), _stats(mid, 0.6), _stats(high, 0.9)]

    class _Img:
        pass

    def fake_extract(opts, on_progress=None):
        captured["opts"] = opts
        if on_progress:
            on_progress(1, 1, "stacking Ha")
        from seestar_processor.stacking.haoiii import HaOIIIResult
        return HaOIIIResult(_Img(), opts.include, [], len(opts.include), 30.0, opts.output_path)

    dlg._extract_runner = fake_extract
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 3, timeout=2000)
    dlg.output_edit.setText(str(tmp_path / "HaOIII_master.fits"))
    dlg.run()
    qtbot.waitUntil(lambda: "opts" in captured, timeout=2000)
    assert captured["opts"].include[0] == high      # best-first
    qtbot.waitUntil(lambda: "img" in got, timeout=2000)


def test_run_requires_output(qtbot):
    dlg = HaOIIIDialog(Settings())
    qtbot.addWidget(dlg)
    dlg.run()
    assert "output" in dlg.status.text().lower()
```

- [ ] **Step 2: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_haoiii_dialog.py -q`
Expected: FAIL (module `seestar_processor.ui.haoiii_dialog` not found).

- [ ] **Step 3: Implement the dialog**

Create `seestar_processor/ui/haoiii_dialog.py`:

```python
from __future__ import annotations

import glob
import os

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..stacking.grade import grade_frames
from ..stacking.haoiii import HaOIIIOptions, run_haoiii_extract
from .worker import run_async

KAPPA = {"Low": 3.0, "Medium": 2.5, "High": 2.0}


class _Signals(QObject):
    progress = Signal(int, int, str)


def _picker_row(edit: QLineEdit, on_browse) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(edit)
    btn = QPushButton("Browse…")
    btn.clicked.connect(on_browse)
    lay.addWidget(btn)
    return row


class HaOIIIDialog(QDialog):
    def __init__(self, settings, parent=None, on_master=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ha/OIII extract")
        self.setMinimumWidth(560)
        self._settings = settings
        self._on_master = on_master
        self._grade_runner = grade_frames       # injectable for tests
        self._extract_runner = run_haoiii_extract  # injectable for tests
        self._stats = []
        self._busy = False
        self._pool = QThreadPool.globalInstance()
        self._signals = _Signals()
        self._signals.progress.connect(self._on_progress)

        self.folder_edit = QLineEdit()
        self.output_edit = QLineEdit()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Use", "File", "Stars", "FWHM", "Bg"])
        self.avg_radio = QRadioButton("Average")
        self.sigma_radio = QRadioButton("Sigma-clipped")
        self.sigma_radio.setChecked(True)
        self.kappa_box = QComboBox()
        self.kappa_box.addItems(list(KAPPA.keys()))
        self.kappa_box.setCurrentText("Medium")
        self.progress = QProgressBar()
        self.status = QLabel("")
        self.status.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Folder of raw subs", _picker_row(self.folder_edit, self._browse_folder))
        method_row = QHBoxLayout()
        method_row.addWidget(self.avg_radio)
        method_row.addWidget(self.sigma_radio)
        method_row.addWidget(QLabel("κ:"))
        method_row.addWidget(self.kappa_box)
        method_row.addStretch(1)
        method_wrap = QWidget()
        method_wrap.setLayout(method_row)
        form.addRow("Integration", method_wrap)
        form.addRow("Output", _picker_row(self.output_edit, self._browse_output))

        self._stack_btn = QPushButton("Extract")
        self._stack_btn.setObjectName("primary")
        self._stack_btn.clicked.connect(self.run)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self._stack_btn)
        buttons.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.table)
        root.addWidget(self.progress)
        root.addWidget(self.status)
        root.addLayout(buttons)

    # --- browse ---
    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder of raw subs")
        if path:
            self.folder_edit.setText(path)
            if not self.output_edit.text().strip():
                self.output_edit.setText(os.path.join(path, "HaOIII_master.fits"))
            self.grade()

    def _browse_output(self) -> None:
        path = QFileDialog.getSaveFileName(self, "Master FITS", "", "FITS (*.fits)")[0]
        if path:
            self.output_edit.setText(path)

    def _discover(self) -> list:
        folder = self.folder_edit.text().strip()
        files: list = []
        for pat in ("*.fit", "*.fits", "*.fts"):
            files.extend(glob.glob(os.path.join(folder, pat)))
        return sorted(files)

    # --- busy ---
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._stack_btn.setEnabled(not busy)

    # --- grade ---
    def grade(self) -> None:
        if self._busy:
            return
        paths = self._discover()
        if not paths:
            self.status.setText("No .fit subs found in that folder.")
            return
        self.status.setText("Grading frames…")
        self._set_busy(True)
        runner = self._grade_runner

        def work():
            return runner(paths, on_progress=lambda i, n, name:
                          self._signals.progress.emit(i, n, "grading"))

        run_async(self._pool, work, self._on_graded, self._on_error)

    def _on_graded(self, stats) -> None:
        self._set_busy(False)
        self._stats = stats
        self.table.setRowCount(len(stats))
        for row, s in enumerate(stats):
            check = QTableWidgetItem()
            check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked if s.included else Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, QTableWidgetItem(os.path.basename(s.path)))
            self.table.setItem(row, 2, QTableWidgetItem(str(s.star_count)))
            self.table.setItem(row, 3, QTableWidgetItem(f"{s.fwhm:.1f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{s.background:.3f}"))
        kept = sum(1 for s in stats if s.included)
        self.status.setText(f"Graded {len(stats)} frames — {kept} kept.")

    # --- run ---
    def _included_best_first(self) -> list:
        chosen = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked:
                chosen.append(self._stats[row])
        chosen.sort(key=lambda s: s.score, reverse=True)
        return [s.path for s in chosen]

    def run(self) -> None:
        if self._busy:
            self.status.setText("Please wait — still working…")
            return
        if not self.output_edit.text().strip():
            self.status.setText("Pick an output path.")
            return
        include = self._included_best_first()
        if len(include) < 3:
            self.status.setText("Select at least 3 frames to extract.")
            return
        method = "sigma_clip" if self.sigma_radio.isChecked() else "average"
        opts = HaOIIIOptions(method, KAPPA[self.kappa_box.currentText()],
                             include, self.output_edit.text().strip())
        runner = self._extract_runner
        self.status.setText("Extracting…")
        self._set_busy(True)

        def work():
            return runner(opts, on_progress=lambda i, n, label:
                          self._signals.progress.emit(i, n, label))

        run_async(self._pool, work, self._on_done, self._on_error)

    def _on_progress(self, i: int, n: int, label: str) -> None:
        self.progress.setMaximum(max(1, n))
        self.progress.setValue(i)
        self.status.setText(f"{label}… {i}/{n}")

    def _on_done(self, result) -> None:
        self._set_busy(False)
        self.status.setText(
            f"Done — {result.frame_count} frames, "
            f"{len(result.rejected)} rejected → {os.path.basename(result.output_path)}"
        )
        if self._on_master is not None:
            self._on_master(result.image)
        self.accept()

    def _on_error(self, exc) -> None:
        self._set_busy(False)
        self.status.setText(f"Failed: {exc}")
```

- [ ] **Step 4: Wire the toolbar action**

In `seestar_processor/ui/main_window.py`, add the toolbar action after the "Stack…" line (`tb.addAction("Stack…", self._open_stack)`):

```python
        tb.addAction("Ha/OIII…", self._open_haoiii)
```

And add the method next to `_open_stack`:

```python
    def _open_haoiii(self) -> None:
        try:
            from .haoiii_dialog import HaOIIIDialog
        except ImportError:
            self._status.setText("Ha/OIII extract unavailable — install astroalign and sep.")
            return
        HaOIIIDialog(self.settings, self,
                     on_master=lambda img: self.open_image(img, "Ha/OIII master")).exec()
```

- [ ] **Step 5: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_haoiii_dialog.py tests/ui/test_main_window.py -q`
Expected: PASS.

- [ ] **Step 6: Full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass. If `test_sharpen_changes_image_and_keeps_shape` fails, it's the known pre-existing flake — rerun it alone to confirm.

- [ ] **Step 7: Update the backlog**

In `TODO.md`, add under the stacking entry:

```markdown
- [x] **Ha/OIII duo-band extraction (lights-only).** Separate "Ha/OIII…" tool: grade raw subs,
      split each CFA sub into Ha (red sites) and OIII (green+blue) planes, register once on Ha
      and reuse the transform for OIII, stack each channel separately, MAD-renorm OIII to Ha,
      and produce a combined RGB master (Ha→R, OIII→G+B) for the editor/Palette.
      `stacking/haoiii.py` + `ui/haoiii_dialog.py`. Inspired by Siril's ExtractHaOIII, no calibration.
```

- [ ] **Step 8: Commit**

```bash
git add seestar_processor/ui/haoiii_dialog.py seestar_processor/ui/main_window.py tests/ui/test_haoiii_dialog.py TODO.md
git commit -m "feat: Ha/OIII Extract dialog + toolbar action + backlog"
```

---

## Definition of Done

- All tasks committed on `haoiii-extract`; full suite green.
- "Ha/OIII…" appears on the toolbar; picking a raw-subs folder grades them; Extract produces a
  combined master that loads into the editor and works with the Palette tool.
- Feature is isolated: removing `stacking/haoiii.py`, `ui/haoiii_dialog.py`, and the toolbar
  action leaves the rest working.
- After merge: validate on the real Pelican (IC 5070) raw subs — compare the duo-band-extracted
  master (via Palette) against the current debayer-then-extract path.
- Finish with **superpowers:finishing-a-development-branch**.
```
