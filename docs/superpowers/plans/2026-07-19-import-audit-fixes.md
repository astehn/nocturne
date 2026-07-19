# Import step — audit fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Fix Import's correctness/trust issues (D1 integration, D2 camera-from-file, U2 target, U1 reassurance, U4 empty fallback) — display/parse only.

**Architecture:** A pure `resolve_integration(meta)` disambiguates EXPTIME semantics; `import_summary` consumes it, reads camera specs from the header with profile fallback, and gains a `filename` arg for the target fallback; the instrument profile's focal length is corrected; the panel gains a reassurance line.

**Tech Stack:** Python, NumPy, astropy, PySide6, pytest.

## Global Constraints

- Display/parse only — never mutate `AstroImage.data` or pipeline behaviour.
- `_plausible_sub(x) = 0.5 <= x <= 600`.
- Profile after fix: `focal_length_mm=160.0`, `aperture_mm=32.0` (f/5, scale ≈ 3.7″/px).
- Ground-truth cases that MUST resolve correctly: Nocturne master (EXPTIME=1620, frames=81 → total 1620, per-sub 20); native (LIVETIME=3220, EXPTIME=20, frames=161 → total 3220, per-sub 20); legacy per-sub (EXPTIME=20, frames=145, no LIVETIME → total 2900, per-sub 20).
- Run tests via `.venv/bin/python -m pytest`.

---

### Task 1: `resolve_integration` + metadata fields

**Files:**
- Modify: `nocturne/core/fits_io.py` (`_parse_metadata`; add `Integration` + `resolve_integration`)
- Test: `tests/core/test_fits_io.py`

**Interfaces:**
- Produces: `resolve_integration(meta: dict) -> Integration | None` where
  `Integration` is a dataclass `(total_s: float | None, per_sub_s: float | None, frames: int | None)`.

- [ ] **Step 1: Write failing tests** in `tests/core/test_fits_io.py`:

```python
def test_resolve_integration_nocturne_master():
    from nocturne.core.fits_io import resolve_integration
    r = resolve_integration({"exposure": 1620.0, "frames": 81})  # EXPTIME=total
    assert round(r.total_s) == 1620 and round(r.per_sub_s) == 20 and r.frames == 81


def test_resolve_integration_native_livetime():
    from nocturne.core.fits_io import resolve_integration
    r = resolve_integration({"livetime": 3220.0, "exposure": 20.0, "frames": 161})
    assert round(r.total_s) == 3220 and round(r.per_sub_s) == 20


def test_resolve_integration_legacy_persub():
    from nocturne.core.fits_io import resolve_integration
    r = resolve_integration({"exposure": 20.0, "frames": 145})  # EXPTIME=per-sub
    assert round(r.total_s) == 2900 and round(r.per_sub_s) == 20


def test_resolve_integration_exposure_only_and_none():
    from nocturne.core.fits_io import resolve_integration
    r = resolve_integration({"exposure": 30.0})
    assert r.total_s is None and round(r.per_sub_s) == 30
    assert resolve_integration({"width": 10}) is None
```

- [ ] **Step 2: Run to confirm failure** — `.venv/bin/python -m pytest tests/core/test_fits_io.py -q` → ImportError/fail.

- [ ] **Step 3: Implement.** In `nocturne/core/fits_io.py` add `from dataclasses import dataclass` and:

```python
@dataclass
class Integration:
    total_s: float | None
    per_sub_s: float | None
    frames: int | None


def _plausible_sub(x: float) -> bool:
    return 0.5 <= x <= 600.0


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def resolve_integration(meta: dict) -> "Integration | None":
    """Resolve total integration + per-sub exposure across the differing header
    conventions. `EXPTIME` is per-sub in native ZWO/Siril files but the *total*
    in Nocturne's own masters; native files carry the standard `LIVETIME` total.
    Rule-2's ratio test only sees Nocturne `EXPTIME=total` masters, because
    native files carry LIVETIME and are handled by rule 1."""
    live = _num(meta.get("livetime"))
    exp = _num(meta.get("exposure"))
    frames = meta.get("frames")
    try:
        frames = int(frames) if frames is not None else None
    except (TypeError, ValueError):
        frames = None

    if live and live > 0:
        per = exp if (exp and _plausible_sub(exp)) else (
            live / frames if frames else None)
        return Integration(live, per, frames)
    if exp and frames:
        cand = exp / frames
        if _plausible_sub(cand):
            return Integration(exp, cand, frames)       # EXPTIME already total
        return Integration(exp * frames, exp, frames)   # EXPTIME per-sub
    if exp:
        return Integration(None, exp, frames)
    return None
```

Then extend `_parse_metadata`'s `mapping` with:

```python
        "livetime": ("LIVETIME",),
        "focal_length": ("FOCALLEN",),
        "pixel_size": ("XPIXSZ", "YPIXSZ"),
```

- [ ] **Step 4: Run to confirm pass** — `.venv/bin/python -m pytest tests/core/test_fits_io.py -q`.

- [ ] **Step 5: Commit** — `git add nocturne/core/fits_io.py tests/core/test_fits_io.py && git commit -m "feat(import): resolve_integration disambiguates EXPTIME semantics"`

---

### Task 2: `import_summary` rework + profile focal length

**Files:**
- Modify: `nocturne/core/fits_io.py` (`import_summary`)
- Modify: `nocturne/core/instrument.py` (focal length / aperture)
- Test: `tests/core/test_fits_io.py`, `tests/core/test_instrument.py`

**Interfaces:**
- Consumes: `resolve_integration`, `Integration` (Task 1).
- Produces: `import_summary(meta: dict, instrument=SEESTAR_S30_PRO, filename: str | None = None) -> str`.

- [ ] **Step 1: Fix the instrument profile.** In `nocturne/core/instrument.py`, set `focal_length_mm=160.0` and `aperture_mm=32.0`; update the inline comment to `# 160 / 32 = f/5 (device header: FOCALLEN=160, APERTURE=5.0)`.

- [ ] **Step 2: Update instrument tests** in `tests/core/test_instrument.py`: `focal_length_mm == 160.0`; `round(p.pixel_scale_arcsec, 1) == 3.7`; keep `f_ratio == 5.0`.

- [ ] **Step 3: Write failing import_summary tests** in `tests/core/test_fits_io.py`:

```python
def test_import_summary_nocturne_master_integration():
    from nocturne.core.fits_io import import_summary
    s = import_summary({"exposure": 1620.0, "frames": 81, "width": 1792, "height": 3656})
    assert "27m 00s" in s and "81 × 20s" in s
    assert "184h" not in s and "81 × 1620s" not in s  # the old bug is gone


def test_import_summary_camera_from_header():
    from nocturne.core.fits_io import import_summary
    s = import_summary({"focal_length": 160.0, "pixel_size": 2.9,
                        "width": 100, "height": 100})
    assert "160 mm" in s and "3.7″" in s


def test_import_summary_target_from_filename():
    from nocturne.core.fits_io import import_summary
    s = import_summary({"width": 10, "height": 10},
                       filename="NGC7000_182x20s_61min.fits")
    assert "NGC7000" in s


def test_import_summary_empty_stack_fallback():
    from nocturne.core.fits_io import import_summary
    s = import_summary({})
    assert "Your stack" in s and "Couldn't read" in s
    assert "Total integration" not in s
```

- [ ] **Step 4: Update the existing token test.** In `test_import_summary_full_and_sparse`, change `"4.0″"` to `"3.7″"`. Everything else in that test stays valid (`"145 × 20s"`, `"48m 20s"` still hold — legacy per-sub case).

- [ ] **Step 5: Run to confirm failures** — `.venv/bin/python -m pytest tests/core/test_fits_io.py tests/core/test_instrument.py -q`.

- [ ] **Step 6: Implement `import_summary`.** Rework so it:
  - Computes `target = meta.get("target") or _target_from_filename(filename)`, where `_target_from_filename` strips the extension and a trailing capture suffix (best-effort: take the stem, cut at the first `_` followed by a digit-run/`x`, e.g. `NGC7000_182x20s_61min` → `NGC7000`; return `None` for a falsy filename).
  - Builds the **"Your stack"** rows: Target (if any); integration via `resolve_integration` — total → `("Total integration", f"{format_integration(total_s)} ({frames} × {per_sub_s:g}s)")` (drop the parenthetical when frames/per_sub unknown), else per_sub-only → `("Exposure", f"{per_sub_s:g}s")`; Frames; Gain; Sensor temp; Captured; Dimensions (as today).
  - **Always renders the "Your stack" section.** If it has no rows beyond nothing, include a fallback row/line containing the text `Couldn't read capture details from this file's header.`
  - **Camera & scope** reads from the header with profile fallback:
    `focal = meta.get("focal_length") or instrument.focal_length_mm`;
    `pix = meta.get("pixel_size") or instrument.pixel_size_um`;
    `scale = 206.265 * float(pix) / float(focal)`; show `Sensor` (profile), `Pixel size {pix:g} µm`, `Focal length {focal:g} mm · f/{instrument.f_ratio:g}`, `Image scale ~{scale:.1f}″ / pixel`. Add a `Gain` row here or under the stack if `meta.get("gain")` is present (guard float()).
  - Keep the existing `_summary_section` HTML helper and overall two-section layout.

- [ ] **Step 7: Run to confirm pass** — `.venv/bin/python -m pytest tests/core/test_fits_io.py tests/core/test_instrument.py -q`.

- [ ] **Step 8: Commit** — `git add nocturne/core/fits_io.py nocturne/core/instrument.py tests/core/ && git commit -m "feat(import): per-file camera info, target fallback, graceful empty readout; fix profile focal length"`

---

### Task 3: UI wiring — filename + reassurance line

**Files:**
- Modify: `nocturne/ui/main_window.py` (pass filename into `import_summary`)
- Modify: `nocturne/ui/step_panels.py` (import branch reassurance label)
- Test: `tests/ui/test_step_panels.py`

**Interfaces:**
- Consumes: `import_summary(..., filename=...)` (Task 2).

- [ ] **Step 1: Thread the filename.** In `nocturne/ui/main_window.py`, the import-panel population currently calls `import_summary(self.project.current().metadata)` (in `_rebuild_panel`). Change it to `import_summary(self.project.current().metadata, filename=self._source_label)`.

- [ ] **Step 2: Write failing panel test** in `tests/ui/test_step_panels.py`:

```python
def test_crop... (leave existing)


def test_import_panel_has_linear_preview_note(qapp):
    w = build_panel(_stage("load"))
    from PySide6.QtWidgets import QLabel
    texts = " ".join(l.text() for l in w.findChildren(QLabel))
    assert "histogram" in texts.lower() or "un-stretched" in texts.lower()
```

- [ ] **Step 3: Run to confirm failure** — `.venv/bin/python -m pytest tests/ui/test_step_panels.py -q`.

- [ ] **Step 4: Add the reassurance label.** In `nocturne/ui/step_panels.py`, in the `stage.kind == "import"` branch, after the existing `meta` label is added, add:

```python
        note = _desc_label(
            "Teal cast and a flat histogram are normal here — this is your "
            "un-stretched data. Colour and contrast come in the next steps.")
        note.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(note)
```

- [ ] **Step 5: Run to confirm pass** — `.venv/bin/python -m pytest tests/ui/test_step_panels.py -q`.

- [ ] **Step 6: Full suite** — `.venv/bin/python -m pytest tests/ -q` → all pass.

- [ ] **Step 7: Commit** — `git add nocturne/ui/main_window.py nocturne/ui/step_panels.py tests/ui/test_step_panels.py && git commit -m "feat(import): thread filename for target fallback + linear-preview reassurance note"`
