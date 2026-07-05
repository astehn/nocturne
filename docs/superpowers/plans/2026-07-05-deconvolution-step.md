# Linear Deconvolution Step Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a linear Deconvolution step (BlurXTerminator before Stretch, free unsharp fallback) and split sharpening out of "Noise & Sharpen" so BXT runs once, in the right place.

**Architecture:** New `DeconvolutionStep` (BXT `sharpen_stars`+`sharpen_nonstellar` on linear data; free `sharpen` fallback), wired as a `"deconvolution"` process stage between Color and Stretch. `NoiseSharpenStep` becomes denoise-only and is relabelled "Noise Reduction".

**Tech Stack:** Python 3.13 (`.venv`), PySide6, RC-Astro BXT/NXT CLI, pytest-qt (`QT_QPA_PLATFORM=offscreen`).

## Global Constraints

- Use `.venv/bin/python` / `.venv/bin/pytest`; system python is 3.9 will fail. Qt tests: prefix `QT_QPA_PLATFORM=offscreen`; tests set `win._async_enabled = False`.
- Deconvolution runs on **linear** data, sharpening stars AND nebula: `_LEVELS = {"light": (0.3, 0.3), "medium": (0.5, 0.5), "strong": (0.7, 0.7)}` (sharpen_stars, sharpen_nonstellar), default `"medium"`. RC-Astro path uses `rc.deconvolve(img, sharpen_stars=ss, sharpen_nonstellar=sn, runner=...)`; free fallback `core/deconvolution.sharpen(img, sn)`. NOT gated-disabled (always works).
- `"deconvolution"` goes into `PROCESSING_ORDER` after `"remove_green"` and before `"stretch"`; `STEP_NAME["deconvolution"] = "Deconvolution"`; a `Stage("deconvolution", "Deconvolution", "process")` sits in `_CORE` after `color`, before `stretch`; `_PROCESS_OPTIONS["deconvolution"] = ["light","medium","strong"]`.
- `NoiseSharpenStep` (id stays `"noise_sharpen"`) becomes denoise-only: `_LEVELS = {"light":0.4,"medium":0.7,"strong":0.9}`; `rc.denoise` / free `reduce_noise`; `name = "Noise Reduction"`; `STEP_NAME["noise_sharpen"] = "Noise Reduction"`; stage label → "Noise Reduction".
- Commit co-author trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Known flake: `test_sharpen_changes_image_and_keeps_shape` — rerun alone if it trips.

---

### Task 1: `DeconvolutionStep` + factory + free fallback

**Files:**
- Create: `seestar_processor/steps/deconvolution_step.py`
- Modify: `seestar_processor/steps/factory.py` (import + branch)
- Test: `tests/steps/test_new_steps.py`, `tests/steps/test_factory.py`

**Interfaces:**
- Produces: `DeconvolutionStep(rcastro=None)` with `apply(img, option)`; `make_step("deconvolution", settings) -> DeconvolutionStep`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/steps/test_new_steps.py` (imports `np`, `AstroImage`, `write_temp_fits`, `RCAstro` already present):
```python
def test_deconvolution_free_fallback_sharpens():
    from seestar_processor.steps.deconvolution_step import DeconvolutionStep
    img = AstroImage(np.random.rand(20, 20, 3).astype(np.float32), is_linear=True)
    out = DeconvolutionStep().apply(img, "medium")        # no RC-Astro -> free unsharp
    assert out.data.shape == img.data.shape
    assert not np.allclose(out.data, img.data)            # sharpening changed the image


def test_deconvolution_uses_bxt_and_sharpens_stars():
    from seestar_processor.steps.deconvolution_step import DeconvolutionStep
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=True)
    calls = []
    def fake(args):
        calls.append(args)
        write_temp_fits(img, args[args.index("-o") + 1])
    step = DeconvolutionStep(rcastro=RCAstro("/fake/rc-astro"))
    step._runner = fake
    step.apply(img, "medium")
    products = [a[a.index("--no-banner") + 1] for a in calls]
    assert products == ["bxt"]                            # BXT deconvolution
    bxt = calls[0]
    assert float(bxt[bxt.index("--sharpen-stars") + 1]) > 0   # tightens stars on linear
```

Add to `tests/steps/test_factory.py` (extend `test_make_step_types`):
```python
    from seestar_processor.steps.deconvolution_step import DeconvolutionStep
    assert isinstance(make_step("deconvolution", s), DeconvolutionStep)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/steps/test_new_steps.py tests/steps/test_factory.py -q -k "deconvolution or make_step_types"`
Expected: FAIL — `ModuleNotFoundError: seestar_processor.steps.deconvolution_step`.

- [ ] **Step 3: Create the step**

Create `seestar_processor/steps/deconvolution_step.py`:
```python
from __future__ import annotations

from ..core.deconvolution import sharpen
from ..core.image import AstroImage
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro

# option -> (sharpen_stars, sharpen_nonstellar)
_LEVELS = {"light": (0.3, 0.3), "medium": (0.5, 0.5), "strong": (0.7, 0.7)}


class DeconvolutionStep(Step):
    """Linear deconvolution (BlurXTerminator): tightens stars and recovers fine
    detail, run before the stretch. Free unsharp-mask fallback without RC-Astro."""

    name = "Deconvolution"

    def __init__(self, rcastro: RCAstro | None = None) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["light", "medium", "strong"]

    def default_option(self) -> str:
        return "medium"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        ss, sn = _LEVELS[option]
        if self._rc is not None:
            return self._rc.deconvolve(
                img, sharpen_stars=ss, sharpen_nonstellar=sn, runner=self._runner)
        return sharpen(img, sn)
```

- [ ] **Step 4: Wire the factory**

In `seestar_processor/steps/factory.py`, add the import alongside the others:
```python
from .deconvolution_step import DeconvolutionStep
```
and add the branch (near the other RC-Astro-wired steps, e.g. after `noise_sharpen`):
```python
    if stage_id == "deconvolution":
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        step = DeconvolutionStep(rc)
        step._runner = rc_runner
        return step
```

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/pytest tests/steps/test_new_steps.py tests/steps/test_factory.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add seestar_processor/steps/deconvolution_step.py seestar_processor/steps/factory.py \
        tests/steps/test_new_steps.py tests/steps/test_factory.py
git commit -m "feat: DeconvolutionStep (linear BXT + free unsharp fallback) + factory"
```

---

### Task 2: Split "Noise & Sharpen" into denoise-only

**Files:**
- Modify: `seestar_processor/steps/noise_sharpen.py`
- Test: `tests/steps/test_new_steps.py`

**Interfaces:**
- Produces: `NoiseSharpenStep.apply` denoises only (`rc.denoise` / free `reduce_noise`); `name = "Noise Reduction"`.

- [ ] **Step 1: Update the failing test**

In `tests/steps/test_new_steps.py`, change the existing `NoiseSharpenStep` product assertion from `["nxt", "bxt"]` to denoise-only:
```python
    assert products == ["nxt"]  # denoise only (sharpening moved to Deconvolution)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/steps/test_new_steps.py -q -k "noise or sharpen"`
Expected: FAIL — current step still runs `bxt` (products `["nxt","bxt"]`).

- [ ] **Step 3: Make the step denoise-only**

Replace `seestar_processor/steps/noise_sharpen.py` with:
```python
from __future__ import annotations

from ..core.image import AstroImage
from ..core.noise import reduce_noise
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro

_LEVELS = {"light": 0.4, "medium": 0.7, "strong": 0.9}   # denoise strengths


class NoiseSharpenStep(Step):
    """Post-stretch denoise (NoiseXTerminator; free reduce_noise fallback).
    Sharpening/deconvolution is the separate Deconvolution step."""

    name = "Noise Reduction"

    def __init__(self, rcastro: RCAstro | None = None) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["light", "medium", "strong"]

    def default_option(self) -> str:
        return "medium"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        dn = _LEVELS[option]
        if self._rc is not None:
            return self._rc.denoise(img, dn, runner=self._runner)
        return reduce_noise(img, dn)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/steps/test_new_steps.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/steps/noise_sharpen.py tests/steps/test_new_steps.py
git commit -m "refactor: Noise & Sharpen -> denoise-only (Noise Reduction); sharpen moves to Deconvolution"
```

---

### Task 3: Pipeline stage, panel options, labels, navigation

**Files:**
- Modify: `seestar_processor/ui/pipeline.py` (`_CORE`, `_IN_APP_TAIL`, `STEP_NAME`, `PROCESSING_ORDER`)
- Modify: `seestar_processor/ui/step_panels.py` (`_PROCESS_OPTIONS`, `_DESCRIPTIONS`)
- Test: `tests/ui/test_pipeline.py`, `tests/ui/test_step_panels.py`, `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `make_step("deconvolution")` (Task 1); `NoiseSharpenStep` denoise-only (Task 2).

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_pipeline.py`:
```python
def test_deconvolution_stage_and_order():
    from seestar_processor.ui.pipeline import (
        PROCESSING_ORDER, STEP_NAME, path_stages)
    assert STEP_NAME["deconvolution"] == "Deconvolution"
    assert STEP_NAME["noise_sharpen"] == "Noise Reduction"
    i = PROCESSING_ORDER.index("deconvolution")
    assert PROCESSING_ORDER[i - 1] == "remove_green"
    assert PROCESSING_ORDER[i + 1] == "stretch"
    ids = [s.id for s in path_stages()]
    assert "deconvolution" in ids and ids.index("deconvolution") < ids.index("stretch")
```

Add to `tests/ui/test_step_panels.py`:
```python
def test_deconvolution_panel_emits_strength(qtbot):
    got = []
    w = build_panel(_stage("deconvolution"), on_apply=got.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "process"
    assert [w.option_box.itemText(i) for i in range(w.option_box.count())] == \
        ["light", "medium", "strong"]
    w.option_box.setCurrentText("strong")
    w.apply_btn.click()
    assert got == ["strong"]
```

In `tests/ui/test_main_window.py`, update `test_default_in_app_path_navigation`'s `seq` to include `"deconvolution"` after `"color"`:
```python
    seq = ["crop", "background", "color", "deconvolution", "stretch", "levels",
           "saturation", "noise_sharpen", "local_contrast", "star_reduction", "export"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_pipeline.py tests/ui/test_step_panels.py tests/ui/test_main_window.py -q -k "deconvolution or in_app_path"`
Expected: FAIL — no `deconvolution` in `STEP_NAME`/`PROCESSING_ORDER`/stages; panel `_PROCESS_OPTIONS` KeyError; nav sequence mismatch.

- [ ] **Step 3: Wire the pipeline**

In `seestar_processor/ui/pipeline.py`:

Add the stage to `_CORE` (after the `color` Stage, before `stretch`):
```python
    Stage("color", "Color", "auto"),
    Stage("deconvolution", "Deconvolution", "process"),
    Stage("stretch", "Stretch", "stretch"),
```
Relabel the noise stage in `_IN_APP_TAIL`:
```python
    Stage("noise_sharpen", "Noise Reduction", "process"),
```
Update `STEP_NAME` (add deconvolution; relabel noise):
```python
    "remove_green": "Remove Green",
    "deconvolution": "Deconvolution",
    "stretch": "Stretch",
    ...
    "noise_sharpen": "Noise Reduction",
```
Insert into `PROCESSING_ORDER` after `"remove_green"`, before `"stretch"`:
```python
PROCESSING_ORDER = [
    "background", "color", "remove_green", "deconvolution", "stretch", "levels",
    "saturation", "noise_sharpen", "local_contrast", "star_reduction",
]
```

- [ ] **Step 4: Wire the panel dicts**

In `seestar_processor/ui/step_panels.py`:
```python
_PROCESS_OPTIONS = {
    "background": ["off", "light", "strong"],
    "deconvolution": ["light", "medium", "strong"],
    "noise_sharpen": ["light", "medium", "strong"],
    "local_contrast": ["light", "medium", "strong"],
    "star_reduction": ["light", "medium", "strong"],
}
```
Update `_DESCRIPTIONS` (add deconvolution; reword noise):
```python
    "deconvolution": "Sharpens stars and recovers fine detail (deconvolution) on the "
                     "linear image, before stretch. Best with RC-Astro; free fallback otherwise.",
    "noise_sharpen": "Reduces grain (noise reduction).",
```

- [ ] **Step 5: Run the UI tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_pipeline.py tests/ui/test_step_panels.py tests/ui/test_main_window.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass (rerun the known sharpen flake alone if it trips).

- [ ] **Step 7: Commit**

```bash
git add seestar_processor/ui/pipeline.py seestar_processor/ui/step_panels.py \
        tests/ui/test_pipeline.py tests/ui/test_step_panels.py tests/ui/test_main_window.py
git commit -m "feat: Deconvolution stage in the pipeline (before Stretch) + Noise Reduction label"
```

---

## Self-Review

- **Spec coverage:** DeconvolutionStep + BXT/free fallback + factory (T1), Noise-Reduction split (T2), pipeline stage/order/labels + panel options + nav (T3) — covered. RL fallback / recipe capture / auto strength are out of scope per the spec.
- **Placeholder scan:** none — complete code in every step.
- **Type consistency:** `DeconvolutionStep(rcastro=None)`, `_LEVELS` (stars, nonstellar) tuple, `rc.deconvolve(sharpen_stars=, sharpen_nonstellar=)`, stage id `"deconvolution"`, and `STEP_NAME`/`PROCESSING_ORDER`/`_PROCESS_OPTIONS` entries used identically across tasks and tests.
- **Green-at-boundary:** T1 additive (new step/factory). T2 changes NoiseSharpen behaviour + its one test together. T3 adds the stage + updates the nav test together (panel `_PROCESS_OPTIONS` gains the key in the same task, so no KeyError). Colourise preservation still holds (deconvolution is inside `_stretch_preceding`).
- **Recipe note (documented):** relabelling `STEP_NAME["noise_sharpen"]` means old recipes referencing "Noise & Sharpen" no longer map — acceptable pre-1.0 (per spec).
