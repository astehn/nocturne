# Colourise Stars — Photoshop Way + User Control — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Colourise brings back the full star field by extracting stars from the display-stretched image (Photoshop/AstroWizard way) and screening them as-is, with a user "Star brightness" slider + live preview.

**Architecture:** `_colourise_starx` runs StarX twice — on the linear base (colour starless) and on a display-stretched copy (bright, complete stars). `compose` screens those already-bright stars as-is with a `star_brightness` factor. The colour engine is unchanged. Advanced… gains a Star-brightness slider.

**Tech Stack:** Python 3.13 (`.venv`), NumPy, PySide6, RC-Astro StarX (real), pytest-qt (`QT_QPA_PLATFORM=offscreen`).

## Global Constraints

- Use `.venv/bin/python` / `.venv/bin/pytest`; system python is 3.9 will fail. Qt tests: prefix `QT_QPA_PLATFORM=offscreen`; tests set `win._async_enabled = False`.
- Stars are extracted from the **display-stretched** image (`autostretch(base)`), NOT the linear one. Colour starless still comes from StarX on the linear base. Two StarX passes, cached together.
- `compose` screens the (already-stretched) stars **as-is** at `star_brightness == 1.0`; higher = brighter, lower = dimmer, via `stars ** (1.0 / star_brightness)`.
- New field: `PaletteParams.star_brightness: float = 1.0`. Remove `restore_stars` and its now-unused imports (`_TARGET_BG`, `_apply_params`, `_stretch_params`); keep `linked_stretch`.
- No RC-Astro → whole-image fallback (`stars is None` → `render_nebula`), unchanged.
- Commit co-author trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Known flake: `test_sharpen_changes_image_and_keeps_shape` — rerun alone if it trips.

---

### Task 1: `compose` screens pre-stretched stars as-is + `star_brightness`; remove `restore_stars`

**Files:**
- Modify: `seestar_processor/core/palette.py` (imports line 8; `PaletteParams`; `compose`; delete `restore_stars`)
- Test: `tests/core/test_palette.py`

**Interfaces:**
- Produces: `PaletteParams(..., star_brightness=1.0)`; `compose(starless, stars, params)` screens `stars` as-is (with the `star_brightness` gamma). `restore_stars` no longer exists.

- [ ] **Step 1: Update the failing tests**

In `tests/core/test_palette.py`:

(a) **Delete** the `restore_stars` tests and their helper: `_ref_and_star`,
`test_restore_stars_keeps_colour_and_brightens_to_source`,
`test_restore_stars_stays_point_source_not_degenerate_blob`, `test_restore_stars_mono_passthrough`.

(b) **Replace** `test_palette_params_no_star_or_denoise_fields` with:
```python
def test_palette_params_star_brightness_default():
    from seestar_processor.core.palette import PaletteParams
    p = PaletteParams()
    assert p.star_brightness == 1.0
    assert not hasattr(p, "denoise")
```

(c) **Replace** `test_compose_screens_stars_back` with (stars are now pre-stretched; compose screens as-is):
```python
def test_compose_screens_pre_stretched_stars_as_is():
    from seestar_processor.core.palette import compose, render_nebula, PaletteParams
    starless = _bicolour_starless()
    stars = AstroImage(np.zeros((20, 20, 3), np.float32), is_linear=False)
    stars.data[5, 5] = 0.9                         # an already-bright star (from StarX-on-stretched)
    neb = render_nebula(starless, PaletteParams()).data
    out = compose(starless, stars, PaletteParams()).data
    assert out[5, 5].mean() > neb[5, 5].mean()     # star brightened the pixel (screened)
    assert out[5, 5].max() > 0.8                    # bright star stays bright (screened as-is)
    assert compose(starless, stars, PaletteParams()).is_linear is False


def test_compose_star_brightness_controls_stars():
    from seestar_processor.core.palette import compose, PaletteParams
    starless = _bicolour_starless()
    stars = AstroImage(np.zeros((20, 20, 3), np.float32), is_linear=False)
    stars.data[5, 5] = 0.3                          # a mid-brightness star
    dim = compose(starless, stars, PaletteParams(star_brightness=0.5)).data[5, 5].mean()
    asis = compose(starless, stars, PaletteParams(star_brightness=1.0)).data[5, 5].mean()
    bright = compose(starless, stars, PaletteParams(star_brightness=2.0)).data[5, 5].mean()
    assert dim < asis < bright                      # higher star_brightness = brighter star
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/core/test_palette.py -q -k "star_brightness or pre_stretched"`
Expected: FAIL — `PaletteParams` has no `star_brightness`; `compose` still calls `restore_stars`.

- [ ] **Step 3: Update imports + `PaletteParams`**

In `seestar_processor/core/palette.py`, change the autostretch import (line 8) to drop the now-unused names:
```python
from .autostretch import linked_stretch
```
Add the field to `PaletteParams` (after `scnr`):
```python
    star_brightness: float = 1.0   # screened stars as-is at 1.0; >1 brighter, <1 dimmer
```

- [ ] **Step 4: Delete `restore_stars`, rewrite `compose`**

Delete the entire `restore_stars` function. Replace `compose` with:
```python
def compose(starless: AstroImage, stars: AstroImage, params: PaletteParams) -> AstroImage:
    """render_nebula(starless), then screen the (already display-stretched) stars
    on top. `stars` come from StarX on the stretched image, so they are screened
    as-is; `params.star_brightness` optionally pushes them brighter/dimmer."""
    nebula = render_nebula(starless, params)
    s = np.clip(stars.data, 0.0, 1.0)
    if params.star_brightness != 1.0:
        s = np.power(s, 1.0 / params.star_brightness)   # gamma: higher param = brighter
    out = screen(nebula.data, s.astype(np.float32))
    return AstroImage(out, is_linear=False, metadata=dict(starless.metadata))
```

- [ ] **Step 5: Run the palette tests**

Run: `.venv/bin/pytest tests/core/test_palette.py -q`
Expected: PASS (new tests + existing; no `restore_stars` references remain).

- [ ] **Step 6: Commit**

```bash
git add seestar_processor/core/palette.py tests/core/test_palette.py
git commit -m "feat: compose screens pre-stretched stars as-is + star_brightness; drop restore_stars"
```

---

### Task 2: `_colourise_starx` extracts stars from the stretched image (two StarX passes)

**Files:**
- Modify: `seestar_processor/ui/main_window.py` (`_colourise_starx`; add `autostretch` import)
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `autostretch` (`core/autostretch`), the injectable `self._remove_stars(img)`.
- Produces: `_colourise_starx(base)` returns `(linear_starless, stretched_stars)` (or `(base, None)` without RC-Astro).

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_main_window.py`:
```python
def test_colourise_starx_extracts_stars_from_stretched(qtbot, tmp_path, monkeypatch):
    import seestar_processor.ui.main_window as mw
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    monkeypatch.setattr(mw, "rcastro_valid", lambda s: True)
    seen_linear = []
    def fake_remove(img):
        seen_linear.append(img.is_linear)
        half = AstroImage(img.data * 0.5, is_linear=img.is_linear)
        return half, half
    win._remove_stars = fake_remove
    base = win.project.current()
    starless, stars = win._colourise_starx(base)
    # StarX was run on BOTH a linear image (for the starless) and a stretched one (for stars)
    assert True in seen_linear and False in seen_linear
    assert stars is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q -k "starx_extracts_stars_from_stretched"`
Expected: FAIL — current `_colourise_starx` runs StarX once (only a linear image; `False` never appears).

- [ ] **Step 3: Add the import**

In `seestar_processor/ui/main_window.py`, add near the other `..core` imports:
```python
from ..core.autostretch import autostretch
```

- [ ] **Step 4: Rewrite `_colourise_starx` (two passes)**

Replace the method body:
```python
    def _colourise_starx(self, base):
        sig = self._base_sig(base)
        if self._colourise_layers is not None and self._colourise_layers[0] == sig:
            return self._colourise_layers[1], self._colourise_layers[2]
        if rcastro_valid(self.settings):
            starless, _ = self._remove_stars(base)                        # linear -> colour starless
            stretched = AstroImage(autostretch(base), is_linear=False)    # display stretch
            _, stars = self._remove_stars(stretched)                      # bright, complete stars
        else:
            starless, stars = base, None
        self._colourise_layers = (sig, starless, stars)
        return starless, stars
```

- [ ] **Step 5: Run the main-window tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q`
Expected: PASS (new test + existing colourise/cache/fallback tests; the whole-image fallback path is unchanged).

- [ ] **Step 6: Commit**

```bash
git add seestar_processor/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat: Colourise extracts stars from the stretched image (StarX two-pass)"
```

---

### Task 3: "Star brightness" slider + live preview in the Advanced dialog

**Files:**
- Modify: `seestar_processor/ui/palette_dialog.py` (add `star_slider`, wire preview, `_params`, `reset`)
- Test: `tests/ui/test_palette_dialog.py`

**Interfaces:**
- Consumes: `PaletteParams.star_brightness` (Task 1).
- Produces: dialog attr `star_slider`; `_params().star_brightness` reflects it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_palette_dialog.py`:
```python
def test_star_brightness_slider_present_and_in_params(qtbot):
    from seestar_processor.ui.reset_slider import ResetSlider
    dlg = _make_dialog(qtbot)
    assert isinstance(dlg.star_slider, ResetSlider) and dlg.star_slider._default == 50
    assert dlg._params().star_brightness == pytest.approx(1.0)   # default 50 -> 1.0
    dlg.star_slider.setValue(100)
    assert dlg._params().star_brightness > 1.0                    # right = brighter


def test_star_slider_change_rerenders(qtbot):
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    before = dlg.preview.pixmap().cacheKey()
    dlg.star_slider.setValue(90)
    assert dlg.preview.pixmap().cacheKey() != before
```
(Add `import pytest` at the top of the file if absent.)

- [ ] **Step 2: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_palette_dialog.py -q -k "star_brightness or star_slider"`
Expected: FAIL — no `star_slider`.

- [ ] **Step 3: Add the slider, wire preview, params, reset**

In `seestar_processor/ui/palette_dialog.py`:

Create the slider next to the others (after `self.sat_slider = ResetSlider(65)`):
```python
        self.star_slider = ResetSlider(50)          # 50 -> star_brightness 1.0 (as-is)
```
Add it to the preview-refresh loop (the `for s in (...)` list) and the form layout (after Saturation):
```python
        for s in (self.ha_slider, self.oiii_slider, self.hue_slider,
                  self.sat_slider, self.star_slider):
            s.valueChanged.connect(lambda _v: self._render_preview())
```
```python
        controls.addRow("Saturation", self.sat_slider)
        controls.addRow("Star brightness", self.star_slider)
```
In `reset`, add:
```python
        self.star_slider.setValue(50)
```
In `_params`, add the field to the returned `PaletteParams(...)`:
```python
            scnr=self.scnr_check.isChecked(),
            star_brightness=max(0.4, self.star_slider.value() / 50.0),
```

- [ ] **Step 4: Run the dialog tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_palette_dialog.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass (rerun the known sharpen flake alone if it trips).

- [ ] **Step 6: Commit**

```bash
git add seestar_processor/ui/palette_dialog.py tests/ui/test_palette_dialog.py
git commit -m "feat: Star brightness slider with live preview in the Colourise Advanced dialog"
```

---

## Self-Review

- **Spec coverage:** stars-from-stretched (T2), screen-as-is + star_brightness (T1), Advanced slider + preview (T3), colour engine untouched (nothing touches `render_nebula`), whole-image fallback preserved (T2) — covered. Recipe capture + single-pass optimisation are out of scope per the spec.
- **Placeholder scan:** none — complete code in every step.
- **Type consistency:** `star_brightness` (float, default 1.0), `_colourise_starx` returning `(starless, stars)`, `star_slider`/`_params().star_brightness`, and the `1.0/star_brightness` gamma are used identically across tasks and tests.
- **Green-at-boundary:** T1 (core) keeps compose's signature; between T1 and T2 the app screens linear stars as-is (dim, not shipped) but tests are green. T2 makes stars bright. T3 adds the slider (default 1.0 = no behaviour change to one-press).
- **Real-data note:** the composite result was validated on the user's NGC 7000 file with real StarX before this plan (full star field recovered); re-verify by eye after merge.
