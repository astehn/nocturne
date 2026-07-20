# HDR Core / Highlight Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Recover Core" step that pulls blown-out bright cores back so they show structure instead of a flat white blob, driven by one novice-proof strength slider with live preview.

**Architecture:** A pure-numpy core function `recover_core(img, amount)` in `nocturne/core/hdr.py` (single-scale local HDR on luminance, hue preserved by the luminance-ratio trick — same shape as `core/local_contrast.enhance`). It is wrapped by `RecoverCoreStep`, registered in the step factory, and inserted as a new pipeline stage right after Stretch. The panel is a slider + numeric readout + Apply button, wired to the standardized debounced live-preview (`_preview_base` → `_show_preview`, updating image and histogram together).

**Tech Stack:** Python, NumPy, scikit-image (`skimage.filters.gaussian`), PySide6, pytest.

## Global Constraints

- `recover_core(img: AstroImage, amount: float) -> AstroImage`; `amount ∈ [0, 1]` clamped; `amount == 0` is an exact no-op.
- Operate in display space on luminance only; preserve hue via `out = RGB * (new_L / max(L, 1e-6))`.
- Preserve `is_linear` and `metadata` on the returned `AstroImage`; output clipped to `[0, 1]`, dtype `float32`.
- No new third-party dependency: use `skimage.filters.gaussian` (already a dependency via `local_contrast`), not `scipy`.
- Highlight-mask constants: `t0 = 0.55`, `t1 = 0.92`; blur `sigma = max(1.0, 0.015 * min(H, W))`; compression/boost exponent `1 + amount`. These are provisional and may be retuned only in Task 5.
- Follow existing patterns exactly: panel branch mirrors the `local_contrast` branch; main_window wiring mirrors the `_lc_*` / `_stretch_*` live-preview methods; step wrapper mirrors `steps/local_contrast.py`.
- Stage id `recover_core`, display name `"Recover Core"`, panel `kind == "recover_core"`, placed after `stretch` and before `levels`.

---

### Task 1: Core `recover_core` function

**Files:**
- Create: `nocturne/core/hdr.py`
- Test: `tests/core/test_hdr.py`

**Interfaces:**
- Consumes: `nocturne.core.image.AstroImage` (`.data` float32 ndarray, `.is_linear` bool, `.metadata` dict; 2-D greyscale or 3-D HxWx3).
- Produces: `recover_core(img: AstroImage, amount: float) -> AstroImage`.

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_hdr.py`:

```python
import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.hdr import recover_core


def _blob():
    """A bright, near-flat core (0.88) with a fine high-frequency ripple, on a
    dark background (0.2). The ripple is the 'structure' that should survive the
    blur into the detail layer and be re-expanded."""
    h = w = 200
    lum = np.full((h, w), 0.2, np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    ripple = 0.04 * np.sin(2 * np.pi * xx / 3.0).astype(np.float32)  # period 3px
    core = slice(60, 140)
    lum[core, core] = 0.88 + ripple[core, core]
    return AstroImage(np.repeat(lum[:, :, None], 3, axis=2).astype(np.float32),
                      is_linear=False)


def _interior(arr):
    """Central patch of the core, away from its edges (blur bleed / mask ramp)."""
    return arr[80:120, 80:120]


def test_amount_zero_is_noop():
    img = _blob()
    out = recover_core(img, 0.0).data
    assert np.allclose(out, img.data, atol=1e-6)


def test_lowers_core_and_raises_relative_contrast():
    img = _blob()
    out = recover_core(img, 0.8).data
    lum_in = img.data.mean(axis=2)
    lum_out = out.mean(axis=2)
    in_c, out_c = _interior(lum_in), _interior(lum_out)
    # Core mean pulled down.
    assert out_c.mean() < in_c.mean() - 0.02
    # Structure's relative contrast (std / mean) raised — detail re-expanded.
    assert out_c.std() / out_c.mean() > in_c.std() / in_c.mean()


def test_background_below_mask_is_untouched():
    img = _blob()
    out = recover_core(img, 0.8).data
    # A far corner, well below the highlight mask ramp — must be unchanged.
    assert np.allclose(out[:20, :20], img.data[:20, :20], atol=1e-6)


def test_output_stays_in_unit_range():
    rng = np.random.default_rng(0)
    img = AstroImage(rng.random((64, 64, 3)).astype(np.float32), is_linear=False)
    out = recover_core(img, 1.0).data
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_preserves_is_linear_and_metadata():
    img = AstroImage(np.full((32, 32, 3), 0.9, np.float32),
                     is_linear=False, metadata={"k": 1})
    out = recover_core(img, 0.5)
    assert out.is_linear is False
    assert out.metadata == {"k": 1}


def test_greyscale_path():
    lum = np.full((64, 64), 0.9, np.float32)
    lum[20:44, 20:44] += 0.03 * np.sin(np.arange(64) / 2.0)[None, 20:44].repeat(24, 0)
    out = recover_core(AstroImage(lum), 0.7)
    assert out.data.ndim == 2
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/core/test_hdr.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nocturne.core.hdr'`.

- [ ] **Step 3: Write the implementation**

Create `nocturne/core/hdr.py`:

```python
from __future__ import annotations

import numpy as np
from skimage.filters import gaussian

from .image import AstroImage

_T0 = 0.55          # highlight mask ramp start (luminance)
_T1 = 0.92          # highlight mask ramp end
_SIGMA_FRAC = 0.015  # Gaussian radius as a fraction of the short edge


def _smoothstep(x: np.ndarray, a: float, b: float) -> np.ndarray:
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def recover_core(img: AstroImage, amount: float) -> AstroImage:
    """Tame blown-out bright cores: under a feathered highlight mask, pull the
    core's local average brightness down and re-expand the fine structure hiding
    inside it, so a clipped white blob shows detail again.

    Single-scale local HDR on luminance only; hue preserved by rescaling RGB with
    the luminance ratio (as `local_contrast.enhance` does). `amount` 0 = no-op;
    higher = stronger pull-down and detail re-expansion.
    """
    amount = float(np.clip(amount, 0.0, 1.0))
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    if amount == 0.0:
        return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))

    mono = data.ndim == 2
    lum = data if mono else data.mean(axis=2)
    h, w = lum.shape
    sigma = max(1.0, _SIGMA_FRAC * min(h, w))

    mask = _smoothstep(lum, _T0, _T1)                       # 0 in sky → 1 in core
    blur = gaussian(lum, sigma=sigma, preserve_range=True).astype(np.float32)
    detail = lum - blur                                     # structure in the blob

    compressed = blur ** (1.0 + amount)                     # darken the bright DC
    boosted = compressed + (1.0 + amount) * detail          # re-expand the detail
    weight = amount * mask
    new_lum = np.clip(lum * (1.0 - weight) + boosted * weight, 0.0, 1.0)

    if mono:
        out = new_lum
    else:
        ratio = new_lum / np.maximum(lum, 1e-6)
        out = np.clip(data * ratio[..., None], 0.0, 1.0)

    return AstroImage(out.astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/core/test_hdr.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add nocturne/core/hdr.py tests/core/test_hdr.py
git commit -m "feat: recover_core single-scale local HDR core function"
```

---

### Task 2: Register the Recover Core stage (step wrapper, factory, pipeline, recipe, help)

**Files:**
- Create: `nocturne/steps/recover_core.py`
- Modify: `nocturne/steps/factory.py`
- Modify: `nocturne/ui/pipeline.py`
- Modify: `nocturne/recipe.py:35`
- Modify: `nocturne/ui/help_content.py`
- Test: `tests/steps/test_factory.py`, `tests/ui/test_pipeline.py` (update frozen lists)

**Interfaces:**
- Consumes: `recover_core` from Task 1; `nocturne.history.step.Step`.
- Produces: `RecoverCoreStep` (class, `name = "Recover Core"`, `apply(img, option) -> AstroImage`); stage id `"recover_core"` present in `path_stages()`, `STEP_NAME`, `PROCESSING_ORDER` (after `stretch`, before `levels`), and `POST_STRETCH_IDS`; `make_step("recover_core", ...)` returns a `RecoverCoreStep`.

- [ ] **Step 1: Write / update the failing tests**

Add to `tests/steps/test_factory.py`:

```python
def test_make_step_recover_core():
    from nocturne.steps.factory import make_step
    from nocturne.steps.recover_core import RecoverCoreStep
    from nocturne.settings import Settings
    step = make_step("recover_core", Settings())
    assert isinstance(step, RecoverCoreStep)
    assert step.name == "Recover Core"


def test_recover_core_step_applies_amount():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.hdr import recover_core
    from nocturne.steps.recover_core import RecoverCoreStep
    img = AstroImage(np.full((32, 32, 3), 0.9, np.float32), is_linear=False)
    got = RecoverCoreStep().apply(img, 0.6).data
    assert np.allclose(got, recover_core(img, 0.6).data)
    # empty option -> no-op amount 0
    assert np.allclose(RecoverCoreStep().apply(img, "").data, img.data, atol=1e-6)
```

Update the two frozen-list tests in `tests/ui/test_pipeline.py`.

Replace `test_path_stages_single_linear_flow`:

```python
def test_path_stages_single_linear_flow():
    ids = [s.id for s in path_stages()]
    assert ids == [
        "load", "crop", "background", "color", "deconvolution", "stretch",
        "recover_core", "levels", "saturation", "noise_sharpen", "local_contrast",
        "star_reduction", "enhancements", "export",
    ]
```

Replace the `PROCESSING_ORDER` assertion inside `test_step_name_and_order`:

```python
    assert PROCESSING_ORDER == [
        "background", "color", "remove_green", "deconvolution", "stretch",
        "recover_core", "levels", "saturation", "noise_sharpen", "local_contrast",
        "star_reduction",
    ]
```

Add a placement + membership test to `tests/ui/test_pipeline.py`:

```python
def test_recover_core_placed_after_stretch():
    from nocturne.ui.pipeline import POST_STRETCH_IDS, STEP_NAME
    ids = [s.id for s in path_stages()]
    assert ids.index("recover_core") == ids.index("stretch") + 1
    assert ids.index("recover_core") < ids.index("levels")
    assert STEP_NAME["recover_core"] == "Recover Core"
    assert "recover_core" in POST_STRETCH_IDS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/steps/test_factory.py tests/ui/test_pipeline.py -q`
Expected: FAIL — `ModuleNotFoundError: nocturne.steps.recover_core` and the updated frozen-list assertions fail (order lacks `recover_core`).

- [ ] **Step 3a: Create the step wrapper**

Create `nocturne/steps/recover_core.py`:

```python
from __future__ import annotations

from ..core.hdr import recover_core
from ..core.image import AstroImage
from ..history.step import Step


class RecoverCoreStep(Step):
    name = "Recover Core"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        amount = float(option) if option not in (None, "") else 0.0
        return recover_core(img, amount)
```

- [ ] **Step 3b: Register in the factory**

In `nocturne/steps/factory.py`, add the import next to the other step imports:

```python
from .recover_core import RecoverCoreStep
```

and add this branch (place it after the `stretch` branch, before `levels`):

```python
    if stage_id == "recover_core":
        return RecoverCoreStep()
```

- [ ] **Step 3c: Register the stage in the pipeline**

In `nocturne/ui/pipeline.py`:

Insert into `_IN_APP_TAIL` as the first element (before Levels):

```python
_IN_APP_TAIL = [
    Stage("recover_core", "Recover Core", "recover_core"),
    Stage("levels", "Levels", "levels"),
    Stage("saturation", "Saturation", "saturation"),
    Stage("noise_sharpen", "Noise Reduction", "process"),
    Stage("local_contrast", "Local Contrast", "local_contrast"),
    Stage("star_reduction", "Star Reduction", "star_reduction"),
    Stage("enhancements", "Enhancements", "enhance"),
    Stage("export", "Export", "export"),
]
```

Add to `STEP_NAME` (after the `"stretch"` entry):

```python
    "stretch": "Stretch",
    "recover_core": "Recover Core",
    "levels": "Levels",
```

Insert into `PROCESSING_ORDER` after `"stretch"`:

```python
PROCESSING_ORDER = [
    "background", "color", "remove_green", "deconvolution", "stretch",
    "recover_core", "levels", "saturation", "noise_sharpen", "local_contrast",
    "star_reduction",
]
```

Add to `POST_STRETCH_IDS`:

```python
POST_STRETCH_IDS = frozenset({
    "recover_core", "levels", "saturation", "noise_sharpen",
    "local_contrast", "star_reduction", "enhancements",
})
```

- [ ] **Step 3d: Recipe serialization**

In `nocturne/recipe.py`, add `recover_core` to the float-option branch at line ~35:

```python
    if stage_id in ("local_contrast", "star_reduction", "recover_core"):
        try:
            return float(option)
        except (TypeError, ValueError):
            return option   # legacy string
```

- [ ] **Step 3e: Help topic**

In `nocturne/ui/help_content.py`:

Add to `_STAGE_TO_TOPIC` (after the `"stretch"` entry):

```python
    "stretch": "stretch",
    "recover_core": "recover_core",
    "levels": "levels",
```

Add a topic to the `_TOPIC_LIST` (place it just before the `local_contrast` `_t(...)` entry so the guide reads in pipeline order):

```python
    _t("recover_core", "Recover Core",
       "Pull blown-out bright cores back so they show detail.",
       "<h4>What it does</h4>"
       "<p>Short exposures blow out the bright centre of targets like M42, M8 or a "
       "galaxy nucleus — after stretching it becomes a featureless white blob. "
       "Recover Core pulls those highlights back down and re-expands the structure "
       "hiding inside them, so the core shows swirls and detail instead of pure white.</p>"
       "<h4>How to use it</h4>"
       "<p>Drag <b>Strength</b> up until the core shows detail without looking flat or "
       "grey. 0 = off. Watch the live preview. Apply.</p>"
       "<h4>Tips</h4>"
       "<p>Only the brightest regions are affected — the sky and faint nebulosity are "
       "left alone. If a core is completely clipped to white in the data there is no "
       "detail left to recover; the region will just darken smoothly.</p>"),
```

Add `"recover_core"` to the "The Steps" `HelpSection` tuple (after `"stretch"`):

```python
    HelpSection("The Steps", ("crop", "background", "color", "deconvolution", "stretch",
                              "recover_core", "levels", "saturation", "noise_sharpen",
                              "local_contrast", "star_reduction", "enhancements", "export")),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/steps/test_factory.py tests/ui/test_pipeline.py tests/ui/test_help_content.py tests/test_recipe.py -q`
Expected: PASS (all green, including the help completeness test now that `recover_core` has a topic).

- [ ] **Step 5: Commit**

```bash
git add nocturne/steps/recover_core.py nocturne/steps/factory.py nocturne/ui/pipeline.py nocturne/recipe.py nocturne/ui/help_content.py tests/steps/test_factory.py tests/ui/test_pipeline.py
git commit -m "feat: register Recover Core stage (step, factory, pipeline, recipe, help)"
```

---

### Task 3: Recover Core panel

**Files:**
- Modify: `nocturne/ui/step_panels.py` (add `on_recover_change` param + `recover_core` branch)
- Test: `tests/ui/test_step_panels.py`

**Interfaces:**
- Consumes: stage `recover_core` from `path_stages()` (Task 2); `ResetSlider`, `QLabel`, `QPushButton`, `QHBoxLayout` (already imported in `step_panels.py`).
- Produces: `build_panel(..., on_recover_change=None)`; panel with `w.recover_slider`, `w.recover_val`, `w.apply_btn`, `w.panel_kind == "recover_core"`; slider `valueChanged` updates `recover_val` (`{value/100:.2f}`) and calls `on_recover_change(value/100.0)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_step_panels.py`:

```python
def test_recover_core_panel_has_live_preview_readout(qtbot):
    seen = {}
    w = build_panel(_stage("recover_core"),
                    on_recover_change=lambda a: seen.__setitem__("amt", a))
    qtbot.addWidget(w)
    assert w.panel_kind == "recover_core"
    assert hasattr(w, "recover_slider")
    assert hasattr(w, "recover_val")
    assert w.recover_slider.value() == 0          # default off
    assert w.recover_val.text().strip() == "0.00"
    w.recover_slider.setValue(60)
    assert w.recover_val.text().strip() == "0.60"  # readout tracks the slider
    assert seen.get("amt") == 0.60                 # live-preview hook fires
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py::test_recover_core_panel_has_live_preview_readout -q`
Expected: FAIL — `build_panel()` got an unexpected keyword `on_recover_change` (or the `recover_core` kind falls through to a bare panel with no `recover_slider`).

- [ ] **Step 3: Implement the panel**

In `nocturne/ui/step_panels.py`, add the parameter to `build_panel`'s signature (next to `on_lc_change=None`):

```python
    on_lc_change=None,
    on_recover_change=None,
    on_sr_change=None,
```

Add the branch (place it before the `local_contrast` branch, matching pipeline order):

```python
    elif stage.kind == "recover_core":
        lay.addWidget(_desc_label(
            "Pull blown-out bright cores back so they show detail instead of a "
            "white blob. 0 = off."))
        slider = ResetSlider(0)
        recover_val = QLabel(f"{slider.value() / 100:.2f}")

        def _emit_recover(*_):
            recover_val.setText(f"{slider.value() / 100:.2f}")
            if on_recover_change is not None:
                on_recover_change(slider.value() / 100.0)

        slider.valueChanged.connect(_emit_recover)
        apply_btn = QPushButton("Apply Recover Core")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(slider.value() / 100.0))
        rec_row = QHBoxLayout()
        rec_row.addWidget(QLabel("Strength (off → full)"))
        rec_row.addWidget(recover_val)
        lay.addLayout(rec_row)
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.recover_slider = slider
        w.recover_val = recover_val
        w.apply_btn = apply_btn
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py -q`
Expected: PASS (all step-panel tests green).

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/step_panels.py tests/ui/test_step_panels.py
git commit -m "feat: Recover Core panel (strength slider + numeric readout)"
```

---

### Task 4: main_window live preview + commit wiring

**Files:**
- Modify: `nocturne/ui/main_window.py` (import, `__init__` timer, preview methods, `_rebuild_panel`)
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `recover_core` (Task 1); `_preview_base`, `_show_preview`, `current_stage_id`, `apply_current`, `build_panel` (existing); `w.recover_slider` (Task 3); stage `recover_core` in `PROCESSING_ORDER`/factory (Task 2, so `apply_current` commits it with no extra code).
- Produces: `_on_recover_change(amount)`, `_render_recover_preview()`; `_recover_pending`/`_recover_timer`; `on_recover_change=self._on_recover_change` wired into the `build_panel(...)` call.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_main_window.py` (mirror the existing `test_stretch_live_preview_renders` / `test_slider_preview_updates_histogram` helpers — `_window`, `_make_fits`, `_go_to_id`):

```python
def test_recover_core_live_preview_renders(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("recover_core")
    win._on_recover_change(0.7)
    win._render_recover_preview()               # non-committing preview
    assert not win.image_view._item.pixmap().isNull()
    assert win.project.current().is_linear      # preview did NOT commit


def test_recover_core_preview_updates_histogram(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("recover_core")
    seen = []
    monkeypatch.setattr(win.histogram_view, "set_image", lambda img: seen.append(img))
    win._on_recover_change(0.5)
    win._render_recover_preview()
    assert seen                                 # shared _show_preview fed the histogram
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py::test_recover_core_live_preview_renders tests/ui/test_main_window.py::test_recover_core_preview_updates_histogram -q`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_render_recover_preview'`.

- [ ] **Step 3a: Import the core function**

In `nocturne/ui/main_window.py`, next to `from ..core.local_contrast import enhance`:

```python
from ..core.hdr import recover_core
```

- [ ] **Step 3b: Add the debounce timer in `__init__`**

After the `local_contrast` timer block (the one ending with
`self._lc_timer.timeout.connect(self._render_lc_preview)`), add:

```python
        self._recover_pending = None
        self._recover_timer = QTimer(self)
        self._recover_timer.setSingleShot(True)
        self._recover_timer.timeout.connect(self._render_recover_preview)
```

- [ ] **Step 3c: Add the preview methods**

After `_render_lc_preview` (and before the `# --- star reduction live preview ---` section), add:

```python
    # --- recover core live preview ---
    def _on_recover_change(self, amount: float) -> None:
        """The Recover Core slider moved: stash the value and (re)start debounce."""
        self._recover_pending = amount
        self._recover_timer.start(90)

    def _render_recover_preview(self) -> None:
        """Non-committing live preview of the current Recover Core setting."""
        if self.project is None or self.current_stage_id() != "recover_core":
            return
        img = self._preview_base("recover_core")
        amount = (self._recover_pending if self._recover_pending is not None
                  else self._panel.recover_slider.value() / 100.0)
        self._show_preview(recover_core(img, amount).data)
```

- [ ] **Step 3d: Reset pending + wire the callback in `_rebuild_panel`**

In `_rebuild_panel`, next to the other per-stage resets (e.g. after the
`if stage.id == "local_contrast": self._lc_pending = None` block):

```python
        if stage.id == "recover_core":
            self._recover_pending = None
```

In the same method's `build_panel(...)` call, add the callback next to
`on_lc_change=self._on_lc_change,`:

```python
            on_lc_change=self._on_lc_change,
            on_recover_change=self._on_recover_change,
            on_sr_change=self._on_sr_change,
```

(Commit needs no new code: `apply_current` already routes any `PROCESSING_ORDER`
stage through `_step_for("recover_core").apply(base, amount)`, which Task 2
registered.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -q`
Expected: PASS (all main-window tests green).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS (all tests green; count = previous total + the new hdr/panel/window/factory/pipeline tests).

- [ ] **Step 6: Commit**

```bash
git add nocturne/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat: Recover Core live preview + histogram wiring in main window"
```

---

### Task 5: Real-data validation and constant tuning

**Files:**
- Modify (only if tuning is needed): `nocturne/core/hdr.py` (`_T0`, `_T1`, `_SIGMA_FRAC`, exponents)
- Update: `TODO.md` (mark the HDR core-recovery item done)

**Interfaces:**
- Consumes: the shipped `recover_core` and Recover Core step.
- Produces: validated constants; before/after evidence for user sign-off.

- [ ] **Step 1: Drive the app on real data**

Launch the app and process to the Recover Core step on a blown-core target:

```bash
.venv/bin/python -m nocturne
```

Open `/Volumes/Work2/Images/Astro/NGC 7000_sub/NGC7000_182x20s_61min.fits` (and, if available, a target with a genuinely bright core), run through Stretch, then land on Recover Core. Drag the Strength slider across its range and watch the live preview + histogram.

- [ ] **Step 2: Judge and, if needed, tune the constants**

Check against the spec's success criteria: bright cores show structure rather than a flat white blob; the sky and faint nebulosity are visibly untouched; no hard halo ring appears at the core edge even at full strength. If any fails, adjust the constants in `nocturne/core/hdr.py` — raise `_T0`/`_T1` if midtones are being pulled; raise `_SIGMA_FRAC` if the split is too local to separate the core; lower the max exponent if halos appear — then re-run `.venv/bin/python -m pytest tests/core/test_hdr.py -q` to confirm the tests still pass, and repeat Step 1.

- [ ] **Step 3: Capture before/after crops for sign-off**

Save an off (`amount=0`) and a tuned-strength screenshot of the core region and present them for the user's approval. Do not merge until the user confirms the look.

- [ ] **Step 4: Mark the backlog item done and commit**

In `TODO.md`, change the "HDR core / highlight recovery (HIGH — top pick)" item from `- [ ]` to `- [x]` with a short "done 2026-07-20" note. If constants were tuned:

```bash
git add nocturne/core/hdr.py TODO.md
git commit -m "tune: Recover Core constants validated on real data; mark backlog done"
```

Otherwise commit just the TODO update:

```bash
git add TODO.md
git commit -m "docs: mark HDR core recovery done (validated on real data)"
```

---

## Self-Review

**Spec coverage:**
- New `core/hdr.py` `recover_core` (single-scale local HDR, hue-preserved, no-op at 0) → Task 1. ✅
- Placement as a new stage after Stretch, before Levels; `POST_STRETCH_IDS` membership; recipe-serializable → Task 2. ✅
- One-slider panel with numeric readout, default off → Task 3. ✅
- Debounced live preview via `_preview_base` → `_show_preview` (image + histogram); commit via `apply_current`/`_PrecomputedStep` → Task 4. ✅
- Tests: core properties, panel, window, factory/pipeline → Tasks 1–4. ✅
- Real-data validation + constant tuning → Task 5. ✅
- Help topic (required by `test_every_stage_has_a_topic`) → Task 2, Step 3e. ✅

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to" — every code step contains full code. ✅

**Type consistency:** `recover_core(img, amount)` signature identical across core, step wrapper, and main_window preview; panel attribute names (`recover_slider`, `recover_val`) match between Task 3 (defined) and Task 4 (consumed); callback name `on_recover_change` consistent across `step_panels.py` and `main_window.py`; stage id `"recover_core"` consistent across pipeline, factory, recipe, help, panel kind. ✅
