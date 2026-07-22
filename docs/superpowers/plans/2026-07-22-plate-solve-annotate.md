# Plate Solve & Annotate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add offline plate-solving (ASTAP, detect-and-shell-out) plus its two first payoffs — auto target identification and an annotation overlay (DSO labels + compass + scale bar) — to Nocturne.

**Architecture:** ASTAP is an optional external tool configured like RC-Astro/GraXpert. On demand we write the *currently displayed* image to a temp FITS, run ASTAP, parse the resulting WCS, project a bundled OpenNGC catalogue through it to place labels, and draw a toggleable `QGraphicsItemGroup` overlay in the image viewer. We re-solve on any image change rather than transforming the WCS through geometry. The solved target name appears in the Import panel; annotations can be burned into a PNG export and the WCS written to a FITS export.

**Tech Stack:** Python 3.11+, PySide6 (Qt), astropy (`astropy.wcs`, `astropy.coordinates`, `astropy.io.fits` — already a dep), ASTAP (external binary, user-installed), OpenNGC (bundled CSV).

## Global Constraints

- **Solver:** ASTAP only, detect-and-shell-out. If ASTAP is not configured/valid, the feature is unavailable (no error dialog, a status-bar hint only). No online solver, no bundled solver.
- **We distribute no star database.** ASTAP + its D05 database are user-installed.
- **Bundled data:** OpenNGC CSV at `nocturne/data/openngc.csv` (CC BY-SA 4.0 — attribute in About/Help/NOTICE). This is the *only* new bundled data.
- **Re-solve on change; never transform a WCS through Crop/Rotate/Flip.** Cache the solve against a display-image signature; a changed signature invalidates it.
- **Solve the display-space (post-geometry, possibly stretched) image**, so the WCS matches what is on screen (WYSIWYG).
- **Never `git add -A`.** Stage only the files named in each task (the repo has pre-existing untracked strays).
- **Run Python via `.venv/bin/python`.** Test baseline before this plan: 638 passing.
- **Solved name goes in `metadata["target_solved"]`** — a distinct key; never overwrite `metadata["target"]`.
- **No `is_color` gate** on solving/annotation (unlike Narrowband) — solving works on mono and colour.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `nocturne/settings.py` (mod) | `astap_path` field, `astap_valid()` | 1 |
| `nocturne/tools/astap.py` (new) | ASTAP CLI wrapper: solve → `SolveResult` (WCS), RA/Dec hint parse | 2 |
| `nocturne/core/fits_io.py` (mod) | Capture RA/DEC cards; "Target (solved)" summary line | 3 |
| `nocturne/core/catalog.py` (new) | Load OpenNGC; project objects into field; identify target | 4 |
| `nocturne/data/openngc.csv` (new) | Bundled DSO catalogue | 4 |
| `nocturne/core/annotate.py` (new) | Compass angles + scale-bar geometry (pure math) | 5 |
| `nocturne/ui/annotation_overlay.py` (new) | Build the `QGraphicsItemGroup` overlay | 6 |
| `nocturne/ui/image_view.py` (mod) | `set_annotations()` toggle on `ImageView` | 6 |
| `nocturne/ui/settings_dialog.py` (mod) | ASTAP path row + Test | 7 |
| `nocturne/ui/main_window.py` (mod) | Toolbar action, async solve, cache, target line, status chip, toggle | 8 |
| `nocturne/ui/step_panels.py` + `nocturne/core/export.py` (mod) | Burn-annotations checkbox; PNG render; FITS WCS header | 9 |
| `packaging/nocturne.spec` (mod) | astropy.wcs/coordinates hiddenimports; bundle openngc.csv | 10 |

Tasks 1–5 are pure/core (no Qt) and independently mergeable. 6–10 wire the UI/packaging.

---

## Task 1: Settings — `astap_path` + `astap_valid`

**Files:**
- Modify: `nocturne/settings.py` (dataclass ~26–31, `load_settings` ~34–44, add `astap_valid` after `rcastro_valid` ~80)
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings.astap_path: str`; `astap_valid(s: Settings) -> bool` (True iff `astap_path` set and `resolve_binary(astap_path)` is a file — mirrors `rcastro_valid`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_settings.py`:
```python
def test_astap_path_round_trips(tmp_path):
    from nocturne.settings import Settings, save_settings, load_settings, astap_valid
    p = str(tmp_path / "settings.json")
    save_settings(Settings(astap_path="/opt/astap/astap"), p)
    assert load_settings(p).astap_path == "/opt/astap/astap"   # survives save+load


def test_astap_valid_checks_file(tmp_path):
    from nocturne.settings import Settings, astap_valid
    assert astap_valid(Settings(astap_path="")) is False
    real = tmp_path / "astap"; real.write_text("x")
    assert astap_valid(Settings(astap_path=str(real))) is True
    assert astap_valid(Settings(astap_path=str(tmp_path / "nope"))) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings.py::test_astap_path_round_trips tests/test_settings.py::test_astap_valid_checks_file -v`
Expected: FAIL (`astap_path` unknown / `astap_valid` not importable).

- [ ] **Step 3: Implement**

In `nocturne/settings.py`, add the field to the `Settings` dataclass:
```python
    astap_path: str = ""
```
In `load_settings`, add to the constructed `Settings(...)` call (it reads each field explicitly):
```python
        astap_path=data.get("astap_path", ""),
```
After `rcastro_valid`, add:
```python
def astap_valid(s: Settings) -> bool:
    return bool(s.astap_path) and os.path.isfile(resolve_binary(s.astap_path))
```
(`save_settings` uses `asdict`, so saving needs no change.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_settings.py -v`
Expected: PASS (all settings tests).

- [ ] **Step 5: Commit**

```bash
git add nocturne/settings.py tests/test_settings.py
git commit -m "feat(settings): astap_path field + astap_valid"
```

---

## Task 2: ASTAP wrapper (`tools/astap.py`)

**Files:**
- Create: `nocturne/tools/astap.py`
- Test: `tests/tools/test_astap.py`

**Interfaces:**
- Consumes: `AstroImage`; `write_temp_fits` from `nocturne/tools/base.py`.
- Produces:
  - `@dataclass SolveResult: solved: bool; wcs: object | None; center_ra_deg: float; center_dec_deg: float; pixscale_arcsec: float`
  - `class ASTAP: __init__(self, binary_path: str)`
  - `ASTAP.solve(self, img: AstroImage, *, fov_deg: float | None = None, ra_hours: float | None = None, dec_deg: float | None = None, runner=None) -> SolveResult`
  - `hint_from_metadata(meta: dict) -> tuple[float, float] | None` → `(ra_hours, dec_deg)` parsed from `meta["ra"]`/`meta["dec"]` (strings), else None.
  - Module constant `FITS_Y_DOWN: bool = True` (see spike) controlling whether ASTAP's WCS y-axis needs flipping to Nocturne's top-row-first display coords. The wrapper stores the WCS **as astropy parses it**; the y-orientation is applied at projection time in Task 4 using this flag — so the wrapper just parses and returns the WCS.
  - `runner` signature: `runner(args: list[str], cwd: str) -> int` (returns process exit code; default `_run_astap` runs `subprocess.run(args, cwd=cwd, capture_output=True, text=True).returncode`). Chosen over `run_cli` because ASTAP returns nonzero on "no solution" and we must not treat that as an exception.

**⚠ Verification spike (do this FIRST, before Step 1):** The exact `.wcs` sidecar format, ASTAP's CLI flags, exit codes, and pixel Y-orientation must be confirmed against a real ASTAP run. If ASTAP is available in the dev environment, solve a known Seestar image and capture: (a) the `.wcs` file contents, (b) exit codes for solved/no-solution, (c) whether `world_to_pixel` on the parsed WCS yields top-down or bottom-up rows (set `FITS_Y_DOWN`). Save the real `.wcs` as the test fixture in Step 1. If ASTAP is **not** available, proceed with the documented format below (FITS-keyword ASCII: `CRVAL1/2`, `CRPIX1/2`, `CD1_1..CD2_2`, `PLTSOLVD=T`) and leave `FITS_Y_DOWN = True` (matching the RC-Astro bottom-up precedent); flag in the task report that a real-ASTAP confirmation is still owed.

- [ ] **Step 1: Write the failing test**

Create `tests/tools/test_astap.py`:
```python
import os
import numpy as np
from nocturne.core.image import AstroImage
from nocturne.tools.astap import ASTAP, SolveResult, hint_from_metadata

# A minimal but real ASTAP .wcs sidecar (FITS-keyword ASCII, 80-char cards).
_WCS_TEXT = (
    "CTYPE1  = 'RA---TAN'\n"
    "CTYPE2  = 'DEC--TAN'\n"
    "CRPIX1  =                960.0\n"
    "CRPIX2  =                540.0\n"
    "CRVAL1  =              314.75\n"
    "CRVAL2  =               44.31\n"
    "CD1_1   =           -0.0005556\n"
    "CD1_2   =                  0.0\n"
    "CD2_1   =                  0.0\n"
    "CD2_2   =            0.0005556\n"
    "PLTSOLVD=                    T\n"
)


def _img():
    return AstroImage(np.zeros((1080, 1920, 3), np.float32), is_linear=False)


def test_solve_parses_wcs_on_success():
    def fake_runner(args, cwd):
        # ASTAP writes <base>.wcs next to the input; find the -o base.
        base = args[args.index("-o") + 1]
        with open(base + ".wcs", "w") as f:
            f.write(_WCS_TEXT)
        return 0
    res = ASTAP("/x/astap").solve(_img(), fov_deg=2.0, runner=fake_runner)
    assert res.solved is True
    assert abs(res.center_ra_deg - 314.75) < 1e-6
    assert abs(res.center_dec_deg - 44.31) < 1e-6
    assert abs(res.pixscale_arcsec - 2.0) < 0.05          # 0.0005556 deg/px * 3600
    assert res.wcs is not None


def test_solve_no_solution_returns_unsolved():
    def fake_runner(args, cwd):
        return 1                                           # no .wcs written, nonzero exit
    res = ASTAP("/x/astap").solve(_img(), runner=fake_runner)
    assert res.solved is False
    assert res.wcs is None


def test_solve_passes_fov_and_hint_flags():
    seen = {}
    def fake_runner(args, cwd):
        seen["args"] = args
        base = args[args.index("-o") + 1]
        open(base + ".wcs", "w").write(_WCS_TEXT)
        return 0
    ASTAP("/x/astap").solve(_img(), fov_deg=2.0, ra_hours=20.98, dec_deg=44.3, runner=fake_runner)
    a = seen["args"]
    assert a[0] == "/x/astap"
    assert "-fov" in a and a[a.index("-fov") + 1] == "2.0"
    assert "-ra" in a and a[a.index("-ra") + 1] == "20.98"
    assert "-spd" in a and a[a.index("-spd") + 1] == "134.3"   # dec + 90


def test_hint_from_metadata_parses_sexagesimal():
    ra_h, dec_d = hint_from_metadata({"ra": "20 58 47", "dec": "+44 18 36"})
    assert abs(ra_h - 20.9797) < 1e-3
    assert abs(dec_d - 44.31) < 1e-2
    assert hint_from_metadata({}) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/tools/test_astap.py -v`
Expected: FAIL (module `nocturne.tools.astap` missing).

- [ ] **Step 3: Implement**

Create `nocturne/tools/astap.py`:
```python
"""ASTAP plate-solver wrapper (optional external tool, detect-and-shell-out).

Writes the given image to a temp FITS, runs ASTAP to solve it, and parses the
resulting `.wcs` sidecar into an astropy WCS. ASTAP returns a NON-ZERO exit code
when it cannot solve, so we use a returncode-returning runner (not run_cli, which
raises on nonzero) and treat the presence of a valid `.wcs`/PLTSOLVD=T as success.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

import numpy as np

from ..core.image import AstroImage
from .base import write_temp_fits

# ASTAP's solved WCS follows the FITS bottom-up pixel convention; Nocturne display
# arrays are top-row-first. Projection (core/catalog) flips y when this is True.
# CONFIRM against a real ASTAP solve (see the verification spike).
FITS_Y_DOWN = True


@dataclass
class SolveResult:
    solved: bool
    wcs: object | None
    center_ra_deg: float
    center_dec_deg: float
    pixscale_arcsec: float


def _run_astap(args: list[str], cwd: str) -> int:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True).returncode


def hint_from_metadata(meta: dict) -> tuple[float, float] | None:
    """(ra_hours, dec_deg) from a FITS OBJCTRA/OBJCTDEC-style metadata pair, or
    None if absent/unparseable. Accepts sexagesimal or decimal strings."""
    ra, dec = meta.get("ra"), meta.get("dec")
    if not ra or not dec:
        return None
    try:
        from astropy.coordinates import Angle
        import astropy.units as u
        ra_h = Angle(str(ra), unit=u.hourangle).hour
        dec_d = Angle(str(dec), unit=u.deg).deg
        return float(ra_h), float(dec_d)
    except Exception:
        return None


class ASTAP:
    def __init__(self, binary_path: str) -> None:
        self.binary_path = binary_path

    def solve(self, img: AstroImage, *, fov_deg: float | None = None,
              ra_hours: float | None = None, dec_deg: float | None = None,
              runner=None) -> SolveResult:
        runner = runner or _run_astap
        tmp = tempfile.mkdtemp(prefix="nocturne_astap_")
        try:
            in_fits = os.path.join(tmp, "solve.fits")
            base = os.path.join(tmp, "solve")
            write_temp_fits(img, in_fits)
            args = [self.binary_path, "-f", in_fits, "-o", base, "-wcs"]
            if fov_deg is not None:
                args += ["-fov", str(round(float(fov_deg), 4))]
            if ra_hours is not None and dec_deg is not None:
                args += ["-ra", str(round(float(ra_hours), 4)),
                         "-spd", str(round(float(dec_deg) + 90.0, 4))]  # south pole distance
            runner(args, tmp)
            wcs_path = base + ".wcs"
            if not os.path.isfile(wcs_path):
                return SolveResult(False, None, 0.0, 0.0, 0.0)
            return self._parse(wcs_path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _parse(self, wcs_path: str) -> SolveResult:
        from astropy.io import fits
        from astropy.wcs import WCS
        header = fits.Header.fromtextfile(wcs_path)
        if str(header.get("PLTSOLVD", "T")).strip().upper() in ("F", "FALSE"):
            return SolveResult(False, None, 0.0, 0.0, 0.0)
        wcs = WCS(header)
        cd = wcs.pixel_scale_matrix           # deg/px 2x2
        pixscale = float(np.sqrt(abs(cd[0, 0] * cd[1, 1] - cd[0, 1] * cd[1, 0])) * 3600.0)
        return SolveResult(True, wcs, float(header["CRVAL1"]), float(header["CRVAL2"]), pixscale)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/tools/test_astap.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add nocturne/tools/astap.py tests/tools/test_astap.py
git commit -m "feat(tools): ASTAP plate-solve wrapper (WCS parse, RA/Dec hint)"
```

---

## Task 3: FITS metadata — RA/DEC capture + "Target (solved)" line

**Files:**
- Modify: `nocturne/core/fits_io.py` (`_parse_metadata` mapping ~37–48; `import_summary` ~141–143)
- Test: `tests/core/test_fits_io.py` (add cases; create if absent)

**Interfaces:**
- Produces: `metadata["ra"]`, `metadata["dec"]` (raw header strings, when present); an extra "Target (solved)" line in `import_summary` output when `meta.get("target_solved")` is set.
- Consumed by: Task 2 `hint_from_metadata` (reads `meta["ra"]`/`["dec"]`); Task 8 (writes `meta["target_solved"]`).

- [ ] **Step 1: Write the failing test**

Add to `tests/core/test_fits_io.py`:
```python
def test_parse_metadata_captures_ra_dec():
    from astropy.io import fits
    from nocturne.core.fits_io import _parse_metadata
    h = fits.Header()
    h["OBJCTRA"] = "20 58 47"
    h["OBJCTDEC"] = "+44 18 36"
    meta = _parse_metadata(h, 1080, 1920)
    assert meta["ra"] == "20 58 47"
    assert meta["dec"] == "+44 18 36"


def test_import_summary_shows_solved_target():
    from nocturne.core.fits_io import import_summary
    out = import_summary({"width": 1920, "height": 1080, "target_solved": "NGC 7000 · North America Nebula"})
    assert "Target (solved)" in out
    assert "NGC 7000" in out
    # absent key -> no solved line
    assert "Target (solved)" not in import_summary({"width": 1920, "height": 1080})
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_fits_io.py -k "ra_dec or solved_target" -v`
Expected: FAIL (`ra`/`dec` not captured; no solved line).

- [ ] **Step 3: Implement**

In `nocturne/core/fits_io.py`, add to the `mapping` dict inside `_parse_metadata` (the tuple lists alternative header cards):
```python
        "ra": ("OBJCTRA", "RA"),
        "dec": ("OBJCTDEC", "DEC"),
```
In `import_summary`, right after the existing "Target" row is appended (the `stack.append(("Target", ...))` area near line 143), add:
```python
    solved = meta.get("target_solved")
    if solved:
        stack.append(("Target (solved)", str(solved)))
```
(Match the surrounding variable name for the section's pair list — the block that builds the "stack"/instrument section. If the summary is built via `_summary_section(title, pairs)`, append to the same `pairs` list used for the Target row.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/core/test_fits_io.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/core/fits_io.py tests/core/test_fits_io.py
git commit -m "feat(fits_io): capture RA/DEC cards + Target (solved) summary line"
```

---

## Task 4: DSO catalogue (`core/catalog.py` + bundled OpenNGC)

**Files:**
- Create: `nocturne/core/catalog.py`
- Create: `nocturne/data/openngc.csv` (from OpenNGC; steps below)
- Test: `tests/core/test_catalog.py`

**Interfaces:**
- Consumes: an `astropy.wcs.WCS`, image `shape=(H, W)`; `FITS_Y_DOWN` from `nocturne.tools.astap`.
- Produces:
  - `@dataclass CatalogObject: name: str; common: str; ra_deg: float; dec_deg: float; major_arcmin: float; x: float; y: float`
  - `load_catalog(path=_DATA) -> list[tuple]` (cached raw rows: name, common, ra_deg, dec_deg, major_arcmin)
  - `objects_in_field(wcs, shape, rows=None) -> list[CatalogObject]` — project each row's (ra,dec) via `wcs.world_to_pixel`, apply the y-flip when `FITS_Y_DOWN`, keep those with `0 <= x < W and 0 <= y < H`.
  - `identify_target(objects, shape) -> str` — the in-field object with the largest `major_arcmin` (ties → nearest centre), formatted `"<name> · <common>"` (or just name if no common), `""` if none.

- [ ] **Step 1: Acquire + trim the OpenNGC data (setup step, folded into this task)**

Download OpenNGC's `NGC.csv` from the upstream repo (mattiaverga/OpenNGC, CC BY-SA 4.0) and produce a trimmed `nocturne/data/openngc.csv` with columns `name,common,ra_deg,dec_deg,major_arcmin`. Write a one-off conversion (the source uses `;`-separated columns `Name;Type;RA;Dec;MajAx;...;Common names`; RA/Dec are sexagesimal). Keep all NGC/IC/Messier rows that have coordinates (a few MB). Save the attribution note to `NOTICE` (create if absent):
```
OpenNGC catalogue (c) Mattia Verga, licensed CC BY-SA 4.0.
https://github.com/mattiaverga/OpenNGC
```
Verify the file loads: `.venv/bin/python -c "import csv; print(sum(1 for _ in csv.reader(open('nocturne/data/openngc.csv'))))"` (expect thousands of rows).

- [ ] **Step 2: Write the failing test**

Create `tests/core/test_catalog.py`:
```python
import numpy as np
from astropy.wcs import WCS
from nocturne.core.catalog import objects_in_field, identify_target, CatalogObject


def _wcs(center_ra=100.0, center_dec=0.0, w=1920, h=1080, scale_deg=0.0005556):
    wc = WCS(naxis=2)
    wc.wcs.crpix = [w / 2, h / 2]
    wc.wcs.crval = [center_ra, center_dec]
    wc.wcs.cd = [[-scale_deg, 0], [0, scale_deg]]
    wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wc


def test_objects_in_field_keeps_in_frame_drops_out():
    wcs = _wcs()
    rows = [
        ("NGC A", "Alpha", 100.0, 0.0, 20.0),     # dead centre -> in
        ("NGC B", "", 100.0, 5.0, 5.0),            # 5 deg north -> far out of a ~0.6x0.3 deg field
    ]
    objs = objects_in_field(wcs, (1080, 1920), rows=rows)
    names = [o.name for o in objs]
    assert "NGC A" in names and "NGC B" not in names
    a = next(o for o in objs if o.name == "NGC A")
    assert abs(a.x - 960) < 2 and abs(a.y - 540) < 2      # centre pixel


def test_identify_target_picks_largest():
    objs = [
        CatalogObject("NGC A", "Alpha", 100.0, 0.0, 5.0, 900, 540),
        CatalogObject("NGC B", "Beta", 100.0, 0.0, 40.0, 1000, 540),
    ]
    assert identify_target(objs, (1080, 1920)) == "NGC B · Beta"
    assert identify_target([], (1080, 1920)) == ""
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_catalog.py -v`
Expected: FAIL (module missing).

- [ ] **Step 4: Implement**

Create `nocturne/core/catalog.py`:
```python
"""Bundled OpenNGC deep-sky catalogue: load rows and project them through a
plate-solved WCS to place annotation labels."""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from ..tools.astap import FITS_Y_DOWN

_DATA = os.path.join(os.path.dirname(__file__), "..", "data", "openngc.csv")


@dataclass
class CatalogObject:
    name: str
    common: str
    ra_deg: float
    dec_deg: float
    major_arcmin: float
    x: float
    y: float


@lru_cache(maxsize=1)
def load_catalog(path: str = _DATA):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                rows.append((r["name"], r.get("common", ""), float(r["ra_deg"]),
                             float(r["dec_deg"]), float(r.get("major_arcmin") or 0.0)))
            except (ValueError, KeyError):
                continue
    return rows


def objects_in_field(wcs, shape, rows=None) -> list[CatalogObject]:
    rows = load_catalog() if rows is None else rows
    h, w = shape
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    out = []
    for name, common, ra, dec, major in rows:
        try:
            x, y = wcs.world_to_pixel(SkyCoord(ra * u.deg, dec * u.deg))
        except Exception:
            continue
        x = float(x)
        y = float(h - 1 - y) if FITS_Y_DOWN else float(y)   # -> top-row-first display
        if 0 <= x < w and 0 <= y < h and np.isfinite(x) and np.isfinite(y):
            out.append(CatalogObject(name, common, ra, dec, major, x, y))
    return out


def identify_target(objects: list[CatalogObject], shape) -> str:
    if not objects:
        return ""
    h, w = shape
    cx, cy = w / 2, h / 2
    best = max(objects, key=lambda o: (o.major_arcmin, -((o.x - cx) ** 2 + (o.y - cy) ** 2)))
    return f"{best.name} · {best.common}" if best.common else best.name
```
**Note on the y-flip:** `objects_in_field` converts to top-row-first display coords. The test uses `FITS_Y_DOWN=True`, so centre maps to `y = 1080-1-540 = 539` (≈540, within tolerance). If the Task 2 spike sets `FITS_Y_DOWN=False`, the same test still passes at centre (symmetric); off-centre objects confirm the direction during real-data validation.

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/core/test_catalog.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nocturne/core/catalog.py nocturne/data/openngc.csv NOTICE tests/core/test_catalog.py
git commit -m "feat(catalog): bundled OpenNGC + project objects into a solved field"
```

---

## Task 5: Annotation geometry (`core/annotate.py`)

**Files:**
- Create: `nocturne/core/annotate.py`
- Test: `tests/core/test_annotate.py`

**Interfaces:**
- Consumes: an `astropy.wcs.WCS`, `shape=(H, W)`, `pixscale_arcsec: float`; `FITS_Y_DOWN`.
- Produces:
  - `compass_angles(wcs, shape) -> tuple[float, float]` → screen angles in degrees (0 = +x/right, 90 = down, matching Qt's y-down screen) for **North** and **East** directions at frame centre.
  - `scale_bar(pixscale_arcsec, width_px) -> tuple[int, str]` → `(length_px, label)` for a "nice" round angular length (from `[1,2,5,10,15,30,60,120] arcmin`) closest to ~20% of the image width; label like `"30′"` or `"1°"`.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_annotate.py`:
```python
import numpy as np
from astropy.wcs import WCS
from nocturne.core.annotate import compass_angles, scale_bar


def _wcs(w=1920, h=1080, scale=0.0005556):
    wc = WCS(naxis=2)
    wc.wcs.crpix = [w / 2, h / 2]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-scale, 0], [0, scale]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wc


def test_compass_north_points_up_for_standard_wcs():
    # Standard astro orientation (N up, E left) with FITS_Y_DOWN flip -> on a
    # top-row-first display, North points UP (screen angle ~ -90 / 270).
    n, e = compass_angles(_wcs(), (1080, 1920))
    assert abs(((n % 360) - 270) % 360) < 15 or abs((n % 360) - 270) < 15
    # East is ~90 deg from North
    assert abs(((e - n) % 360) - 90) < 20 or abs(((n - e) % 360) - 90) < 20


def test_scale_bar_picks_round_length():
    length_px, label = scale_bar(2.0, 1920)   # 2 arcsec/px -> 1920 px = 64 arcmin
    # ~20% of 1920 = 384 px = ~12.8 arcmin -> nearest nice = 15 arcmin -> 450 px
    assert label in ("15′", "10′")
    assert 250 < length_px < 500
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_annotate.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

Create `nocturne/core/annotate.py`:
```python
"""Overlay geometry: compass (N/E screen directions) and a round scale bar,
derived from a plate-solved WCS. Pure math, no Qt."""
from __future__ import annotations

import numpy as np

from ..tools.astap import FITS_Y_DOWN

_NICE_ARCMIN = [1, 2, 5, 10, 15, 30, 60, 120]


def _screen_xy(wcs, ra, dec, h):
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    x, y = wcs.world_to_pixel(SkyCoord(ra * u.deg, dec * u.deg))
    return float(x), (float(h - 1 - y) if FITS_Y_DOWN else float(y))


def compass_angles(wcs, shape) -> tuple[float, float]:
    """Screen angles (deg, 0=+x, 90=down) of North and East at frame centre."""
    h, w = shape
    ra0, dec0 = wcs.wcs.crval
    x0, y0 = _screen_xy(wcs, ra0, dec0, h)
    d = 0.05  # degrees step
    xn, yn = _screen_xy(wcs, ra0, dec0 + d, h)                  # North
    xe, ye = _screen_xy(wcs, ra0 + d / np.cos(np.radians(dec0)), dec0, h)  # East
    north = float(np.degrees(np.arctan2(yn - y0, xn - x0)))
    east = float(np.degrees(np.arctan2(ye - y0, xe - x0)))
    return north % 360, east % 360


def scale_bar(pixscale_arcsec: float, width_px: int) -> tuple[int, str]:
    target_arcmin = (width_px * 0.20 * pixscale_arcsec) / 60.0
    nice = min(_NICE_ARCMIN, key=lambda a: abs(a - target_arcmin))
    length_px = int(round(nice * 60.0 / pixscale_arcsec))
    label = f"{nice // 60}°" if nice >= 60 and nice % 60 == 0 else f"{nice}′"
    return length_px, label
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/core/test_annotate.py -v`
Expected: PASS. (If the compass assertion is direction-sensitive to `FITS_Y_DOWN`, the test's tolerant `or` handles both; real-data validation confirms N visually.)

- [ ] **Step 5: Commit**

```bash
git add nocturne/core/annotate.py tests/core/test_annotate.py
git commit -m "feat(annotate): compass + scale-bar geometry from a solved WCS"
```

---

## Task 6: Annotation overlay widget (`ui/annotation_overlay.py` + `ImageView.set_annotations`)

**Files:**
- Create: `nocturne/ui/annotation_overlay.py`
- Modify: `nocturne/ui/image_view.py` (add `set_annotations`, mirror `set_compare`/crop-overlay teardown ~353–359)
- Test: `tests/ui/test_annotation_overlay.py`

**Interfaces:**
- Consumes: `list[CatalogObject]` (Task 4), `compass_angles`/`scale_bar` (Task 5), `shape`.
- Produces:
  - `build_annotation_group(objects, north_angle, scale_len_px, scale_label, shape, theme) -> QGraphicsItemGroup` — a group with: one text label per object anchored at `(o.x, o.y)`; a small compass (N arrow at `north_angle`) pinned near a corner; a scale bar + label near the bottom. All child items flagged `QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations` for constant on-screen size. Items in **scene = display-pixel coords**.
  - `ImageView.set_annotations(self, group: QGraphicsItemGroup | None) -> None` — remove any existing annotation group, add the new one at a Z below the crop handles (e.g. z=8), store on `self._annotations`.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_annotation_overlay.py`:
```python
import pytest
pytest.importorskip("PySide6")
import numpy as np
from nocturne.core.catalog import CatalogObject
from nocturne.ui.annotation_overlay import build_annotation_group


def test_group_has_a_label_per_object(qtbot):
    objs = [CatalogObject("NGC 7000", "North America", 314.0, 44.0, 120.0, 960, 540),
            CatalogObject("NGC 6997", "", 314.5, 44.5, 8.0, 1200, 400)]
    g = build_annotation_group(objs, north_angle=270.0, scale_len_px=300,
                               scale_label="30′", shape=(1080, 1920), theme="dark")
    # every object contributes at least one child (its label); plus compass + scale
    assert len(g.childItems()) >= len(objs) + 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_annotation_overlay.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement the overlay builder**

Create `nocturne/ui/annotation_overlay.py`:
```python
"""Builds the annotation overlay (DSO labels + compass + scale bar) as a
QGraphicsItemGroup in image-pixel (scene) coordinates. Child items ignore the
view transform so they stay constant size under zoom/pan."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsItemGroup, QGraphicsLineItem,
                               QGraphicsSimpleTextItem)

_IGNORE = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations


def _text(s, color):
    t = QGraphicsSimpleTextItem(s)
    t.setBrush(QColor(color))
    f = QFont(); f.setPointSizeF(10.0); t.setFont(f)
    t.setFlag(_IGNORE, True)
    return t


def build_annotation_group(objects, north_angle, scale_len_px, scale_label,
                           shape, theme="dark") -> QGraphicsItemGroup:
    color = "#e7ebf3" if theme == "dark" else "#161c27"
    accent = "#5b9cf0"
    g = QGraphicsItemGroup()
    h, w = shape

    for o in objects:
        label = _text(f"{o.name}" + (f"  {o.common}" if o.common else ""), color)
        label.setPos(o.x + 6, o.y + 6)                 # anchored on the object
        g.addToGroup(label)
        dot = QGraphicsLineItem(o.x, o.y, o.x, o.y)    # a marker point
        dot.setPen(QPen(QColor(accent), 3)); dot.setFlag(_IGNORE, True)
        g.addToGroup(dot)

    # compass: a short N line from a fixed corner anchor
    ax, ay = w - 90, 90
    rad = math.radians(north_angle)
    n = QGraphicsLineItem(ax, ay, ax + 40 * math.cos(rad), ay + 40 * math.sin(rad))
    n.setPen(QPen(QColor(accent), 2)); n.setFlag(_IGNORE, True)
    g.addToGroup(n)
    nlab = _text("N", accent); nlab.setPos(ax + 44 * math.cos(rad), ay + 44 * math.sin(rad))
    g.addToGroup(nlab)

    # scale bar near the bottom-left
    bx, by = 80, h - 80
    bar = QGraphicsLineItem(bx, by, bx + scale_len_px, by)
    bar.setPen(QPen(QColor(color), 2)); bar.setFlag(_IGNORE, True)
    g.addToGroup(bar)
    slab = _text(scale_label, color); slab.setPos(bx, by - 20)
    g.addToGroup(slab)
    return g
```
**Note:** the scale-bar line is in scene coords, so its on-screen length is only correct at 1:1 zoom. If zoom-invariant *bar length* matters later, recompute on zoom — deferred; at fit-zoom (the default) it reads correctly. Labels/compass are already constant-size via `_IGNORE`.

- [ ] **Step 4: Add `set_annotations` to `ImageView`**

In `nocturne/ui/image_view.py`, in `__init__` add `self._annotations = None`, and add:
```python
    def set_annotations(self, group):
        if self._annotations is not None:
            self._scene.removeItem(self._annotations)
            self._annotations = None
        if group is not None:
            group.setZValue(8)
            self._scene.addItem(group)
            self._annotations = group
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_annotation_overlay.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nocturne/ui/annotation_overlay.py nocturne/ui/image_view.py tests/ui/test_annotation_overlay.py
git commit -m "feat(ui): annotation overlay group + ImageView.set_annotations"
```

---

## Task 7: Settings dialog — ASTAP row + Test

**Files:**
- Modify: `nocturne/ui/settings_dialog.py` (fields ~50–55, rows ~63–66, test handlers ~85–89, `result_settings` ~91–98)
- Test: `tests/ui/test_settings_dialog.py` (add case; create if absent)

**Interfaces:**
- Consumes: `Settings.astap_path`, `resolve_binary`, `probe_binary` (existing).
- Produces: the dialog reads/writes `astap_path`; a Test button reports validity.

**Note on Test:** ASTAP has no reliable exit-0 `--version`/`--help`. v1 Test = existence/executable check via `astap_valid`, surfaced as an ok/not-ok message (do **not** run a full solve). If the implementer confirms a clean exit-0 probe arg exists for the installed ASTAP, `probe_binary` may be used instead.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_settings_dialog.py`:
```python
import pytest
pytest.importorskip("PySide6")


def test_settings_dialog_round_trips_astap_path(qtbot):
    from nocturne.ui.settings_dialog import SettingsDialog
    from nocturne.settings import Settings
    dlg = SettingsDialog(Settings(astap_path="/opt/astap/astap"))
    qtbot.addWidget(dlg)
    assert dlg.result_settings().astap_path == "/opt/astap/astap"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_settings_dialog.py -k astap -v`
Expected: FAIL (`result_settings` drops `astap_path`, resets to "").

- [ ] **Step 3: Implement**

In `nocturne/ui/settings_dialog.py`:
- Add the field near `self._gx`/`self._rc`:
```python
        self._astap = QLineEdit(settings.astap_path)
        self._astap_result = QLabel("")
```
- Add a form row near the others:
```python
        form.addRow("ASTAP (optional)", _path_row(self._astap, self._test_astap, self._astap_result))
```
- Add the test handler near `_test_rcastro`:
```python
    def _test_astap(self):
        from ..settings import astap_valid, Settings
        ok = astap_valid(Settings(astap_path=self._astap.text().strip()))
        self._astap_result.setText("✓ Found ASTAP" if ok else "✗ Not found")
```
- Add to the `Settings(...)` returned by `result_settings`:
```python
            astap_path=self._astap.text().strip(),
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_settings_dialog.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/settings_dialog.py tests/ui/test_settings_dialog.py
git commit -m "feat(ui): ASTAP path row + Test in Settings"
```

---

## Task 8: Main-window integration (toolbar, async solve, cache, target line, chip, toggle)

**Files:**
- Modify: `nocturne/ui/main_window.py` (toolbar ~409–412; new handlers; `_update_tools_label` ~436–447; `_rebuild_panel` ~1463–1465)
- Test: `tests/ui/test_main_window.py` (add cases)

**Interfaces:**
- Consumes: `astap_valid`, `ASTAP`/`SolveResult`/`hint_from_metadata` (Task 2), `objects_in_field`/`identify_target` (Task 4), `compass_angles`/`scale_bar` (Task 5), `build_annotation_group` + `ImageView.set_annotations` (Task 6).
- Produces: `_open_plate_solve` (toolbar handler), `_solve_current()` returning `(SolveResult, objects)`, `self._solve` cache keyed by an image signature, `metadata["target_solved"]` populated, an `ASTAP ✓/✗` status chip.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_main_window.py`:
```python
def test_plate_solve_sets_target_and_overlay(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.settings.astap_path = str(tmp_path / "astap"); (tmp_path / "astap").write_text("x")

    # Fake a solve: a WCS centred on the frame + one catalogue object dead-centre.
    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    from nocturne.core.catalog import CatalogObject
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    monkeypatch.setattr(win, "_solve_current",
                        lambda: (SolveResult(True, wc, 100.0, 0.0, 3.6),
                                 [CatalogObject("NGC 7000", "North America", 100.0, 0.0, 120.0, 12, 12)]))
    win._open_plate_solve()
    assert win.project.current().metadata.get("target_solved", "").startswith("NGC 7000")
    assert win.image_view._annotations is not None            # overlay shown
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -k plate_solve -v`
Expected: FAIL (`_open_plate_solve`/`_solve_current` missing).

- [ ] **Step 3: Implement**

In `nocturne/ui/main_window.py`:
- Toolbar (near the other tool actions ~409–412):
```python
        tb.addAction(load_icon("haoiii", ACCENT), "Plate Solve…", self._open_plate_solve)
```
- `__init__`: `self._solve = None  # (sig, SolveResult, objects)`.
- Add the handlers:
```python
    def _solve_current(self):
        """Blocking solve of the current display image; returns (SolveResult, objects)."""
        from ..tools.astap import ASTAP, hint_from_metadata
        from ..core.catalog import objects_in_field
        img = self.project.current()
        meta = img.metadata
        h, w = img.data.shape[:2]
        # FOV from focal length + pixel size if known.
        fov = None
        fl, px = meta.get("focal_length"), meta.get("pixel_size")
        if fl and px:
            fov = (206.265 * float(px) / float(fl)) * h / 3600.0
        hint = hint_from_metadata(meta)
        ra_h, dec_d = hint if hint else (None, None)
        res = ASTAP(resolve_binary(self.settings.astap_path)).solve(
            img, fov_deg=fov, ra_hours=ra_h, dec_deg=dec_d)
        objs = objects_in_field(res.wcs, (h, w)) if res.solved else []
        return res, objs

    def _open_plate_solve(self):
        if self.project is None:
            return
        if not astap_valid(self.settings):
            self._status.setText("Set the ASTAP path in Settings to plate-solve.")
            return
        sig = self._sr_sig(self.project.current())
        if self._solve and self._solve[0] == sig:          # cached: toggle overlay
            if self.image_view._annotations is not None:
                self.image_view.set_annotations(None)
            else:
                self._show_annotations(*self._solve[1:])
            return
        self._status.setText("Plate-solving…")
        self._run_busy(self._solve_current,
                       lambda r: self._on_solved(sig, *r),
                       "Plate-solving…", "Plate-solve failed")

    def _on_solved(self, sig, res, objs):
        if not res.solved:
            self._status.setText("Couldn't plate-solve this image — try after Stretch, "
                                 "or check the field isn't mostly empty.")
            return
        self._solve = (sig, res, objs)
        from ..core.catalog import identify_target
        h, w = self.project.current().data.shape[:2]
        name = identify_target(objs, (h, w))
        if name:
            self.project.current().metadata["target_solved"] = name
        self._status.setText("")
        self._show_annotations(res, objs)
        self._rebuild_panel()                               # refresh Target line

    def _show_annotations(self, res, objs):
        from ..core.annotate import compass_angles, scale_bar
        from .annotation_overlay import build_annotation_group
        h, w = self.project.current().data.shape[:2]
        north, _east = compass_angles(res.wcs, (h, w))
        length, label = scale_bar(res.pixscale_arcsec, w)
        theme = "dark"
        self.image_view.set_annotations(
            build_annotation_group(objs, north, length, label, (h, w), theme))
```
- Status chip: in `_update_tools_label`, add an ASTAP chip alongside GraXpert/RC-Astro using `astap_valid(self.settings)` (copy the existing `chip(name, ok)` call pattern).
- Import `astap_valid`: ensure `from ..settings import ... astap_valid ...` is present (the module already imports `rcastro_valid`, `resolve_binary`).
- **Invalidate the overlay when the image changes:** the cache is keyed by `_sr_sig`; on any nav/apply that calls `_refresh`, if `self.image_view._annotations is not None` and the current signature ≠ `self._solve[0]`, call `self.image_view.set_annotations(None)`. Add that guard at the end of `_refresh`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -v`
Expected: PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat(ui): Plate Solve toolbar action — solve, target ID, annotation toggle, chip"
```

---

## Task 9: Export — burn annotations (PNG) + FITS WCS header

**Files:**
- Modify: `nocturne/ui/step_panels.py` (export branch ~557–573), `nocturne/ui/main_window.py` (`export_final` ~1337–1387), `nocturne/core/export.py` (`save_fits` already takes `header`)
- Test: `tests/ui/test_main_window.py` (add case)

**Interfaces:**
- Consumes: `self._solve` cache (Task 8), `save_fits(img, path, header=...)` (existing).
- Produces: `w.burn_annotations` checkbox; PNG export renders the overlay in; FITS export writes solved WCS keys.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_main_window.py`:
```python
def test_export_fits_writes_wcs_when_solved(qtbot, tmp_path, monkeypatch):
    from astropy.io import fits
    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    win._solve = (win._sr_sig(win.project.current()), SolveResult(True, wc, 100.0, 0.0, 3.6), [])
    out = tmp_path / "out.fits"
    monkeypatch.setattr("nocturne.ui.main_window.QFileDialog.getSaveFileName",
                        lambda *a, **k: (str(out), ""))
    win.export_final("FITS")
    qtbot.waitUntil(lambda: out.exists(), timeout=3000)
    assert "CRVAL1" in fits.getheader(str(out))
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -k export_fits_writes_wcs -v`
Expected: FAIL (no WCS header written).

- [ ] **Step 3: Implement**

- `nocturne/ui/step_panels.py` export branch: add
```python
        w.burn_annotations = QCheckBox("Burn annotations (PNG)")
        w.burn_annotations.setEnabled(False)   # main_window enables when a solve exists
        lay.addWidget(w.burn_annotations)
```
- `nocturne/ui/main_window.py` `export_final`:
  - In the FITS branch, when `self._solve` matches the current signature, build a header dict from the solved WCS and pass it: `header = dict(self._solve[1].wcs.to_header()) if self._solve else None` → `save_fits(img, path, header=header)`.
  - In the standard branch, for `fmt == "PNG"` when `w.burn_annotations.isChecked()` and a solve matches the current signature: build the annotation group the same way `_show_annotations` does (recompute `compass_angles` + `scale_bar` from `self._solve[1]`, then `build_annotation_group(...)`), then render offscreen and save. Concrete method:
```python
    from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem
    from PySide6.QtGui import QImage, QPixmap, QPainter
    base = to_qimage(img)                              # display-space QImage
    scene = QGraphicsScene()
    scene.addItem(QGraphicsPixmapItem(QPixmap.fromImage(base)))
    scene.addItem(group)                               # the annotation group (scene = pixel coords)
    out = QImage(base.size(), QImage.Format.Format_ARGB32)
    painter = QPainter(out)
    scene.render(painter, target=out.rect(), source=scene.itemsBoundingRect())
    painter.end()
    out.save(path)                                     # 8-bit annotated PNG
```
  (To avoid re-parenting the live overlay, build a fresh group for export rather than reusing the one on the view.)
  - When rebuilding the export panel, enable `burn_annotations` iff `self._solve` matches the current signature.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/step_panels.py nocturne/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat(export): burn annotations into PNG; write WCS into exported FITS"
```

---

## Task 10: Packaging — hidden imports + bundle the catalogue

**Files:**
- Modify: `packaging/nocturne.spec` (hiddenimports ~16, datas ~collect area)

**Interfaces:** none (build config). Verified by a frozen-app smoke test.

- [ ] **Step 1: Implement**

In `packaging/nocturne.spec`:
- Ensure `from PyInstaller.utils.hooks import collect_submodules` is imported.
- Extend hidden imports:
```python
hiddenimports += collect_submodules("astropy.wcs") + collect_submodules("astropy.coordinates")
```
- Add the catalogue to `datas`:
```python
datas += [("../nocturne/data/openngc.csv", "nocturne/data")]
```
(Match the spec's existing `datas`/`hiddenimports` assignment style.)

- [ ] **Step 2: Verify the frozen bundle (manual)**

Build and smoke-test:
```bash
.venv/bin/python -m PyInstaller packaging/nocturne.spec --noconfirm
./dist/Nocturne.app/Contents/MacOS/Nocturne  # launches; open an image, run Plate Solve with ASTAP configured
```
Expected: app launches; `astropy.wcs`/`coordinates` import (no ModuleNotFound); `openngc.csv` loads (no FileNotFound). Confirm no matplotlib is pulled into the bundle (`du -sh dist/Nocturne.app` in the same ballpark as before).

- [ ] **Step 3: Commit**

```bash
git add packaging/nocturne.spec
git commit -m "build: bundle openngc.csv + astropy.wcs/coordinates hidden imports"
```

---

## Post-plan: real-data validation (user)

After the tasks land, validate on a real Seestar frame with ASTAP + D05 installed:
1. Solve identifies the correct target in the Import panel.
2. Annotation labels sit on the right objects; **North points the right way** (confirms `FITS_Y_DOWN`); scale bar reads plausibly.
3. Re-solve after a Crop/Rotate keeps labels correct (WYSIWYG).
4. PNG burn-in and FITS-with-WCS export both open correctly elsewhere (e.g. the FITS solves/loads in Siril).

If North is mirrored, flip `FITS_Y_DOWN` in `nocturne/tools/astap.py` and re-check (the one real-data-dependent constant).
