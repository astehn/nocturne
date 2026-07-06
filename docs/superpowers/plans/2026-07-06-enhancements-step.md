# Enhancements Step Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Enhancements" step at the end of the pipeline with five tap-to-stack buttons — Boost Red (Ha), Boost Cyan (OIII), Boost Blue, Darken Sky, Lighten Sky — each a small, individually-undoable nudge.

**Architecture:** Pure ops in `core/enhance.py` (hue-selective saturation boost; shadow-masked additive darken/lighten). A new `"enhancements"` Stage (kind `"enhance"`) with a button panel; each tap appends an undoable history step via a `_enhance(op)` handler (append-only, like rotate/flip).

**Tech Stack:** Python 3.13 (`.venv`), NumPy, scikit-image (HSV), PySide6, pytest-qt (`QT_QPA_PLATFORM=offscreen`).

## Global Constraints

- Use `.venv/bin/python` / `.venv/bin/pytest`; system python is 3.9 will fail. Qt tests: prefix `QT_QPA_PLATFORM=offscreen`; tests set `win._async_enabled = False`.
- Defaults (tuned on real data): `boost_hue(amount=0.15, width=0.12)`; hue targets Red `0.0`, Cyan `0.5`, Blue `0.667`. Sky ops: shadow weight `clip(1 - lum/0.4, 0, 1)**2`, `amount=0.08`; **additive** — darken `data - amount*w`, lighten `data + amount*w*(1-data)` (multiplicative darken was too weak on real data).
- The five op names, exact: `"Boost Red"`, `"Boost Cyan"`, `"Boost Blue"`, `"Darken Sky"`, `"Lighten Sky"`. `ENHANCE_NAMES` = that tuple.
- Enhancement ops are **append-only trailing ops** — NOT in `PROCESSING_ORDER`/`STEP_NAME` (like `GEOMETRY_NAMES`). The `"enhancements"` Stage goes in `_IN_APP_TAIL` after `star_reduction`, before `export`.
- Commit co-author trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Known flake: `test_sharpen_changes_image_and_keeps_shape` — rerun alone if it trips.

---

### Task 1: `core/enhance.py` — targeted colour + sky ops

**Files:**
- Create: `seestar_processor/core/enhance.py`
- Test: `tests/core/test_enhance.py`

**Interfaces:**
- Produces: `boost_hue(img, hue, amount=0.15, width=0.12)`, `darken_sky(img, amount=0.08)`, `lighten_sky(img, amount=0.08)` — all `AstroImage -> AstroImage`.

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_enhance.py`:
```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.enhance import boost_hue, darken_sky, lighten_sky


def _rgb(pixels):
    return AstroImage(np.array([pixels], dtype=np.float32), is_linear=False)


def test_boost_hue_is_selective():
    # a red pixel and a teal pixel side by side; Boost Red raises red saturation, not teal
    from skimage.color import rgb2hsv
    img = _rgb([(0.6, 0.2, 0.2), (0.2, 0.6, 0.6)])   # red-ish, teal-ish
    out = boost_hue(img, 0.0).data                    # hue 0 = red
    before = rgb2hsv(np.clip(img.data, 0, 1))
    after = rgb2hsv(np.clip(out, 0, 1))
    assert after[0, 0, 1] > before[0, 0, 1] + 0.01    # red pixel more saturated
    assert abs(after[0, 1, 1] - before[0, 1, 1]) < 0.01   # teal pixel ~unchanged


def test_boost_cyan_and_blue_target_their_hues():
    from skimage.color import rgb2hsv
    teal = _rgb([(0.2, 0.6, 0.6)])
    assert rgb2hsv(boost_hue(teal, 0.5).data)[0, 0, 1] > rgb2hsv(teal.data)[0, 0, 1] + 0.01
    blue = _rgb([(0.2, 0.2, 0.6)])
    assert rgb2hsv(boost_hue(blue, 0.667).data)[0, 0, 1] > rgb2hsv(blue.data)[0, 0, 1] + 0.01


def test_darken_sky_lowers_background_keeps_bright():
    img = _rgb([(0.10, 0.10, 0.10), (0.80, 0.80, 0.80)])   # dark bg, bright
    out = darken_sky(img).data
    assert out[0, 0].mean() < 0.10                          # background pulled down
    assert abs(out[0, 1].mean() - 0.80) < 0.005             # bright untouched
    assert out.min() >= 0.0


def test_lighten_sky_raises_background_keeps_bright():
    img = _rgb([(0.10, 0.10, 0.10), (0.80, 0.80, 0.80)])
    out = lighten_sky(img).data
    assert out[0, 0].mean() > 0.10                          # background lifted
    assert abs(out[0, 1].mean() - 0.80) < 0.01
    assert out.max() <= 1.0


def test_boost_hue_mono_passthrough():
    mono = AstroImage(np.full((4, 4), 0.3, np.float32), is_linear=False)
    assert boost_hue(mono, 0.0).data.ndim == 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/core/test_enhance.py -q`
Expected: FAIL — `ModuleNotFoundError: seestar_processor.core.enhance`.

- [ ] **Step 3: Create the module**

Create `seestar_processor/core/enhance.py`:
```python
from __future__ import annotations

import numpy as np

from .image import AstroImage

_KNEE = 0.4   # luminance above which the sky ops fade to nothing


def _shadow_weight(lum: np.ndarray) -> np.ndarray:
    return np.clip(1.0 - lum / _KNEE, 0.0, 1.0) ** 2   # 1 near black, 0 above the knee


def boost_hue(img: AstroImage, hue: float, amount: float = 0.15,
              width: float = 0.12) -> AstroImage:
    """Increase saturation of pixels near `hue` (0..1) with smooth circular
    falloff. Mono is returned unchanged."""
    if not img.is_color:
        return img.copy()
    from skimage.color import hsv2rgb, rgb2hsv
    hsv = rgb2hsv(np.clip(img.data, 0.0, 1.0))
    dist = np.abs(hsv[..., 0] - hue)
    dist = np.minimum(dist, 1.0 - dist)                # circular hue distance
    w = np.exp(-(dist ** 2) / (2.0 * width ** 2))
    hsv[..., 1] = np.clip(hsv[..., 1] * (1.0 + amount * w), 0.0, 1.0)
    return AstroImage(np.clip(hsv2rgb(hsv), 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def darken_sky(img: AstroImage, amount: float = 0.08) -> AstroImage:
    """Shadow-masked darken: pull the dark background down, leave bright signal."""
    data = np.clip(img.data, 0.0, 1.0)
    lum = data.mean(axis=2, keepdims=True) if img.is_color else data
    out = np.clip(data - amount * _shadow_weight(lum), 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear,
                      metadata=dict(img.metadata))


def lighten_sky(img: AstroImage, amount: float = 0.08) -> AstroImage:
    """Shadow-masked lighten: gently lift the dark background."""
    data = np.clip(img.data, 0.0, 1.0)
    lum = data.mean(axis=2, keepdims=True) if img.is_color else data
    out = np.clip(data + amount * _shadow_weight(lum) * (1.0 - data), 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear,
                      metadata=dict(img.metadata))
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/core/test_enhance.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/core/enhance.py tests/core/test_enhance.py
git commit -m "feat: core enhance ops (hue-selective boost, shadow-masked darken/lighten sky)"
```

---

### Task 2: Pipeline stage + panel

**Files:**
- Modify: `seestar_processor/ui/pipeline.py` (`_IN_APP_TAIL`, add `ENHANCE_NAMES`)
- Modify: `seestar_processor/ui/step_panels.py` (`build_panel` signature; new `enhance` branch)
- Test: `tests/ui/test_pipeline.py`, `tests/ui/test_step_panels.py`, `tests/ui/test_main_window.py`

**Interfaces:**
- Produces: `Stage("enhancements", "Enhancements", "enhance")`; `ENHANCE_NAMES`; `build_panel(..., on_enhance=None)` with enhance-panel attrs `boost_red_btn`/`boost_cyan_btn`/`boost_blue_btn`/`darken_sky_btn`/`lighten_sky_btn`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_pipeline.py`:
```python
def test_enhancements_stage_and_names():
    from seestar_processor.ui.pipeline import ENHANCE_NAMES, PROCESSING_ORDER, path_stages
    assert ENHANCE_NAMES == ("Boost Red", "Boost Cyan", "Boost Blue", "Darken Sky", "Lighten Sky")
    ids = [s.id for s in path_stages()]
    assert ids.index("star_reduction") < ids.index("enhancements") < ids.index("export")
    assert "enhancements" not in PROCESSING_ORDER   # append-only, not a truncating position
```

Add to `tests/ui/test_step_panels.py`:
```python
def test_enhance_panel_buttons_invoke_callback(qtbot):
    ops = []
    w = build_panel(_stage("enhancements"), on_enhance=ops.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "enhance"
    w.boost_red_btn.click()
    w.darken_sky_btn.click()
    w.lighten_sky_btn.click()
    assert ops == ["Boost Red", "Darken Sky", "Lighten Sky"]
```

Update `test_default_in_app_path_navigation` in `tests/ui/test_main_window.py` — add `"enhancements"` before `"export"`:
```python
    seq = ["crop", "background", "color", "deconvolution", "stretch", "levels",
           "saturation", "noise_sharpen", "local_contrast", "star_reduction",
           "enhancements", "export"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_pipeline.py tests/ui/test_step_panels.py tests/ui/test_main_window.py -q -k "enhance or in_app_path"`
Expected: FAIL — no `ENHANCE_NAMES`/`enhancements` stage; panel has no `enhance` branch; nav sequence mismatch.

- [ ] **Step 3: Add the stage + names**

In `seestar_processor/ui/pipeline.py`, add to `_IN_APP_TAIL` before the `export` Stage:
```python
    Stage("star_reduction", "Star Reduction", "process"),
    Stage("enhancements", "Enhancements", "enhance"),
    Stage("export", "Export", "export"),
```
and add near `GEOMETRY_NAMES`:
```python
ENHANCE_NAMES = ("Boost Red", "Boost Cyan", "Boost Blue", "Darken Sky", "Lighten Sky")
```

- [ ] **Step 4: Add the enhance panel branch**

In `seestar_processor/ui/step_panels.py`, add `on_enhance=None` to `build_panel`'s signature, and add a branch (after the `process` branch):
```python
    elif stage.kind == "enhance":
        lay.addWidget(_desc_label(
            "Final targeted tweaks — tap to stack, Undo to peel back."))
        _specs = [
            ("boost_red_btn", "Boost Red (Ha)", "Boost Red"),
            ("boost_cyan_btn", "Boost Cyan (OIII)", "Boost Cyan"),
            ("boost_blue_btn", "Boost Blue", "Boost Blue"),
            ("darken_sky_btn", "Darken Sky", "Darken Sky"),
            ("lighten_sky_btn", "Lighten Sky", "Lighten Sky"),
        ]
        for attr, label, op in _specs:
            btn = QPushButton(label)
            if on_enhance is not None:
                btn.clicked.connect(lambda _=False, o=op: on_enhance(o))
            lay.addWidget(btn)
            setattr(w, attr, btn)
```

- [ ] **Step 5: Run the UI tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_pipeline.py tests/ui/test_step_panels.py tests/ui/test_main_window.py -q`
Expected: PASS (the nav test now includes `enhancements`; the panel builds with the buttons; nothing else asserting the tail should break — if a test hard-codes "export is the last stage", update it to reflect enhancements before export).

- [ ] **Step 6: Commit**

```bash
git add seestar_processor/ui/pipeline.py seestar_processor/ui/step_panels.py \
        tests/ui/test_pipeline.py tests/ui/test_step_panels.py tests/ui/test_main_window.py
git commit -m "feat: Enhancements stage + tap-to-stack button panel"
```

---

### Task 3: `_enhance` handler + wiring + done-mark

**Files:**
- Modify: `seestar_processor/ui/main_window.py` (`_ENHANCE_FN`, `_enhance`, `_rebuild_panel` wiring, `_done_ids`)
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `core.enhance` (Task 1), `ENHANCE_NAMES` (Task 2), the enhance panel `on_enhance` (Task 2).
- Produces: `MainWindow._enhance(op)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_main_window.py`:
```python
def test_enhance_appends_undoable_steps(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)                    # _async_enabled False
    win.open_fits(_make_fits(tmp_path))
    before = win.project.current().data.copy()
    win._enhance("Boost Red")
    assert win.project.entries()[-1][0] == "Boost Red"
    assert not np.allclose(win.project.current().data, before)   # image changed
    win._enhance("Darken Sky")                        # taps stack
    names = [n for n, _ in win.project.entries()]
    assert names[-2:] == ["Boost Red", "Darken Sky"]
    win.project.undo()                                # Undo peels one off
    assert win.project.entries()[-1][0] == "Boost Red"
    assert "enhancements" in win._done_ids()


def test_enhance_truncated_by_earlier_step(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._enhance("Boost Blue")
    win._go_to_id("saturation")
    win.apply_current(0.6)                             # earlier processing step
    names = [n for n, _ in win.project.entries()]
    assert "Boost Blue" not in names                  # trailing enhancement truncated
```

- [ ] **Step 2: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q -k "enhance_appends or enhance_truncated"`
Expected: FAIL — `MainWindow` has no `_enhance`.

- [ ] **Step 3: Add the enhance function map + handler**

In `seestar_processor/ui/main_window.py`, add the import and a module-level map (near the top, after imports):
```python
from ..core.enhance import boost_hue, darken_sky, lighten_sky

_ENHANCE_FN = {
    "Boost Red": lambda i: boost_hue(i, 0.0),
    "Boost Cyan": lambda i: boost_hue(i, 0.5),
    "Boost Blue": lambda i: boost_hue(i, 0.667),
    "Darken Sky": darken_sky,
    "Lighten Sky": lighten_sky,
}
```
Add the handler (near `_apply_geometry`):
```python
    def _enhance(self, op: str) -> None:
        if self.project is None or self._busy:
            return
        result = _ENHANCE_FN[op](self.project.current())
        self.project.run_step(_PrecomputedStep(op, result), "")
        self.log_panel.append_entry(format_log_entry(op, "", None))
        self._status.setText("")
        self._refresh()
```

- [ ] **Step 4: Wire the panel + done-mark**

In `_rebuild_panel`'s `build_panel(...)` call, add:
```python
            on_enhance=self._enhance,
```
Import `ENHANCE_NAMES` from `.pipeline` (add it to the existing pipeline import), and in `_done_ids`, after the existing marks:
```python
        if any(e in applied for e in ENHANCE_NAMES):
            done.add("enhancements")
```

- [ ] **Step 5: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass (rerun the known sharpen flake alone if it trips).

- [ ] **Step 7: Commit**

```bash
git add seestar_processor/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat: Enhancements tap-to-stack handler (append-only, undoable) + wiring"
```

---

## Self-Review

- **Spec coverage:** core ops with tuned defaults (T1), Enhancements stage + ENHANCE_NAMES + button panel (T2), append-only handler + wiring + done-mark (T3) — covered. Recipe capture / overall-boost are out of scope per the spec.
- **Placeholder scan:** none — complete code + validated numbers in every step.
- **Type consistency:** the five op-name strings, `ENHANCE_NAMES`, `_ENHANCE_FN` keys, `boost_hue`/`darken_sky`/`lighten_sky` signatures, and the panel button attrs are used identically across tasks and tests.
- **Green-at-boundary:** T1 additive (new module). T2 adds the stage + panel + updates the nav test together (panel builds with `on_enhance=None` default, buttons inert until T3 — no crash). T3 wires the handler. Enhancement ops are trailing/append-only, so no `PROCESSING_ORDER` interaction.
- **Real-data note:** defaults tuned on the user's NGC 7000 colourised crop (hue boost selective, additive sky moves visible on background, bright untouched).
