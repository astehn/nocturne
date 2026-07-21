# Masked Nebula Saturation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Nebula boost" to the Saturation step — a star-separated, mask-aware saturation that lifts nebulosity (faint included) while leaving the sky background and stars untouched.

**Architecture:** A new `nebula_saturate(starless, stars, strength)` (StarX split → sky-anchored nebula mask → in-mask chroma boost → screen stars back) runs BEFORE the existing global `saturate()`. It's wired into the existing Saturation step as a second slider, with a lazily-triggered cached StarX split (RC-Astro-gated, Green-Fringe pattern). The step option becomes `(amount, nebula)`.

**Tech Stack:** Python, NumPy, scikit-image (`gaussian`), PySide6, RC-Astro StarXTerminator, pytest. No new third-party dependency.

## Global Constraints

- `nebula_saturate(starless: AstroImage, stars: AstroImage, strength: float) -> AstroImage`: `strength` clamped [0,1]; `strength == 0` → plain screen recombine `1-(1-starless)*(1-stars)`; boost only the starless chroma within the nebula mask (`sat = L + (starless-L)*(1 + _GAIN*strength*mask)`), screen stars back; output clipped [0,1] float32, `is_linear`/`metadata` from `starless`; mono starless → no chroma change.
- `_nebula_mask(lum)`: sky-anchored feathered mask — `smoothstep(lum, p25, p60)` then Gaussian-blur (`sigma = 1.5% of short edge`); returns float in [0,1].
- `saturate(img, amount)` is UNCHANGED.
- Saturation step option is `(amount, nebula)`; `SaturationStep(rcastro)` splits internally when `nebula>0`; a legacy bare float `amount` → `(amount, 0.0)`; empty → `(0.5, 0.0)`.
- Nebula boost is RC-Astro-gated (disabled + "Needs RC-Astro — set its path in Settings." when absent); the global Saturation slider always works.
- Full step result = `saturate(nebula_saturate(starless, stars, nebula), amount)`; live app reuses a lazily-cached split; recipe serializes `[amount, nebula]` with legacy-float back-compat.
- Reuse the existing `_sr_sig` fingerprint and `_remove_stars(img)` split helper.

---

### Task 1: Core `nebula_saturate` + `_nebula_mask`

**Files:**
- Modify: `nocturne/core/saturation.py`
- Test: `tests/core/test_saturation.py`

**Interfaces:**
- Produces: `_nebula_mask(lum: np.ndarray) -> np.ndarray`; `nebula_saturate(starless: AstroImage, stars: AstroImage, strength: float) -> AstroImage`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/core/test_saturation.py`:

```python
def _screen(a, b):
    return 1.0 - (1.0 - a) * (1.0 - b)


def _sky_and_nebula():
    from nocturne.core.image import AstroImage
    a = np.full((100, 100, 3), 0.12, np.float32)      # sky
    a[30:70, 30:70] = (0.6, 0.3, 0.3)                  # reddish nebula block (lum 0.4)
    return AstroImage(a, is_linear=False, metadata={"k": 1})


def test_nebula_mask_sky_low_nebula_high():
    from nocturne.core.saturation import _nebula_mask
    lum = _sky_and_nebula().data.mean(axis=2)
    m = _nebula_mask(lum)
    assert m[50, 50] > 0.8        # nebula interior
    assert m[5, 5] < 0.2          # sky corner


def test_nebula_saturate_strength_zero_is_recombine():
    from nocturne.core.saturation import nebula_saturate
    from nocturne.core.image import AstroImage
    starless = _sky_and_nebula()
    stars = AstroImage(np.zeros((100, 100, 3), np.float32), is_linear=False)
    out = nebula_saturate(starless, stars, 0.0).data
    assert np.allclose(out, _screen(starless.data, stars.data))


def test_nebula_saturate_boosts_nebula_spares_sky():
    from nocturne.core.saturation import nebula_saturate
    from nocturne.core.image import AstroImage
    starless = _sky_and_nebula()
    stars = AstroImage(np.zeros((100, 100, 3), np.float32), is_linear=False)
    out = nebula_saturate(starless, stars, 1.0).data
    # nebula pixel: chroma (distance from its own luminance) grew
    def chroma(px):
        return float(np.abs(px - px.mean()).sum())
    assert chroma(out[50, 50]) > chroma(starless.data[50, 50])
    # sky pixel unchanged (mask ~0, stars 0 there)
    assert np.allclose(out[5, 5], starless.data[5, 5], atol=1e-3)


def test_nebula_saturate_screens_stars_untouched():
    from nocturne.core.saturation import nebula_saturate
    from nocturne.core.image import AstroImage
    starless = _sky_and_nebula()
    star_layer = np.zeros((100, 100, 3), np.float32)
    star_layer[5, 5] = (0.9, 0.9, 0.9)                 # a star over sky
    stars = AstroImage(star_layer, is_linear=False)
    out = nebula_saturate(starless, stars, 1.0).data
    plain = _screen(starless.data, star_layer)
    assert np.allclose(out[5, 5], plain[5, 5], atol=1e-3)   # star pixel unaffected by boost


def test_nebula_saturate_range_dtype_metadata():
    from nocturne.core.saturation import nebula_saturate
    from nocturne.core.image import AstroImage
    starless = _sky_and_nebula()
    stars = AstroImage(np.zeros((100, 100, 3), np.float32), is_linear=False)
    out = nebula_saturate(starless, stars, 0.7)
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
    assert out.is_linear is False and out.metadata == {"k": 1}


def test_nebula_saturate_mono_no_chroma_change():
    from nocturne.core.saturation import nebula_saturate
    from nocturne.core.image import AstroImage
    starless = AstroImage(np.full((16, 16), 0.4, np.float32), is_linear=False)
    stars = AstroImage(np.zeros((16, 16), np.float32), is_linear=False)
    out = nebula_saturate(starless, stars, 1.0).data
    assert np.allclose(out, _screen(starless.data, stars.data))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/core/test_saturation.py -q`
Expected: FAIL — `ImportError: cannot import name '_nebula_mask'` / `nebula_saturate`.

- [ ] **Step 3: Implement**

In `nocturne/core/saturation.py`, add the `gaussian` import at the top and the new functions below the existing `saturate` (leave `saturate` unchanged):

```python
from skimage.filters import gaussian
```

```python
_MASK_LO_PCT = 25.0        # sky level percentile (mask floor)
_MASK_HI_PCT = 60.0        # low-nebula percentile (mask ramps to 1 by here)
_MASK_SIGMA_FRAC = 0.015   # feather radius as a fraction of the short edge
_GAIN = 1.5                # max chroma boost multiplier at strength 1, mask 1


def _smoothstep(x, a, b):
    t = np.clip((x - a) / max(float(b) - float(a), 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _nebula_mask(lum: np.ndarray) -> np.ndarray:
    """A sky-anchored, feathered mask: 0 at/below the sky level, ramping to 1 as
    signal rises above it. `lum` is a 2-D luminance array in [0,1]."""
    lo, hi = np.percentile(lum, [_MASK_LO_PCT, _MASK_HI_PCT])
    m = _smoothstep(lum, lo, hi).astype(np.float32)
    h, w = lum.shape
    sigma = max(1.0, _MASK_SIGMA_FRAC * min(h, w))
    return gaussian(m, sigma=sigma, preserve_range=True).astype(np.float32)


def nebula_saturate(starless: AstroImage, stars: AstroImage,
                    strength: float) -> AstroImage:
    """Boost chroma on the starless layer within the nebula mask, then screen the
    untouched stars back on top — so only nebulosity gains colour (sky and stars
    are unchanged). `strength` 0 = plain recombine."""
    strength = float(np.clip(strength, 0.0, 1.0))
    base = np.clip(starless.data.astype(np.float32), 0.0, 1.0)
    st = np.clip(stars.data.astype(np.float32), 0.0, 1.0)
    if base.ndim == 3 and strength > 0.0:
        lum = base.mean(axis=2, keepdims=True)
        m = _nebula_mask(base.mean(axis=2))[:, :, None]
        base = np.clip(lum + (base - lum) * (1.0 + _GAIN * strength * m), 0.0, 1.0)
    out = 1.0 - (1.0 - base) * (1.0 - st)
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=starless.is_linear, metadata=dict(starless.metadata))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/core/test_saturation.py -q`
Expected: PASS (existing `saturate` tests + 6 new).

- [ ] **Step 5: Commit**

```bash
git add nocturne/core/saturation.py tests/core/test_saturation.py
git commit -m "feat: nebula_saturate — masked, star-separated chroma boost"
```

---

### Task 2: `SaturationStep` (amount, nebula) + factory + recipe

**Files:**
- Modify: `nocturne/steps/saturation_step.py`
- Modify: `nocturne/steps/factory.py`
- Modify: `nocturne/recipe.py`
- Test: `tests/steps/test_saturation_step.py`, `tests/test_recipe.py`

**Interfaces:**
- Consumes: `saturate`, `nebula_saturate` (Task 1); `RCAstro`, `run_cli`.
- Produces: `SaturationStep(rcastro)` with `apply(img, option)` handling `(amount, nebula)` / legacy float / empty; `make_step("saturation", settings)` constructs it with `RCAstro(...)` + `rc_runner`; recipe round-trips `[amount, nebula]` (+ legacy float).

- [ ] **Step 1: Write / update the failing tests**

Replace the saturation-step test file `tests/steps/test_saturation_step.py` contents (or add these; if it already asserts the old zero-arg construction, update it):

```python
import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.saturation import saturate, nebula_saturate
from nocturne.steps.saturation_step import SaturationStep


def _img():
    a = np.full((16, 16, 3), 0.12, np.float32)
    a[4:12, 4:12] = (0.6, 0.3, 0.3)
    return AstroImage(a, is_linear=False)


class _FakeRC:
    def __init__(self, starless, stars):
        self._s = (starless, stars)

    def remove_stars(self, img, runner=None):
        return self._s


def test_apply_combines_nebula_then_global():
    img = _img()
    starless = _img()
    stars = AstroImage(np.zeros((16, 16, 3), np.float32), is_linear=False)
    step = SaturationStep(_FakeRC(starless, stars))
    out = step.apply(img, (0.7, 0.6)).data
    expected = saturate(nebula_saturate(starless, stars, 0.6), 0.7).data
    assert np.allclose(out, expected)


def test_apply_legacy_float_is_global_only():
    img = _img()
    step = SaturationStep(_FakeRC(_img(), _img()))   # rc unused when nebula 0
    assert np.allclose(step.apply(img, 0.7).data, saturate(img, 0.7).data)


def test_apply_empty_option_is_native():
    img = _img()
    step = SaturationStep(_FakeRC(_img(), _img()))
    assert np.allclose(step.apply(img, "").data, saturate(img, 0.5).data)
```

Add to `tests/steps/test_factory.py`:

```python
def test_make_step_saturation_has_rcastro():
    from nocturne.steps.factory import make_step
    from nocturne.steps.saturation_step import SaturationStep
    from nocturne.settings import Settings
    step = make_step("saturation", Settings())
    assert isinstance(step, SaturationStep)
    assert step._rc is not None            # constructed with an RCAstro
```

Add to `tests/test_recipe.py`:

```python
def test_saturation_option_round_trip():
    from nocturne.recipe import serialize_option, deserialize_option
    assert serialize_option("saturation", (0.7, 0.4)) == [0.7, 0.4]
    assert deserialize_option("saturation", [0.7, 0.4]) == (0.7, 0.4)
    assert deserialize_option("saturation", 0.7) == (0.7, 0.0)   # legacy bare float
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/steps/test_saturation_step.py tests/steps/test_factory.py tests/test_recipe.py -q`
Expected: FAIL — `SaturationStep()` now requires `rcastro`; recipe has no `saturation` branch.

- [ ] **Step 3a: Rework the step**

Replace `nocturne/steps/saturation_step.py` with:

```python
from __future__ import annotations

from ..core.image import AstroImage
from ..core.saturation import nebula_saturate, saturate
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro


def parse_saturation_option(option) -> tuple[float, float]:
    """Return (amount, nebula) from the step option: a 2-tuple/2-list
    (amount, nebula), a legacy bare float amount (nebula 0), or empty (native)."""
    if option is None or option == "":
        return (0.5, 0.0)
    if isinstance(option, (tuple, list)):
        amount, nebula = option
        return (float(amount), float(nebula))
    return (float(option), 0.0)


class SaturationStep(Step):
    name = "Saturation"

    def __init__(self, rcastro: RCAstro) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        amount, nebula = parse_saturation_option(option)
        if nebula > 0.0:
            starless, stars = self._rc.remove_stars(img, runner=self._runner)
            img = nebula_saturate(starless, stars, nebula)
        return saturate(img, amount)
```

- [ ] **Step 3b: Rework the factory branch**

In `nocturne/steps/factory.py`, replace the `saturation` branch with (mirroring `star_reduction`):

```python
    if stage_id == "saturation":
        step = SaturationStep(RCAstro(resolve_binary(settings.rcastro_path)))
        step._runner = rc_runner
        return step
```

(`RCAstro`/`resolve_binary` are already imported in `factory.py`.)

- [ ] **Step 3c: Recipe branch**

In `nocturne/recipe.py`, add to `serialize_option` (before the final `return option`):

```python
    if stage_id == "saturation":
        amount, nebula = option if isinstance(option, (tuple, list)) else (option, 0.0)
        return [float(amount), float(nebula)]
```

and to `deserialize_option` (before the final `return value`):

```python
    if stage_id == "saturation":
        if isinstance(value, (tuple, list)):
            return (float(value[0]), float(value[1]))
        return (float(value), 0.0)   # legacy bare float
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/steps/test_saturation_step.py tests/steps/test_factory.py tests/test_recipe.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/steps/saturation_step.py nocturne/steps/factory.py nocturne/recipe.py tests/steps/test_saturation_step.py tests/steps/test_factory.py tests/test_recipe.py
git commit -m "feat: SaturationStep gains (amount, nebula) + RC-Astro split"
```

---

### Task 3: Saturation panel — Nebula boost slider

**Files:**
- Modify: `nocturne/ui/step_panels.py`
- Test: `tests/ui/test_step_panels.py`

**Interfaces:**
- Consumes: `ResetSlider`, `_desc_label`, `QLabel`, `QPushButton`, `QHBoxLayout`, `QSlider`.
- Produces: `build_panel(..., on_sat_apply=None)`; `on_sat_change` now called with `(amount, nebula)`; panel exposes `sat_slider`, `sat_val`, `neb_slider`, `neb_val`, `neb_status`, `apply_btn`; Apply calls `on_sat_apply(amount, nebula)`.

- [ ] **Step 1: Replace the failing test**

Replace the existing saturation-panel test in `tests/ui/test_step_panels.py` (find the one asserting `sat_slider`/`on_sat_change(amount)`) with:

```python
def test_saturation_panel_has_nebula_boost(qtbot):
    changed, applied = [], []
    w = build_panel(_stage("saturation"),
                    on_sat_change=lambda a, n: changed.append((a, n)),
                    on_sat_apply=lambda a, n: applied.append((a, n)))
    qtbot.addWidget(w)
    assert w.panel_kind == "saturation"
    for attr in ("sat_slider", "sat_val", "neb_slider", "neb_val", "neb_status", "apply_btn"):
        assert hasattr(w, attr)
    assert w.sat_slider.value() == 50          # native default
    assert w.neb_slider.value() == 0           # off default
    w.neb_slider.setValue(60)
    assert changed[-1] == (0.50, 0.60)         # (amount, nebula)
    assert w.neb_val.text().strip() == "0.60"
    w.apply_btn.click()
    assert applied[-1] == (0.50, 0.60)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py::test_saturation_panel_has_nebula_boost -q`
Expected: FAIL — `on_sat_apply` not a param; `on_sat_change` called with one arg; no `neb_slider`.

- [ ] **Step 3: Rework the panel**

In `nocturne/ui/step_panels.py`, add `on_sat_apply=None` to `build_panel`'s signature (next to `on_sat_change=None`).

Replace the entire `elif stage.kind == "saturation":` branch with:

```python
    elif stage.kind == "saturation":
        lay.addWidget(_desc_label(
            "Drag Saturation left to mute colour, right to boost. Centre = no change. "
            "Nebula boost lifts only the nebulosity (stars & sky untouched); needs RC-Astro."))
        slider = ResetSlider(50)
        slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider.setTickInterval(50)
        sat_val = QLabel(f"{slider.value() / 100:.2f}")
        neb = ResetSlider(0)
        neb_val = QLabel(f"{neb.value() / 100:.2f}")
        neb_status = _desc_label("")   # main_window sets "Separating stars…" / gate text

        def _emit_sat(*_):
            sat_val.setText(f"{slider.value() / 100:.2f}")
            neb_val.setText(f"{neb.value() / 100:.2f}")
            if on_sat_change is not None:
                on_sat_change(slider.value() / 100.0, neb.value() / 100.0)

        slider.valueChanged.connect(_emit_sat)
        neb.valueChanged.connect(_emit_sat)
        apply_btn = QPushButton("Apply Saturation")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_sat_apply is not None:
            apply_btn.clicked.connect(
                lambda: on_sat_apply(slider.value() / 100.0, neb.value() / 100.0))
        sat_row = QHBoxLayout()
        sat_row.addWidget(QLabel("Saturation (mute ← native → boost)"))
        sat_row.addWidget(sat_val)
        lay.addLayout(sat_row)
        lay.addWidget(slider)
        neb_row = QHBoxLayout()
        neb_row.addWidget(QLabel("Nebula boost (off → strong)"))
        neb_row.addWidget(neb_val)
        lay.addLayout(neb_row)
        lay.addWidget(neb)
        lay.addWidget(neb_status)
        lay.addWidget(apply_btn)
        w.sat_slider = slider
        w.sat_val = sat_val
        w.neb_slider = neb
        w.neb_val = neb_val
        w.neb_status = neb_status
        w.apply_btn = apply_btn
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/step_panels.py tests/ui/test_step_panels.py
git commit -m "feat: Saturation panel — Nebula boost slider + status"
```

---

### Task 4: main_window — lazy cached split + custom apply

**Files:**
- Modify: `nocturne/ui/main_window.py`
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `saturate` (existing import), `nebula_saturate` (Task 1); `_remove_stars`, `_sr_sig`, `_preview_base`, `_leading_kept`, `_show_preview`, `_run_busy`, `rcastro_valid`, `_PrecomputedStep`, `format_log_entry`, `GEOMETRY_NAMES`, `STEP_NAME`, `PROCESSING_ORDER`; panel `neb_slider`/`neb_status`/`sat_slider`/`apply_btn` (Task 3).
- Produces: `_sat_preceding`, `_setup_saturation`, `_on_sat_split`, reworked `_on_sat_change(amount, nebula)` / `_render_saturation_preview`, `_apply_saturation(amount, nebula)`; state `_sat_layers`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_main_window.py`:

```python
def test_saturation_nebula_gated_without_rcastro(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("saturation")
    assert win._panel.neb_slider.isEnabled() is False
    assert "RC-Astro" in win._panel.neb_status.text()
    assert win._panel.sat_slider.isEnabled() is True      # global still works


def test_saturation_global_only_applies_without_rcastro(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("saturation")
    win._apply_saturation(0.7, 0.0)
    assert [n for n, _ in win.project.entries()][-1] == "Saturation"


def _fake_sat_split(win, monkeypatch):
    import numpy as np
    from nocturne.core.image import AstroImage
    starless = AstroImage(np.full((16, 16, 3), 0.3, np.float32), is_linear=False)
    stars = np.zeros((16, 16, 3), np.float32); stars[8, 8] = (0.2, 0.9, 0.3)
    stars = AstroImage(stars, is_linear=False)
    monkeypatch.setattr(win, "_remove_stars", lambda img: (starless, stars))
    monkeypatch.setattr("nocturne.ui.main_window.rcastro_valid", lambda s: True)


def test_saturation_nebula_caches_split_and_previews(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _fake_sat_split(win, monkeypatch)
    win._go_to_id("saturation")
    entries_before = [n for n, _ in win.project.entries()]
    win._on_sat_change(0.5, 0.6)              # sync split (_async_enabled False)
    win._render_saturation_preview()
    assert not win.image_view._item.pixmap().isNull()
    assert [n for n, _ in win.project.entries()] == entries_before   # no commit
    win._apply_saturation(0.5, 0.6)
    assert [n for n, _ in win.project.entries()][-1] == "Saturation"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py::test_saturation_nebula_gated_without_rcastro -q`
Expected: FAIL — `_panel` has no `neb_slider` wired / `_apply_saturation` missing.

- [ ] **Step 3a: Import `nebula_saturate`**

In `nocturne/ui/main_window.py`, update the saturation import:

```python
from ..core.saturation import nebula_saturate, saturate
```

- [ ] **Step 3b: Add `_sat_layers` state in `__init__`**

Next to the existing `self._sat_pending`/`self._sat_timer` block, add:

```python
        self._sat_layers = None   # (sig, starless, stars) once a split lands
```

- [ ] **Step 3c: Replace the saturation preview methods**

Replace the existing `_on_sat_change` + `_render_saturation_preview` methods with:

```python
    # --- saturation live preview (global + lazy cached-split nebula boost) ---
    def _sat_preceding(self) -> set:
        return set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index("saturation")]
        }

    def _setup_saturation(self) -> None:
        """On entering Saturation: gate the Nebula slider on RC-Astro. The global
        slider always works; the StarX split is deferred until the Nebula slider
        is first raised (lazy)."""
        self._sat_pending = None
        if self.project is None or not hasattr(self._panel, "neb_slider"):
            return
        if rcastro_valid(self.settings):
            self._panel.neb_slider.setEnabled(True)
            self._panel.neb_status.setText("")
        else:
            self._panel.neb_slider.setEnabled(False)
            self._panel.neb_status.setText("Needs RC-Astro — set its path in Settings.")

    def _on_sat_change(self, amount: float, nebula: float) -> None:
        """A Saturation slider moved: stash both values; lazily split for the
        nebula boost; (re)start the debounce."""
        self._sat_pending = (amount, nebula)
        if nebula > 0.0 and rcastro_valid(self.settings) and not self._busy:
            base = self._preview_base("saturation")
            sig = self._sr_sig(base)
            if not (self._sat_layers and self._sat_layers[0] == sig):
                self._panel.neb_status.setText("Separating stars…")
                self._run_busy(lambda: self._remove_stars(base),
                               lambda layers: self._on_sat_split(sig, layers),
                               "Separating stars…", "Star separation failed")
        self._sat_timer.start(90)

    def _on_sat_split(self, sig, layers) -> None:
        if self.current_stage_id() != "saturation":
            return
        self._sat_layers = (sig, layers[0], layers[1])
        if hasattr(self._panel, "neb_status"):
            self._panel.neb_status.setText("")
        self._render_saturation_preview()

    def _sat_result(self, base, amount, nebula):
        """The Saturation output for the given base: nebula boost (from the cached
        split, when available) then the global saturate. Falls back to global-only
        when the split isn't ready."""
        img = base
        if nebula > 0.0 and self._sat_layers and self._sat_layers[0] == self._sr_sig(base):
            _, starless, stars = self._sat_layers
            img = nebula_saturate(starless, stars, nebula)
        return saturate(img, amount)

    def _render_saturation_preview(self) -> None:
        """Non-committing live preview of Saturation + Nebula boost."""
        if self.project is None or self.current_stage_id() != "saturation":
            return
        if self._sat_pending is not None:
            amount, nebula = self._sat_pending
        else:
            amount = self._panel.sat_slider.value() / 100.0
            nebula = self._panel.neb_slider.value() / 100.0
        base = self._preview_base("saturation")
        self._show_preview(self._sat_result(base, amount, nebula).data)

    def _apply_saturation(self, amount: float, nebula: float) -> None:
        """Commit Saturation (+ Nebula boost) using the cached split — instant."""
        if self.project is None or self._busy:
            return
        self.project.jump_back(
            self._leading_kept(self.project.entries(), self._sat_preceding()))
        base = self.project.current()
        result = self._sat_result(base, amount, nebula)
        self.project.run_step(_PrecomputedStep("Saturation", result), (amount, nebula))
        self.log_panel.append_entry(
            format_log_entry("Saturation", f"{amount:.2f} / neb {nebula:.2f}", None))
        self._status.setText("")
        self._refresh()
```

- [ ] **Step 3d: Wire the panel + setup in `_rebuild_panel`**

In `_rebuild_panel`, the `if stage.id == "saturation": self._sat_pending = None` reset already exists — keep it. In the `build_panel(...)` call, next to `on_sat_change=self._on_sat_change,` add:

```python
            on_sat_change=self._on_sat_change,
            on_sat_apply=self._apply_saturation,
```

At the end of `_rebuild_panel`, next to the existing `if stage.id == "star_reduction": self._setup_star_reduction()`, add:

```python
        if stage.id == "saturation":
            self._setup_saturation()
```

- [ ] **Step 3e: Log label (belt-and-suspenders)**

In `_log_step`, add a `saturation` branch before the `isinstance(option, float)` check (the option is now a tuple; this path is only hit if some flow routes saturation through `_log_step`):

```python
        elif stage_id == "saturation" and isinstance(option, (tuple, list)):
            label = f"{float(option[0]):.2f} / neb {float(option[1]):.2f}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nocturne/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat: Saturation nebula boost — lazy cached split + custom apply"
```

---

### Task 5: Real-data validation

**Files:**
- Update: `TODO.md`

- [ ] **Step 1: Drive the app on real data**

```bash
.venv/bin/python -m nocturne
```

Open a nebula target, process to **Saturation**. Confirm: the global **Saturation** slider behaves exactly as before (instant). Raise **Nebula boost** — you'll see "Separating stars…" once, then the nebulosity (including faint) gains colour while the **sky background stays neutral and stars stay unchanged**; the live preview equals the committed result. With RC-Astro unset, the Nebula slider is disabled with the message, and global Saturation still works.

- [ ] **Step 2: Capture before/after for sign-off**

Save Nebula-0 and boosted screenshots and present for approval. Do not merge until confirmed. Tune `_GAIN`, `_MASK_LO_PCT`/`_MASK_HI_PCT`, `_MASK_SIGMA_FRAC` in `core/saturation.py` here if the mask over/under-reaches or the boost is too strong/weak.

- [ ] **Step 3: Mark the backlog item done**

In `TODO.md`, mark the "Masked 'nebula-only' saturation" item `- [x]` with a "done 2026-07-21" note (integrated into the Saturation step as a second slider; StarX-split star separation + sky-anchored nebula mask; RC-Astro-gated). This closes group B.

```bash
git add TODO.md
git commit -m "docs: mark masked nebula saturation done (closes group B)"
```

---

## Self-Review

**Spec coverage:**
- `nebula_saturate` + `_nebula_mask` (mask, boost, recombine, no-op at 0, mono) → Task 1. ✅
- `SaturationStep(amount, nebula)` + RC-Astro split + legacy float; factory; recipe round-trip → Task 2. ✅
- Panel Nebula-boost slider + status + `on_sat_change(amount,nebula)`/`on_sat_apply` → Task 3. ✅
- main_window lazy cached split, gating, preview (global + nebula), custom apply, log label → Task 4. ✅
- Real-data validation + TODO → Task 5. ✅

**Placeholder scan:** No TBD/"handle edge cases"/"similar to" — every code step has full code. ✅

**Type consistency:** `nebula_saturate(starless, stars, strength)` consistent across core, step, and main_window; `parse_saturation_option` and the recipe branch agree on `(amount, nebula)` / legacy-float / empty; panel attribute names (`sat_slider`/`neb_slider`/`neb_status`) match Task 3 → Task 4; `on_sat_change(amount, nebula)` / `on_sat_apply(amount, nebula)` consistent between `step_panels.py` and `main_window.py`; `_sat_layers` tuple `(sig, starless, stars)` consistent across `_on_sat_split`/`_sat_result`; reuses `_sr_sig`/`_remove_stars`; `saturation` unchanged in pipeline lists. ✅
