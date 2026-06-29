# Seestar Processor v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable, native-feeling PySide6 desktop app that takes a ZWO Seestar S30 Pro stacked FITS through Load → Background extraction (GraXpert) → Stretch → Export, with a cached non-destructive history (undo/redo/jump-back, before/after).

**Architecture:** Layered Python package. `core/` holds the image model + numeric ops (FITS I/O, autostretch, real stretch, export). `history/` holds the step abstraction and the cached project history. `tools/` wraps external CLIs (GraXpert) behind a subprocess+temp-FITS adapter. `steps/` implements each flow step on top of core+tools. `ui/` (PySide6) renders previews and navigation and never does image math. Linear 32-bit float is the source of truth; autostretch is display-only until the real Stretch step.

**Tech Stack:** Python 3.11+, PySide6 (Qt), astropy (FITS), numpy, scipy, scikit-image, colour-demosaicing (Bayer→RGB), Pillow (TIFF/JPEG export), pytest + pytest-qt.

## Global Constraints

- Target instrument: ZWO Seestar S30 Pro = Sony **IMX585**, **3840×2160**, **2.9 µm** pixels, OSC RGGB Bayer, 150mm f/5, ~4″/px. Hardcode this profile; do not parse it per-image.
- All in-memory pixel data is **numpy `float32`**, range nominally [0, 1]. Color images are shape `(H, W, 3)`; mono images `(H, W)`.
- Linear data is the source of truth. `AstroImage.is_linear` starts `True`; only the Stretch step sets it `False`.
- GraXpert is **required**; RC-Astro path field exists in Settings but is **unused in v1**.
- CLI handoff uses temporary **32-bit float FITS** files in a per-op temp dir, always cleaned up.
- Python **3.11+**. Tests use `pytest`; GUI tests use `pytest-qt`.
- Package name: `seestar_processor`. Run via `python -m seestar_processor`.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `seestar_processor/__init__.py`
- Create: `seestar_processor/__main__.py` (placeholder)
- Create: `tests/__init__.py`
- Create: `.gitignore`

**Interfaces:**
- Produces: installable package `seestar_processor`; `pytest` runs green on an empty suite.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "seestar-processor"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "PySide6>=6.6",
    "astropy>=6.0",
    "numpy>=1.26",
    "scipy>=1.11",
    "scikit-image>=0.22",
    "colour-demosaicing>=0.2.5",
    "Pillow>=10.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-qt>=4.4"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create package files**

`seestar_processor/__init__.py`:
```python
__version__ = "0.1.0"
```

`seestar_processor/__main__.py`:
```python
def main() -> None:
    raise SystemExit("UI not yet implemented")


if __name__ == "__main__":
    main()
```

`tests/__init__.py`: empty file.

`.gitignore`:
```
__pycache__/
*.pyc
.venv/
*.egg-info/
.pytest_cache/
build/
dist/
```

- [ ] **Step 3: Create venv, install, verify pytest runs**

Run:
```bash
cd /Volumes/Work/Code/Editor
python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```
Expected: `no tests ran` (exit 0/5), install succeeds. (System `python3` is 3.9; use `python3.13` explicitly.)

- [ ] **Step 4: Initialize git and commit**

```bash
git init
git add -A
git commit -m "chore: scaffold seestar_processor package"
```

---

### Task 2: Instrument profile

**Files:**
- Create: `seestar_processor/core/__init__.py`
- Create: `seestar_processor/core/instrument.py`
- Test: `tests/core/test_instrument.py`

**Interfaces:**
- Produces: `SEESTAR_S30_PRO: Instrument` with fields `name: str`, `width: int`, `height: int`, `pixel_size_um: float`, `focal_length_mm: float`, `bayer_pattern: str`, `pixel_scale_arcsec: float`.

- [ ] **Step 1: Write the failing test**

`tests/core/test_instrument.py`:
```python
from seestar_processor.core.instrument import SEESTAR_S30_PRO


def test_seestar_s30_pro_profile():
    p = SEESTAR_S30_PRO
    assert p.width == 3840
    assert p.height == 2160
    assert p.pixel_size_um == 2.9
    assert p.focal_length_mm == 150.0
    assert p.bayer_pattern == "RGGB"
    assert round(p.pixel_scale_arcsec, 1) == 4.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/core/test_instrument.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

Create `tests/core/__init__.py` (empty).

`seestar_processor/core/instrument.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    name: str
    width: int
    height: int
    pixel_size_um: float
    focal_length_mm: float
    bayer_pattern: str

    @property
    def pixel_scale_arcsec(self) -> float:
        return 206.265 * self.pixel_size_um / self.focal_length_mm


SEESTAR_S30_PRO = Instrument(
    name="ZWO Seestar S30 Pro",
    width=3840,
    height=2160,
    pixel_size_um=2.9,
    focal_length_mm=150.0,
    bayer_pattern="RGGB",
)
```

`seestar_processor/core/__init__.py`: empty.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/core/test_instrument.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/core tests/core
git commit -m "feat: add Seestar S30 Pro instrument profile"
```

---

### Task 3: AstroImage model

**Files:**
- Create: `seestar_processor/core/image.py`
- Test: `tests/core/test_image.py`

**Interfaces:**
- Produces: `AstroImage` dataclass with `data: np.ndarray` (float32), `is_linear: bool = True`, `metadata: dict`. Methods: `is_color -> bool`, `copy() -> AstroImage`. Constructor coerces to float32 and validates ndim in (2, 3).

- [ ] **Step 1: Write the failing test**

`tests/core/test_image.py`:
```python
import numpy as np
import pytest
from seestar_processor.core.image import AstroImage


def test_coerces_to_float32_and_detects_color():
    img = AstroImage(np.zeros((4, 4, 3), dtype=np.uint8))
    assert img.data.dtype == np.float32
    assert img.is_color is True
    assert img.is_linear is True


def test_mono_is_not_color():
    img = AstroImage(np.zeros((4, 4), dtype=np.float32))
    assert img.is_color is False


def test_copy_is_independent():
    img = AstroImage(np.ones((2, 2), dtype=np.float32))
    c = img.copy()
    c.data[0, 0] = 9.0
    assert img.data[0, 0] == 1.0


def test_rejects_bad_ndim():
    with pytest.raises(ValueError):
        AstroImage(np.zeros((2, 2, 3, 1), dtype=np.float32))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/core/test_image.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/core/image.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class AstroImage:
    data: np.ndarray
    is_linear: bool = True
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        arr = np.asarray(self.data, dtype=np.float32)
        if arr.ndim not in (2, 3):
            raise ValueError(f"data must be 2D or 3D, got {arr.ndim}D")
        if arr.ndim == 3 and arr.shape[2] != 3:
            raise ValueError("3D data must have 3 channels (H, W, 3)")
        self.data = arr

    @property
    def is_color(self) -> bool:
        return self.data.ndim == 3

    def copy(self) -> "AstroImage":
        return AstroImage(self.data.copy(), self.is_linear, dict(self.metadata))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/core/test_image.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/core/image.py tests/core/test_image.py
git commit -m "feat: add AstroImage model"
```

---

### Task 4: FITS load + debayer

**Files:**
- Create: `seestar_processor/core/fits_io.py`
- Test: `tests/core/test_fits_io.py`

**Interfaces:**
- Consumes: `AstroImage` (Task 3), `SEESTAR_S30_PRO` (Task 2).
- Produces: `load_fits(path: str) -> AstroImage`. Detects 3-plane color FITS (already debayered) vs 2D mono-Bayer. Mono-Bayer is debayered with the instrument's RGGB pattern. Output normalized to float32 [0, 1] by dividing by the data's positive max (guard against zero). 3-plane FITS may be stored as `(3, H, W)` — transpose to `(H, W, 3)`.

- [ ] **Step 1: Write the failing test**

`tests/core/test_fits_io.py`:
```python
import numpy as np
from astropy.io import fits
from seestar_processor.core.fits_io import load_fits


def _write(path, arr):
    fits.PrimaryHDU(arr).writeto(path, overwrite=True)


def test_loads_planar_color_as_hwc(tmp_path):
    arr = np.random.randint(0, 4096, size=(3, 16, 16)).astype(np.uint16)
    p = tmp_path / "color.fits"
    _write(str(p), arr)
    img = load_fits(str(p))
    assert img.is_color is True
    assert img.data.shape == (16, 16, 3)
    assert img.data.max() <= 1.0
    assert img.is_linear is True


def test_debayers_mono_to_color(tmp_path):
    arr = np.random.randint(0, 4096, size=(16, 16)).astype(np.uint16)
    p = tmp_path / "mono.fits"
    _write(str(p), arr)
    img = load_fits(str(p))
    assert img.is_color is True
    assert img.data.shape == (16, 16, 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/core/test_fits_io.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/core/fits_io.py`:
```python
from __future__ import annotations

import numpy as np
from astropy.io import fits
from colour_demosaicing import demosaicing_CFA_Bayer_bilinear

from .image import AstroImage
from .instrument import SEESTAR_S30_PRO


def _normalize(arr: np.ndarray) -> np.ndarray:
    arr = arr.astype(np.float32)
    peak = float(arr.max())
    if peak > 0:
        arr = arr / peak
    return arr


def load_fits(path: str) -> AstroImage:
    with fits.open(path) as hdul:
        raw = np.asarray(hdul[0].data)
    if raw.ndim == 3:
        # FITS color cubes are typically (channels, H, W).
        if raw.shape[0] == 3:
            raw = np.transpose(raw, (1, 2, 0))
        data = _normalize(raw)
        return AstroImage(data, is_linear=True)
    # 2D mono-Bayer -> debayer with instrument pattern.
    norm = _normalize(raw)
    rgb = demosaicing_CFA_Bayer_bilinear(norm, SEESTAR_S30_PRO.bayer_pattern)
    return AstroImage(np.clip(rgb, 0.0, 1.0).astype(np.float32), is_linear=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/core/test_fits_io.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/core/fits_io.py tests/core/test_fits_io.py
git commit -m "feat: load Seestar FITS with color/mono-Bayer detection"
```

---

### Task 5: Display autostretch

**Files:**
- Create: `seestar_processor/core/autostretch.py`
- Test: `tests/core/test_autostretch.py`

**Interfaces:**
- Consumes: `AstroImage`.
- Produces: `autostretch(img: AstroImage) -> np.ndarray` returning a float32 [0,1] array (same shape) suitable for **display only** (does not mutate `img`). Uses a midtones transfer function (MTF) computed from median + MAD, per channel.

- [ ] **Step 1: Write the failing test**

`tests/core/test_autostretch.py`:
```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.autostretch import autostretch


def test_autostretch_brightens_dark_image_without_mutating():
    data = np.full((8, 8), 0.02, dtype=np.float32)
    data[0, 0] = 0.9
    img = AstroImage(data.copy())
    out = autostretch(img)
    assert out.shape == data.shape
    assert out.dtype == np.float32
    assert out.min() >= 0.0 and out.max() <= 1.0
    # median should be lifted well above the original 0.02
    assert np.median(out) > 0.1
    # original image is untouched
    assert np.allclose(img.data, data)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/core/test_autostretch.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/core/autostretch.py`:
```python
from __future__ import annotations

import numpy as np

from .image import AstroImage

_TARGET_BG = 0.25  # target median for the stretched display
_SIGMA = 2.8


def _mtf(m: float, x: np.ndarray) -> np.ndarray:
    # Midtones transfer function (PixInsight/Siril style).
    num = (m - 1.0) * x
    den = (2.0 * m - 1.0) * x - m
    return np.where(x == 0, 0.0, np.where(x == 1, 1.0, num / den))


def _stretch_channel(c: np.ndarray) -> np.ndarray:
    med = float(np.median(c))
    mad = float(np.median(np.abs(c - med))) or 1e-6
    shadow = max(0.0, med - _SIGMA * mad)
    c = np.clip((c - shadow) / max(1e-6, 1.0 - shadow), 0.0, 1.0)
    med2 = float(np.median(c)) or 1e-6
    # midtones balance that maps current median to _TARGET_BG
    m = _mtf_midtones(med2, _TARGET_BG)
    return _mtf(m, c).astype(np.float32)


def _mtf_midtones(current_med: float, target: float) -> float:
    # Solve MTF midtones param so that _mtf(m, current_med) == target.
    if current_med <= 0:
        return 0.5
    return ((target - 1.0) * current_med) / (
        (2.0 * target - 1.0) * current_med - target
    )


def autostretch(img: AstroImage) -> np.ndarray:
    data = img.data
    if data.ndim == 2:
        return np.clip(_stretch_channel(data), 0.0, 1.0)
    out = np.empty_like(data, dtype=np.float32)
    for ch in range(data.shape[2]):
        out[..., ch] = _stretch_channel(data[..., ch])
    return np.clip(out, 0.0, 1.0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/core/test_autostretch.py -v`
Expected: PASS. If midtones math drifts, verify `_mtf(_mtf_midtones(med, t), med) ≈ t` in a REPL.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/core/autostretch.py tests/core/test_autostretch.py
git commit -m "feat: add display autostretch (MTF)"
```

---

### Task 6: Real stretch with presets

**Files:**
- Create: `seestar_processor/core/stretch.py`
- Test: `tests/core/test_stretch.py`

**Interfaces:**
- Consumes: `AstroImage`.
- Produces: `STRETCH_PRESETS = ("Small", "Medium", "Large")` and `apply_stretch(img: AstroImage, preset: str) -> AstroImage` returning a NEW `AstroImage` with `is_linear=False`. Uses an asinh stretch whose intensity scales with the preset.

- [ ] **Step 1: Write the failing test**

`tests/core/test_stretch.py`:
```python
import numpy as np
import pytest
from seestar_processor.core.image import AstroImage
from seestar_processor.core.stretch import apply_stretch, STRETCH_PRESETS


def test_stretch_marks_nonlinear_and_brightens():
    data = np.linspace(0, 0.1, 64, dtype=np.float32).reshape(8, 8)
    img = AstroImage(data.copy())
    out = apply_stretch(img, "Medium")
    assert out.is_linear is False
    assert out is not img
    assert np.median(out.data) > np.median(data)
    assert out.data.max() <= 1.0


def test_larger_preset_brightens_more():
    data = np.full((8, 8), 0.05, dtype=np.float32)
    small = apply_stretch(AstroImage(data.copy()), "Small")
    large = apply_stretch(AstroImage(data.copy()), "Large")
    assert np.median(large.data) > np.median(small.data)


def test_unknown_preset_raises():
    with pytest.raises(ValueError):
        apply_stretch(AstroImage(np.zeros((4, 4), np.float32)), "Huge")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/core/test_stretch.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/core/stretch.py`:
```python
from __future__ import annotations

import numpy as np

from .image import AstroImage

STRETCH_PRESETS = ("Small", "Medium", "Large")
_INTENSITY = {"Small": 10.0, "Medium": 50.0, "Large": 200.0}


def apply_stretch(img: AstroImage, preset: str) -> AstroImage:
    if preset not in _INTENSITY:
        raise ValueError(f"unknown preset {preset!r}; expected {STRETCH_PRESETS}")
    a = _INTENSITY[preset]
    x = np.clip(img.data, 0.0, 1.0)
    out = np.arcsinh(a * x) / np.arcsinh(a)
    return AstroImage(out.astype(np.float32), is_linear=False, metadata=dict(img.metadata))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/core/test_stretch.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/core/stretch.py tests/core/test_stretch.py
git commit -m "feat: add real asinh stretch with presets"
```

---

### Task 7: Image export

**Files:**
- Create: `seestar_processor/core/export.py`
- Test: `tests/core/test_export.py`

**Interfaces:**
- Consumes: `AstroImage`.
- Produces: `save_tiff(img: AstroImage, path: str) -> None` (16-bit) and `save_jpeg(img: AstroImage, path: str, quality: int = 95) -> None` (8-bit). Mono is written as single-channel; color as RGB.

- [ ] **Step 1: Write the failing test**

`tests/core/test_export.py`:
```python
import numpy as np
from PIL import Image
from seestar_processor.core.image import AstroImage
from seestar_processor.core.export import save_tiff, save_jpeg


def test_save_tiff_is_16bit(tmp_path):
    img = AstroImage(np.linspace(0, 1, 48, dtype=np.float32).reshape(4, 4, 3))
    out = tmp_path / "o.tiff"
    save_tiff(img, str(out))
    with Image.open(out) as im:
        assert im.size == (4, 4)
        assert im.mode in ("RGB", "I;16", "RGB;16")


def test_save_jpeg_roundtrips(tmp_path):
    img = AstroImage(np.full((4, 4, 3), 0.5, dtype=np.float32))
    out = tmp_path / "o.jpg"
    save_jpeg(img, str(out))
    with Image.open(out) as im:
        assert im.size == (4, 4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/core/test_export.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/core/export.py`:
```python
from __future__ import annotations

import numpy as np
from PIL import Image

from .image import AstroImage


def _to_uint(data: np.ndarray, bits: int) -> np.ndarray:
    maxval = (2 ** bits) - 1
    clipped = np.clip(data, 0.0, 1.0)
    dtype = np.uint16 if bits == 16 else np.uint8
    return (clipped * maxval + 0.5).astype(dtype)


def save_tiff(img: AstroImage, path: str) -> None:
    arr = _to_uint(img.data, 16)
    if arr.ndim == 2:
        Image.fromarray(arr, mode="I;16").save(path, format="TIFF")
    else:
        Image.fromarray(arr).save(path, format="TIFF")


def save_jpeg(img: AstroImage, path: str, quality: int = 95) -> None:
    arr = _to_uint(img.data, 8)
    mode = "L" if arr.ndim == 2 else "RGB"
    Image.fromarray(arr, mode=mode).save(path, format="JPEG", quality=quality)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/core/test_export.py -v`
Expected: PASS. (If Pillow lacks 16-bit RGB TIFF on this platform, the test allows several modes; do not over-constrain.)

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/core/export.py tests/core/test_export.py
git commit -m "feat: add TIFF/JPEG export"
```

---

### Task 8: Step abstraction

**Files:**
- Create: `seestar_processor/history/__init__.py`
- Create: `seestar_processor/history/step.py`
- Test: `tests/history/test_step.py`

**Interfaces:**
- Consumes: `AstroImage`.
- Produces: abstract `Step` with `name: str`, `options() -> list[str]`, `default_option() -> str`, and `apply(img: AstroImage, option: str) -> AstroImage`. Plus a concrete test double is defined in the test only.

- [ ] **Step 1: Write the failing test**

`tests/history/__init__.py` (empty), then `tests/history/test_step.py`:
```python
import numpy as np
import pytest
from seestar_processor.core.image import AstroImage
from seestar_processor.history.step import Step


class _Double(Step):
    name = "double"

    def options(self):
        return ["x1", "x2"]

    def default_option(self):
        return "x1"

    def apply(self, img, option):
        factor = 2.0 if option == "x2" else 1.0
        return AstroImage(img.data * factor, img.is_linear)


def test_step_apply_uses_option():
    s = _Double()
    img = AstroImage(np.ones((2, 2), np.float32))
    assert s.apply(img, "x2").data[0, 0] == 2.0
    assert s.default_option() == "x1"


def test_abstract_step_cannot_instantiate():
    with pytest.raises(TypeError):
        Step()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/history/test_step.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/history/step.py`:
```python
from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.image import AstroImage


class Step(ABC):
    name: str = ""

    @abstractmethod
    def options(self) -> list[str]:
        ...

    @abstractmethod
    def default_option(self) -> str:
        ...

    @abstractmethod
    def apply(self, img: AstroImage, option: str) -> AstroImage:
        ...
```

`seestar_processor/history/__init__.py`: empty.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/history/test_step.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/history tests/history
git commit -m "feat: add Step abstraction"
```

---

### Task 9: Project history (cached, disk-spilled, undo/redo/jump-back)

**Files:**
- Create: `seestar_processor/history/project.py`
- Test: `tests/history/test_project.py`

**Interfaces:**
- Consumes: `AstroImage`, `Step`.
- Produces: `Project(base: AstroImage, cache_dir: str)`. Methods:
  - `run_step(step: Step, option: str) -> AstroImage` — applies step to the current image, appends a `(step_name, option)` record, caches the result to disk (`.npy`), returns it.
  - `current() -> AstroImage` — image at the current position.
  - `can_undo() -> bool`, `can_redo() -> bool`, `undo() -> None`, `redo() -> None`.
  - `before_after() -> tuple[AstroImage, AstroImage]` — (previous cached, current). At base, previous == current.
  - `jump_back(index: int) -> None` — truncate forward history to `index` (0 = base), discarding later cached states.
  - `entries() -> list[tuple[str, str]]` — ordered (step_name, option) records up to current position.

Implementation note: keep a list of cache file paths (index 0 = base). `position` indexes that list. Undo/redo move `position`. `run_step` truncates anything after `position`, then appends.

- [ ] **Step 1: Write the failing test**

`tests/history/test_project.py`:
```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.history.project import Project
from tests.history.test_step import _Double


def _base():
    return AstroImage(np.ones((2, 2), np.float32))


def test_run_step_caches_and_advances(tmp_path):
    p = Project(_base(), str(tmp_path))
    out = p.run_step(_Double(), "x2")
    assert out.data[0, 0] == 2.0
    assert p.current().data[0, 0] == 2.0
    assert p.entries() == [("double", "x2")]


def test_undo_redo(tmp_path):
    p = Project(_base(), str(tmp_path))
    p.run_step(_Double(), "x2")
    assert p.can_undo() is True
    p.undo()
    assert p.current().data[0, 0] == 1.0
    assert p.can_redo() is True
    p.redo()
    assert p.current().data[0, 0] == 2.0


def test_before_after(tmp_path):
    p = Project(_base(), str(tmp_path))
    p.run_step(_Double(), "x2")
    before, after = p.before_after()
    assert before.data[0, 0] == 1.0
    assert after.data[0, 0] == 2.0


def test_jump_back_truncates_forward(tmp_path):
    p = Project(_base(), str(tmp_path))
    p.run_step(_Double(), "x2")   # -> 2.0
    p.run_step(_Double(), "x2")   # -> 4.0
    p.jump_back(1)                # keep only first step
    assert p.current().data[0, 0] == 2.0
    assert p.can_redo() is False
    p.run_step(_Double(), "x1")   # new branch -> 2.0
    assert p.entries() == [("double", "x2"), ("double", "x1")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/history/test_project.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/history/project.py`:
```python
from __future__ import annotations

import os

import numpy as np

from ..core.image import AstroImage
from .step import Step


class Project:
    def __init__(self, base: AstroImage, cache_dir: str) -> None:
        os.makedirs(cache_dir, exist_ok=True)
        self._dir = cache_dir
        self._paths: list[str] = []
        self._records: list[tuple[str, str]] = []
        self._meta: list[dict] = []
        self._linear: list[bool] = []
        self._position = 0
        self._save(0, base)

    def _path(self, index: int) -> str:
        return os.path.join(self._dir, f"state_{index}.npy")

    def _save(self, index: int, img: AstroImage) -> None:
        path = self._path(index)
        np.save(path, img.data)
        if index < len(self._paths):
            self._paths[index] = path
            self._meta[index] = dict(img.metadata)
            self._linear[index] = img.is_linear
        else:
            self._paths.append(path)
            self._meta.append(dict(img.metadata))
            self._linear.append(img.is_linear)

    def _load(self, index: int) -> AstroImage:
        data = np.load(self._paths[index])
        return AstroImage(data, self._linear[index], dict(self._meta[index]))

    def current(self) -> AstroImage:
        return self._load(self._position)

    def run_step(self, step: Step, option: str) -> AstroImage:
        # Truncate any forward (redo) history.
        del self._paths[self._position + 1:]
        del self._records[self._position:]
        del self._meta[self._position + 1:]
        del self._linear[self._position + 1:]
        result = step.apply(self.current(), option)
        index = self._position + 1
        self._save(index, result)
        self._records.append((step.name, option))
        self._position = index
        return result

    def can_undo(self) -> bool:
        return self._position > 0

    def can_redo(self) -> bool:
        return self._position < len(self._paths) - 1

    def undo(self) -> None:
        if self.can_undo():
            self._position -= 1

    def redo(self) -> None:
        if self.can_redo():
            self._position += 1

    def before_after(self) -> tuple[AstroImage, AstroImage]:
        prev = max(0, self._position - 1)
        return self._load(prev), self._load(self._position)

    def jump_back(self, index: int) -> None:
        if not 0 <= index <= self._position:
            raise IndexError(index)
        self._position = index
        del self._paths[index + 1:]
        del self._records[index:]
        del self._meta[index + 1:]
        del self._linear[index + 1:]

    def entries(self) -> list[tuple[str, str]]:
        return list(self._records[: self._position])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/history/test_project.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/history/project.py tests/history/test_project.py
git commit -m "feat: add cached project history with undo/redo/jump-back"
```

---

### Task 10: CLI tool base (subprocess + temp FITS round-trip)

**Files:**
- Create: `seestar_processor/tools/__init__.py`
- Create: `seestar_processor/tools/base.py`
- Test: `tests/tools/test_base.py`

**Interfaces:**
- Consumes: `AstroImage`, `astropy.io.fits`.
- Produces:
  - `write_temp_fits(img: AstroImage, path: str) -> None` (float32 FITS; color saved as `(3, H, W)`).
  - `read_fits_array(path: str) -> AstroImage` (inverse; `(3,H,W)`→`(H,W,3)`).
  - `run_cli(args: list[str]) -> None` — runs subprocess, raises `ToolError(returncode, stderr)` on nonzero exit.
  - `ToolError(Exception)` with `.returncode` and `.stderr`.

- [ ] **Step 1: Write the failing test**

`tests/tools/__init__.py` (empty), then `tests/tools/test_base.py`:
```python
import numpy as np
import pytest
from seestar_processor.core.image import AstroImage
from seestar_processor.tools.base import (
    write_temp_fits, read_fits_array, run_cli, ToolError,
)


def test_fits_roundtrip_color(tmp_path):
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    p = tmp_path / "t.fits"
    write_temp_fits(img, str(p))
    back = read_fits_array(str(p))
    assert back.data.shape == (8, 8, 3)
    assert np.allclose(back.data, img.data, atol=1e-5)


def test_run_cli_raises_on_failure():
    with pytest.raises(ToolError) as e:
        run_cli(["python", "-c", "import sys; sys.exit(3)"])
    assert e.value.returncode == 3


def test_run_cli_succeeds():
    run_cli(["python", "-c", "print('ok')"])  # no exception
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/tools/test_base.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/tools/base.py`:
```python
from __future__ import annotations

import subprocess

import numpy as np
from astropy.io import fits

from ..core.image import AstroImage


class ToolError(Exception):
    def __init__(self, returncode: int, stderr: str) -> None:
        super().__init__(f"CLI failed ({returncode}): {stderr}")
        self.returncode = returncode
        self.stderr = stderr


def write_temp_fits(img: AstroImage, path: str) -> None:
    data = img.data.astype(np.float32)
    if data.ndim == 3:
        data = np.transpose(data, (2, 0, 1))  # (3, H, W)
    fits.PrimaryHDU(data).writeto(path, overwrite=True)


def read_fits_array(path: str) -> AstroImage:
    with fits.open(path) as hdul:
        data = np.asarray(hdul[0].data, dtype=np.float32)
    if data.ndim == 3 and data.shape[0] == 3:
        data = np.transpose(data, (1, 2, 0))
    return AstroImage(data, is_linear=True)


def run_cli(args: list[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ToolError(proc.returncode, proc.stderr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/tools/test_base.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/tools tests/tools
git commit -m "feat: add CLI tool base with temp FITS round-trip"
```

---

### Task 11: GraXpert adapter

**Files:**
- Create: `seestar_processor/tools/graxpert.py`
- Test: `tests/tools/test_graxpert.py`

**Interfaces:**
- Consumes: `AstroImage`, Task 10 helpers.
- Produces: `GraXpert(binary_path: str)` with `background_extraction(img: AstroImage, strength: float, *, runner=run_cli) -> AstroImage`. It writes the input to a temp FITS, builds the command, invokes the runner, reads the produced output FITS, and cleans up temp files. The `runner` parameter is injectable for testing. Command template (flags verified from `graxpert --help` at execution time; this is the documented CLI shape):
  `[binary, "-cmd", "background-extraction", in_fits, "-output", out_stem, "-smoothing", str(strength)]`
  GraXpert writes `<out_stem>.fits`.

- [ ] **Step 1: Write the failing test**

`tests/tools/test_graxpert.py`:
```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.tools.base import write_temp_fits
from seestar_processor.tools.graxpert import GraXpert


def test_background_extraction_invokes_cli_and_reads_output(tmp_path):
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    captured = {}

    def fake_runner(args):
        # GraXpert command shape: -output gives a stem; tool writes <stem>.fits
        captured["args"] = args
        out_stem = args[args.index("-output") + 1]
        # Simulate GraXpert producing a darker background-removed file.
        write_temp_fits(AstroImage(img.data * 0.5), out_stem + ".fits")

    gx = GraXpert(binary_path="/fake/graxpert")
    result = gx.background_extraction(img, strength=0.5, runner=fake_runner)

    assert "background-extraction" in captured["args"]
    assert captured["args"][0] == "/fake/graxpert"
    assert result.data.shape == (8, 8, 3)
    assert np.allclose(result.data, img.data * 0.5, atol=1e-5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/tools/test_graxpert.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/tools/graxpert.py`:
```python
from __future__ import annotations

import os
import tempfile

from ..core.image import AstroImage
from .base import read_fits_array, run_cli, write_temp_fits


class GraXpert:
    def __init__(self, binary_path: str) -> None:
        self.binary_path = binary_path

    def background_extraction(
        self, img: AstroImage, strength: float, *, runner=run_cli
    ) -> AstroImage:
        tmp = tempfile.mkdtemp(prefix="gx_")
        in_fits = os.path.join(tmp, "in.fits")
        out_stem = os.path.join(tmp, "out")
        out_fits = out_stem + ".fits"
        try:
            write_temp_fits(img, in_fits)
            runner([
                self.binary_path, "-cmd", "background-extraction",
                in_fits, "-output", out_stem, "-smoothing", str(strength),
            ])
            result = read_fits_array(out_fits)
            result.is_linear = img.is_linear
            return result
        finally:
            for f in (in_fits, out_fits):
                if os.path.exists(f):
                    os.remove(f)
            if os.path.isdir(tmp):
                os.rmdir(tmp)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/tools/test_graxpert.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/tools/graxpert.py tests/tools/test_graxpert.py
git commit -m "feat: add GraXpert background-extraction adapter"
```

---

### Task 12: Settings (binary paths + persistence)

**Files:**
- Create: `seestar_processor/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings` dataclass with `graxpert_path: str = ""`, `rcastro_path: str = ""`. Functions `load_settings(path: str) -> Settings` (missing file → defaults) and `save_settings(s: Settings, path: str) -> None` (JSON). `graxpert_valid(s) -> bool` returns True iff `graxpert_path` is a non-empty existing file.

- [ ] **Step 1: Write the failing test**

`tests/test_settings.py`:
```python
from seestar_processor.settings import (
    Settings, load_settings, save_settings, graxpert_valid,
)


def test_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    save_settings(Settings(graxpert_path="/x/graxpert"), str(p))
    loaded = load_settings(str(p))
    assert loaded.graxpert_path == "/x/graxpert"


def test_missing_file_returns_defaults(tmp_path):
    s = load_settings(str(tmp_path / "nope.json"))
    assert s.graxpert_path == ""


def test_graxpert_valid(tmp_path):
    f = tmp_path / "graxpert"
    f.write_text("#!/bin/sh\n")
    assert graxpert_valid(Settings(graxpert_path=str(f))) is True
    assert graxpert_valid(Settings(graxpert_path="/nope")) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_settings.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/settings.py`:
```python
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass


@dataclass
class Settings:
    graxpert_path: str = ""
    rcastro_path: str = ""


def load_settings(path: str) -> Settings:
    if not os.path.exists(path):
        return Settings()
    with open(path) as f:
        data = json.load(f)
    return Settings(
        graxpert_path=data.get("graxpert_path", ""),
        rcastro_path=data.get("rcastro_path", ""),
    )


def save_settings(s: Settings, path: str) -> None:
    with open(path, "w") as f:
        json.dump(asdict(s), f, indent=2)


def graxpert_valid(s: Settings) -> bool:
    return bool(s.graxpert_path) and os.path.isfile(s.graxpert_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_settings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/settings.py tests/test_settings.py
git commit -m "feat: add settings load/save and GraXpert validation"
```

---

### Task 13: Concrete steps (Load, Background, Stretch)

**Files:**
- Create: `seestar_processor/steps/__init__.py`
- Create: `seestar_processor/steps/load.py`
- Create: `seestar_processor/steps/background.py`
- Create: `seestar_processor/steps/stretch_step.py`
- Test: `tests/steps/test_steps.py`

**Interfaces:**
- Consumes: `Step`, `apply_stretch`, `STRETCH_PRESETS`, `GraXpert`.
- Produces:
  - `BackgroundStep(graxpert: GraXpert)` — `name="Background"`, options `["Small","Medium","Large"]` mapped to smoothing strengths `{Small:0.2, Medium:0.5, Large:0.8}`; `apply` calls `graxpert.background_extraction`.
  - `StretchStep()` — `name="Stretch"`, options `STRETCH_PRESETS`, `apply` calls `apply_stretch`.
  - Load is handled directly by the UI via `load_fits` (no Step needed since it produces the base), so no `LoadStep` class — document this in `steps/load.py` as a thin re-export of `load_fits`.

- [ ] **Step 1: Write the failing test**

`tests/steps/__init__.py` (empty), then `tests/steps/test_steps.py`:
```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.tools.graxpert import GraXpert
from seestar_processor.steps.background import BackgroundStep
from seestar_processor.steps.stretch_step import StretchStep


def test_background_step_maps_option_to_strength(monkeypatch):
    img = AstroImage(np.ones((4, 4, 3), np.float32))
    seen = {}

    def fake_runner(args):
        from seestar_processor.tools.base import write_temp_fits
        seen["strength"] = args[args.index("-smoothing") + 1]
        out_stem = args[args.index("-output") + 1]
        write_temp_fits(img, out_stem + ".fits")

    step = BackgroundStep(GraXpert("/fake"))
    step._runner = fake_runner  # injected for test
    step.apply(img, "Medium")
    assert seen["strength"] == "0.5"


def test_stretch_step_marks_nonlinear():
    step = StretchStep()
    out = step.apply(AstroImage(np.full((4, 4), 0.05, np.float32)), "Medium")
    assert out.is_linear is False
    assert step.options() == ["Small", "Medium", "Large"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/steps/test_steps.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/steps/__init__.py`: empty.

`seestar_processor/steps/load.py`:
```python
# Load produces the project base image and is invoked directly by the UI.
from ..core.fits_io import load_fits

__all__ = ["load_fits"]
```

`seestar_processor/steps/background.py`:
```python
from __future__ import annotations

from ..core.image import AstroImage
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.graxpert import GraXpert

_STRENGTH = {"Small": 0.2, "Medium": 0.5, "Large": 0.8}


class BackgroundStep(Step):
    name = "Background"

    def __init__(self, graxpert: GraXpert) -> None:
        self._gx = graxpert
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["Small", "Medium", "Large"]

    def default_option(self) -> str:
        return "Medium"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        return self._gx.background_extraction(
            img, _STRENGTH[option], runner=self._runner
        )
```

`seestar_processor/steps/stretch_step.py`:
```python
from __future__ import annotations

from ..core.image import AstroImage
from ..core.stretch import STRETCH_PRESETS, apply_stretch
from ..history.step import Step


class StretchStep(Step):
    name = "Stretch"

    def options(self) -> list[str]:
        return list(STRETCH_PRESETS)

    def default_option(self) -> str:
        return "Medium"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        return apply_stretch(img, option)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/steps/test_steps.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/steps tests/steps
git commit -m "feat: add Background and Stretch steps"
```

---

### Task 14: Qt preview helper (numpy → QImage)

**Files:**
- Create: `seestar_processor/ui/__init__.py`
- Create: `seestar_processor/ui/preview.py`
- Test: `tests/ui/test_preview.py`

**Interfaces:**
- Consumes: `AstroImage`, `autostretch`.
- Produces: `to_qimage(img: AstroImage) -> QImage`. If `img.is_linear`, apply `autostretch` first; else render data directly. Converts to 8-bit RGB `QImage` (mono is expanded to RGB).

- [ ] **Step 1: Write the failing test**

`tests/ui/__init__.py` (empty), then `tests/ui/test_preview.py`:
```python
import numpy as np
import pytest
from seestar_processor.core.image import AstroImage

pytest.importorskip("PySide6")
from seestar_processor.ui.preview import to_qimage  # noqa: E402


def test_to_qimage_dimensions(qapp):
    img = AstroImage(np.random.rand(6, 10, 3).astype(np.float32))
    qimg = to_qimage(img)
    assert qimg.width() == 10
    assert qimg.height() == 6


def test_to_qimage_mono(qapp):
    img = AstroImage(np.random.rand(6, 10).astype(np.float32))
    qimg = to_qimage(img)
    assert qimg.width() == 10
```

(`qapp` fixture is provided by pytest-qt.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ui/test_preview.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/ui/__init__.py`: empty.

`seestar_processor/ui/preview.py`:
```python
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage

from ..core.autostretch import autostretch
from ..core.image import AstroImage


def to_qimage(img: AstroImage) -> QImage:
    data = autostretch(img) if img.is_linear else np.clip(img.data, 0.0, 1.0)
    if data.ndim == 2:
        data = np.repeat(data[:, :, None], 3, axis=2)
    rgb = (data * 255 + 0.5).astype(np.uint8)
    rgb = np.ascontiguousarray(rgb)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/ui/test_preview.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui tests/ui
git commit -m "feat: add numpy->QImage preview helper"
```

---

### Task 15: Main window + app entry point (manual verification)

**Files:**
- Create: `seestar_processor/ui/settings_dialog.py`
- Create: `seestar_processor/ui/main_window.py`
- Modify: `seestar_processor/__main__.py`
- Test: `tests/ui/test_main_window.py` (pytest-qt smoke test)

**Interfaces:**
- Consumes: `load_fits`, `Project`, `BackgroundStep`, `StretchStep`, `to_qimage`, `Settings`/`load_settings`/`save_settings`/`graxpert_valid`, `GraXpert`, `save_tiff`/`save_jpeg`.
- Produces: `MainWindow(settings_path: str)` Qt window wiring the flow:
  - Toolbar: Open FITS, Settings, Undo, Redo, Before/After (hold), Export.
  - Left: ordered step list (Load → Background → Stretch) with the active step highlighted; clicking an earlier entry calls `Project.jump_back`.
  - Center: preview `QLabel` rendering `to_qimage(project.current())`.
  - Right: `step_panel` with the current step's options as a segmented/radio control + an "Apply" button calling `Project.run_step`.
  - Settings dialog edits GraXpert/RC-Astro paths; Background step is disabled until `graxpert_valid`.

- [ ] **Step 1: Write the smoke test**

`tests/ui/test_main_window.py`:
```python
import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from seestar_processor.ui.main_window import MainWindow  # noqa: E402


def test_open_and_stretch_updates_preview(qtbot, tmp_path):
    # synthetic Seestar-like color FITS
    arr = (np.random.rand(3, 32, 32) * 1000).astype(np.uint16)
    fpath = tmp_path / "stack.fits"
    fits.PrimaryHDU(arr).writeto(str(fpath))

    win = MainWindow(settings_path=str(tmp_path / "settings.json"))
    qtbot.addWidget(win)
    win.open_fits(str(fpath))
    assert win.project is not None
    assert win.project.current().is_linear is True

    win.apply_step(win.stretch_step, "Medium")
    assert win.project.current().is_linear is False
    assert win.preview_label.pixmap() is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ui/test_main_window.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write the implementation**

`seestar_processor/ui/settings_dialog.py`:
```python
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QLineEdit, QPushButton, QHBoxLayout,
    QDialogButtonBox, QWidget,
)

from ..settings import Settings


def _path_row(edit: QLineEdit) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(edit)
    browse = QPushButton("Browse…")
    browse.clicked.connect(
        lambda: edit.setText(QFileDialog.getOpenFileName(row)[0] or edit.text())
    )
    lay.addWidget(browse)
    return row


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._gx = QLineEdit(settings.graxpert_path)
        self._rc = QLineEdit(settings.rcastro_path)
        form = QFormLayout(self)
        form.addRow("GraXpert binary", _path_row(self._gx))
        form.addRow("RC-Astro binary (optional)", _path_row(self._rc))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def result_settings(self) -> Settings:
        return Settings(self._gx.text().strip(), self._rc.text().strip())
```

`seestar_processor/ui/main_window.py`:
```python
from __future__ import annotations

import os

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QListWidget, QMainWindow, QPushButton,
    QVBoxLayout, QWidget, QComboBox, QMessageBox,
)

from ..core.export import save_jpeg, save_tiff
from ..history.project import Project
from ..settings import load_settings, save_settings, graxpert_valid
from ..steps.background import BackgroundStep
from ..steps.load import load_fits
from ..steps.stretch_step import StretchStep
from ..tools.graxpert import GraXpert
from .preview import to_qimage
from .settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self, settings_path: str) -> None:
        super().__init__()
        self.setWindowTitle("Seestar Processor")
        self._settings_path = settings_path
        self.settings = load_settings(settings_path)
        self.project: Project | None = None
        self._cache_dir = os.path.join(os.path.dirname(settings_path), "cache")

        self.stretch_step = StretchStep()

        central = QWidget()
        root = QHBoxLayout(central)

        self.step_list = QListWidget()
        self.step_list.itemClicked.connect(self._on_step_clicked)
        root.addWidget(self.step_list, 1)

        self.preview_label = QLabel("Open a FITS file to begin")
        self.preview_label.setMinimumSize(640, 360)
        root.addWidget(self.preview_label, 4)

        panel = QWidget()
        pl = QVBoxLayout(panel)
        self.option_box = QComboBox()
        pl.addWidget(QLabel("Strength / preset"))
        pl.addWidget(self.option_box)
        self.bg_button = QPushButton("Apply Background")
        self.bg_button.clicked.connect(self._apply_background)
        self.stretch_button = QPushButton("Apply Stretch")
        self.stretch_button.clicked.connect(self._apply_stretch)
        pl.addWidget(self.bg_button)
        pl.addWidget(self.stretch_button)
        pl.addStretch(1)
        root.addWidget(panel, 1)

        self.setCentralWidget(central)
        self._build_toolbar()
        self._refresh_enabled()

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Main")
        tb.addAction("Open FITS", self._choose_fits)
        tb.addAction("Settings", self._open_settings)
        self._undo_act = tb.addAction("Undo", self._undo)
        self._redo_act = tb.addAction("Redo", self._redo)
        self._ba_act = tb.addAction("Before/After", self._toggle_before_after)
        self._ba_act.setCheckable(True)
        tb.addAction("Export", self._export)

    # --- file / project ---
    def _choose_fits(self) -> None:
        path = QFileDialog.getOpenFileName(self, "Open FITS", "", "FITS (*.fit *.fits)")[0]
        if path:
            self.open_fits(path)

    def open_fits(self, path: str) -> None:
        base = load_fits(path)
        os.makedirs(self._cache_dir, exist_ok=True)
        self.project = Project(base, self._cache_dir)
        self._render()
        self._refresh_steps()
        self._refresh_enabled()

    # --- steps ---
    def apply_step(self, step, option: str) -> None:
        assert self.project is not None
        self.project.run_step(step, option)
        self._render()
        self._refresh_steps()
        self._refresh_enabled()

    def _apply_background(self) -> None:
        gx = GraXpert(self.settings.graxpert_path)
        self.apply_step(BackgroundStep(gx), self.option_box.currentText() or "Medium")

    def _apply_stretch(self) -> None:
        self.apply_step(self.stretch_step, self.option_box.currentText() or "Medium")

    # --- history ---
    def _undo(self) -> None:
        if self.project:
            self.project.undo()
            self._render(); self._refresh_enabled()

    def _redo(self) -> None:
        if self.project:
            self.project.redo()
            self._render(); self._refresh_enabled()

    def _toggle_before_after(self) -> None:
        if not self.project:
            return
        before, after = self.project.before_after()
        self._show(before if self._ba_act.isChecked() else after)

    def _on_step_clicked(self, item) -> None:
        if self.project:
            self.project.jump_back(self.step_list.row(item))
            self._render(); self._refresh_steps(); self._refresh_enabled()

    # --- export ---
    def _export(self) -> None:
        if not self.project:
            return
        path = QFileDialog.getSaveFileName(self, "Export", "", "TIFF (*.tiff);;JPEG (*.jpg)")[0]
        if not path:
            return
        img = self.project.current()
        if path.lower().endswith((".jpg", ".jpeg")):
            save_jpeg(img, path)
        else:
            save_tiff(img, path)

    # --- settings ---
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.result_settings()
            save_settings(self.settings, self._settings_path)
            self._refresh_enabled()

    # --- rendering / state ---
    def _render(self) -> None:
        if self.project:
            self._show(self.project.current())
        # populate option box from current default step (stretch presets are fine for both)
        if self.option_box.count() == 0:
            self.option_box.addItems(["Small", "Medium", "Large"])

    def _show(self, img) -> None:
        self.preview_label.setPixmap(QPixmap.fromImage(to_qimage(img)))

    def _refresh_steps(self) -> None:
        self.step_list.clear()
        self.step_list.addItem("Load")
        if self.project:
            for name, opt in self.project.entries():
                self.step_list.addItem(f"{name} ({opt})")

    def _refresh_enabled(self) -> None:
        has = self.project is not None
        self.bg_button.setEnabled(has and graxpert_valid(self.settings))
        self.stretch_button.setEnabled(has)
        self._undo_act.setEnabled(bool(self.project and self.project.can_undo()))
        self._redo_act.setEnabled(bool(self.project and self.project.can_redo()))
```

`seestar_processor/__main__.py`:
```python
import os
import sys

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    settings_path = os.path.join(
        os.path.expanduser("~"), ".seestar_processor", "settings.json"
    )
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    win = MainWindow(settings_path=settings_path)
    win.resize(1200, 720)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run smoke test**

Run: `.venv/bin/pytest tests/ui/test_main_window.py -v`
Expected: PASS. (Note: the smoke test calls `apply_step` directly, bypassing GraXpert, so it does not require a GraXpert binary.)

- [ ] **Step 5: Full suite + manual end-to-end verification**

Run: `.venv/bin/pytest -q`
Expected: all PASS.

Then manual (requires a real GraXpert install + a Seestar S30 Pro stacked FITS):
```bash
.venv/bin/python -m seestar_processor
```
- Settings → set GraXpert binary path; confirm "Apply Background" enables only when the path is a real file.
- Open a Seestar FITS → preview shows a debayered, autostretched image.
- Apply Background (Small/Medium/Large) → image updates; toggle Before/After.
- Undo/redo are instant; click "Load" in the step list to jump back, then re-apply.
- Apply Stretch → preview switches to the stretched render.
- Export TIFF and JPEG → open the files and confirm they match the screen.

- [ ] **Step 6: Commit**

```bash
git add seestar_processor/ui tests/ui seestar_processor/__main__.py
git commit -m "feat: add main window, settings dialog, and app entry point"
```

---

## Self-Review notes

- **Spec coverage:** Load+autostretch (T4,T5,T14), Background via GraXpert (T11,T13), real Stretch (T6,T13), Export (T7), cached history + undo/redo + jump-back + before/after (T9), settings binary paths + GraXpert-required/RC-optional gating (T12,T15), instrument profile (T2), modular step/tool boundaries (T8,T10). Deferred (crop, color, decon, noise, final fixes, RC-Astro, project reopen) are intentionally out of v1 per the approved plan.
- **Linear-vs-display invariant** is enforced: only `apply_stretch` sets `is_linear=False`; `to_qimage` autostretches only while linear.
- **GraXpert flag syntax** (`-cmd background-extraction … -output … -smoothing …`) must be confirmed against the installed `graxpert --help` during Task 11/15; the adapter is structured so only the `args` list changes if flags differ.
```
