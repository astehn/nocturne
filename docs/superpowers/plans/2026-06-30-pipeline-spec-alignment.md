# PIPELINE_SPEC Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Refactor the app's flow to match `PIPELINE_SPEC.md`: Import&assess → Destination branch → (linear core: Crop-autodetect → Background → Color-auto → Stretch) → external[export TIFF/split] OR in-app[Saturation → Noise+Sharpen → Export]. Reuse the existing engine (GraXpert/RC-Astro adapters, stretch, history, export); reshape steps + UI to one-control-per-step.

**Architecture:** Keep `core/` math, `history/`, `tools/` adapters. Replace the fixed linear stepper with a **destination-aware** pipeline. Remove the pre-stretch Deconvolution and Noise stages and the in-app Stars editing stage; star separation becomes an export option on the external path. Add metadata parsing, auto-crop border detection, a saturation slider step, a combined post-stretch noise+sharpen step, and PNG/FITS export.

**Tech Stack:** Python 3.13 (`.venv`), PySide6, astropy, numpy, scikit-image, tifffile, Pillow, pytest+pytest-qt.

## Global Constraints

- `PIPELINE_SPEC.md` is the source of truth. Order (linear, non-negotiable): crop, background, color BEFORE stretch; saturation, noise, sharpening AFTER stretch.
- **At most one user control per step** (one slider or one 3-way preset). Never surface raw algorithm parameters.
- Linear 32-bit float is the source of truth; autostretch is display-only until Stretch (sets `is_linear=False`).
- Destination chosen at Step 2: `external` (run core, export 16-bit TIFF, stop) | `in_app` (full pipeline).
- Preset wording: Background = **off / light / strong**; Stretch = **gentle / balanced / punchy**; Noise+Sharpen = **light / medium / strong**.
- Star/starless separation exists ONLY as an external-export option ("Single 16-bit TIFF" | "Two 16-bit TIFFs: starless + stars-only"), gated on RC-Astro. Not an in-app editing step.
- Reuse engine modules; do NOT modify `history/`, `tools/base.py`, `tools/graxpert.py`, `tools/rcastro.py`, `core/stretch.py`, `core/color.py`, `core/autostretch.py`, `core/image.py`, `core/instrument.py` except where a task says so.
- Run tests with `.venv/bin/pytest`; Python `.venv/bin/python` (3.13). pytest-qt works headless.

---

### Task 1: FITS metadata parsing

**Files:**
- Modify: `seestar_processor/core/fits_io.py`
- Test: `tests/core/test_fits_io.py` (add cases)

**Interfaces:**
- Produces: `load_fits` populates `AstroImage.metadata` with available keys from the FITS header: `exposure` (EXPTIME), `gain` (GAIN), `target` (OBJECT), `frames` (STACKCNT or NFRAMES or NCOMBINE), `width`, `height`, `bitpix` (BITPIX). Missing keys are omitted. Add `format_metadata(meta: dict) -> str` returning a short human-readable summary.

- [ ] **Step 1: Write the failing test**

```python
def test_metadata_parsed_from_header(tmp_path):
    from seestar_processor.core.fits_io import format_metadata
    arr = np.random.randint(0, 4096, size=(3, 16, 16)).astype(np.uint16)
    hdu = fits.PrimaryHDU(arr)
    hdu.header["EXPTIME"] = 30.0
    hdu.header["OBJECT"] = "M31"
    hdu.header["STACKCNT"] = 120
    p = tmp_path / "m.fits"
    hdu.writeto(str(p), overwrite=True)
    img = load_fits(str(p))
    assert img.metadata["exposure"] == 30.0
    assert img.metadata["target"] == "M31"
    assert img.metadata["frames"] == 120
    assert img.metadata["width"] == 16 and img.metadata["height"] == 16
    summary = format_metadata(img.metadata)
    assert "M31" in summary and "30" in summary
```

- [ ] **Step 2: Run test → FAIL** (`format_metadata` undefined / metadata empty).

- [ ] **Step 3: Implement** — in `fits_io.py`, after opening the header, build a metadata dict and pass it into the returned `AstroImage`(s). Add:

```python
def _parse_metadata(header, height: int, width: int) -> dict:
    meta: dict = {"width": width, "height": height}
    mapping = {
        "exposure": ("EXPTIME",), "gain": ("GAIN",), "target": ("OBJECT",),
        "frames": ("STACKCNT", "NFRAMES", "NCOMBINE"), "bitpix": ("BITPIX",),
    }
    for key, candidates in mapping.items():
        for card in candidates:
            if card in header:
                meta[key] = header[card]
                break
    return meta


def format_metadata(meta: dict) -> str:
    parts = []
    if meta.get("target"):
        parts.append(str(meta["target"]))
    if meta.get("exposure") is not None:
        parts.append(f"{meta['exposure']:g}s")
    if meta.get("frames") is not None:
        parts.append(f"{meta['frames']} frames")
    if meta.get("width") and meta.get("height"):
        parts.append(f"{meta['width']}x{meta['height']}")
    return "  •  ".join(parts) if parts else "No metadata"
```
Read `header = hdul[0].header` in `load_fits`, compute height/width from the final `(H,W,..)` shape, and pass `metadata=_parse_metadata(header, h, w)` into each `AstroImage(...)` return.

- [ ] **Step 4: Run test → PASS.** Also re-run existing `tests/core/test_fits_io.py`.
- [ ] **Step 5: Commit** `feat: parse FITS metadata on load`.

---

### Task 2: Auto-crop border detection

**Files:**
- Modify: `seestar_processor/core/crop.py`
- Test: `tests/core/test_crop_autodetect.py`

**Interfaces:**
- Produces: `detect_content_bounds(img: AstroImage, threshold: float = 0.002) -> tuple[int,int,int,int]` returning `(top, bottom, left, right)` row/col bounds of the non-black content (the largest axis-aligned box whose edge rows/cols exceed `threshold` mean). `auto_crop(img: AstroImage, margin: float = 0.0) -> AstroImage` crops to detected bounds, then trims an extra `margin` fraction off each side. Keep existing `CropSettings`/`apply_crop` (still used? No — superseded; leave for now, unused).

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.crop import detect_content_bounds, auto_crop


def _bordered():
    data = np.zeros((40, 50, 3), dtype=np.float32)
    data[5:35, 8:45] = 0.4  # content rectangle inside a black border
    return AstroImage(data)


def test_detect_bounds_finds_content_rect():
    t, b, l, r = detect_content_bounds(_bordered())
    assert (t, b, l, r) == (5, 35, 8, 45)


def test_auto_crop_removes_border():
    out = auto_crop(_bordered())
    assert out.data.shape == (30, 37, 3)
    assert out.data.min() > 0.0  # border gone


def test_auto_crop_extra_margin():
    out = auto_crop(_bordered(), margin=0.10)  # 10% off each side of the 30x37 box
    assert out.data.shape[0] < 30 and out.data.shape[1] < 37


def test_auto_crop_preserves_is_linear():
    img = AstroImage(_bordered().data, is_linear=True)
    assert auto_crop(img).is_linear is True
```

- [ ] **Step 2: Run test → FAIL.**

- [ ] **Step 3: Implement** in `crop.py`:

```python
def detect_content_bounds(img: AstroImage, threshold: float = 0.002) -> tuple[int, int, int, int]:
    data = img.data
    gray = data.mean(axis=2) if data.ndim == 3 else data
    rows = np.where(gray.mean(axis=1) > threshold)[0]
    cols = np.where(gray.mean(axis=0) > threshold)[0]
    if rows.size == 0 or cols.size == 0:
        return 0, gray.shape[0], 0, gray.shape[1]
    return int(rows[0]), int(rows[-1] + 1), int(cols[0]), int(cols[-1] + 1)


def auto_crop(img: AstroImage, margin: float = 0.0) -> AstroImage:
    t, b, l, r = detect_content_bounds(img)
    data = img.data[t:b, l:r]
    if margin > 0:
        h, w = data.shape[:2]
        dh, dw = int(h * margin), int(w * margin)
        data = data[dh:h - dh, dw:w - dw]
    return AstroImage(
        np.ascontiguousarray(data.astype(np.float32)),
        is_linear=img.is_linear, metadata=dict(img.metadata),
    )
```

- [ ] **Step 4: Run test → PASS.**
- [ ] **Step 5: Commit** `feat: add auto-crop border detection`.

---

### Task 3: PNG and FITS export

**Files:**
- Modify: `seestar_processor/core/export.py`
- Test: `tests/core/test_export.py` (add cases)

**Interfaces:**
- Produces: `save_png(img: AstroImage, path: str) -> None` (8-bit), `save_fits(img: AstroImage, path: str) -> None` (32-bit float; color saved as `(3,H,W)` like `tools/base.write_temp_fits`). Existing `save_tiff`/`save_jpeg` unchanged.

- [ ] **Step 1: Write the failing test**

```python
def test_save_png(tmp_path):
    from seestar_processor.core.export import save_png
    img = AstroImage(np.full((4, 4, 3), 0.5, dtype=np.float32))
    out = tmp_path / "o.png"
    save_png(img, str(out))
    with Image.open(out) as im:
        assert im.size == (4, 4) and im.format == "PNG"


def test_save_fits_roundtrips_float(tmp_path):
    from astropy.io import fits as _fits
    from seestar_processor.core.export import save_fits
    img = AstroImage(np.linspace(0, 1, 48, dtype=np.float32).reshape(4, 4, 3))
    out = tmp_path / "o.fits"
    save_fits(img, str(out))
    with _fits.open(out) as h:
        assert h[0].data.shape == (3, 4, 4)  # channels-first
        assert h[0].data.dtype == np.float32
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement:**

```python
from astropy.io import fits


def save_png(img: AstroImage, path: str) -> None:
    arr = _to_uint(img.data, 8)
    mode = "L" if arr.ndim == 2 else "RGB"
    Image.fromarray(arr, mode=mode).save(path, format="PNG")


def save_fits(img: AstroImage, path: str) -> None:
    data = img.data.astype(np.float32)
    if data.ndim == 3:
        data = np.transpose(data, (2, 0, 1))
    fits.PrimaryHDU(data).writeto(path, overwrite=True)
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: add PNG and FITS export`.

---

### Task 4: Saturation (post-stretch, slider)

**Files:**
- Create: `seestar_processor/core/saturation.py`
- Test: `tests/core/test_saturation.py`

**Interfaces:**
- Produces: `saturate(img: AstroImage, amount: float) -> AstroImage`. `amount` in [0,1] maps to a chroma factor 1.0..2.0 (`1 + amount`). Mono is a no-op. Output float32 clipped.

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.saturation import saturate


def test_saturation_increases_chroma():
    data = np.tile(np.array([0.6, 0.4, 0.2], np.float32), (8, 8, 1))
    out = saturate(AstroImage(data), 1.0)
    assert (out.data[0, 0].max() - out.data[0, 0].min()) > (0.6 - 0.2)


def test_zero_amount_is_noop():
    data = np.random.rand(8, 8, 3).astype(np.float32)
    out = saturate(AstroImage(data), 0.0)
    assert np.allclose(out.data, data)


def test_mono_noop():
    img = AstroImage(np.full((8, 8), 0.5, np.float32))
    assert np.allclose(saturate(img, 1.0).data, img.data)
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement:**

```python
from __future__ import annotations
import numpy as np
from .image import AstroImage


def saturate(img: AstroImage, amount: float) -> AstroImage:
    if not img.is_color or amount <= 0:
        return img.copy()
    factor = 1.0 + float(amount)
    data = img.data
    lum = data.mean(axis=2, keepdims=True)
    out = np.clip(lum + (data - lum) * factor, 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear, metadata=dict(img.metadata))
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: add saturation adjustment`.

---

### Task 5: Pipeline model (destination-aware)

**Files:**
- Rewrite: `seestar_processor/ui/pipeline.py`
- Test: `tests/ui/test_pipeline.py` (rewrite)

**Interfaces:**
- Produces: `Stage(id, label, kind, enabled)`; `core_stages()` and `path_stages(destination: str) -> list[Stage]` returning the ordered visible stages for the destination. Stage ids/kinds:
  - shared: `load`(import), `destination`(branch), `crop`(crop), `background`(process), `color`(auto), `stretch`(stretch)
  - external tail: `export_external`(export_external)
  - in-app tail: `saturation`(saturation), `noise_sharpen`(process), `export`(export)
  - `STEP_NAME` maps processing-history stage ids → names: `{"crop":"Crop","background":"Background","color":"Color","stretch":"Stretch","saturation":"Saturation","noise_sharpen":"Noise & Sharpen"}`.
  - `PROCESSING_ORDER = ["crop","background","color","stretch","saturation","noise_sharpen"]`.
  - `next_enabled(stages, index)` / `prev_enabled(stages, index)` operate on a given stage list.

- [ ] **Step 1: Write the failing test**

```python
from seestar_processor.ui.pipeline import path_stages, core_stages


def test_external_path_stops_after_stretch_with_export():
    ids = [s.id for s in path_stages("external")]
    assert ids == ["load", "destination", "crop", "background", "color", "stretch", "export_external"]


def test_in_app_path_has_cosmetic_then_export():
    ids = [s.id for s in path_stages("in_app")]
    assert ids == ["load", "destination", "crop", "background", "color", "stretch",
                   "saturation", "noise_sharpen", "export"]


def test_core_stages_shared_prefix():
    assert [s.id for s in core_stages()] == ["load", "destination", "crop", "background", "color", "stretch"]
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** `pipeline.py` with the `Stage` dataclass, the core list, two tail lists, `path_stages(dest)` concatenating core + tail, `core_stages()`, `STEP_NAME`, `PROCESSING_ORDER`, and `next_enabled(stages,i)`/`prev_enabled(stages,i)` that skip `enabled=False` within the passed list. (All stages enabled; `enabled` retained for future use.)
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: destination-aware pipeline model`.

---

### Task 6: Steps for the new flow

**Files:**
- Create: `seestar_processor/steps/crop_auto.py` (`CropAutoStep`: `apply(img, margin_float)` → `auto_crop`)
- Create: `seestar_processor/steps/saturation_step.py` (`SaturationStep`: `apply(img, amount_float)` → `saturate`)
- Create: `seestar_processor/steps/noise_sharpen.py` (`NoiseSharpenStep(rcastro)`: post-stretch; `apply(img, "light|medium|strong")` → denoise then sharpen; RC-Astro NoiseX+BlurX if present else `reduce_noise`+`sharpen`)
- Modify: `seestar_processor/steps/background.py` (accept `"off"` → return image unchanged)
- Test: `tests/steps/test_new_steps.py`
- Reuse: `ColorStep` (auto: `apply(img, ColorSettings())`), `StretchStep` (presets relabelled in panel, values unchanged).

**Interfaces:**
- `NoiseSharpenStep` strength map: `{"light":(0.4,0.3),"medium":(0.7,0.5),"strong":(0.9,0.7)}` = (denoise, sharpen). Injectable `_runner`.
- `BackgroundStep` options become `["off","light","strong"]`; `_STRENGTH = {"light":0.3,"strong":0.7}`; `"off"` returns `img` unchanged (no CLI call).

- [ ] **Step 1: Write the failing tests** (one per step) — e.g.:

```python
def test_background_off_is_noop():
    from seestar_processor.steps.background import BackgroundStep
    from seestar_processor.tools.graxpert import GraXpert
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    out = BackgroundStep(GraXpert("/fake")).apply(img, "off")
    assert np.allclose(out.data, img.data)


def test_noise_sharpen_fallback_changes_image():
    from seestar_processor.steps.noise_sharpen import NoiseSharpenStep
    rng = np.random.default_rng(0)
    img = AstroImage(np.clip(0.5 + rng.normal(0, 0.1, (24, 24, 3)), 0, 1).astype(np.float32))
    out = NoiseSharpenStep(rcastro=None).apply(img, "medium")
    assert out.data.shape == img.data.shape
    assert not np.allclose(out.data, img.data)


def test_crop_auto_step_removes_border():
    from seestar_processor.steps.crop_auto import CropAutoStep
    data = np.zeros((40, 50, 3), np.float32); data[5:35, 8:45] = 0.4
    out = CropAutoStep().apply(AstroImage(data), 0.0)
    assert out.data.shape == (30, 37, 3)


def test_saturation_step():
    from seestar_processor.steps.saturation_step import SaturationStep
    data = np.tile(np.array([0.6, 0.4, 0.2], np.float32), (8, 8, 1))
    out = SaturationStep().apply(AstroImage(data), 1.0)
    assert out.data[0, 0].max() - out.data[0, 0].min() > 0.4
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** the four step modules + modify `BackgroundStep`. `NoiseSharpenStep.apply`: if `_rc`: `img = self._rc.denoise(img, dn, runner=self._runner); return self._rc.deconvolve(img, sharpen_stars=0.0, sharpen_nonstellar=sh, runner=self._runner)`; else `return sharpen(reduce_noise(img, dn), sh)`.
- [ ] **Step 4: Run → PASS** (+ existing step tests; `BackgroundStep` options changed — update `tests/steps/test_steps.py` mapping `Medium`→`light`/`strong`).
- [ ] **Step 5: Commit** `feat: add crop-auto, saturation, noise+sharpen steps; background off option`.

---

### Task 7: Step panels for the new flow

**Files:**
- Rewrite: `seestar_processor/ui/step_panels.py`
- Test: `tests/ui/test_step_panels.py` (rewrite)

**Interfaces:**
- `build_panel(stage, *, on_open, on_destination, on_apply, on_export_external, on_export, apply_enabled=True)`.
- Panel kinds and controls (one each):
  - `import`: shows `on_open` button + a metadata `QLabel` (text set later via `panel.meta_label`).
  - `destination`: two radio buttons "Continue in external software" / "Finish here" → `on_destination("external"|"in_app")`; exposes `panel.external_radio`.
  - `crop`: a margin `QSlider` (0–20%) + Apply → `on_apply(margin_float)`; exposes `panel.margin_slider`, `panel.apply_btn`.
  - `process` (background, noise_sharpen): a 3-way `QComboBox` from `stage`-specific options + Apply → `on_apply(option_str)`. Background options off/light/strong; noise_sharpen light/medium/strong. Store `panel.option_box`.
  - `auto` (color): a label "Automatic — no settings" + Apply → `on_apply(None)`; `panel.apply_btn`.
  - `stretch`: 3-way gentle/balanced/punchy + Apply → `on_apply(label)`; map labels to `STRETCH_PRESETS` in the step call (see Task 8).
  - `saturation`: a `QSlider` (0–100 → 0..1) + Apply → `on_apply(amount_float)`; `panel.sat_slider`.
  - `export_external`: a `QComboBox` ["Single 16-bit TIFF","Two TIFFs: starless + stars"] + Export → `on_export_external(choice_str)`; second option disabled unless `apply_enabled` (RC-Astro). `panel.fmt_box`.
  - `export`: a `QComboBox` ["TIFF (16-bit)","PNG","FITS"] + Export → `on_export(fmt)`.
- Each panel sets `panel.panel_kind`.

- [ ] **Step 1: Write failing tests** for each kind (emit assertions like prior panel tests). 
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** the panel builder with the kinds above.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: step panels for spec-aligned flow`.

---

### Task 8: MainWindow refactor (destination branch, dynamic stepper, metadata, exports)

**Files:**
- Rewrite: `seestar_processor/ui/main_window.py`
- Test: `tests/ui/test_main_window.py` (rewrite)

**Interfaces / behavior:**
- `MainWindow(settings_path)`; `self.destination = "in_app"` default. `self._stages = path_stages(self.destination)`; `self._stage` indexes `self._stages`.
- `open_fits(path)`: load, build `Project`, set the import panel's `meta_label` from `format_metadata(img.metadata)`, advance to `destination` stage.
- `set_destination(dest)`: set flag, rebuild `self._stages` (preserving position at the `destination` stage), refresh stepper.
- Stretch panel labels map: `{"gentle":"Small","balanced":"Medium","punchy":"Large"}` → `apply_stretch`.
- `apply_current(option)`: as today but uses `self._stages`/`PROCESSING_ORDER`; `_step_for` returns: crop→`CropAutoStep`, background→`BackgroundStep(GraXpert)`, color→`ColorStep`, stretch→`StretchStep`(map label), saturation→`SaturationStep`, noise_sharpen→`NoiseSharpenStep(rcastro|None)`.
- `export_external(choice)`: render current; if "Two TIFFs" → `RCAstro.remove_stars` then `save_tiff(starless)`,`save_tiff(stars)` into a chosen folder; else `save_tiff(single)`. Gated: split option needs `rcastro_valid`.
- `export_final(fmt)`: save TIFF/PNG/FITS to a chosen file.
- Stepper is rebuilt from `self._stages` (a helper `Stepper.set_stages(stages)` — Task 9). Navigation/undo/redo/before-after/zoom unchanged.
- Background apply gated on `graxpert_valid`; color/crop/saturation/noise_sharpen always enabled when project loaded (noise_sharpen has a fallback).

- [ ] **Step 1: Write the smoke/logic tests** — open advances to destination; choosing external yields stepper ending in `export_external`; choosing in_app yields the cosmetic tail; applying stretch sets `is_linear=False`; `_step_for` returns correct types; export_external split gated without RC-Astro.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** the rewritten `MainWindow` (reuse the prior structure: stepper left, ImageView center, right panel + Back/Next, toolbar with Open/Settings/Undo/Redo/Before-After/Fit/100%).
- [ ] **Step 4: Run → PASS** + full suite.
- [ ] **Step 5: Commit** `feat: spec-aligned MainWindow with destination branch`.

---

### Task 9: Stepper accepts dynamic stages

**Files:**
- Modify: `seestar_processor/ui/stepper.py`
- Test: `tests/ui/test_stepper.py` (update)

**Interfaces:**
- `Stepper()` starts empty; `set_stages(stages: list[Stage]) -> None` (re)populates rows from a given list (disabled stages greyed); `stageSelected(int)` emits the index within the current stage list; `set_current(i)`, `mark_done(done_ids)` operate on the current list. `_on_click` guards using the stored stage list.

- [ ] **Step 1: Write failing tests** — `set_stages` populates rows; clicking an enabled row emits its index; `mark_done` checks rows.
- [ ] **Step 2–4:** implement + pass.
- [ ] **Step 5: Commit** `feat: Stepper supports dynamic stage lists`.

> Note: Task 9 is consumed by Task 8; implement Task 9 first if executing in order (reorder as 8↔9). Task list order for execution: 1,2,3,4,5,6,7,9,8.

---

### Task 10: Cleanup removed stages

**Files:**
- Delete: `seestar_processor/steps/deconvolution.py`, `seestar_processor/steps/noise.py`, `seestar_processor/steps/crop.py`, `seestar_processor/steps/color.py` is **kept** (ColorStep reused), `seestar_processor/steps/final_fixes.py`, `seestar_processor/steps/stretch_step.py` kept.
- Delete tests for removed modules; keep `core/deconvolution.py`, `core/noise.py`, `core/crop.py` (used by NoiseSharpen fallback + auto_crop).
- Verify no remaining imports reference deleted modules (`grep -rn "steps.deconvolution\|steps.noise\b\|steps.final_fixes\|steps.crop\b" seestar_processor tests`).

- [ ] **Step 1:** remove the now-unused step modules + their tests; fix any imports.
- [ ] **Step 2:** `.venv/bin/pytest -q` → all pass, pristine.
- [ ] **Step 3: Commit** `refactor: remove pre-stretch decon/noise and final-fixes/stars editing stages`.

---

## Verification (end to end)

`.venv/bin/python -m seestar_processor`:
- Open FITS → metadata shows; lands on Destination.
- External path: Crop(auto, margin) → Background(off/light/strong) → Color(auto) → Stretch(gentle/balanced/punchy) → Export (single TIFF, or split starless+stars with RC-Astro). No cosmetic steps.
- In-app path: …Stretch → Saturation(slider) → Noise+Sharpen(light/medium/strong) → Export(FITS/PNG/TIFF).
- Undo/redo, before/after, zoom/pan still work.

## Self-Review notes
- Spec coverage: Step1 (T1+T8 metadata panel), Step2 destination (T5,T7,T8), Step3 crop-auto (T2,T6,T7), Step4 background off/light/strong (T6,T7), Step5 color auto (T6,T7), Step6 stretch presets (T7,T8), external export single/split (T3,T7,T8), Step7 saturation (T4,T6,T7), Step8 noise+sharpen post-stretch (T6,T7), Step9 export FITS/PNG/TIFF (T3,T7,T8). One-control-per-step enforced in T7 panels.
- Reversals from current build handled in T6/T10: decon+noise move post-stretch & merge; stars → external export option; final-fixes removed; color controls removed.
- Engine modules untouched except `fits_io`, `crop`, `export`, `background` step.
