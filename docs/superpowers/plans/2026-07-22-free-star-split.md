# Free Star Split (no-RC-Astro fallback) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A free `split_stars(img) → (starless, stars)` (sep-based) that lets Star Reduction, Remove Green Fringe, and the Nebula boost work without RC-Astro StarXTerminator.

**Architecture:** New pure-numpy `core/starless.py` detects stars with `sep`, fills the holes with a fast local-median background, and derives **screen-compatible** star layers (screen-recombine reconstructs the original exactly). A resolver picks StarX when RC-Astro is present, else the free split; the three steps + their live previews route through it; the UI stops gating them.

**Tech Stack:** Python, numpy, `sep`, scipy.ndimage (`gaussian_filter`), skimage (`resize`), PySide6.

## Global Constraints

- **Screen-compatibility (verified):** the free split MUST satisfy `1-(1-starless)*(1-stars) == img` exactly, so it drops into the steps' existing screen recombine and matches the StarX-`--unscreen` behaviour. Derive stars as `clip(1 - (1-img)/max(1-starless, 1e-4), 0, 1)`.
- **Availability, not quality:** it will be rougher than StarX (faint stars missed, big stars leave residual). Present honestly; never claim StarX quality.
- **No change when RC-Astro is present:** StarX is always used then. The free path is only for `rc is None` / `not rcastro_valid`.
- **Operates on display-space (stretched) images** — the domain the three steps run in.
- **Degenerate inputs** (no detections, `sep` failure): return an identity split — `starless = img.copy()`, `stars = zeros` — so the steps become no-ops, never crash.
- Keep the full suite green. Stage only named files (pre-existing untracked strays exist — never `git add -A`).

---

### Task 1: Core — `split_stars`

**Files:**
- Create: `nocturne/core/starless.py`
- Test: `tests/core/test_starless.py`

**Interfaces:**
- Consumes: `nocturne.core.image.AstroImage`; `sep`; `scipy.ndimage.gaussian_filter`; `skimage.transform.resize`; `scipy.ndimage.median_filter`.
- Produces: `split_stars(img: AstroImage) -> tuple[AstroImage, AstroImage]` (starless, stars).

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_starless.py`:

```python
import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.starless import split_stars


def _scene(h=200, w=200, seed=0):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    neb = 0.25 + 0.12 * np.exp(-(((yy - h // 2) ** 2 + (xx - w // 2) ** 2) / (2 * 50 ** 2)))
    img = neb + 0.02 * rng.standard_normal((h, w))
    stars = np.zeros((h, w), np.float32)
    for _ in range(60):
        cy, cx = rng.integers(8, h - 8), rng.integers(8, w - 8)
        stars += rng.uniform(0.2, 0.9) * np.exp(
            -(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * rng.uniform(0.9, 2.2) ** 2)))
    return np.clip(img + stars, 0, 1).astype(np.float32)


def test_screen_recombine_reconstructs_exactly():
    data = _scene()
    img = AstroImage(np.stack([data] * 3, axis=2), is_linear=False)
    starless, stars = split_stars(img)
    recon = 1.0 - (1.0 - starless.data) * (1.0 - stars.data)
    assert np.abs(recon - img.data).max() < 1e-4          # screen recombine == original


def test_starless_removes_star_peaks_keeps_nebula():
    data = _scene()
    img = AstroImage(np.stack([data] * 3, axis=2), is_linear=False)
    starless, _ = split_stars(img)
    assert starless.data.max() < img.data.max() - 0.05    # bright star peaks pulled down
    # a star-free nebula corner is essentially unchanged
    corner = (slice(0, 12), slice(0, 12))
    assert np.abs(starless.data[corner] - img.data[corner]).mean() < 0.02
    assert np.isfinite(starless.data).all()


def test_no_stars_is_identity_split():
    flat = np.full((40, 40, 3), 0.3, np.float32)          # nothing for sep to find
    img = AstroImage(flat, is_linear=False)
    starless, stars = split_stars(img)
    assert np.allclose(starless.data, flat)
    assert np.allclose(stars.data, 0.0)


def test_mono_image_splits():
    data = _scene()
    img = AstroImage(data, is_linear=False)               # 2-D
    starless, stars = split_stars(img)
    recon = 1.0 - (1.0 - starless.data) * (1.0 - stars.data)
    assert np.abs(recon - img.data).max() < 1e-4
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/core/test_starless.py -q`
Expected: FAIL — `ModuleNotFoundError: nocturne.core.starless`.

- [ ] **Step 3: Implement `split_stars`**

Create `nocturne/core/starless.py`:

```python
"""Free star/starless split — a no-RC-Astro fallback for the star-separation
steps. Detects stars with `sep`, fills the holes with a fast local-median
background, and derives screen-compatible star layers so that
`1-(1-starless)*(1-stars)` reconstructs the original exactly. Rougher than
StarXTerminator (faint stars are missed, big stars leave some residual) — an
availability fallback, not a quality match.
"""
from __future__ import annotations

import numpy as np
import sep
from scipy.ndimage import gaussian_filter, median_filter
from skimage.transform import resize

from .image import AstroImage

_THRESH = 4.0        # sep detection threshold (sigma above background)
_RMIN, _RMAX = 2, 12  # star mask radius clamp (px)
_RFAC = 2.5          # mask radius = _RFAC * sqrt(a*b)
_FEATHER = 2.0       # gaussian feather of the star mask (px)
_BG_STEP = 4         # local-median background downscale factor (speed)
_BG_MED = 5          # median window on the downscaled image


def _local_background(data: np.ndarray) -> np.ndarray:
    """Smooth local background for filling star holes: a median at 1/_BG_STEP
    scale (fast), upscaled. Median rejects the bright star, so the fill doesn't
    inherit the star's glow the way a gaussian would."""
    small = data[::_BG_STEP, ::_BG_STEP]
    if small.ndim == 3:
        med = np.stack([median_filter(small[..., c], size=_BG_MED)
                        for c in range(small.shape[2])], axis=2)
    else:
        med = median_filter(small, size=_BG_MED)
    return resize(med, data.shape, order=1, preserve_range=True,
                  anti_aliasing=False).astype(np.float32)


def _star_mask(lum: np.ndarray) -> np.ndarray:
    """Feathered 0..1 mask of detected stars (empty if none / sep fails)."""
    h, w = lum.shape
    mask = np.zeros((h, w), np.float32)
    try:
        bkg = sep.Background(np.ascontiguousarray(lum))
        obj = sep.extract(lum - bkg.back(), _THRESH, err=bkg.globalrms)
    except Exception:
        return mask
    for o in obj:
        r = int(np.clip(_RFAC * np.sqrt(float(o["a"]) * float(o["b"])), _RMIN, _RMAX))
        y0, y1 = max(0, int(o["y"]) - r), min(h, int(o["y"]) + r + 1)
        x0, x1 = max(0, int(o["x"]) - r), min(w, int(o["x"]) + r + 1)
        if y1 <= y0 or x1 <= x0:
            continue
        gy, gx = np.mgrid[y0:y1, x0:x1]
        mask[y0:y1, x0:x1] = np.maximum(
            mask[y0:y1, x0:x1],
            ((gy - o["y"]) ** 2 + (gx - o["x"]) ** 2 <= r * r).astype(np.float32))
    if mask.max() <= 0.0:
        return mask
    return np.clip(gaussian_filter(mask, _FEATHER), 0.0, 1.0)


def split_stars(img: AstroImage) -> tuple[AstroImage, AstroImage]:
    """Free (starless, stars) split. `stars` is screen-compatible: the steps'
    `1-(1-starless)*(1-stars)` reconstructs the original exactly."""
    data = np.clip(img.data.astype(np.float32), 0.0, 1.0)
    mono = data.ndim == 2
    lum = data if mono else data.mean(axis=2)
    mask = _star_mask(np.ascontiguousarray(lum, dtype=np.float32))

    def _wrap(a):
        return AstroImage(np.clip(a, 0.0, 1.0).astype(np.float32),
                          is_linear=img.is_linear, metadata=dict(img.metadata))

    if mask.max() <= 0.0:                                   # no stars -> identity split
        return _wrap(data.copy()), _wrap(np.zeros_like(data))

    bg = _local_background(data)
    m = mask if mono else mask[..., None]
    starless = (1.0 - m) * data + m * np.minimum(data, bg)  # fill holes, never brighten
    starless = np.clip(starless, 0.0, 1.0).astype(np.float32)
    stars = np.clip(1.0 - (1.0 - data) / np.clip(1.0 - starless, 1e-4, None), 0.0, 1.0)
    return _wrap(starless), _wrap(stars)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/core/test_starless.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (existing count + 4).

- [ ] **Step 6: Commit**

```bash
git add nocturne/core/starless.py tests/core/test_starless.py
git commit -m "feat(starless): free sep-based star split (screen-compatible starless/stars)"
```

---

### Task 2: Resolver + wire the three steps + factory

**Files:**
- Create: `nocturne/steps/star_split.py`
- Modify: `nocturne/steps/star_reduction.py`, `nocturne/steps/green_fringe.py`, `nocturne/steps/saturation_step.py`
- Modify: `nocturne/steps/factory.py`
- Test: `tests/steps/test_new_steps.py`

**Interfaces:**
- Consumes: `split_stars` (Task 1); `RCAstro.remove_stars`.
- Produces: `resolve_star_split(img, rc, runner=run_cli) -> (starless, stars)` — `rc.remove_stars(img, runner=runner)` if `rc` is not None, else `split_stars(img)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/steps/test_new_steps.py`:

```python
def test_resolve_star_split_picks_free_when_no_rcastro(monkeypatch):
    from nocturne.core.image import AstroImage
    from nocturne.steps import star_split
    import numpy as np
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=False)
    called = {"free": False, "rc": False}

    def fake_free(i):
        called["free"] = True
        return i, i
    monkeypatch.setattr(star_split, "split_stars", fake_free)

    class FakeRC:
        def remove_stars(self, i, runner=None):
            called["rc"] = True
            return i, i

    star_split.resolve_star_split(img, None)              # no RC-Astro -> free
    assert called == {"free": True, "rc": False}
    called.update(free=False, rc=False)
    star_split.resolve_star_split(img, FakeRC())          # RC-Astro -> StarX
    assert called == {"free": False, "rc": True}


def test_star_split_steps_work_without_rcastro():
    # Each of the three steps, built with rc=None, changes the image via the free split.
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.steps.star_reduction import StarReductionStep
    from nocturne.steps.green_fringe import GreenFringeStep
    from nocturne.steps.saturation_step import SaturationStep
    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[0:40, 0:40]
    data = np.clip(0.3 + 0.4 * np.exp(-(((yy - 20) ** 2 + (xx - 20) ** 2) / (2 * 1.5 ** 2)))
                   + 0.02 * rng.standard_normal((40, 40)), 0, 1).astype(np.float32)
    img = AstroImage(np.stack([data] * 3, axis=2), is_linear=False)
    assert StarReductionStep(None).apply(img, 0.6).data.shape == (40, 40, 3)
    assert GreenFringeStep(None).apply(img, 1.0).data.shape == (40, 40, 3)
    assert SaturationStep(None).apply(img, (0.5, 0.6)).data.shape == (40, 40, 3)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/steps/test_new_steps.py -k "star_split or without_rcastro" -q`
Expected: FAIL — `nocturne.steps.star_split` missing; the steps' `__init__` reject `None` / call `rc.remove_stars` on None.

- [ ] **Step 3: Create the resolver**

Create `nocturne/steps/star_split.py`:

```python
from __future__ import annotations

from ..core.image import AstroImage
from ..core.starless import split_stars
from ..tools.base import run_cli


def resolve_star_split(img: AstroImage, rc, runner=run_cli):
    """(starless, stars) via StarXTerminator when `rc` is available, else the
    free sep-based split. Both are screen-recombine compatible."""
    if rc is not None:
        return rc.remove_stars(img, runner=runner)
    return split_stars(img)
```

- [ ] **Step 4: Route the three steps through the resolver**

`nocturne/steps/star_reduction.py` — make `rcastro` optional and use the resolver:

```python
    def __init__(self, rcastro: RCAstro | None = None) -> None:
        self._rc = rcastro
        self._runner = run_cli
```
and in `apply`, replace `starless, stars = self._rc.remove_stars(img, runner=self._runner)` with:
```python
        from .star_split import resolve_star_split
        starless, stars = resolve_star_split(img, self._rc, runner=self._runner)
```

`nocturne/steps/green_fringe.py` — same two changes (`rcastro: RCAstro | None = None`, and the resolver call in `apply`).

`nocturne/steps/saturation_step.py` — `__init__` to `rcastro: RCAstro | None`, and in `apply` replace the `remove_stars` line inside the `if nebula > 0.0:` block with:
```python
            from .star_split import resolve_star_split
            starless, stars = resolve_star_split(img, self._rc, runner=self._runner)
```

- [ ] **Step 5: Factory builds them rc-or-None**

In `nocturne/steps/factory.py`, change the `saturation`, `green_fringe`, and `star_reduction` cases so `rc` is `None` when RC-Astro is absent (matching the `deconvolution`/`noise_sharpen` cases):

```python
    if stage_id == "saturation":
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        step = SaturationStep(rc)
        step._runner = rc_runner
        return step
    if stage_id == "green_fringe":
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        step = GreenFringeStep(rc)
        step._runner = rc_runner
        return step
```
and:
```python
    if stage_id == "star_reduction":
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        step = StarReductionStep(rc)
        step._runner = rc_runner
        return step
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/steps/test_new_steps.py -k "star_split or without_rcastro" -q`
Expected: PASS. Also confirm the pre-existing saturation/green-fringe/star-reduction step tests still pass (they construct the steps with a fake/real rc, which is still accepted).

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add nocturne/steps/star_split.py nocturne/steps/star_reduction.py nocturne/steps/green_fringe.py nocturne/steps/saturation_step.py nocturne/steps/factory.py tests/steps/test_new_steps.py
git commit -m "feat(steps): route star-split steps through StarX-or-free resolver (factory rc-or-None)"
```

---

### Task 3: Ungate the three panels + free-detection note

**Files:**
- Modify: `nocturne/ui/main_window.py` (`_remove_stars`, `_setup_saturation`, `_on_sat_change`, `_setup_green_fringe`, `_setup_star_reduction`)
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `split_stars` (Task 1) for the live-preview resolver.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_main_window.py`:

```python
def test_star_reduction_ungated_without_rcastro(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    monkeypatch.setattr(mw, "rcastro_valid", lambda s: False)   # simulate no RC-Astro
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch"); win.apply_current(0.6)
    win._go_to_id("star_reduction")
    # panel slider is ENABLED (not gated) and shows a free-detection note, not "Needs RC-Astro"
    assert win._panel.sr_slider.isEnabled() is True
    assert "RC-Astro" in win._panel.sr_status.text()            # note mentions RC-Astro
    assert "Needs RC-Astro" not in win._panel.sr_status.text()  # but not the old gate text


def test_remove_stars_uses_free_split_without_rcastro(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    import numpy as np
    monkeypatch.setattr(mw, "rcastro_valid", lambda s: False)
    used = {"free": False}
    monkeypatch.setattr(mw, "split_stars",
                        lambda img: (used.__setitem__("free", True) or (img, img)))
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    img = win.project.current()
    win._remove_stars(img)
    assert used["free"] is True                                 # free split, no RC-Astro call
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -k "ungated or free_split" -q`
Expected: FAIL — the panel is still gated / `_remove_stars` always builds RCAstro.

- [ ] **Step 3: `_remove_stars` resolves StarX-or-free**

In `nocturne/ui/main_window.py`, add `split_stars` to the imports (near the other core imports), then change `_remove_stars`:

```python
    def _remove_stars(self, img):
        if rcastro_valid(self.settings):
            rc = RCAstro(resolve_binary(self.settings.rcastro_path))
            return rc.remove_stars(img, runner=self._rc_runner)
        return split_stars(img)
```

- [ ] **Step 4: Ungate the three setup handlers**

Define a note constant near the top of the class or module:
```python
_FREE_STAR_NOTE = "Using free star detection — set RC-Astro (StarX) in Settings for cleaner separation."
```

**`_setup_saturation`** — replace the `if rcastro_valid(...): enable/clear else: disable/needs-note` block with: always enable the Nebula slider, and show the free note when RC-Astro is absent:
```python
        self._panel.neb_slider.setEnabled(True)
        self._panel.neb_status.setText("" if rcastro_valid(self.settings) else _FREE_STAR_NOTE)
```
**`_on_sat_change`** — drop the `rcastro_valid` condition so the nebula split runs (free or StarX) whenever the nebula slider is raised:
```python
        if nebula > 0.0 and not self._busy:
```

**`_setup_green_fringe`** — replace the `if not rcastro_valid: disable + return` block so it never returns early; show the note when RC-Astro is absent, then fall through to the normal split/cache path:
```python
        if not rcastro_valid(self.settings) and hasattr(panel, "fringe_status"):
            panel.fringe_status.setText(_FREE_STAR_NOTE)
        # (fall through — the split runs via _remove_stars, free or StarX)
```
(Keep the slider/apply ENABLED. Do not set `_fringe_ready = False` / return.)

**`_setup_star_reduction`** — same: replace the `if not rcastro_valid: disable + return` block with a note-only version that falls through to the split/cache path, leaving `sr_slider`/apply enabled:
```python
        if not rcastro_valid(self.settings) and hasattr(panel, "sr_status"):
            panel.sr_status.setText(_FREE_STAR_NOTE)
```

Read each handler's surrounding code and remove exactly the disable+return lines while preserving the rest of the split/cache logic that follows.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -k "ungated or free_split" -q`
Expected: PASS (2 tests).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. Confirm no existing saturation/green-fringe/star-reduction UI tests broke (they may have asserted the gated behaviour — if so, update them to the ungated behaviour, since gating is now intentionally removed).

- [ ] **Step 7: Commit**

```bash
git add nocturne/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat(ui): ungate Star Reduction / Green Fringe / Nebula boost without RC-Astro (free split + note)"
```

---

## After all tasks

- Whole-branch review (opus): screen-compatibility of the free split, resolver correctness (free only when rc is None), no regression when RC-Astro IS present, the ungating leaves no dead "Needs RC-Astro" gate, recipe/batch replay works with rc=None.
- **User real-data validation (RC-Astro path cleared):** do Star Reduction / Remove Green Fringe / Nebula boost now work and look acceptable? Tune `split_stars` constants (`_THRESH`, `_RFAC`, `_RMIN/_RMAX`, `_FEATHER`, `_BG_STEP/_BG_MED`) and the note wording. Confirm no change when RC-Astro is configured. Check the free split isn't too slow on full-res (the async "Separating stars…" path covers it).
- Then `superpowers:finishing-a-development-branch`.

## Help / docs (fold into Task 3 if quick; else TODO)

- Update the Star Reduction / Remove Green Fringe / Saturation help topics: they now work without RC-Astro via free star detection (rougher; RC-Astro is cleaner). Non-blocking.
