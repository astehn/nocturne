# Saturation Remap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-centre the Saturation slider so the middle is native, left desaturates to grey, and right boosts harder (with star protection kept on the boost side).

**Architecture:** Rewrite `core/saturation.saturate` to map `amount` (0..1) to a chroma multiplier (0=grey, 0.5=native, 1=strong, boost tapered toward highlights); update the saturation panel (default 50, relabel, centre tick); update/extend the tests.

**Tech Stack:** numpy, PySide6, Python 3.11+.

## Global Constraints

- Package `seestar_processor` (no rename). Venv `.venv`; UI tests headless (`QT_QPA_PLATFORM=offscreen`).
- Slider semantics: `amount` 0..1 with **0.5 = native (no-op)**, 0 = greyscale, 1 = strong (`S_MAX = 2.5`). Boost side (`amount > 0.5`) tapers the extra by `(1 - lum)`; desaturate side (`amount <= 0.5`) is uniform. Mono returned unchanged.
- Panel: saturation slider default **50**; label `"Saturation (mute ← native → boost)"`; description `"Drag left to mute colour, right to boost. Centre = no change."`; centre tick.
- Known accepted behaviour change: old recipes' saturation values are reinterpreted (0.5=native now) — no migration.
- Commit after each task. Create the `saturation-remap` branch first (do not start on `main`).

---

## File Structure

- `seestar_processor/core/saturation.py` — rewrite `saturate`.
- `seestar_processor/ui/step_panels.py` — saturation branch: default 50, label/desc, centre tick.
- `tests/core/test_saturation.py` — replace the `0=noop` test; add greyscale / partial-desat / monotonic tests.
- `tests/ui/test_step_panels.py` — add a saturation-default assertion (if not present).

---

## Task 0: Branch setup

- [ ] **Step 1: Create the feature branch**

```bash
cd /Volumes/Work/Code/Editor
git checkout -b saturation-remap
git status   # expect: On branch saturation-remap, clean
```

---

## Task 1: Remap `saturate` + panel + tests

**Files:**
- Modify: `seestar_processor/core/saturation.py`
- Modify: `seestar_processor/ui/step_panels.py`
- Modify: `tests/core/test_saturation.py`, `tests/ui/test_step_panels.py`

**Interfaces:**
- Produces: `saturate(img: AstroImage, amount: float) -> AstroImage` with the re-centred semantics; saturation panel slider default 50.

- [ ] **Step 1: Update the core tests (write the new semantics first)**

In `tests/core/test_saturation.py`:

Replace `test_zero_amount_is_noop` with a native no-op at 0.5 and a greyscale at 0.0:

```python
def test_half_amount_is_noop():
    data = np.random.rand(8, 8, 3).astype(np.float32)
    out = saturate(AstroImage(data), 0.5)
    assert np.allclose(out.data, data, atol=1e-6)


def test_zero_amount_is_greyscale():
    data = np.tile(np.array([0.6, 0.4, 0.2], np.float32), (8, 8, 1))
    out = saturate(AstroImage(data), 0.0).data[0, 0]
    assert out.max() - out.min() < 1e-6           # R=G=B -> grey
```

Add these tests:

```python
def test_partial_desaturation():
    data = np.tile(np.array([0.6, 0.4, 0.2], np.float32), (8, 8, 1))
    native = 0.6 - 0.2
    out = saturate(AstroImage(data), 0.25).data[0, 0]
    chroma = out.max() - out.min()
    assert 0.0 < chroma < native                  # muted but not grey


def test_monotonic_chroma_across_slider():
    data = np.tile(np.array([0.5, 0.35, 0.2], np.float32), (4, 4, 1))  # dark coloured pixel
    def chroma(a):
        px = saturate(AstroImage(data), a).data[0, 0]
        return float(px.max() - px.min())
    vals = [chroma(a) for a in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert vals == sorted(vals) and vals[0] < vals[-1]
```

(Leave `test_saturation_increases_chroma`, `test_mono_noop`, `test_preserves_is_linear_and_range`,
`test_highlights_protected_vs_midtones` — they hold under the new math. Note
`test_preserves_is_linear_and_range` uses `amount=0.5` which is now the native no-op; still
valid.)

- [ ] **Step 2: Run core tests, expect failure**

Run: `.venv/bin/pytest tests/core/test_saturation.py -q`
Expected: FAIL (`test_half_amount_is_noop`/`test_zero_amount_is_greyscale` fail against the old
additive `saturate`).

- [ ] **Step 3: Implement `core/saturation.py`**

Replace the `saturate` function body with:

```python
def saturate(img: AstroImage, amount: float) -> AstroImage:
    """Re-centred saturation: amount 0=greyscale, 0.5=native, 1=strong boost.
    The boost above native tapers toward highlights so bright stars keep natural
    colour; desaturation is uniform. Mono is returned unchanged."""
    if not img.is_color:
        return img.copy()
    S_MAX = 2.5
    t = float(amount)
    data = img.data
    lum = data.mean(axis=2, keepdims=True)
    if t <= 0.5:
        s_px = 2.0 * t                          # 0 -> grey, 0.5 -> native (uniform)
    else:
        s = 1.0 + (2.0 * t - 1.0) * (S_MAX - 1.0)
        s_px = 1.0 + (s - 1.0) * (1.0 - lum)    # taper boost toward highlights
    out = np.clip(lum + (data - lum) * s_px, 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear,
                      metadata=dict(img.metadata))
```

- [ ] **Step 4: Run core tests, expect pass**

Run: `.venv/bin/pytest tests/core/test_saturation.py -q`
Expected: PASS (all — new + retained).

- [ ] **Step 5: Update the panel test**

In `tests/ui/test_step_panels.py`, find the saturation panel test (it builds
`build_panel(_stage("saturation"), ...)`). Add an assertion that the default is 50 — either add
to the existing test or add a new one:

```python
def test_saturation_panel_default_is_native(qtbot):
    w = build_panel(_stage("saturation"))
    qtbot.addWidget(w)
    assert w.sat_slider.value() == 50
```

- [ ] **Step 6: Run panel test, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_step_panels.py::test_saturation_panel_default_is_native -q`
Expected: FAIL (default is still 40).

- [ ] **Step 7: Implement the panel change**

In `seestar_processor/ui/step_panels.py`, in the `elif stage.kind == "saturation":` branch,
replace the description + slider setup so it reads:

```python
    elif stage.kind == "saturation":
        lay.addWidget(_desc_label(
            "Drag left to mute colour, right to boost. Centre = no change."))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(50)
        slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider.setTickInterval(50)
        apply_btn = QPushButton("Apply Saturation")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(slider.value() / 100.0))
        lay.addWidget(QLabel("Saturation (mute ← native → boost)"))
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.sat_slider = slider
        w.apply_btn = apply_btn
```

- [ ] **Step 8: Run panel + full suite, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_step_panels.py tests/core/test_saturation.py -q`
then `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass. If `test_sharpen_changes_image_and_keeps_shape` fails, it's the known
pre-existing flake — rerun it alone to confirm.

- [ ] **Step 9: Commit**

```bash
git add seestar_processor/core/saturation.py seestar_processor/ui/step_panels.py tests/core/test_saturation.py tests/ui/test_step_panels.py
git commit -m "feat: re-centred saturation slider (mute / native / boost)"
```

---

## Task 2: Backlog

- [ ] **Step 1: Mark the tweak done**

In `TODO.md`, change the **Saturation remap** bullet from `- [ ]` to `- [x]` and append:
`Shipped: centre-neutral slider (0=grey, 50=native, 100=strong, boost tapered toward highlights); default 50.`

- [ ] **Step 2: Commit**

```bash
git add TODO.md
git commit -m "docs: mark saturation remap done in backlog"
```

---

## Definition of Done

- Committed on `saturation-remap`; full suite green.
- Saturation slider starts centred (native); left mutes toward grey, right boosts (stronger than
  before) with stars protected. `S_MAX` is a one-line tunable in `saturate`.
- After merge: eyeball on a real colour image; adjust `S_MAX` if the top feels weak/garish.
- Finish with **superpowers:finishing-a-development-branch**.
