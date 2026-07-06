# Richer Import Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one-line Import summary with a grouped "Your stack" + "Camera & scope" readout, including computed total integration time and S30 Pro sensor/scope context.

**Architecture:** Enrich the `Instrument` profile (sensor, aperture, f-ratio); parse a couple more header fields and add `format_integration` + `import_summary` formatters in `core/fits_io.py`; render the rich-HTML readout in the Import panel.

**Tech Stack:** Python 3.13 (`.venv`), PySide6 (Qt), astropy (FITS), pytest-qt (headless via `QT_QPA_PLATFORM=offscreen`).

## Global Constraints

- Python interpreter: `.venv/bin/python`; tests: `.venv/bin/pytest` (system python3 is 3.9 — do NOT use it). Run the suite with `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`.
- Dimensions render as `"{width} × {height}"` (spaces around ×). Total integration formatted h/m/s via `format_integration`. Sub-exposure folded into the integration line: `"{total} ({frames} × {exp:g}s)"`.
- Present-fields-only: a header field absent → no row. Numeric formats (`temp`, integration) guarded so a non-numeric header value skips the row rather than crashing.
- `format_metadata` is removed (its only app caller is the Import panel, which this change replaces); its test is repointed to `import_summary`.
- Instrument f-ratio = focal_length / aperture; S30 Pro = 150 / 30 = f/5. Sensor = "Sony IMX585".
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Instrument enrichment + fits_io parsing & formatters

**Files:**
- Modify: `seestar_processor/core/instrument.py`
- Modify: `seestar_processor/core/fits_io.py` (`_parse_metadata`; add `format_integration`, `import_summary`; remove `format_metadata`)
- Test: `tests/core/test_instrument.py`, `tests/core/test_fits_io.py`

**Interfaces:**
- Produces:
  - `Instrument.sensor: str`, `Instrument.aperture_mm: float`, `Instrument.f_ratio -> float`.
  - `fits_io.format_integration(seconds: float) -> str`.
  - `fits_io.import_summary(meta: dict, instrument=SEESTAR_S30_PRO) -> str` (rich HTML).
  - `_parse_metadata` additionally captures `"temp"` (CCD-TEMP) and `"date"` (DATE-OBS).

- [ ] **Step 1: Write the failing tests**

Append to `tests/core/test_instrument.py`:

```python
def test_seestar_s30_pro_sensor_and_fratio():
    p = SEESTAR_S30_PRO
    assert p.sensor == "Sony IMX585"
    assert p.f_ratio == 5.0
```

Add to `tests/core/test_fits_io.py`:

```python
def test_format_integration():
    from seestar_processor.core.fits_io import format_integration
    assert format_integration(2900) == "48m 20s"
    assert format_integration(8100) == "2h 15m"
    assert format_integration(20) == "20s"


def test_parse_metadata_temp_and_date(tmp_path):
    from astropy.io import fits
    import numpy as np
    arr = np.random.randint(0, 4096, size=(3, 8, 8)).astype(np.uint16)
    hdu = fits.PrimaryHDU(arr)
    hdu.header["CCD-TEMP"] = 26.0
    hdu.header["DATE-OBS"] = "2026-06-18T21:34:00"
    p = tmp_path / "t.fits"
    hdu.writeto(str(p), overwrite=True)
    img = load_fits(str(p))
    assert img.metadata["temp"] == 26.0
    assert str(img.metadata["date"]).startswith("2026-06-18")


def test_import_summary_full_and_sparse():
    from seestar_processor.core.fits_io import import_summary
    full = import_summary({"exposure": 20, "frames": 145, "target": "IC 5070",
                           "width": 2160, "height": 3840})
    for token in ("IC 5070", "48m 20s", "145 × 20s", "2160 × 3840",
                  "Sony IMX585", "4.0″"):
        assert token in full, token
    sparse = import_summary({"width": 10, "height": 10})
    assert "Sony IMX585" in sparse and "10 × 10" in sparse
    assert "Total integration" not in sparse
```

Update the existing `test_metadata_parsed_from_header` in `tests/core/test_fits_io.py`: change the import and final two lines from `format_metadata` to `import_summary`:

```python
    from seestar_processor.core.fits_io import import_summary
    # … existing parse assertions unchanged …
    summary = import_summary(img.metadata)
    assert "M31" in summary and "30" in summary
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/core/test_instrument.py tests/core/test_fits_io.py -q`
Expected: FAIL (`AttributeError: 'Instrument' object has no attribute 'sensor'` / `ImportError: cannot import name 'format_integration'`).

- [ ] **Step 3a: Enrich the instrument profile**

In `seestar_processor/core/instrument.py`, add `sensor` and `aperture_mm` fields and the `f_ratio` property, and update the singleton:

```python
@dataclass(frozen=True)
class Instrument:
    name: str
    sensor: str
    width: int
    height: int
    pixel_size_um: float
    focal_length_mm: float
    aperture_mm: float
    bayer_pattern: str

    @property
    def pixel_scale_arcsec(self) -> float:
        return 206.265 * self.pixel_size_um / self.focal_length_mm

    @property
    def f_ratio(self) -> float:
        return self.focal_length_mm / self.aperture_mm


SEESTAR_S30_PRO = Instrument(
    name="ZWO Seestar S30 Pro",
    sensor="Sony IMX585",
    width=3840,
    height=2160,
    pixel_size_um=2.9,
    focal_length_mm=150.0,
    aperture_mm=30.0,   # 150 / 30 = f/5
    bayer_pattern="GRBG",
)
```

- [ ] **Step 3b: Parse temp & date; add formatters; remove `format_metadata`**

In `seestar_processor/core/fits_io.py`, extend the `_parse_metadata` mapping:

```python
    mapping = {
        "exposure": ("EXPTIME",),
        "gain": ("GAIN",),
        "target": ("OBJECT",),
        "frames": ("STACKCNT", "NFRAMES", "NCOMBINE"),
        "bitpix": ("BITPIX",),
        "temp": ("CCD-TEMP", "CCD_TEMP"),
        "date": ("DATE-OBS", "DATE"),
    }
```

Delete the `format_metadata` function and replace it with:

```python
def format_integration(seconds: float) -> str:
    """Human total integration: 2900 -> '48m 20s', 8100 -> '2h 15m', 20 -> '20s'."""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def _summary_section(title: str, pairs: list[tuple[str, str]]) -> str:
    rows = "".join(
        f"<tr><td style='color:#8a9099'>{k}</td><td>&nbsp;&nbsp;{v}</td></tr>"
        for k, v in pairs
    )
    return f"<b>{title}</b><table cellspacing='0'>{rows}</table>"


def import_summary(meta: dict, instrument=SEESTAR_S30_PRO) -> str:
    """Grouped rich-HTML readout: 'Your stack' (header, present fields only) +
    'Camera & scope' (from the instrument profile)."""
    stack: list[tuple[str, str]] = []
    if meta.get("target"):
        stack.append(("Target", str(meta["target"])))
    exp, frames = meta.get("exposure"), meta.get("frames")
    if exp is not None and frames is not None:
        try:
            total = format_integration(float(exp) * float(frames))
            stack.append(("Total integration", f"{total} ({frames} × {float(exp):g}s)"))
        except (TypeError, ValueError):
            pass
    if frames is not None:
        stack.append(("Frames", f"{frames}"))
    if meta.get("gain") is not None:
        try:
            stack.append(("Gain", f"{float(meta['gain']):g}"))
        except (TypeError, ValueError):
            pass
    if meta.get("temp") is not None:
        try:
            stack.append(("Sensor temp", f"{float(meta['temp']):g} °C"))
        except (TypeError, ValueError):
            pass
    if meta.get("date"):
        stack.append(("Captured", str(meta["date"]).split("T")[0]))
    if meta.get("width") and meta.get("height"):
        stack.append(("Dimensions", f"{meta['width']} × {meta['height']}"))

    scope = [
        ("Sensor", f"{instrument.sensor} (colour)"),
        ("Pixel size", f"{instrument.pixel_size_um:g} µm"),
        ("Focal length", f"{instrument.focal_length_mm:g} mm · f/{instrument.f_ratio:g}"),
        ("Image scale", f"~{instrument.pixel_scale_arcsec:.1f}″ / pixel"),
    ]

    html = _summary_section("Your stack", stack) if stack else ""
    html += _summary_section("Camera &amp; scope", scope)
    return html
```

(`SEESTAR_S30_PRO` is already imported at the top of `fits_io.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/core/test_instrument.py tests/core/test_fits_io.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/core/instrument.py seestar_processor/core/fits_io.py tests/core/test_instrument.py tests/core/test_fits_io.py
git commit -m "feat: import_summary + integration time; enrich instrument profile

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Render the readout in the Import panel

**Files:**
- Modify: `seestar_processor/ui/step_panels.py` (import branch — rich text on `meta_label`)
- Modify: `seestar_processor/ui/main_window.py` (import of `import_summary`; `_rebuild_panel` line ~780)
- Test: `tests/ui/test_main_window.py`, `tests/ui/test_step_panels.py`

**Interfaces:**
- Consumes: `fits_io.import_summary` (Task 1).

- [ ] **Step 1: Write / update the failing tests**

In `tests/ui/test_main_window.py`, update the metadata assertion (currently `assert "24x24" in win._panel.meta_label.text()` around line 30):

```python
    assert "24 × 24" in win._panel.meta_label.text()
    assert "Sony IMX585" in win._panel.meta_label.text()
```

Add to `tests/ui/test_step_panels.py`:

```python
def test_import_panel_meta_label_is_rich_text(qtbot):
    from PySide6.QtCore import Qt
    from seestar_processor.ui.step_panels import build_panel
    from seestar_processor.ui.pipeline import path_stages
    stage = next(s for s in path_stages() if s.kind == "import")
    w = build_panel(stage)
    qtbot.addWidget(w)
    assert w.meta_label.textFormat() == Qt.TextFormat.RichText
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py::test_open_fits_stays_on_import_with_metadata tests/ui/test_step_panels.py::test_import_panel_meta_label_is_rich_text -q`
Expected: FAIL (`"24 × 24"` not found — still shows the old `format_metadata`; `textFormat` is not RichText).

- [ ] **Step 3a: Render the import meta label as rich text**

In `seestar_processor/ui/step_panels.py`, the `import` branch — set the label to rich text:

```python
    if stage.kind == "import":
        btn = QPushButton("Open FITS…")
        if on_open is not None:
            btn.clicked.connect(lambda: on_open())
        lay.addWidget(btn)
        meta = _desc_label("Open a stacked Seestar FITS to begin.")
        meta.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(meta)
        w.meta_label = meta
```

(`Qt` is already imported in `step_panels.py`.)

- [ ] **Step 3b: Feed `import_summary` into the panel**

In `seestar_processor/ui/main_window.py`, change the import on line 15 from
`from ..core.fits_io import format_metadata` to `from ..core.fits_io import import_summary`,
and update `_rebuild_panel` (line ~780):

```python
        if stage.kind == "import" and loaded and hasattr(new_panel, "meta_label"):
            new_panel.meta_label.setText(import_summary(self.project.current().metadata))
```

- [ ] **Step 4: Run the affected files, then the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py tests/ui/test_step_panels.py -q`
Expected: PASS.

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: PASS (all green; `grep -rn format_metadata seestar_processor tests` returns nothing).

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/step_panels.py seestar_processor/ui/main_window.py tests/ui/test_main_window.py tests/ui/test_step_panels.py
git commit -m "feat: render grouped import readout (stack + camera/scope) in Import panel

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Grouped "Your stack" + "Camera & scope" readout → Task 1 `import_summary`, Task 2 rendering. ✅
- Total integration computed + folded sub-exposure line → Task 1 (`format_integration`, integration row). ✅
- Present-fields-only, numeric guards → Task 1 (`.get` + try/except). ✅
- Sensor/aperture/f-ratio + image scale from profile → Task 1 instrument enrichment + scope rows. ✅
- Parse CCD-TEMP / DATE-OBS → Task 1 `_parse_metadata`. ✅
- Remove `format_metadata`, repoint its test → Task 1 (delete + `test_metadata_parsed_from_header` update). ✅
- Deferred (no target common-name, no bit-depth/Bayer rows) → not built. ✅

**Placeholder scan:** All code blocks complete; no TBD/vague steps. ✅

**Type consistency:** `import_summary(meta, instrument=SEESTAR_S30_PRO) -> str`, `format_integration(seconds) -> str`, `Instrument.sensor/aperture_mm/f_ratio` used identically across Tasks 1–2 and tests. Dimension string `"{w} × {h}"` matches the main_window assertion `"24 × 24"`. ✅
