# Diffraction Star Spikes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Star Spikes" step that draws colour-matched 4-point diffraction spikes on the brightest stars, with Length / Number-of-stars / Rotation sliders and live preview.

**Architecture:** A pure-numpy core (`nocturne/core/star_spikes.py`: `detect_stars` via the already-present `sep`, and `add_spikes` line-splatting render) drives a new `star_spikes` stage after Star Reduction. Detection is cached once on entering the step (off-thread, like the StarX split) so the three sliders re-render instantly; the commit step is self-contained (detect + render) for recipe/batch.

**Tech Stack:** Python, NumPy, `sep` (already a dependency), PySide6, pytest. No new third-party dependency.

## Global Constraints

- No new third-party dependency — `sep` is already used by `nocturne/stacking/grade.py`.
- `add_spikes(img, stars, length, count, angle)`: `length ∈ [0,1]` (0 = off), `count` int, `angle` degrees; `length==0` or `count==0` or empty `stars` → exact no-op. Screen-blend (`out = 1 - (1-img)(1-layer)`), output clipped `[0,1]` float32, `is_linear`/`metadata` preserved, greyscale → white spikes.
- Spikes are 4-point (arms at `angle, angle+90, angle+180, angle+270`), tinted by each star's sampled colour, arm length scales with star brightness (`0.4 + 0.6*w`), brightness falls off linearly to the tip; `max_len = 0.08 * min(H, W)`.
- `detect_stars(data)` returns stars brightest-first with a sampled RGB colour; caps at 100; robust to `sep` errors (returns `[]`).
- Defaults: Length **0** (off), Number-of-stars **6** (range 0–50), Rotation **0°** (range 0–90).
- Stage id `star_spikes`, display name `"Star Spikes"`, panel `kind == "star_spikes"`, placed AFTER `star_reduction` and BEFORE `enhancements`; added to `PROCESSING_ORDER` (end) and `POST_STRETCH_IDS`.
- Recipe option is `(length, count, angle)` serialized `[length, count, angle]` — its own branch.
- Follow existing patterns: step wrapper mirrors `steps/local_contrast.py`; the cached-async-detection + preview wiring mirrors the Star Reduction wiring in `main_window.py`; the panel mirrors the Star Reduction panel (status label + disabled-until-ready controls).

---

### Task 1: Core star-spikes engine (`core/star_spikes.py`)

**Files:**
- Create: `nocturne/core/star_spikes.py`
- Test: `tests/core/test_star_spikes.py`

**Interfaces:**
- Consumes: `nocturne.core.image.AstroImage`; `sep`.
- Produces:
  - `Star` dataclass: `x: float, y: float, flux: float, color: tuple`.
  - `detect_stars(data: np.ndarray) -> list[Star]` (brightest first).
  - `add_spikes(img: AstroImage, stars: list[Star], length: float, count: int, angle: float) -> AstroImage`.

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_star_spikes.py`:

```python
import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.star_spikes import Star, detect_stars, add_spikes


def _blob(h=64, w=64, cy=20, cx=40, amp=0.9, sigma=2.0):
    yy, xx = np.mgrid[0:h, 0:w]
    g = amp * np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * sigma ** 2)))
    rng = np.random.default_rng(0)
    lum = np.clip(g + 0.004 * rng.standard_normal((h, w)), 0, 1).astype(np.float32)
    return np.repeat(lum[:, :, None], 3, axis=2)


def test_detect_finds_bright_star():
    stars = detect_stars(_blob(cy=20, cx=40))
    assert len(stars) >= 1
    s = stars[0]                       # brightest first
    assert abs(s.x - 40) <= 2 and abs(s.y - 20) <= 2   # x=col, y=row
    assert len(s.color) == 3


def test_detect_empty_on_flat():
    assert detect_stars(np.zeros((32, 32, 3), np.float32)) == []


def _one_star(flux=1.0, color=(1.0, 1.0, 1.0), cy=32, cx=32):
    return [Star(x=float(cx), y=float(cy), flux=flux, color=color)]


def _dark(h=64, w=64):
    return AstroImage(np.zeros((h, w, 3), np.float32), is_linear=False)


def test_length_zero_is_noop():
    img = _dark()
    out = add_spikes(img, _one_star(), 0.0, 6, 0.0).data
    assert np.allclose(out, img.data)


def test_count_zero_is_noop():
    img = _dark()
    assert np.allclose(add_spikes(img, _one_star(), 0.5, 0, 0.0).data, img.data)


def test_spikes_brighten_the_four_arms():
    out = add_spikes(_dark(), _one_star(), 1.0, 1, 0.0).data
    assert out[32, 35].max() > 0.05        # on the horizontal arm (3 px out)
    assert out[35, 32].max() > 0.05        # on the vertical arm
    assert out[35, 35].max() < 0.02        # off any arm -> essentially untouched


def test_brighter_star_gets_longer_arm():
    def extent(flux):
        out = add_spikes(_dark(), _one_star(flux=flux), 1.0, 1, 0.0).data
        lit = np.where(out[32, 32:].max(axis=1) > 0.02)[0]
        return int(lit.max()) if len(lit) else 0
    assert extent(1.0) > extent(0.3)


def test_rotation_puts_spikes_on_the_diagonal():
    out = add_spikes(_dark(), _one_star(), 1.0, 1, 45.0).data
    assert out[35, 35].max() > 0.05        # diagonal arm now lit
    assert out[32, 35].max() < 0.02        # pure horizontal no longer lit


def test_star_colour_tints_its_spikes():
    out = add_spikes(_dark(), _one_star(color=(1.0, 0.0, 0.0)), 1.0, 1, 0.0).data
    px = out[32, 34]
    assert px[0] > px[1] and px[0] > px[2]     # red spike


def test_output_range_dtype_and_metadata():
    img = AstroImage(np.full((48, 48, 3), 0.2, np.float32),
                     is_linear=False, metadata={"k": 1})
    out = add_spikes(img, _one_star(cy=24, cx=24), 0.8, 3, 30.0)
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
    assert out.is_linear is False and out.metadata == {"k": 1}


def test_greyscale_path():
    img = AstroImage(np.zeros((48, 48), np.float32))
    out = add_spikes(img, _one_star(cy=24, cx=24), 1.0, 1, 0.0)
    assert out.data.ndim == 2
    assert out.data.max() > 0.05


def test_count_exceeding_star_list_is_safe():
    out = add_spikes(_dark(), _one_star(), 0.5, 50, 0.0).data   # only 1 star present
    assert np.all(np.isfinite(out))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/core/test_star_spikes.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nocturne.core.star_spikes'`.

- [ ] **Step 3: Write the implementation**

Create `nocturne/core/star_spikes.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import sep

from .image import AstroImage

_MAX_STARS = 100          # detection cap; the slider picks how many actually draw
_MAX_LEN_FRAC = 0.08      # longest arm as a fraction of the short edge
_THICKNESS = 1.0          # gaussian sigma (px) across each arm


@dataclass
class Star:
    x: float          # column centroid
    y: float          # row centroid
    flux: float
    color: tuple


def detect_stars(data: np.ndarray) -> list[Star]:
    """Detect stars via SEP on the display-space luminance; return them
    brightest-first with a sampled RGB colour. `data` is HxWx3 or HxW in [0,1]."""
    mono = data.ndim == 2
    lum = np.ascontiguousarray(data if mono else data.mean(axis=2), dtype=np.float32)
    try:
        bkg = sep.Background(lum)
        objects = sep.extract(lum - bkg.back(), 5.0, err=bkg.globalrms)
    except Exception:
        return []
    if len(objects) == 0:
        return []
    order = np.argsort(objects["flux"])[::-1][:_MAX_STARS]
    h, w = lum.shape
    stars: list[Star] = []
    for i in order:
        flux = float(objects["flux"][i])
        if flux <= 0:
            continue
        x = float(objects["x"][i])
        y = float(objects["y"][i])
        xi = int(np.clip(round(x), 0, w - 1))
        yi = int(np.clip(round(y), 0, h - 1))
        if mono:
            color = (1.0, 1.0, 1.0)
        else:
            px = data[yi, xi].astype(np.float32)
            m = float(px.max())
            color = tuple((px / m).tolist()) if m > 1e-6 else (1.0, 1.0, 1.0)
        stars.append(Star(x, y, flux, color))
    return stars


def _splat_line(layer, xs, ys, fall, col):
    """Accumulate a gaussian-thickness line into `layer` (HxWx3): each sample
    point (xs[i], ys[i]) with intensity fall[i], tinted by `col`."""
    h, w = layer.shape[:2]
    xi = np.round(xs).astype(np.int64)
    yi = np.round(ys).astype(np.int64)
    for dxp in (-1, 0, 1):
        for dyp in (-1, 0, 1):
            wgt = float(np.exp(-(dxp * dxp + dyp * dyp) / (2.0 * _THICKNESS ** 2)))
            xx = xi + dxp
            yy = yi + dyp
            m = (xx >= 0) & (xx < w) & (yy >= 0) & (yy < h)
            if not np.any(m):
                continue
            contrib = (fall[m] * wgt)[:, None] * np.asarray(col, np.float32)[None, :]
            np.add.at(layer, (yy[m], xx[m]), contrib)


def add_spikes(img: AstroImage, stars: list[Star], length: float, count: int,
               angle: float) -> AstroImage:
    """Draw 4-point diffraction spikes on the brightest `count` stars, tinted by
    each star's colour, and screen-blend onto the image. No-op when length or
    count is 0 or there are no stars."""
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    length = float(np.clip(length, 0.0, 1.0))
    count = int(count)
    mono = data.ndim == 2
    if length <= 0.0 or count <= 0 or not stars:
        return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))

    h, w = data.shape[:2] if not mono else data.shape
    rgb = np.repeat(data[:, :, None], 3, axis=2) if mono else data
    layer = np.zeros((h, w, 3), np.float32)

    chosen = stars[:count]
    fmax = max(s.flux for s in chosen) or 1.0
    max_len = _MAX_LEN_FRAC * min(h, w)
    arm_angles = [np.deg2rad(angle) + k * np.pi / 2 for k in range(4)]

    for s in chosen:
        wgt = float(np.clip(s.flux / fmax, 0.0, 1.0))
        arm = max_len * (0.4 + 0.6 * wgt) * length
        if arm < 1.0:
            continue
        n = int(arm * 2) + 2
        ts = np.linspace(0.0, arm, n)
        fall = wgt * (1.0 - ts / arm)
        for a in arm_angles:
            _splat_line(layer, s.x + ts * np.cos(a), s.y + ts * np.sin(a), fall, s.color)

    screened = 1.0 - (1.0 - rgb) * (1.0 - np.clip(layer, 0.0, 1.0))
    out = np.clip(screened, 0.0, 1.0)
    if mono:
        out = out.mean(axis=2)
    return AstroImage(out.astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/core/test_star_spikes.py -q`
Expected: PASS (12 passed).

- [ ] **Step 5: Commit**

```bash
git add nocturne/core/star_spikes.py tests/core/test_star_spikes.py
git commit -m "feat: star-spikes core — sep detection + line-splatting add_spikes"
```

---

### Task 2: Register the Star Spikes stage (step, factory, pipeline, recipe, help)

**Files:**
- Create: `nocturne/steps/star_spikes.py`
- Modify: `nocturne/steps/factory.py`
- Modify: `nocturne/ui/pipeline.py`
- Modify: `nocturne/recipe.py`
- Modify: `nocturne/ui/help_content.py`
- Test: `tests/steps/test_factory.py`, `tests/ui/test_pipeline.py`, `tests/test_recipe.py`

**Interfaces:**
- Consumes: `detect_stars`, `add_spikes` from `nocturne.core.star_spikes` (Task 1); `nocturne.history.step.Step`.
- Produces: `StarSpikesStep` (`name = "Star Spikes"`, self-contained `apply(img, option)` → `add_spikes(img, detect_stars(img.data), *option)`); stage id `"star_spikes"` in `path_stages()`, `STEP_NAME`, `PROCESSING_ORDER` (end, after `star_reduction`), `POST_STRETCH_IDS`; `make_step("star_spikes", ...)` → `StarSpikesStep`; recipe round-trips `(length, count, angle)`.

- [ ] **Step 1: Write / update the failing tests**

Add to `tests/steps/test_factory.py`:

```python
def test_make_step_star_spikes():
    from nocturne.steps.factory import make_step
    from nocturne.steps.star_spikes import StarSpikesStep
    from nocturne.settings import Settings
    assert isinstance(make_step("star_spikes", Settings()), StarSpikesStep)


def test_star_spikes_step_is_self_contained_noop_on_empty():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.steps.star_spikes import StarSpikesStep
    img = AstroImage(np.zeros((32, 32, 3), np.float32), is_linear=False)
    # empty option -> no-op; length 0 -> no-op
    assert np.allclose(StarSpikesStep().apply(img, "").data, img.data)
    assert np.allclose(StarSpikesStep().apply(img, (0.0, 6, 0.0)).data, img.data)
```

Update the frozen lists in `tests/ui/test_pipeline.py`.

Replace `test_path_stages_single_linear_flow`:

```python
def test_path_stages_single_linear_flow():
    ids = [s.id for s in path_stages()]
    assert ids == [
        "load", "crop", "background", "color", "deconvolution", "stretch",
        "recover_core", "levels", "curves", "saturation", "noise_sharpen",
        "local_contrast", "star_reduction", "star_spikes", "enhancements", "export",
    ]
```

Replace the `PROCESSING_ORDER` assertion inside `test_step_name_and_order`:

```python
    assert PROCESSING_ORDER == [
        "background", "color", "remove_green", "deconvolution", "stretch",
        "recover_core", "levels", "curves", "saturation", "noise_sharpen",
        "local_contrast", "star_reduction", "star_spikes",
    ]
```

Update the exact-set assertion in `test_post_stretch_ids_are_the_finishing_steps_minus_export` to include `"star_spikes"` (add to the expected `frozenset({...})`, keeping every existing member).

Add:

```python
def test_star_spikes_placed_after_star_reduction():
    from nocturne.ui.pipeline import POST_STRETCH_IDS, STEP_NAME
    ids = [s.id for s in path_stages()]
    assert ids.index("star_spikes") == ids.index("star_reduction") + 1
    assert ids.index("star_spikes") < ids.index("enhancements")
    assert STEP_NAME["star_spikes"] == "Star Spikes"
    assert "star_spikes" in POST_STRETCH_IDS
```

Add to `tests/test_recipe.py`:

```python
def test_star_spikes_option_round_trip():
    from nocturne.recipe import serialize_option, deserialize_option
    opt = (0.3, 8, 45.0)
    ser = serialize_option("star_spikes", opt)
    assert ser == [0.3, 8, 45.0]
    assert deserialize_option("star_spikes", ser) == opt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/steps/test_factory.py tests/ui/test_pipeline.py tests/test_recipe.py -q`
Expected: FAIL — `ModuleNotFoundError: nocturne.steps.star_spikes` and the updated frozen-list assertions fail.

- [ ] **Step 3a: Create the step wrapper**

Create `nocturne/steps/star_spikes.py`:

```python
from __future__ import annotations

from ..core.image import AstroImage
from ..core.star_spikes import add_spikes, detect_stars
from ..history.step import Step


class StarSpikesStep(Step):
    name = "Star Spikes"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        if not option:
            return AstroImage(img.data.copy(),
                              is_linear=img.is_linear, metadata=dict(img.metadata))
        length, count, angle = option
        return add_spikes(img, detect_stars(img.data), length, count, angle)
```

- [ ] **Step 3b: Register in the factory**

In `nocturne/steps/factory.py`, add the import next to the other step imports:

```python
from .star_spikes import StarSpikesStep
```

and add this branch after the `star_reduction` branch:

```python
    if stage_id == "star_spikes":
        return StarSpikesStep()
```

- [ ] **Step 3c: Register the stage in the pipeline**

In `nocturne/ui/pipeline.py`:

Insert into `_IN_APP_TAIL` after the `star_reduction` Stage, before `enhancements`:

```python
    Stage("star_reduction", "Star Reduction", "star_reduction"),
    Stage("star_spikes", "Star Spikes", "star_spikes"),
    Stage("enhancements", "Enhancements", "enhance"),
```

Add to `STEP_NAME` after the `"star_reduction"` entry:

```python
    "star_reduction": "Star Reduction",
    "star_spikes": "Star Spikes",
```

Append `"star_spikes"` to the end of `PROCESSING_ORDER`:

```python
PROCESSING_ORDER = [
    "background", "color", "remove_green", "deconvolution", "stretch",
    "recover_core", "levels", "curves", "saturation", "noise_sharpen",
    "local_contrast", "star_reduction", "star_spikes",
]
```

Add `"star_spikes"` to `POST_STRETCH_IDS`:

```python
POST_STRETCH_IDS = frozenset({
    "recover_core", "levels", "curves", "saturation", "noise_sharpen",
    "local_contrast", "star_reduction", "star_spikes", "enhancements",
})
```

- [ ] **Step 3d: Recipe serialization**

In `nocturne/recipe.py`, add a `star_spikes` branch to both functions.

In `serialize_option`, before the final `return option`:

```python
    if stage_id == "star_spikes":
        length, count, angle = option if option else (0.0, 6, 0.0)
        return [float(length), int(count), float(angle)]
```

In `deserialize_option`, before the final `return value`:

```python
    if stage_id == "star_spikes":
        length, count, angle = value
        return (float(length), int(count), float(angle))
```

- [ ] **Step 3e: Help topic**

In `nocturne/ui/help_content.py`:

Add to `_STAGE_TO_TOPIC` after the `"star_reduction"` entry:

```python
    "star_reduction": "star_reduction",
    "star_spikes": "star_spikes",
```

Add a topic to `_TOPIC_LIST` (place it just before the `enhancements` `_t(...)` entry so the guide reads in pipeline order):

```python
    _t("star_spikes", "Star Spikes",
       "Add diffraction spikes to the brightest stars.",
       "<h4>What it does</h4>"
       "<p>Refractor scopes like the Seestar produce no diffraction spikes — the "
       "four-point flares many people associate with an astrophoto. This step draws "
       "tasteful, colour-matched spikes on the brightest stars.</p>"
       "<h4>How to use it</h4>"
       "<p><b>Length</b> sets how long the spikes are (0 = off). <b>Number of stars</b> "
       "chooses how many of the brightest stars get spikes. <b>Rotation</b> tilts the "
       "cross (e.g. 45° for a diagonal X). Brighter stars get bolder spikes automatically. "
       "Watch the live preview. Apply.</p>"
       "<h4>Tips</h4>"
       "<p>Less is more — a few long spikes on the brightest stars looks intentional; "
       "spikes on everything looks fake. Keep the count low.</p>"),
```

Add `"star_spikes"` to the "The Steps" `HelpSection` tuple after `"star_reduction"`:

```python
    HelpSection("The Steps", ("crop", "background", "color", "deconvolution", "stretch",
                              "recover_core", "levels", "curves", "saturation",
                              "noise_sharpen", "local_contrast", "star_reduction",
                              "star_spikes", "enhancements", "export")),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/steps/test_factory.py tests/ui/test_pipeline.py tests/ui/test_help_content.py tests/test_recipe.py -q`
Expected: PASS (all green, including the help completeness test now that `star_spikes` has a topic).

- [ ] **Step 5: Commit**

```bash
git add nocturne/steps/star_spikes.py nocturne/steps/factory.py nocturne/ui/pipeline.py nocturne/recipe.py nocturne/ui/help_content.py tests/steps/test_factory.py tests/ui/test_pipeline.py tests/test_recipe.py
git commit -m "feat: register Star Spikes stage (step, factory, pipeline, recipe, help)"
```

---

### Task 3: Star Spikes panel

**Files:**
- Modify: `nocturne/ui/step_panels.py` (add `on_spikes_change` param + `star_spikes` branch)
- Test: `tests/ui/test_step_panels.py`

**Interfaces:**
- Consumes: stage `star_spikes` from `path_stages()` (Task 2); `ResetSlider`, `QLabel`, `QPushButton`, `QHBoxLayout` (already imported).
- Produces: `build_panel(..., on_spikes_change=None)`; panel with `w.spikes_status`, `w.length_slider`, `w.stars_slider`, `w.angle_slider`, `w.length_val`, `w.stars_val`, `w.angle_val`, `w.apply_btn`, `w.panel_kind == "star_spikes"`. Sliders + Apply start **disabled**. Slider `valueChanged` updates readouts and calls `on_spikes_change(length/100, stars, float(angle))`; Apply calls `on_apply((length/100, stars, float(angle)))`.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_step_panels.py`:

```python
def test_star_spikes_panel_controls(qtbot):
    seen = []
    w = build_panel(_stage("star_spikes"), on_spikes_change=lambda *a: seen.append(a))
    qtbot.addWidget(w)
    assert w.panel_kind == "star_spikes"
    for attr in ("spikes_status", "length_slider", "stars_slider", "angle_slider",
                 "length_val", "stars_val", "angle_val", "apply_btn"):
        assert hasattr(w, attr)
    # sliders start disabled (enabled by main_window once detection caches)
    assert w.length_slider.isEnabled() is False
    assert w.apply_btn.isEnabled() is False
    # defaults
    assert w.stars_slider.value() == 6
    # a change fires the callback with (length, count, angle) and updates readouts
    w.length_slider.setEnabled(True)
    w.length_slider.setValue(40)
    assert seen and seen[-1] == (0.40, 6, 0.0)
    assert w.length_val.text().strip() == "0.40"
    assert w.angle_val.text().strip() == "0°"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py::test_star_spikes_panel_controls -q`
Expected: FAIL — `build_panel()` got an unexpected keyword `on_spikes_change` (or the `star_spikes` kind falls through to a bare panel).

- [ ] **Step 3: Implement the panel**

In `nocturne/ui/step_panels.py`, add the parameter to `build_panel`'s signature (next to `on_sr_apply=None`):

```python
    on_sr_apply=None,
    on_spikes_change=None,
```

Add the branch (place it after the `star_reduction` branch, matching pipeline order):

```python
    elif stage.kind == "star_spikes":
        lay.addWidget(_desc_label(
            "Add diffraction spikes to the brightest stars. Length 0 = off. "
            "Keep the star count low so it looks intentional."))
        status = _desc_label("")   # main_window sets "Detecting stars…"
        lay.addWidget(status)
        length = ResetSlider(0)
        stars = ResetSlider(6, minimum=0, maximum=50)
        angle = ResetSlider(0, minimum=0, maximum=90)
        length_val = QLabel(f"{length.value() / 100:.2f}")
        stars_val = QLabel(str(stars.value()))
        angle_val = QLabel(f"{angle.value()}°")

        def _emit(*_):
            length_val.setText(f"{length.value() / 100:.2f}")
            stars_val.setText(str(stars.value()))
            angle_val.setText(f"{angle.value()}°")
            if on_spikes_change is not None:
                on_spikes_change(length.value() / 100.0, stars.value(),
                                 float(angle.value()))

        length.valueChanged.connect(_emit)
        stars.valueChanged.connect(_emit)
        angle.valueChanged.connect(_emit)

        apply_btn = QPushButton("Apply Star Spikes")
        apply_btn.setObjectName("primary")
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(
                (length.value() / 100.0, stars.value(), float(angle.value()))))

        # Start disabled — main_window enables once detection has cached.
        for wdg in (length, stars, angle, apply_btn):
            wdg.setEnabled(False)

        def _row(label, val):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(val)
            lay.addLayout(row)

        _row("Length (off → long)", length_val)
        lay.addWidget(length)
        _row("Number of stars", stars_val)
        lay.addWidget(stars)
        _row("Rotation", angle_val)
        lay.addWidget(angle)
        lay.addWidget(apply_btn)

        w.spikes_status = status
        w.length_slider = length
        w.stars_slider = stars
        w.angle_slider = angle
        w.length_val = length_val
        w.stars_val = stars_val
        w.angle_val = angle_val
        w.apply_btn = apply_btn
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py -q`
Expected: PASS (all step-panel tests green).

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/step_panels.py tests/ui/test_step_panels.py
git commit -m "feat: Star Spikes panel (Length / Number-of-stars / Rotation sliders)"
```

---

### Task 4: main_window cached detection, live preview + commit wiring

**Files:**
- Modify: `nocturne/ui/main_window.py` (import, `__init__` state+timer, setup/detect/preview methods, `_rebuild_panel`, `_log_step`)
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `detect_stars`, `add_spikes` (Task 1); `_preview_base`, `_show_preview`, `_run_busy`, `_sr_sig`, `current_stage_id`, `apply_current`, `build_panel` (existing); `w.length_slider`/`stars_slider`/`angle_slider`/`spikes_status`/`apply_btn` (Task 3); stage `star_spikes` in `PROCESSING_ORDER`/factory (Task 2, so `apply_current` commits it).
- Produces: `_setup_star_spikes()`, `_on_spikes_detected(sig, stars)`, `_enable_spikes_panel(on, status="")`, `_on_spikes_change(length, count, angle)`, `_render_spikes_preview()`; `_spikes_pending`/`_spikes_stars`/`_spikes_ready`/`_spikes_timer`; `on_spikes_change` wired into `build_panel(...)`; `_rebuild_panel` resets pending and calls `_setup_star_spikes()` on entry; `"star_spikes"` handled in `_log_step`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_main_window.py`:

```python
def test_star_spikes_caches_stars_and_enables_controls(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("star_spikes")            # sync detection (_async_enabled False in tests)
    assert win._spikes_ready is True
    assert win._panel.length_slider.isEnabled() is True


def test_star_spikes_preview_renders_without_commit(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("star_spikes")
    entries_before = [name for name, _ in win.project.entries()]
    win._on_spikes_change(0.6, 6, 0.0)
    win._render_spikes_preview()
    assert not win.image_view._item.pixmap().isNull()
    assert [name for name, _ in win.project.entries()] == entries_before   # no commit


def test_star_spikes_preview_updates_histogram(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("star_spikes")
    seen = []
    monkeypatch.setattr(win.histogram_view, "set_image", lambda img: seen.append(img))
    win._on_spikes_change(0.6, 6, 0.0)
    win._render_spikes_preview()
    assert seen
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py::test_star_spikes_caches_stars_and_enables_controls -q`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_spikes_ready'` (or `_setup_star_spikes`).

- [ ] **Step 3a: Import the core functions**

In `nocturne/ui/main_window.py`, next to `from ..core.star_reduction import reduce_stars`:

```python
from ..core.star_spikes import add_spikes, detect_stars
```

- [ ] **Step 3b: Add state + debounce timer in `__init__`**

After the star-reduction timer/state block in `__init__` (search for `self._sr_timer` / `self._sr_layers`), add:

```python
        self._spikes_pending = None
        self._spikes_stars = None      # (sig, list[Star]) cache, or None
        self._spikes_ready = False
        self._spikes_timer = QTimer(self)
        self._spikes_timer.setSingleShot(True)
        self._spikes_timer.timeout.connect(self._render_spikes_preview)
```

- [ ] **Step 3c: Add the setup / detect / preview methods**

After `_apply_star_reduction` (before the `# --- history ---` section), add:

```python
    # --- star spikes live preview (cached SEP detection) ---
    def _enable_spikes_panel(self, on: bool, status: str = "") -> None:
        panel = self._panel
        if not hasattr(panel, "length_slider"):
            return
        for wdg in (panel.length_slider, panel.stars_slider,
                    panel.angle_slider, panel.apply_btn):
            wdg.setEnabled(on)
        panel.spikes_status.setText(status)

    def _setup_star_spikes(self) -> None:
        """On entering Star Spikes: detect stars once, off-thread, and cache them.
        The three sliders then re-render instantly. A cached detection for the same
        base is reused."""
        self._spikes_pending = None
        if self.project is None:
            return
        base = self._preview_base("star_spikes")
        sig = self._sr_sig(base)
        if self._spikes_stars is not None and self._spikes_stars[0] == sig:
            self._spikes_ready = True
            self._enable_spikes_panel(True)
            self._render_spikes_preview()
            return
        self._spikes_ready = False
        self._enable_spikes_panel(False, "Detecting stars…")
        self._run_busy(lambda: detect_stars(base.data),
                       lambda stars: self._on_spikes_detected(sig, stars),
                       "Detecting stars…", "Star detection failed")

    def _on_spikes_detected(self, sig, stars) -> None:
        if self.current_stage_id() != "star_spikes":
            return
        self._spikes_stars = (sig, stars)
        self._spikes_ready = True
        self._enable_spikes_panel(True)
        self._render_spikes_preview()

    def _on_spikes_change(self, length: float, count: int, angle: float) -> None:
        self._spikes_pending = (length, count, angle)
        if self._spikes_ready:
            self._spikes_timer.start(90)

    def _render_spikes_preview(self) -> None:
        """Non-committing live preview against the cached star list."""
        if (self.project is None or self.current_stage_id() != "star_spikes"
                or not self._spikes_ready or self._spikes_stars is None):
            return
        if self._spikes_pending is not None:
            length, count, angle = self._spikes_pending
        else:
            p = self._panel
            length = p.length_slider.value() / 100.0
            count = p.stars_slider.value()
            angle = float(p.angle_slider.value())
        base = self._preview_base("star_spikes")
        _, stars = self._spikes_stars
        self._show_preview(add_spikes(base, stars, length, count, angle).data)
```

- [ ] **Step 3d: Reset pending, wire callback, and set up on entry in `_rebuild_panel`**

In `_rebuild_panel`, next to the other per-stage resets:

```python
        if stage.id == "star_spikes":
            self._spikes_pending = None
```

In the same method's `build_panel(...)` call, add the callback next to `on_sr_apply=self._apply_star_reduction,`:

```python
            on_sr_apply=self._apply_star_reduction,
            on_spikes_change=self._on_spikes_change,
```

At the end of `_rebuild_panel`, next to the existing `if stage.id == "star_reduction": self._setup_star_reduction()`:

```python
        if stage.id == "star_spikes":
            self._setup_star_spikes()
```

- [ ] **Step 3e: Format the log label**

In `_log_step`, add a `star_spikes` branch (the option is a `(length, count, angle)` tuple, not user-facing text). Place it before the `isinstance(option, float)` check:

```python
        elif stage_id == "star_spikes":
            length, cnt, ang = option
            label = f"len {length:.2f}, {cnt} stars, {int(ang)}°"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -q`
Expected: PASS (all main-window tests green).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS (all tests green; count = previous total + the new star_spikes/panel/window/factory/pipeline/recipe tests).

- [ ] **Step 6: Commit**

```bash
git add nocturne/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat: Star Spikes cached detection, live preview + commit wiring"
```

---

### Task 5: Real-data validation

**Files:**
- Modify (only if tuning is needed): `nocturne/core/star_spikes.py` (`_MAX_LEN_FRAC`, `_THICKNESS`, arm/falloff constants, default count)
- Update: `TODO.md` (mark the Star Spikes item done)

**Interfaces:**
- Consumes: the shipped Star Spikes step.
- Produces: validated look; before/after evidence for sign-off.

- [ ] **Step 1: Drive the app on real data**

```bash
.venv/bin/python -m nocturne
```

Open a stretched target with a decent star field (e.g. `/Volumes/Work2/Images/Astro/NGC 7000_sub/NGC7000_182x20s_61min.fits`), run through to **Star Spikes** (after Star Reduction). Confirm: entering the step shows "Detecting stars…" briefly then enables the sliders; dragging **Length** grows spikes on the brightest stars; **Number of stars** adds/removes how many stars get spikes; **Rotation** tilts the cross; spikes are colour-matched to their stars; brighter stars get bolder spikes; the live preview equals the committed result after Apply.

- [ ] **Step 2: Judge and, if needed, tune the constants**

Check against the spec's success criterion — spikes look intentional, not fake. If too long/short, adjust `_MAX_LEN_FRAC`; if too thin/thick, `_THICKNESS`; if too many stars by default, lower the panel's `stars` default (in `step_panels.py`). Re-run `.venv/bin/python -m pytest tests/core/test_star_spikes.py -q` after any core change, and repeat Step 1.

- [ ] **Step 3: Capture before/after for sign-off**

Save a Length-0 (off) and a tuned screenshot and present them for approval. Do not merge until the user confirms.

- [ ] **Step 4: Mark the backlog item done and commit**

In `TODO.md`, change the "Diffraction / star spikes" item from `- [ ]` to `- [x]` with a "done 2026-07-20" note. If constants were tuned:

```bash
git add nocturne/core/star_spikes.py TODO.md
git commit -m "tune: Star Spikes constants validated on real data; mark backlog done"
```

Otherwise commit just the TODO update:

```bash
git add TODO.md
git commit -m "docs: mark diffraction star spikes done (validated on real data)"
```

---

## Self-Review

**Spec coverage:**
- `core/star_spikes.py` `Star`, `detect_stars` (sep, brightest-first, colour, robust), `add_spikes` (4-point, brightness-scaled length, falloff, colour tint, screen blend, no-op at length/count 0, greyscale) → Task 1. ✅
- Stage after Star Reduction; `POST_STRETCH_IDS`; recipe `(length,count,angle)` round-trip; help topic; self-contained `StarSpikesStep` → Task 2. ✅
- Panel: 3 sliders + readouts + status + Apply, disabled until ready → Task 3. ✅
- Cached async detection on entry; debounced live preview via `_preview_base`→`_show_preview` (image + histogram); commit via `apply_current`; log label → Task 4. ✅
- Real-data validation + tuning → Task 5. ✅
- Tests: core, panel, window, factory, pipeline (frozen lists), recipe → Tasks 1–4. ✅

**Placeholder scan:** No TBD/"handle edge cases"/"similar to" — every code step contains full code. ✅

**Type consistency:** `detect_stars(data) -> list[Star]` and `add_spikes(img, stars, length, count, angle)` consistent across core, step wrapper, and main_window preview; the `(length, count, angle)` option shape is consistent across panel Apply, `apply_current`, `StarSpikesStep.apply`, recipe serialize/deserialize, and `_log_step`; panel attribute names (`length_slider`/`stars_slider`/`angle_slider`/`spikes_status`) match between Task 3 (defined) and Task 4 (consumed); callback `on_spikes_change` consistent between `step_panels.py` and `main_window.py`; stage id `"star_spikes"` consistent across pipeline, factory, recipe, help, panel kind; `_sr_sig` reused for the detection cache fingerprint. ✅
