# Narrowband Core Engine (Increment 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure-numpy `nocturne/core/narrowband.py` that reproduces PixInsight NarrowbandNormalization's HOO palette on a broadband Seestar image, and validate it on the real NGC 7000 LP master.

**Architecture:** A single new Qt-free core module. NBN's normalization (black-point → robust level → MTF-midtone-solve) lifts faint OIII to match Ha; a Blanshan/Foraxx dynamic blend builds the synthetic green; NBN's tone stages (highlight reduction / brightness / highlight recover) finish. `render_hoo(img, params)` chains it. Reuses `autostretch._mtf` and `saturation.saturate`.

**Tech Stack:** Python 3.13 (`.venv/bin/python`), numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-07-18-narrowband-core-design.md`

## Global Constraints

- Run tests: `.venv/bin/python -m pytest tests/core/test_narrowband.py -q` from `/Volumes/Work/Code/Editor`.
- `~x = 1-x`; `mtf(m,x) = ((m-1)x)/((2m-1)x - m)` — **reuse** `from .autostretch import _mtf` (do not re-implement).
- NBN defaults: blackpoint 1.0, oiii_boost 1.0, blend_amount 0.6, highlight_reduction 1.0, brightness 1.0, highlight_recover 1.0, saturation 0.6.
- Pure numpy, Qt-free. **No app/UI changes, nothing removed** — this increment is the core module + tests + a scratch validation script only. `core/palette.py` is NOT touched.
- All outputs `np.float32`, clipped to [0,1].
- Commit with trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Normalization core — `channel_level`, `normalize_to_reference`

**Files:**
- Create: `nocturne/core/narrowband.py`
- Test: `tests/core/test_narrowband.py`

**Interfaces:**
- Consumes: `nocturne/core/autostretch._mtf(m: float, x: np.ndarray) -> np.ndarray`.
- Produces:
  - `channel_level(c: np.ndarray, blackpoint: float) -> tuple[float, float]` returning `(M, E0)`.
  - `normalize_to_reference(secondary, reference, blackpoint=1.0, boost=1.0) -> np.ndarray` — the NBN OIII→Ha match, with degenerate guards (identity, no NaN).

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_narrowband.py`:

```python
import numpy as np

from nocturne.core.narrowband import channel_level, normalize_to_reference


def _grad(median, spread=0.05, shape=(64, 64), seed=0):
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(median, spread, shape), 0.0, 1.0).astype(np.float32)


def test_channel_level_blackpoint_interpolates_min_median():
    c = _grad(0.3)
    M0, _ = channel_level(c, 0.0)          # blackpoint 0 → at min
    M1, _ = channel_level(c, 1.0)          # blackpoint 1 → at median
    assert M0 < M1
    assert abs(M1 - float(np.median(c))) < 1e-6
    assert abs(M0 - float(c.min())) < 1e-6


def test_normalize_lifts_faint_oiii_toward_ha():
    ha = _grad(0.40, seed=1)
    oiii = _grad(0.12, seed=2)             # much fainter
    before = abs(float(np.median(oiii)) - float(np.median(ha)))
    out = normalize_to_reference(oiii, ha, blackpoint=1.0, boost=1.0)
    after = abs(float(np.median(out)) - float(np.median(ha)))
    assert after < before                  # OIII level moved toward Ha
    assert np.isfinite(out).all()
    assert out.dtype == np.float32


def test_normalize_boost_lifts_further():
    ha = _grad(0.40, seed=1)
    oiii = _grad(0.12, seed=2)
    base = float(np.median(normalize_to_reference(oiii, ha, 1.0, 1.0)))
    boosted = float(np.median(normalize_to_reference(oiii, ha, 1.0, 0.7)))  # boost = /0.7 > 1
    assert boosted > base


def test_normalize_degenerate_oiii_is_identity_no_nan():
    ha = _grad(0.40, seed=1)
    zero = np.zeros((64, 64), dtype=np.float32)
    out = normalize_to_reference(zero, ha, 1.0, 1.0)
    assert np.isfinite(out).all()
    assert np.allclose(out, zero)          # empty OIII → unchanged
    same = normalize_to_reference(ha, ha, 1.0, 1.0)   # OIII ≈ Ha
    assert np.isfinite(same).all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/core/test_narrowband.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'nocturne.core.narrowband'`.

- [ ] **Step 3: Implement in `nocturne/core/narrowband.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .autostretch import _mtf
from .image import AstroImage
from .saturation import saturate


def channel_level(c: np.ndarray, blackpoint: float) -> tuple[float, float]:
    """NBN per-channel black point M and robust signal level E0.
    M = min + blackpoint*(median - min); E0 = adev/1.2533 + mean - M."""
    c = np.asarray(c, dtype=np.float32)
    lo = float(c.min())
    med = float(np.median(c))
    mean = float(c.mean())
    M = lo + float(blackpoint) * (med - lo)
    adev = float(np.mean(np.abs(c - mean)))          # PixInsight adev (mean abs deviation)
    E0 = adev / 1.2533 + mean - M
    return M, E0


def normalize_to_reference(secondary: np.ndarray, reference: np.ndarray,
                           blackpoint: float = 1.0, boost: float = 1.0) -> np.ndarray:
    """NBN normalization: MTF-match the secondary channel's robust level to the
    reference's. Returns the normalized secondary (2D float32). Degenerate inputs
    (faint/empty channel, near-equal levels) fall back to identity — no NaN."""
    sec = np.clip(np.asarray(secondary, dtype=np.float32), 0.0, 1.0)
    ref = np.clip(np.asarray(reference, dtype=np.float32), 0.0, 1.0)
    M_sec, E0_sec = channel_level(sec, blackpoint)
    _, E0_ref = channel_level(ref, blackpoint)
    headroom = 1.0 - M_sec
    if headroom <= 1e-6:
        return sec
    A_sec = E0_sec / headroom
    A_ref = E0_ref / headroom
    denom = A_sec - 2.0 * A_sec * A_ref + A_ref
    if abs(denom) < 1e-6 or A_sec <= 1e-6 or A_ref <= 1e-6:
        return sec
    m = float(np.clip((A_sec * (1.0 - A_ref) / denom) / boost, 1e-3, 1.0 - 1e-3))
    e2 = np.clip((sec - M_sec) / max(1e-6, 1.0 - M_sec), 0.0, 1.0)      # rescale [M,1]->[0,1]
    stretched = _mtf(m, e2)
    sub = np.minimum(sec, M_sec)                                        # sub-blackpoint part
    out = 1.0 - (1.0 - stretched) * (1.0 - sub)                        # ~(~mtf * ~sub)
    return np.clip(out, 0.0, 1.0).astype(np.float32)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/core/test_narrowband.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/core/narrowband.py tests/core/test_narrowband.py
git commit -m "feat(narrowband): NBN normalization core (black point, level, MTF match)"
```

---

### Task 2: Blend + tone helpers

**Files:**
- Modify: `nocturne/core/narrowband.py`
- Test: `tests/core/test_narrowband.py`

**Interfaces:**
- Consumes: `_mtf` (already imported).
- Produces:
  - `extract_ha_oiii(img: AstroImage) -> tuple[np.ndarray, np.ndarray]` (Ha=red, OIII=(G+B)/2).
  - `synthetic_green(ha, oiii, amount=0.6) -> np.ndarray`.
  - `highlight_reduction(x, amount=1.0)`, `brightness(x, amount=1.0)`, `highlight_recover(x, amount=1.0)` — each identity at amount 1.0.

- [ ] **Step 1: Write the failing tests**

Append to `tests/core/test_narrowband.py`:

```python
from nocturne.core.narrowband import (
    brightness, extract_ha_oiii, highlight_recover, highlight_reduction,
    synthetic_green,
)
from nocturne.core.image import AstroImage


def test_extract_ha_oiii_mapping():
    data = np.zeros((4, 4, 3), dtype=np.float32)
    data[..., 0] = 0.6      # red = Ha
    data[..., 1] = 0.2      # green
    data[..., 2] = 0.4      # blue -> OIII = (0.2+0.4)/2 = 0.3
    ha, oiii = extract_ha_oiii(AstroImage(data))
    assert np.allclose(ha, 0.6)
    assert np.allclose(oiii, 0.3)


def test_extract_ha_oiii_rejects_mono():
    import pytest
    with pytest.raises(ValueError):
        extract_ha_oiii(AstroImage(np.zeros((4, 4), dtype=np.float32)))


def test_synthetic_green_amount_zero_is_oiii():
    ha = np.full((8, 8), 0.7, dtype=np.float32)
    oiii = np.full((8, 8), 0.2, dtype=np.float32)
    assert np.allclose(synthetic_green(ha, oiii, 0.0), oiii)


def test_synthetic_green_bounded_between_channels():
    rng = np.random.default_rng(0)
    ha = rng.random((16, 16)).astype(np.float32)
    oiii = rng.random((16, 16)).astype(np.float32)
    g = synthetic_green(ha, oiii, 0.6)
    lo = np.minimum(ha, oiii)
    hi = np.maximum(ha, oiii)
    assert np.all(g >= lo - 1e-5) and np.all(g <= hi + 1e-5)


def test_tone_stages_identity_at_one():
    x = np.linspace(0, 1, 50, dtype=np.float32)
    assert np.allclose(highlight_reduction(x, 1.0), x, atol=1e-4)
    assert np.allclose(brightness(x, 1.0), x, atol=1e-4)
    assert np.allclose(highlight_recover(x, 1.0), x, atol=1e-4)


def test_brightness_direction():
    x = np.full((8, 8), 0.4, dtype=np.float32)
    assert brightness(x, 2.0).mean() > x.mean()    # >1 brightens
    assert brightness(x, 0.6).mean() < x.mean()    # <1 darkens


def test_highlight_recover_scales_down():
    x = np.full((8, 8), 0.8, dtype=np.float32)
    assert np.allclose(highlight_recover(x, 2.0), 0.4)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/core/test_narrowband.py -q`
Expected: FAIL on the new imports (`cannot import name 'extract_ha_oiii'`).

- [ ] **Step 3: Implement — append to `nocturne/core/narrowband.py`**

```python
def extract_ha_oiii(img: AstroImage) -> tuple[np.ndarray, np.ndarray]:
    """Broadband → pseudo-channels: Ha = red, OIII = (green+blue)/2. 2D float32."""
    if not img.is_color:
        raise ValueError("Narrowband palette needs a colour image")
    data = np.clip(img.data, 0.0, 1.0)
    ha = data[..., 0].astype(np.float32)
    oiii = ((data[..., 1] + data[..., 2]) / 2.0).astype(np.float32)
    return ha, oiii


def synthetic_green(ha: np.ndarray, oiii: np.ndarray, amount: float = 0.6) -> np.ndarray:
    """Blanshan/Foraxx dynamic green blend, mixed toward OIII by (1-amount).
    amount=0 → pure OIII; amount=1 → full dynamic blend."""
    ha = np.clip(ha, 0.0, 1.0).astype(np.float32)
    oiii = np.clip(oiii, 0.0, 1.0).astype(np.float32)
    p = np.clip(ha * oiii, 0.0, 1.0)
    w = np.power(p, 1.0 - p).astype(np.float32)          # dynamic per-pixel weight
    dynamic = w * ha + (1.0 - w) * oiii
    g = float(amount) * dynamic + (1.0 - float(amount)) * oiii
    return np.clip(g, 0.0, 1.0).astype(np.float32)


def highlight_reduction(x: np.ndarray, amount: float = 1.0) -> np.ndarray:
    """NBN E11: reversed-curve highlight taming. Identity at amount=1.0."""
    x = np.clip(np.asarray(x, dtype=np.float32), 0.0, 1.0)
    m = float(np.clip(1.0 - 0.5 / amount, 1e-3, 1.0 - 1e-3))
    return np.clip(_mtf(m, x) * x + x * (1.0 - x), 0.0, 1.0).astype(np.float32)


def brightness(x: np.ndarray, amount: float = 1.0) -> np.ndarray:
    """NBN E12: overall brightness MTF. Identity at amount=1.0; >1 brighter."""
    x = np.clip(np.asarray(x, dtype=np.float32), 0.0, 1.0)
    m = float(np.clip(0.5 / amount, 1e-3, 1.0 - 1e-3))
    return np.clip(_mtf(m, x), 0.0, 1.0).astype(np.float32)


def highlight_recover(x: np.ndarray, amount: float = 1.0) -> np.ndarray:
    """NBN E13: rescale(x, 0, amount) — divide down to recover clipped highlights."""
    x = np.clip(np.asarray(x, dtype=np.float32), 0.0, 1.0)
    return np.clip(x / max(1e-6, amount), 0.0, 1.0).astype(np.float32)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/core/test_narrowband.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/core/narrowband.py tests/core/test_narrowband.py
git commit -m "feat(narrowband): synthetic-green blend + NBN tone stages"
```

---

### Task 3: `NarrowbandParams` + `render_hoo` pipeline

**Files:**
- Modify: `nocturne/core/narrowband.py`
- Test: `tests/core/test_narrowband.py`

**Interfaces:**
- Consumes: everything from Tasks 1–2, `saturation.saturate` (imported).
- Produces:
  - `NarrowbandParams` dataclass (fields per Global Constraints defaults).
  - `render_hoo(img: AstroImage, params: NarrowbandParams) -> AstroImage`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/core/test_narrowband.py`:

```python
from nocturne.core.narrowband import NarrowbandParams, render_hoo


def test_params_defaults():
    p = NarrowbandParams()
    assert p.palette == "HOO"
    assert (p.blackpoint, p.oiii_boost, p.blend_amount) == (1.0, 1.0, 0.6)
    assert (p.highlight_reduction, p.brightness, p.highlight_recover) == (1.0, 1.0, 1.0)
    assert p.saturation == 0.6


def _dualband(shape=(48, 48)):
    """Synthetic dual-band-ish frame: strong Ha (red), faint OIII in a patch."""
    data = np.zeros((*shape, 3), dtype=np.float32)
    data[..., 0] = 0.45                      # Ha everywhere (red)
    data[:, :24, 1] = 0.30                    # OIII present on the left half (green+blue)
    data[:, :24, 2] = 0.30
    return AstroImage(data)


def test_render_hoo_makes_oiii_region_teal():
    out = render_hoo(_dualband(), NarrowbandParams())
    assert out.is_color and out.data.dtype == np.float32
    assert float(out.data.max()) <= 1.0 and float(out.data.min()) >= 0.0
    left = out.data[:, :24]                   # has OIII → should carry green+blue (teal)
    right = out.data[:, 24:]                  # Ha only → red-dominant
    assert left[..., 2].mean() > right[..., 2].mean()      # more blue where OIII exists
    assert left[..., 2].mean() > left[..., 0].mean() * 0.3  # OIII region is visibly non-red


def test_render_hoo_does_not_blow_out_or_blur():
    img = _dualband()
    out = render_hoo(img, NarrowbandParams())
    assert float(out.data.mean()) < 0.98                    # not blown to white
    # per-pixel op: a lone hot pixel does not smear into neighbours
    spiky = img.data.copy(); spiky[10, 10, 0] = 1.0
    o2 = render_hoo(AstroImage(spiky), NarrowbandParams())
    assert o2.data[10, 11, 0] == render_hoo(img, NarrowbandParams()).data[10, 11, 0]


def test_render_hoo_rejects_mono():
    import pytest
    with pytest.raises(ValueError):
        render_hoo(AstroImage(np.zeros((8, 8), dtype=np.float32)), NarrowbandParams())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/core/test_narrowband.py -q`
Expected: FAIL (`cannot import name 'render_hoo'`).

- [ ] **Step 3: Implement — append to `nocturne/core/narrowband.py`**

```python
@dataclass
class NarrowbandParams:
    palette: str = "HOO"
    blackpoint: float = 1.0
    oiii_boost: float = 1.0
    blend_amount: float = 0.6
    highlight_reduction: float = 1.0
    brightness: float = 1.0
    highlight_recover: float = 1.0
    saturation: float = 0.6


def render_hoo(img: AstroImage, params: NarrowbandParams) -> AstroImage:
    """HOO narrowband palette: normalize OIII→Ha, build synthetic green, apply
    NBN tone stages + saturation. Operates on a stretched (display-range) image."""
    ha, oiii = extract_ha_oiii(img)
    oiii_n = normalize_to_reference(oiii, ha, params.blackpoint, params.oiii_boost)
    r = ha
    g = synthetic_green(ha, oiii_n, params.blend_amount)
    b = oiii_n
    rgb = np.stack([r, g, b], axis=2).astype(np.float32)
    rgb = highlight_reduction(rgb, params.highlight_reduction)
    rgb = brightness(rgb, params.brightness)
    rgb = highlight_recover(rgb, params.highlight_recover)
    tinted = AstroImage(np.clip(rgb, 0.0, 1.0).astype(np.float32),
                        is_linear=False, metadata=dict(img.metadata))
    out = saturate(tinted, params.saturation)
    return AstroImage(np.clip(out.data, 0.0, 1.0).astype(np.float32),
                      is_linear=False, metadata=dict(img.metadata))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/core/test_narrowband.py -q`
Expected: all PASS.

- [ ] **Step 5: Run the full core suite (no regressions — module is additive)**

Run: `.venv/bin/python -m pytest tests/core/ -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add nocturne/core/narrowband.py tests/core/test_narrowband.py
git commit -m "feat(narrowband): NarrowbandParams + render_hoo HOO pipeline"
```

---

### Task 4: Real-data validation on the NGC 7000 LP master

**Files:** none committed — a scratch validation script only.

- [ ] **Step 1: Full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 2: Render HOO on the real master and produce comparison crops**

Write a scratch script at `<scratchpad>/validate_narrowband.py` (do NOT commit) that:
- loads `/Volumes/Work2/Images/Astro/NGC 7000_sub/lights/NGC7000_182x20s_61min.fits`;
- makes a display-range image with `nocturne.core.stretch.apply_stretch(img, 0.5)` (this is the "finishing step on the edited image");
- renders `render_hoo(stretched, NarrowbandParams())`;
- also renders the current `nocturne.core.palette.render_nebula(stretched_starless_or_stretched, PaletteParams(palette="HOO"))` for side-by-side (extract via the existing path — if it needs starless, run on the stretched image directly, matching whole-image fallback);
- saves matched centre crops (`narrowband_hoo_new.png`, `narrowband_hoo_old.png`) plus the plain stretched input (`narrowband_input.png`).

```python
import os, sys
sys.path.insert(0, "/Volumes/Work/Code/Editor")
import numpy as np
from PIL import Image
from nocturne.core.fits_io import load_fits
from nocturne.core.stretch import apply_stretch
from nocturne.core.narrowband import render_hoo, NarrowbandParams
from nocturne.core.palette import render_nebula, PaletteParams

OUT = "<scratchpad>"
img = load_fits("/Volumes/Work2/Images/Astro/NGC 7000_sub/lights/NGC7000_182x20s_61min.fits")
stretched = apply_stretch(img, 0.5)

def crop(a, name):
    h, w = a.shape[:2]
    c = a[h//2-400:h//2+400, w//2-400:w//2+400]
    Image.fromarray((np.clip(c,0,1)*255).astype(np.uint8)).save(f"{OUT}/{name}")

crop(stretched.data, "narrowband_input.png")
crop(render_hoo(stretched, NarrowbandParams()).data, "narrowband_hoo_new.png")
try:
    crop(render_nebula(stretched, PaletteParams(palette="HOO")).data, "narrowband_hoo_old.png")
except Exception as e:
    print("old palette path failed (fine):", e)
print("DONE")
```

Run: `.venv/bin/python <scratchpad>/validate_narrowband.py`

- [ ] **Step 3: Present the crops to the user**

Read `narrowband_input.png`, `narrowband_hoo_new.png`, `narrowband_hoo_old.png` and present them side by side. Ask the user how the new HOO output compares to what NarrowbandNormalization gives them in PixInsight on the same file — and whether the teal/OIII balance, background neutrality, and overall look are close. Record their reaction as the steer for iterating `synthetic_green` / defaults (still within this pure module) or for greenlighting Increment 2.

- [ ] **Step 4: Note follow-ups**

If the user wants tuning, iterate defaults/blend in `narrowband.py` (with tests) before closing. Otherwise record in `TODO.md` that Increment 1 (narrowband core, HOO) is done and Increment 2 (standalone dialog + tool, remove old Colourise/palette) is next.

```bash
git add TODO.md && git commit -m "docs: narrowband Increment 1 (HOO core) done; Increment 2 next"
```

---

## Self-Review Notes

- Spec coverage: normalization core (Task 1), extract/blend/tone (Task 2), params+render_hoo (Task 3), real-data validation (Task 4). Degenerate guards in Task 1 cover the spec's error-handling. `mtf`/`saturate` reuse per spec.
- Type consistency: `channel_level → (M, E0)`, `normalize_to_reference(secondary, reference, blackpoint, boost)`, `synthetic_green(ha, oiii, amount)`, `render_hoo(img, params)` used identically across tasks; `NarrowbandParams` field names match `render_hoo` and the defaults in Global Constraints.
- No placeholders; every code step shows complete code. `<scratchpad>` in Task 4 is the session scratchpad path, substituted at run time (scratch only, uncommitted).
