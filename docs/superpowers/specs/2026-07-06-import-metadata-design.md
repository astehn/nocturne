# Richer Import Metadata — Design

**Date:** 2026-07-06
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — building under standing authorization.

## Motivation

When a stacked FITS is opened, the Import panel shows a single dim line
(`IC 5070 · 20s · 145 frames · gain 200 · 2160x3840`) and leaves the rest of the panel
empty. Users want to understand their data better — especially **total integration time**
(currently not shown, though it's just frames × sub-exposure) — and some **sensor/scope
context**. There is plenty of space in the Import panel to present this well.

## Decisions (from discussion)

- Replace the one-line summary with a **grouped label/value readout** in the Import panel,
  in two sections:
  - **Your stack** — from the FITS header, showing only fields actually present: Target,
    **Total integration** (computed, e.g. `48m 20s (145 × 20s)`), Frames, Gain, Sensor temp,
    Captured (date), Dimensions.
  - **Camera & scope** — from the hardcoded S30 Pro profile (always available): Sensor
    (Sony IMX585), Pixel size, Focal length + f-ratio, and computed Image scale (~4″/px).
- **Total integration time** = `frames × sub-exposure`, formatted h/m/s; omitted if either
  value is missing. Sub-exposure is shown folded into that line, not as a separate row.
- Missing header fields produce **no row** (graceful) — no blanks.
- **Deferred (YAGNI):** common-name lookup for targets (e.g. "Pelican Nebula"), bit-depth /
  Bayer-pattern rows (too techy for the default view).

## Architecture / changes

### `core/instrument.py` — enrich the profile

Add a sensor name, aperture, and an f-ratio property:

```python
@dataclass(frozen=True)
class Instrument:
    name: str
    sensor: str                 # NEW — e.g. "Sony IMX585"
    width: int
    height: int
    pixel_size_um: float
    focal_length_mm: float
    aperture_mm: float          # NEW — for the f-ratio
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
    width=3840, height=2160,
    pixel_size_um=2.9,
    focal_length_mm=150.0,
    aperture_mm=30.0,           # 150 / 30 = f/5
    bayer_pattern="GRBG",
)
```

### `core/fits_io.py` — parse more, and format the readout

Extend `_parse_metadata`'s mapping to also capture (best-effort; only if present):

```python
        "temp": ("CCD-TEMP", "CCD_TEMP"),
        "date": ("DATE-OBS", "DATE"),
```

Add two formatters. `format_metadata`'s only app caller is the Import panel (main_window.py
line 780), which this change replaces — so after the change it is dead code (only its own
test remains). **Remove `format_metadata` and repoint its test** to `import_summary`:

```python
def format_integration(seconds: float) -> str:
    """Human total integration, e.g. 2900 -> '48m 20s', 8100 -> '2h 15m'."""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def import_summary(meta: dict, instrument=SEESTAR_S30_PRO) -> str:
    """Rich-HTML grouped readout for the Import panel: 'Your stack' (from the
    header, present fields only) + 'Camera & scope' (from the instrument)."""
    # builds <b>Your stack</b> rows for present fields, computing Total
    # integration from meta['exposure'] * meta['frames'] when both exist;
    # then <b>Camera & scope</b> rows from the instrument profile. Returns HTML.
```

`import_summary` row rules:
- Target: `meta["target"]` if present.
- Total integration: if `meta["exposure"]` and `meta["frames"]` → `format_integration(exp*frames)` + ` ({frames} × {exp:g}s)`.
- Frames: `meta["frames"]`.
- Gain: `meta["gain"]` (`:g`).
- Sensor temp: `meta["temp"]` → `{:g} °C` (skip if non-numeric).
- Captured: `meta["date"]` → the date portion (`str(date).split("T")[0]`).
- Dimensions: `{width} × {height}` (always present).
- Camera & scope (always): Sensor `instrument.sensor` + " (colour)"; Pixel size
  `{pixel_size_um:g} µm`; Focal length `{focal_length_mm:g} mm · f/{f_ratio:g}`; Image scale
  `~{pixel_scale_arcsec:.1f}″ / pixel`.

### `ui/step_panels.py` — render as rich text

In the `import` branch, the `meta_label` must render HTML: set
`meta.setTextFormat(Qt.TextFormat.RichText)` (import `Qt`) so the grouped readout displays.
The default text ("Open a stacked Seestar FITS to begin.") still renders fine.

### `ui/main_window.py` — feed the richer summary

In `_rebuild_panel`, replace:

```python
            new_panel.meta_label.setText(format_metadata(self.project.current().metadata))
```

with:

```python
            new_panel.meta_label.setText(import_summary(self.project.current().metadata))
```

and update the import: `from ..core.fits_io import import_summary` (drop `format_metadata`,
which is being removed).

## Data flow

Open a FITS → `load_fits` → `_parse_metadata` captures target/exposure/frames/gain/temp/date
+ dimensions → `open_image` → `_rebuild_panel` sets the Import `meta_label` to
`import_summary(meta)` (rich text) → the panel shows the grouped "Your stack" + "Camera &
scope" readout, filling the space.

## Error handling

- Every header field is optional; `import_summary` emits a row only when the value exists,
  so a sparse header degrades to just Dimensions + the always-present Camera & scope section.
- `temp`/`exposure` guarded against non-numeric values (wrap the numeric format in a
  try/except → skip the row) so an odd header never crashes the panel.
- `import_summary` never raises on missing keys (uses `.get`).

## Testing

- **instrument** (`tests/core/test_instrument.py`): `SEESTAR_S30_PRO.f_ratio == 5.0`;
  `SEESTAR_S30_PRO.sensor == "Sony IMX585"`; existing pixel-scale test still passes.
- **fits_io** (`tests/core/test_fits_io.py`):
  - `format_integration(2900) == "48m 20s"`; `format_integration(8100) == "2h 15m"`;
    `format_integration(20) == "20s"`.
  - `_parse_metadata` captures `temp` from `CCD-TEMP` and `date` from `DATE-OBS` when present.
  - `import_summary({"exposure":20,"frames":145,"target":"IC 5070","width":2160,"height":3840})`
    contains "IC 5070", "48m 20s", "145 × 20s", "2160 × 3840", and (from the profile)
    "Sony IMX585" and "4.0″".
  - `import_summary({"width":10,"height":10})` (sparse) contains "Sony IMX585" and "10 × 10"
    and does NOT contain "Total integration".
  - Update/replace the existing `format_metadata` test to match whichever function survives
    (if `format_metadata` is removed, its test is replaced by the `import_summary` tests).
- **main_window** (`tests/ui/test_main_window.py`): update the assertion that currently
  checks `"24x24"` in `meta_label.text()` to the new format (`"24 × 24"`); assert the label
  also contains "Sony IMX585".
- **step_panels** (`tests/ui/test_step_panels.py`): the import panel exposes `meta_label`
  (unchanged) and it renders rich text (its `textFormat()` is `RichText`).
- Full suite green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`).

## Verification (by eye)

Open a stacked Seestar FITS: the Import panel fills with a two-section readout — "Your
stack" (Target, Total integration 48m 20s (145 × 20s), Frames, Gain, Sensor temp, Captured,
Dimensions — only the fields your file carries) and "Camera & scope" (Sony IMX585, 2.9 µm,
150 mm · f/5, ~4.0″/pixel). A file with a sparse header still shows Dimensions + the camera
section without blank rows.
