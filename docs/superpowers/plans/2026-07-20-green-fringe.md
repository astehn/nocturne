# Remove Green Fringe — Star-Layer Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the Remove Green Fringe step so it de-greens ONLY the stars — split the image into starless + stars (StarXTerminator), suppress green excess on the stars layer, and screen-recombine — leaving the background and nebula colour untouched. Gate on RC-Astro like Star Reduction.

**Architecture:** This makes Remove Green Fringe a clone of the Star Reduction architecture: a slow StarX split runs once on entering the step (off-thread, cached in `_fringe_layers`), the Strength slider previews an instant `remove_green_fringe(starless, stars, strength)` recombine, and the step is gated (disabled + "Needs RC-Astro" message) when RC-Astro is absent. It reworks the existing (global, unmerged) green-fringe implementation on this branch.

**Tech Stack:** Python, NumPy, PySide6, RC-Astro StarXTerminator (via `tools/rcastro.py`), pytest. No new third-party dependency.

## Global Constraints

- `remove_green_fringe(starless: AstroImage, stars: AstroImage, strength: float) -> AstroImage`: de-green the stars layer via green-excess suppression, screen-recombine `out = 1-(1-starless)*(1-degreened_stars)`; `strength` clamped [0,1]; `strength == 0` → plain screen recombine (no de-green); output clipped [0,1] float32; `is_linear`/`metadata` from `starless`.
- Green-excess suppression (helper `_suppress_green_excess(data, strength)`): `avg_rb=(R+B)/2`; `G -= strength*max(G-avg_rb, 0)`; red/blue never modified; mono/2-D layer → returned unchanged.
- `GreenFringeStep(rcastro)` mirrors `StarReductionStep`: `apply` splits via `rc.remove_stars(img, runner=...)` then calls `remove_green_fringe`. Factory constructs `GreenFringeStep(RCAstro(resolve_binary(settings.rcastro_path)))` with `step._runner = rc_runner`.
- UI mirrors Star Reduction: cached split on entry (`_fringe_layers`, `_fringe_ready`, `_fringe_pending`, `_fringe_timer`), gated on `rcastro_valid(self.settings)` (disabled controls + "Needs RC-Astro — set its path in Settings."), status label, disabled-until-ready slider/Apply, custom `_apply_green_fringe` (NOT generic `apply_current`), records `_PrecomputedStep("Remove Green Fringe", result)`.
- The `green_fringe` stage stays registered (pipeline lists, recipe float branch, help topic) — those are unchanged from the current branch. Only the algorithm, step, panel, and main_window wiring change.
- Reuse the existing `_sr_sig` fingerprint and `_remove_stars(img)` split helper (do not add new ones).

---

### Task 1: Rework core to layer-based `remove_green_fringe`

**Files:**
- Modify: `nocturne/core/color.py` (replace the global `remove_green_fringe`)
- Modify: `tests/core/test_green_fringe.py` (replace the tests)

**Interfaces:**
- Consumes: `nocturne.core.image.AstroImage`.
- Produces: `_suppress_green_excess(data: np.ndarray, strength: float) -> np.ndarray`; `remove_green_fringe(starless: AstroImage, stars: AstroImage, strength: float) -> AstroImage`.

- [ ] **Step 1: Replace the tests**

Replace the ENTIRE contents of `tests/core/test_green_fringe.py` with:

```python
import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.color import remove_green_fringe, _suppress_green_excess


def _screen(a, b):
    return 1.0 - (1.0 - a) * (1.0 - b)


def test_suppress_green_excess_reduces_green_keeps_rb():
    data = np.zeros((1, 1, 3), np.float32)
    data[0, 0] = (0.2, 0.8, 0.3)                 # avg_rb 0.25, excess 0.55
    out = _suppress_green_excess(data, 0.5)
    assert np.isclose(out[0, 0, 1], 0.8 - 0.5 * 0.55)
    assert np.isclose(out[0, 0, 0], 0.2) and np.isclose(out[0, 0, 2], 0.3)


def test_suppress_green_excess_noop_on_neutral_and_zero():
    grey = np.full((2, 2, 3), 0.5, np.float32)
    assert np.allclose(_suppress_green_excess(grey, 1.0), grey)          # excess 0
    g = np.zeros((1, 1, 3), np.float32); g[0, 0] = (0.2, 0.8, 0.3)
    assert np.allclose(_suppress_green_excess(g, 0.0), g)                # strength 0


def _layers():
    starless = AstroImage(np.full((4, 4, 3), 0.3, np.float32), is_linear=False,
                          metadata={"k": 1})
    stars = np.zeros((4, 4, 3), np.float32)
    stars[2, 2] = (0.2, 0.9, 0.3)                # a green-fringed star pixel
    return starless, AstroImage(stars, is_linear=False)


def test_strength_zero_is_plain_recombine():
    starless, stars = _layers()
    out = remove_green_fringe(starless, stars, 0.0).data
    assert np.allclose(out, _screen(starless.data, stars.data))


def test_degreens_star_pixel_only_background_untouched():
    starless, stars = _layers()
    out = remove_green_fringe(starless, stars, 1.0).data
    # star pixel green reduced vs the plain recombine
    plain = _screen(starless.data, stars.data)
    assert out[2, 2, 1] < plain[2, 2, 1]
    # a background pixel (stars==0 there) equals the untouched starless value
    assert np.allclose(out[0, 0], starless.data[0, 0])


def test_range_dtype_and_metadata_from_starless():
    starless, stars = _layers()
    out = remove_green_fringe(starless, stars, 0.7)
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
    assert out.is_linear is False and out.metadata == {"k": 1}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/core/test_green_fringe.py -q`
Expected: FAIL — `ImportError: cannot import name '_suppress_green_excess'` (and the old single-arg `remove_green_fringe` signature no longer matches).

- [ ] **Step 3: Replace the implementation**

In `nocturne/core/color.py`, REPLACE the existing `remove_green_fringe(img, strength)` function (the global one added earlier) with:

```python
def _suppress_green_excess(data: np.ndarray, strength: float) -> np.ndarray:
    """Reduce green where it exceeds the red/blue average, scaled by `strength`.
    Red and blue are never modified. Returns a new float32 array. Non-3-channel
    input is returned unchanged (no green channel to fix)."""
    out = data.astype(np.float32).copy()
    if out.ndim != 3 or out.shape[-1] < 3:
        return out
    avg_rb = (out[..., 0] + out[..., 2]) / 2.0
    excess = np.maximum(out[..., 1] - avg_rb, 0.0)
    out[..., 1] = out[..., 1] - float(strength) * excess
    return out


def remove_green_fringe(starless: AstroImage, stars: AstroImage,
                        strength: float) -> AstroImage:
    """De-green the stars layer (green-excess suppression) and screen-recombine
    with the untouched starless background — so only stars change and the
    background/nebula colour is preserved. `strength` 0 = plain recombine."""
    strength = float(np.clip(strength, 0.0, 1.0))
    base = np.clip(starless.data.astype(np.float32), 0.0, 1.0)
    st = np.clip(stars.data.astype(np.float32), 0.0, 1.0)
    if strength > 0.0:
        st = _suppress_green_excess(st, strength)
    out = 1.0 - (1.0 - base) * (1.0 - st)
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=starless.is_linear, metadata=dict(starless.metadata))
```

(Leave the existing `remove_green` function untouched.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/core/test_green_fringe.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add nocturne/core/color.py tests/core/test_green_fringe.py
git commit -m "refactor: remove_green_fringe de-greens the stars layer only (starless untouched)"
```

---

### Task 2: Rework `GreenFringeStep` + factory to use RC-Astro split

**Files:**
- Modify: `nocturne/steps/green_fringe.py`
- Modify: `nocturne/steps/factory.py`
- Modify: `nocturne/ui/help_content.py` (reword the topic for star-targeted + RC-Astro)
- Test: `tests/steps/test_factory.py`

**Interfaces:**
- Consumes: `remove_green_fringe` (Task 1); `RCAstro`; `run_cli`.
- Produces: `GreenFringeStep(rcastro)` (splits internally then de-greens); `make_step("green_fringe", settings)` constructs it with `RCAstro(resolve_binary(settings.rcastro_path))` and `step._runner = rc_runner`.

- [ ] **Step 1: Update the failing factory tests**

Replace the two green-fringe tests in `tests/steps/test_factory.py` (`test_make_step_green_fringe` and `test_green_fringe_step_applies_strength`) with:

```python
def test_make_step_green_fringe():
    from nocturne.steps.factory import make_step
    from nocturne.steps.green_fringe import GreenFringeStep
    from nocturne.settings import Settings
    assert isinstance(make_step("green_fringe", Settings()), GreenFringeStep)


def test_green_fringe_step_splits_then_degreens():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.color import remove_green_fringe
    from nocturne.steps.green_fringe import GreenFringeStep

    starless = AstroImage(np.full((4, 4, 3), 0.3, np.float32), is_linear=False)
    stars = np.zeros((4, 4, 3), np.float32); stars[2, 2] = (0.2, 0.9, 0.3)
    stars = AstroImage(stars, is_linear=False)

    class _FakeRC:
        def remove_stars(self, img, runner=None):
            return starless, stars

    step = GreenFringeStep(_FakeRC())
    out = step.apply(AstroImage(np.full((4, 4, 3), 0.5, np.float32)), 0.6).data
    assert np.allclose(out, remove_green_fringe(starless, stars, 0.6).data)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/steps/test_factory.py -q`
Expected: FAIL — `GreenFringeStep()` now requires an `rcastro` argument (old zero-arg construction breaks).

- [ ] **Step 3a: Rework the step wrapper**

Replace the entire contents of `nocturne/steps/green_fringe.py` with:

```python
from __future__ import annotations

from ..core.color import remove_green_fringe
from ..core.image import AstroImage
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro


class GreenFringeStep(Step):
    name = "Remove Green Fringe"

    def __init__(self, rcastro: RCAstro) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        starless, stars = self._rc.remove_stars(img, runner=self._runner)
        strength = float(option) if option not in (None, "") else 0.0
        return remove_green_fringe(starless, stars, strength)
```

- [ ] **Step 3b: Rework the factory construction**

In `nocturne/steps/factory.py`, replace the `green_fringe` branch with (mirroring `star_reduction`):

```python
    if stage_id == "green_fringe":
        step = GreenFringeStep(RCAstro(resolve_binary(settings.rcastro_path)))
        step._runner = rc_runner
        return step
```

(`RCAstro` and `resolve_binary` are already imported in `factory.py`; the `from .green_fringe import GreenFringeStep` import is already present.)

- [ ] **Step 3c: Reword the help topic**

In `nocturne/ui/help_content.py`, update the `_t("green_fringe", ...)` topic body to reflect star-targeting + RC-Astro (replace its "What it does" / "How to use it" paragraphs):

```python
    _t("green_fringe", "Remove Green Fringe",
       "Remove the green colour fringe around stars.",
       "<h4>What it does</h4>"
       "<p>Stars are never truly green, so a green fringe or halo around them is an "
       "artifact (chromatic aberration or debayering). This splits the stars from the "
       "background with <b>StarXTerminator</b>, removes the green excess from the stars "
       "only, and recombines — so the nebula and background colour are left completely "
       "untouched.</p>"
       "<h4>How to use it</h4>"
       "<p>Raise <b>Strength</b> until the green fringe on the stars fades (0 = off). "
       "The star split runs once when you enter the step, then the slider previews "
       "instantly. Needs RC-Astro (StarXTerminator) — set its path in Settings.</p>"
       "<h4>Tips</h4>"
       "<p>A little usually does it. Because only the stars are affected, you can be "
       "fairly aggressive without shifting the overall colour.</p>"),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/steps/test_factory.py tests/ui/test_help_content.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/steps/green_fringe.py nocturne/steps/factory.py nocturne/ui/help_content.py tests/steps/test_factory.py
git commit -m "refactor: GreenFringeStep splits via RC-Astro and de-greens stars layer"
```

---

### Task 3: Rework the panel (status + gating + custom apply)

**Files:**
- Modify: `nocturne/ui/step_panels.py` (rework the `green_fringe` branch; add `on_fringe_apply` param)
- Test: `tests/ui/test_step_panels.py` (replace the panel test)

**Interfaces:**
- Consumes: stage `green_fringe`; `ResetSlider`, `_desc_label`, `QLabel`, `QPushButton`, `QHBoxLayout`.
- Produces: `build_panel(..., on_fringe_change=None, on_fringe_apply=None)`; panel with `w.fringe_status`, `w.fringe_slider`, `w.fringe_val`, `w.apply_btn`; slider + Apply start disabled; slider `valueChanged` → readout + `on_fringe_change(strength)`; Apply → `on_fringe_apply(strength)`.

- [ ] **Step 1: Replace the failing test**

Replace `test_green_fringe_panel_has_slider_readout` in `tests/ui/test_step_panels.py` with:

```python
def test_green_fringe_panel_gated_and_wired(qtbot):
    changed, applied = {}, {}
    w = build_panel(_stage("green_fringe"),
                    on_fringe_change=lambda s: changed.__setitem__("s", s),
                    on_fringe_apply=lambda s: applied.__setitem__("s", s))
    qtbot.addWidget(w)
    assert w.panel_kind == "green_fringe"
    assert hasattr(w, "fringe_status") and hasattr(w, "fringe_slider")
    # slider + Apply start disabled (main_window enables once the split lands)
    assert w.fringe_slider.isEnabled() is False
    assert w.apply_btn.isEnabled() is False
    w.fringe_slider.setEnabled(True)
    w.fringe_slider.setValue(60)
    assert w.fringe_val.text().strip() == "0.60"
    assert changed.get("s") == 0.60
    w.apply_btn.setEnabled(True)
    w.apply_btn.click()
    assert applied.get("s") == 0.60
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py::test_green_fringe_panel_gated_and_wired -q`
Expected: FAIL — `on_fringe_apply` is not a `build_panel` param, and the slider does not start disabled.

- [ ] **Step 3: Rework the panel**

In `nocturne/ui/step_panels.py`, add the `on_fringe_apply=None` parameter to `build_panel`'s signature (next to the existing `on_fringe_change=None`).

Replace the existing `elif stage.kind == "green_fringe":` branch with:

```python
    elif stage.kind == "green_fringe":
        lay.addWidget(_desc_label(
            "Remove the green colour fringe around stars. Splits the stars from the "
            "background and de-greens only the stars, so nebula colour is untouched. "
            "0 = off. Needs RC-Astro."))
        status = _desc_label("")   # main_window sets "Separating stars…" / gate text
        lay.addWidget(status)
        slider = ResetSlider(0)
        fringe_val = QLabel(f"{slider.value() / 100:.2f}")

        def _emit_fringe(*_):
            fringe_val.setText(f"{slider.value() / 100:.2f}")
            if on_fringe_change is not None:
                on_fringe_change(slider.value() / 100.0)

        slider.valueChanged.connect(_emit_fringe)
        apply_btn = QPushButton("Apply Remove Green Fringe")
        apply_btn.setObjectName("primary")
        if on_fringe_apply is not None:
            apply_btn.clicked.connect(lambda: on_fringe_apply(slider.value() / 100.0))
        # Start disabled — main_window enables once the (slow) StarX split is ready.
        slider.setEnabled(False)
        apply_btn.setEnabled(False)
        fringe_row = QHBoxLayout()
        fringe_row.addWidget(QLabel("Strength (off → full)"))
        fringe_row.addWidget(fringe_val)
        lay.addLayout(fringe_row)
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.fringe_status = status
        w.fringe_slider = slider
        w.fringe_val = fringe_val
        w.apply_btn = apply_btn
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/step_panels.py tests/ui/test_step_panels.py
git commit -m "refactor: Green Fringe panel — status + disabled-until-ready + custom apply"
```

---

### Task 4: Rework main_window to StarX-cached split + gating

**Files:**
- Modify: `nocturne/ui/main_window.py`
- Test: `tests/ui/test_main_window.py` (replace the green-fringe tests)

**Interfaces:**
- Consumes: `remove_green_fringe` (Task 1); `_remove_stars`, `_sr_sig`, `_preview_base`, `_leading_kept`, `_show_preview`, `_run_busy`, `rcastro_valid`, `_PrecomputedStep`, `format_log_entry`, `GEOMETRY_NAMES`, `STEP_NAME`, `PROCESSING_ORDER` (all existing); `w.fringe_slider`/`fringe_status`/`apply_btn` (Task 3).
- Produces: `_fringe_preceding`, `_fringe_base`, `_setup_green_fringe`, `_on_fringe_split`, `_on_fringe_change`, `_render_fringe_preview`, `_apply_green_fringe`; `_fringe_layers`/`_fringe_ready`/`_fringe_pending`/`_fringe_timer` state.

- [ ] **Step 1: Replace the failing tests**

Replace the two existing green-fringe tests in `tests/ui/test_main_window.py`
(`test_green_fringe_live_preview_renders_without_commit`,
`test_green_fringe_preview_updates_histogram`) with:

```python
def test_green_fringe_gated_without_rcastro(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("green_fringe")               # no RC-Astro configured in tests
    assert win._panel.fringe_slider.isEnabled() is False
    assert "RC-Astro" in win._panel.fringe_status.text()


def _fake_rc_layers(win, monkeypatch):
    import numpy as np
    from nocturne.core.image import AstroImage
    starless = AstroImage(np.full((16, 16, 3), 0.3, np.float32), is_linear=False)
    stars = np.zeros((16, 16, 3), np.float32); stars[8, 8] = (0.2, 0.9, 0.3)
    stars = AstroImage(stars, is_linear=False)
    monkeypatch.setattr(win, "_remove_stars", lambda img: (starless, stars))
    monkeypatch.setattr("nocturne.ui.main_window.rcastro_valid", lambda s: True)


def test_green_fringe_caches_split_and_previews(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _fake_rc_layers(win, monkeypatch)
    win._go_to_id("green_fringe")               # sync split (_async_enabled False)
    assert win._fringe_ready is True
    assert win._panel.fringe_slider.isEnabled() is True
    entries_before = [name for name, _ in win.project.entries()]
    win._on_fringe_change(0.6)
    win._render_fringe_preview()
    assert not win.image_view._item.pixmap().isNull()
    assert [name for name, _ in win.project.entries()] == entries_before   # no commit


def test_green_fringe_apply_records_step(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _fake_rc_layers(win, monkeypatch)
    win._go_to_id("green_fringe")
    win._apply_green_fringe(0.6)
    names = [name for name, _ in win.project.entries()]
    assert names[-1] == "Remove Green Fringe"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py::test_green_fringe_gated_without_rcastro -q`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_setup_green_fringe'` (panel `fringe_status` never set), or `_fringe_ready` missing.

- [ ] **Step 3a: Replace the `__init__` green-fringe state block**

In `nocturne/ui/main_window.py`, REPLACE the existing simple green-fringe timer block in `__init__` (the one added earlier: `self._fringe_pending = None` + the `_fringe_timer` QTimer + comment "Green-fringe live-preview: a debounced (90 ms) non-committing render.") with:

```python
        # Green-fringe live-preview: the (slow) StarX split runs once on entering
        # the step (async, cached in _fringe_layers); the slider then previews the
        # instant de-green + recombine via a debounced (90 ms) render.
        self._fringe_layers = None    # (sig, starless, stars) once the split lands
        self._fringe_pending = None
        self._fringe_ready = False
        self._fringe_timer = QTimer(self)
        self._fringe_timer.setSingleShot(True)
        self._fringe_timer.timeout.connect(self._render_fringe_preview)
```

- [ ] **Step 3b: Replace the preview methods**

REPLACE the existing simple `_on_fringe_change` + `_render_fringe_preview` methods (added earlier) with this full block (mirroring the Star Reduction methods). Place it where the old methods were:

```python
    # --- green fringe live preview (cached StarX split) ---
    def _fringe_preceding(self) -> set:
        """Names of the steps that precede Remove Green Fringe — the predecessors
        a commit preserves (and whose state the split runs on)."""
        return set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index("green_fringe")]
        }

    def _fringe_base(self):
        """The pre-Remove-Green-Fringe image the split + commit both operate on."""
        return self.project.state_at(
            self._leading_kept(self.project.entries(), self._fringe_preceding()))

    def _setup_green_fringe(self) -> None:
        """On entering Remove Green Fringe: run the StarX split once, off-thread,
        and cache it. The slider then previews the instant de-green recombine. A
        cached split for the same base is reused; without RC-Astro the step is
        gated with a note and the slider/Apply stay disabled."""
        self._fringe_pending = None
        if self.project is None:
            return
        panel = self._panel
        if not rcastro_valid(self.settings):
            self._fringe_ready = False
            if hasattr(panel, "fringe_slider"):
                panel.fringe_status.setText("Needs RC-Astro — set its path in Settings.")
                panel.fringe_slider.setEnabled(False)
                panel.apply_btn.setEnabled(False)
            return
        base = self._fringe_base()
        sig = self._sr_sig(base)
        if self._fringe_layers and self._fringe_layers[0] == sig:
            self._fringe_ready = True
            if hasattr(panel, "fringe_slider"):
                panel.fringe_slider.setEnabled(True)
                panel.apply_btn.setEnabled(True)
                panel.fringe_status.setText("")
            self._render_fringe_preview()
            return
        self._fringe_ready = False
        if hasattr(panel, "fringe_slider"):
            panel.fringe_slider.setEnabled(False)
            panel.apply_btn.setEnabled(False)
            panel.fringe_status.setText("Separating stars…")
        self._run_busy(lambda: self._remove_stars(base),
                       lambda layers: self._on_fringe_split(sig, layers),
                       "Separating stars…", "Star separation failed")

    def _on_fringe_split(self, sig, layers) -> None:
        if self.current_stage_id() != "green_fringe":
            return
        self._fringe_layers = (sig, layers[0], layers[1])
        self._fringe_ready = True
        if hasattr(self._panel, "fringe_slider"):
            self._panel.fringe_slider.setEnabled(True)
            self._panel.apply_btn.setEnabled(True)
            self._panel.fringe_status.setText("")
        self._render_fringe_preview()

    def _on_fringe_change(self, strength: float) -> None:
        self._fringe_pending = strength
        if self._fringe_ready:
            self._fringe_timer.start(90)

    def _render_fringe_preview(self) -> None:
        if (self.project is None or self.current_stage_id() != "green_fringe"
                or not self._fringe_ready or not self._fringe_layers):
            return
        strength = (self._fringe_pending if self._fringe_pending is not None
                    else self._panel.fringe_slider.value() / 100.0)
        _, starless, stars = self._fringe_layers
        self._show_preview(remove_green_fringe(starless, stars, strength).data)

    def _apply_green_fringe(self, strength) -> None:
        if self.project is None or not self._fringe_ready or self._busy or not self._fringe_layers:
            return
        self.project.jump_back(
            self._leading_kept(self.project.entries(), self._fringe_preceding()))
        _, starless, stars = self._fringe_layers
        result = remove_green_fringe(starless, stars, float(strength))
        self.project.run_step(_PrecomputedStep("Remove Green Fringe", result), float(strength))
        self.log_panel.append_entry(
            format_log_entry("Remove Green Fringe", f"{float(strength):.2f}", None))
        self._status.setText("")
        self._refresh()
```

- [ ] **Step 3c: Wire the panel + setup in `_rebuild_panel`**

In `_rebuild_panel`, the `if stage.id == "green_fringe": self._fringe_pending = None` reset already exists — keep it.

In the `build_panel(...)` call, the `on_fringe_change=self._on_fringe_change,` line already exists — add the apply callback next to it:

```python
            on_fringe_change=self._on_fringe_change,
            on_fringe_apply=self._apply_green_fringe,
```

At the end of `_rebuild_panel`, next to the existing `if stage.id == "star_reduction": self._setup_star_reduction()`, add:

```python
        if stage.id == "green_fringe":
            self._setup_green_fringe()
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
git commit -m "refactor: Green Fringe uses cached StarX split + RC-Astro gate (Star Reduction pattern)"
```

---

### Task 5: Real-data validation

**Files:**
- Update: `TODO.md`

- [ ] **Step 1: Drive the app on real data**

```bash
.venv/bin/python -m nocturne
```

Open a green-fringe target, process to **Remove Green Fringe** (after Saturation). Confirm: entering the step shows "Separating stars…" then enables the slider; dragging **Strength** fades the green fringe on stars while the **background and nebula colour stay unchanged** (no magenta shift); the live preview equals the committed result; and with RC-Astro unset the step is disabled with the "Needs RC-Astro" message.

- [ ] **Step 2: Capture before/after for sign-off**

Save Strength-0 and tuned screenshots and present for approval. Do not merge until confirmed.

- [ ] **Step 3: Mark the backlog item done and commit**

Record in `TODO.md` that Remove Green Fringe shipped as a star-layer-targeted finishing step (StarX split → de-green stars only → recombine; RC-Astro-gated), noting the deferred non-RC-Astro fallback.

```bash
git add TODO.md
git commit -m "docs: mark Remove Green Fringe done (star-layer targeted, validated)"
```

---

## Self-Review

**Spec coverage:**
- Layer-based `remove_green_fringe(starless, stars, strength)` + `_suppress_green_excess`; strength 0 = plain recombine; starless untouched → Task 1. ✅
- `GreenFringeStep(rcastro)` splits internally; factory constructs with RCAstro; help reworded → Task 2. ✅
- Panel: status + disabled-until-ready + custom `on_fringe_apply` → Task 3. ✅
- main_window: cached StarX split, `rcastro_valid` gate, preview from cache, custom apply recording a precomputed step → Task 4. ✅
- Real-data validation → Task 5. ✅
- Stage registration (pipeline/recipe float/help topic) unchanged and still covered by existing tests. ✅

**Placeholder scan:** No TBD/"handle edge cases"/"similar to" — every step shows full code or an exact replace target. ✅

**Type consistency:** `remove_green_fringe(starless, stars, strength)` signature consistent across core, step wrapper, and main_window preview/apply; `GreenFringeStep(rcastro)` matches the factory construction and the fake-rc test; panel attribute names (`fringe_status`/`fringe_slider`/`fringe_val`/`apply_btn`) match between Task 3 (defined) and Task 4 (consumed); `on_fringe_change`/`on_fringe_apply` consistent across `step_panels.py` and `main_window.py`; `_fringe_layers` tuple shape `(sig, starless, stars)` consistent between `_on_fringe_split`, `_render_fringe_preview`, and `_apply_green_fringe`; reuses `_sr_sig` and `_remove_stars`. ✅
