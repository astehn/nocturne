# Transparent Stacking Frame Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the over-aggressive 3×raw-MAD frame rejection with a Siril-style iterative k-sigma judge that explains every verdict in plain language, plus a transparent stack-dialog UX (verdict column, autostretched preview, strictness knob, human status line, informative master filename).

**Architecture:** Split grading into an expensive `measure` phase (sep photometry, run once per folder) and a cheap `judge` phase (thresholds, re-runnable instantly when strictness changes). Verdicts carry machine codes + human reason strings so the UI never re-derives *why*. The dialog grows a Verdict column, a preview pane, a strictness dropdown, and auto-derives the master filename from the selection.

**Tech Stack:** Python 3.13 (`.venv/bin/python`), numpy, sep, astropy (via existing `fits_io`), PySide6, pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-07-17-stacking-grading-design.md`

## Global Constraints

- Run tests with `.venv/bin/python -m pytest <path> -q` from `/Volumes/Work/Code/Editor`.
- `FrameStats` is constructed **positionally with 6 args** in existing tests (`FrameStats(path, 100, 3.0, 0.02, score, included)`) — every new field MUST have a default so those calls keep working.
- `grade_frames(paths, on_progress=None)` is also used by `ui/haoiii_dialog.py` — its signature stays backward compatible (new args keyword-with-default only).
- Reason strings are exact copy (used in UI and tests):
  - clouds: `"Very few stars — likely clouds or trailing"`
  - soft: `"Stars softer than the rest of the session"`
  - sky warning: `"Brighter sky (twilight, moon or light pollution) — kept"`
  - measure failure: `"Couldn't measure this frame — excluded"`
- Strictness → k mapping: `{"relaxed": 4.0, "normal": 3.0, "strict": 2.0}`, default `"normal"`. k scales the FWHM and background gates only; the 50%-of-median cloud gate is fixed.
- Colours come from `nocturne/ui/theme.py` tokens: `WARNING` (amber `#e3b341`), `TEXT_FAINT` (`#5e636b`).
- Commit after every task with the trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Judge engine — verdict fields, iterative k-sigma gate, `judge()`

**Files:**
- Modify: `nocturne/stacking/grade.py`
- Test: `tests/stacking/test_grade.py`

**Interfaces:**
- Consumes: nothing new (pure functions over `FrameStats`).
- Produces (later tasks rely on these exact names):
  - `FrameStats` gains defaulted fields: `exposure: float = 0.0`, `target: str = ""`, `reason_code: str = ""`, `reason: str = ""`, `warning: str = ""`, `error: bool = False`.
  - `STRICTNESS_K: dict[str, float]` module constant.
  - `REASON_CLOUDS`, `REASON_SOFT`, `WARN_SKY`, `REASON_MEASURE` module string constants (values in Global Constraints).
  - `upper_gate(values: list[float], k: float) -> float` — iterative one-tailed median + k×SD.
  - `judge(stats: list[FrameStats], strictness: str = "normal") -> None` — mutates `included`/`reason_code`/`reason`/`warning` in place.

- [ ] **Step 1: Write the failing tests**

Append to `tests/stacking/test_grade.py`:

```python
from nocturne.stacking.grade import (
    REASON_CLOUDS, REASON_MEASURE, REASON_SOFT, WARN_SKY,
    FrameStats, judge, upper_gate,
)


def _fs(path="f.fit", stars=800, fwhm=2.5, bg=1200.0, included=True):
    return FrameStats(path, stars, fwhm, bg, 0.5, included)


def test_upper_gate_simple_median_plus_k_sd():
    # No values above the gate -> single pass: median 2.5, SD of [2,2.5,3]
    vals = [2.0, 2.5, 3.0]
    import numpy as np
    expected = 2.5 + 3.0 * float(np.asarray(vals).std())
    assert upper_gate(vals, 3.0) == pytest.approx(expected)


def test_upper_gate_iterates_until_stable():
    # One catastrophic outlier inflates SD; after it is clipped the gate
    # tightens and must be recomputed from the surviving values.
    vals = [2.0] * 20 + [2.1] * 20 + [50.0]
    gate = upper_gate(vals, 3.0)
    assert gate < 10.0          # outlier no longer poisons the statistics
    assert gate > 2.1           # but normal frames stay under the gate


def test_judge_tight_distribution_rejects_nothing():
    # The property the old 3xMAD code failed: uniformly good, tightly
    # clustered sessions must keep every frame.
    stats = [_fs(path=f"f{i}.fit", stars=800 + i, fwhm=2.4 + 0.01 * i,
                 bg=1200.0 + i) for i in range(50)]
    judge(stats)
    assert all(s.included for s in stats)
    assert all(s.reason == "" for s in stats)


def test_judge_rejects_star_collapse_as_clouds():
    stats = [_fs(path=f"f{i}.fit") for i in range(20)]
    stats.append(_fs(path="cloudy.fit", stars=300))   # < 50% of median 800
    judge(stats)
    bad = stats[-1]
    assert bad.included is False
    assert bad.reason_code == "clouds"
    assert bad.reason.startswith(REASON_CLOUDS)


def test_judge_rejects_soft_fwhm_with_detail():
    stats = [_fs(path=f"f{i}.fit", fwhm=2.4 + 0.001 * i) for i in range(30)]
    stats.append(_fs(path="soft.fit", fwhm=6.0))
    judge(stats)
    bad = stats[-1]
    assert bad.included is False
    assert bad.reason_code == "soft_stars"
    assert bad.reason.startswith(REASON_SOFT)
    assert "6.0" in bad.reason        # measured value visible to the user


def test_judge_bright_sky_warns_but_keeps():
    stats = [_fs(path=f"f{i}.fit", bg=1200.0 + i) for i in range(30)]
    stats.append(_fs(path="twilight.fit", bg=2400.0))
    judge(stats)
    bright = stats[-1]
    assert bright.included is True
    assert bright.warning == WARN_SKY
    assert bright.reason == ""


def test_judge_strictness_relaxed_keeps_more_than_strict():
    stats = [_fs(path=f"f{i}.fit", fwhm=2.4) for i in range(30)]
    stats.append(_fs(path="edge.fit", fwhm=2.9))
    judge(stats, strictness="strict")
    strict_included = stats[-1].included
    judge(stats, strictness="relaxed")
    relaxed_included = stats[-1].included
    assert (not strict_included) or relaxed_included  # relaxed never harsher


def test_judge_under_five_frames_keeps_all():
    stats = [_fs(path=f"f{i}.fit", stars=100 * (i + 1)) for i in range(4)]
    judge(stats)
    assert all(s.included for s in stats)


def test_judge_skips_error_frames_and_leaves_them_excluded():
    stats = [_fs(path=f"f{i}.fit") for i in range(10)]
    broken = FrameStats("bad.fit", 0, 0.0, 0.0, 0.0, False,
                        reason_code="measure_failed", reason=REASON_MEASURE,
                        error=True)
    stats.append(broken)
    judge(stats)
    assert broken.included is False
    assert broken.reason == REASON_MEASURE
    # its zero FWHM/bg must not have polluted the gates:
    assert all(s.included for s in stats[:-1])
```

Also add `import pytest` at the top of the file if not present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/stacking/test_grade.py -q`
Expected: FAIL / ERROR with `ImportError: cannot import name 'judge'`.

- [ ] **Step 3: Implement in `nocturne/stacking/grade.py`**

Replace the `FrameStats` dataclass and add the constants/functions (keep `_measure`, `grade_frame`, `_mad`, `grade_frames` for now — Task 2 reworks them):

```python
STRICTNESS_K = {"relaxed": 4.0, "normal": 3.0, "strict": 2.0}

REASON_CLOUDS = "Very few stars — likely clouds or trailing"
REASON_SOFT = "Stars softer than the rest of the session"
WARN_SKY = "Brighter sky (twilight, moon or light pollution) — kept"
REASON_MEASURE = "Couldn't measure this frame — excluded"


@dataclass
class FrameStats:
    path: str
    star_count: int
    fwhm: float
    background: float
    score: float
    included: bool
    exposure: float = 0.0
    target: str = ""
    reason_code: str = ""   # "clouds" | "soft_stars" | "measure_failed" | ""
    reason: str = ""        # human-readable, non-empty iff rejected
    warning: str = ""       # human-readable, kept-with-warning (bright sky)
    error: bool = False     # measurement failed; excluded from statistics


def upper_gate(values: list[float], k: float) -> float:
    """Siril-style one-tailed gate: median + k*SD, iteratively recomputed
    after clipping values above the gate, until stable. Clipped frames no
    longer pollute the statistics, so one catastrophic frame can't widen
    the gate for everyone else."""
    vals = np.asarray(values, dtype=float)
    while True:
        gate = float(np.median(vals) + k * vals.std())
        keep = vals <= gate
        if keep.all() or keep.sum() < 3:
            return gate
        vals = vals[keep]


def judge(stats: list[FrameStats], strictness: str = "normal") -> None:
    """Apply verdicts in place. Cheap — re-run freely when strictness changes."""
    k = STRICTNESS_K[strictness]
    usable = [s for s in stats if not s.error]
    for s in usable:
        s.included, s.reason_code, s.reason, s.warning = True, "", "", ""
    if len(usable) < 5:
        return  # too few frames to grade reliably — keep everything

    star_floor = 0.5 * float(np.median([s.star_count for s in usable]))
    fwhm_gate = upper_gate([s.fwhm for s in usable], k)
    bg_gate = upper_gate([s.background for s in usable], k)

    for s in usable:
        if s.star_count < star_floor:
            s.included = False
            s.reason_code = "clouds"
            s.reason = (f"{REASON_CLOUDS} "
                        f"({s.star_count} stars vs session median {star_floor / 0.5:.0f})")
        elif s.fwhm > fwhm_gate:
            s.included = False
            s.reason_code = "soft_stars"
            s.reason = f"{REASON_SOFT} (FWHM {s.fwhm:.1f} vs limit {fwhm_gate:.1f})"
        elif s.background > bg_gate:
            s.warning = WARN_SKY
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/stacking/test_grade.py -q`
Expected: all PASS (the two pre-existing tests still pass — `grade_frames` untouched so far).

- [ ] **Step 5: Commit**

```bash
git add nocturne/stacking/grade.py tests/stacking/test_grade.py
git commit -m "feat(stacking): verdict fields + iterative k-sigma judge"
```

---

### Task 2: Measure phase — exposure/target capture, error handling, `grade_frames` rewired

**Files:**
- Modify: `nocturne/stacking/grade.py`
- Test: `tests/stacking/test_grade.py`

**Interfaces:**
- Consumes: `judge`, `REASON_MEASURE` from Task 1; `load_sub`/`luminance` from `stacking/frames.py` (`load_sub(path, normalize=False).metadata` has keys `"exposure"` and `"target"` via `fits_io`).
- Produces:
  - `grade_frame(path) -> FrameStats` — now fills `exposure`/`target`; on any exception returns an `error=True` stats with `reason_code="measure_failed"`, `reason=REASON_MEASURE`, `included=False`.
  - `grade_frames(paths, on_progress=None, strictness="normal") -> list[FrameStats]` — measures, normalizes scores, calls `judge`, sorts worst→best (unchanged external behaviour otherwise).

- [ ] **Step 1: Write the failing tests**

Append to `tests/stacking/test_grade.py`:

```python
def test_grade_frame_captures_exposure_and_target(tmp_path):
    p = tmp_path / "s.fit"
    write_color_fits(p, make_star_field(n_stars=25, seed=3))  # exptime=10.0
    stats = grade_frame(str(p))
    assert stats.exposure == pytest.approx(10.0)
    assert stats.error is False


def test_grade_frame_unreadable_returns_error_verdict(tmp_path):
    p = tmp_path / "garbage.fit"
    p.write_bytes(b"this is not a FITS file")
    stats = grade_frame(str(p))
    assert stats.error is True
    assert stats.included is False
    assert stats.reason == REASON_MEASURE
    assert stats.reason_code == "measure_failed"


def test_grade_frames_strictness_kwarg(tmp_path):
    paths = []
    for i in range(6):
        p = tmp_path / f"g{i}.fit"
        write_color_fits(p, make_star_field(n_stars=30, seed=i, bg=0.02))
        paths.append(str(p))
    graded = grade_frames(paths, strictness="relaxed")
    assert all(s.included for s in graded)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/stacking/test_grade.py -q`
Expected: the two new `grade_frame` tests FAIL (`exposure` is 0.0 / exception propagates).

- [ ] **Step 3: Implement**

In `nocturne/stacking/grade.py`, replace `grade_frame` and `grade_frames`:

```python
def grade_frame(path: str) -> FrameStats:
    try:
        img = load_sub(path, normalize=False)
        star_count, fwhm, background = _measure(luminance(img.data))
    except Exception:
        return FrameStats(path, 0, 0.0, 0.0, 0.0, False,
                          reason_code="measure_failed", reason=REASON_MEASURE,
                          error=True)
    score = star_count * (1.0 / (1.0 + fwhm)) * (1.0 / (1.0 + background * 10.0))
    return FrameStats(path, star_count, fwhm, background, float(score), True,
                      exposure=float(img.metadata.get("exposure", 0.0) or 0.0),
                      target=str(img.metadata.get("target") or ""))


def grade_frames(paths: list[str], on_progress=None,
                 strictness: str = "normal") -> list[FrameStats]:
    stats: list[FrameStats] = []
    n = len(paths)
    for i, path in enumerate(paths):
        stats.append(grade_frame(path))
        if on_progress is not None:
            on_progress(i + 1, n, os.path.basename(path))

    best = max((s.score for s in stats), default=1.0) or 1.0
    for s in stats:
        s.score = s.score / best
    judge(stats, strictness)
    stats.sort(key=lambda s: s.score)  # worst -> best
    return stats
```

Delete the now-unused `_mad` helper.

- [ ] **Step 4: Run the full stacking + UI test files**

Run: `.venv/bin/python -m pytest tests/stacking/ tests/ui/test_stack_dialog.py tests/ui/test_haoiii_dialog.py -q`
Expected: all PASS. (`test_grade_frames_flags_cloudy_outlier` must still pass: the 3-star cloudy frame is < 50% of the median star count → rejected as clouds.)

- [ ] **Step 5: Commit**

```bash
git add nocturne/stacking/grade.py tests/stacking/test_grade.py
git commit -m "feat(stacking): measure phase captures exposure/target, tolerates unreadable frames"
```

---

### Task 3: Informative master filename builder

**Files:**
- Modify: `nocturne/stacking/stacker.py`
- Test: `tests/stacking/test_stacker.py`

**Interfaces:**
- Consumes: nothing (pure function on primitives — deliberately not coupled to `FrameStats`).
- Produces: `master_filename(target: str, count: int, exposure_s: float, total_s: float) -> str` in `nocturne/stacking/stacker.py`. Examples: `("NGC 7000", 177, 20.0, 3540.0)` → `"NGC7000_177x20s_59min.fits"`; `("", 10, 0.0, 0.0)` → `"master_10frames.fits"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/stacking/test_stacker.py`:

```python
from nocturne.stacking.stacker import master_filename


def test_master_filename_full_info():
    assert master_filename("NGC 7000", 177, 20.0, 3540.0) == "NGC7000_177x20s_59min.fits"


def test_master_filename_sanitizes_target():
    assert master_filename("M 31 / Andromeda", 50, 10.0, 500.0) == \
        "M31Andromeda_50x10s_8min.fits"


def test_master_filename_no_target():
    assert master_filename("", 177, 20.0, 3540.0) == "master_177x20s_59min.fits"


def test_master_filename_no_exposure():
    assert master_filename("NGC 7000", 177, 0.0, 0.0) == "NGC7000_177frames.fits"


def test_master_filename_fractional_exposure():
    assert master_filename("Moon", 100, 0.5, 50.0) == "Moon_100x0.5s_1min.fits"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/stacking/test_stacker.py -q`
Expected: FAIL with `ImportError: cannot import name 'master_filename'`.

- [ ] **Step 3: Implement in `nocturne/stacking/stacker.py`**

Add near the top (after imports; add `import re` to the imports):

```python
def master_filename(target: str, count: int, exposure_s: float, total_s: float) -> str:
    """Descriptive default filename for a master, e.g. NGC7000_177x20s_59min.fits.
    Degrades gracefully as header info is missing; worst case master.fits."""
    obj = re.sub(r"[^A-Za-z0-9-]+", "", target or "") or "master"
    if exposure_s > 0:
        frames = f"{count}x{exposure_s:g}s"
    elif count > 0:
        frames = f"{count}frames"
    else:
        return f"{obj}.fits"
    minutes = f"{max(1, round(total_s / 60))}min" if total_s > 0 else ""
    parts = [obj, frames] + ([minutes] if minutes else [])
    return "_".join(parts) + ".fits"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/stacking/test_stacker.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/stacking/stacker.py tests/stacking/test_stacker.py
git commit -m "feat(stacking): descriptive master filename builder"
```

---

### Task 4: Dialog — Verdict column, row colouring, human status line

**Files:**
- Modify: `nocturne/ui/stack_dialog.py`
- Test: `tests/ui/test_stack_dialog.py`

**Interfaces:**
- Consumes: `FrameStats` verdict fields from Task 1 (`reason`, `warning`, `error`, `exposure`).
- Produces: table now has 6 columns `["Use", "File", "Stars", "FWHM", "Bg", "Verdict"]`; `_on_graded(stats)` behaviour later tasks extend; `_selection_summary() -> str` used by the status line and re-used in Task 5/6.

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/test_stack_dialog.py` (note the `_stats` helper there builds 6-arg `FrameStats`; extend it):

```python
def _stats2(path, score, included=True, reason="", warning="", exposure=20.0):
    s = FrameStats(path, 100, 3.0, 0.02, score, included)
    s.reason, s.warning, s.exposure = reason, warning, exposure
    return s


def test_verdict_column_shows_reasons_and_warnings(qtbot, tmp_path):
    for name in ("a.fit", "b.fit", "c.fit"):
        (tmp_path / name).write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": [
        _stats2(str(tmp_path / "a.fit"), 0.2, included=False,
                reason="Stars softer than the rest of the session (FWHM 3.5 vs limit 3.0)"),
        _stats2(str(tmp_path / "b.fit"), 0.8, warning="Brighter sky (twilight, moon or light pollution) — kept"),
        _stats2(str(tmp_path / "c.fit"), 0.9),
    ]
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 3, timeout=2000)
    assert dlg.table.columnCount() == 6
    assert "softer" in dlg.table.item(0, 5).text()
    assert "Brighter sky" in dlg.table.item(1, 5).text()
    assert dlg.table.item(2, 5).text() == "OK"


def test_status_line_speaks_minutes_of_light(qtbot, tmp_path):
    for i in range(4):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    stats = [_stats2(str(tmp_path / f"f{i}.fit"), 0.5 + 0.1 * i) for i in range(4)]
    stats[0].included = False
    stats[0].reason = "Very few stars — likely clouds or trailing"
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": stats
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 4, timeout=2000)
    # 3 of 4 kept x 20s = 1 of 1 minute
    assert "Keeping 3 of 4 frames" in dlg.status.text()
    assert "minute" in dlg.status.text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_stack_dialog.py -q`
Expected: the two new tests FAIL (5 columns; old status wording).

- [ ] **Step 3: Implement in `nocturne/ui/stack_dialog.py`**

1. In `__init__`, change the table construction:

```python
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Use", "File", "Stars", "FWHM", "Bg", "Verdict"])
```

2. Add imports at the top:

```python
from PySide6.QtGui import QColor

from . import theme
```

3. Replace `_on_graded` with:

```python
    def _on_graded(self, stats) -> None:
        self._set_busy(False)
        self._stats = stats
        self.table.setRowCount(len(stats))
        for row, s in enumerate(stats):
            check = QTableWidgetItem()
            check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked if s.included else Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, QTableWidgetItem(os.path.basename(s.path)))
            self.table.setItem(row, 2, QTableWidgetItem(str(s.star_count)))
            self.table.setItem(row, 3, QTableWidgetItem(f"{s.fwhm:.1f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{s.background:.3f}"))
            self.table.setItem(row, 5, QTableWidgetItem(self._verdict_text(s)))
            self._tint_row(row, s)
        self.status.setText(self._selection_summary())

    @staticmethod
    def _verdict_text(s) -> str:
        if s.reason:
            return s.reason
        if s.warning:
            return s.warning
        return "OK"

    def _tint_row(self, row: int, s) -> None:
        colour = None
        if s.reason:
            colour = QColor(theme.TEXT_FAINT)   # rejected: dimmed
        elif s.warning:
            colour = QColor(theme.WARNING)      # kept with warning: amber
        for col in range(1, self.table.columnCount()):
            item = self.table.item(row, col)
            if item is not None:
                item.setForeground(colour) if colour else item.setForeground(QColor(theme.TEXT))

    def _selection_summary(self) -> str:
        total = len(self._stats)
        kept = [s for s in self._stats if s.included]
        text = f"Keeping {len(kept)} of {total} frames"
        kept_s = sum(s.exposure for s in kept)
        all_s = sum(s.exposure for s in self._stats)
        if all_s > 0:
            unit = "minute" if round(all_s / 60) == 1 else "minutes"
            text += (f" — {max(1, round(kept_s / 60))} of "
                     f"{max(1, round(all_s / 60))} {unit} of light")
        if 0 < total < 5:
            text += " (too few frames to grade reliably — keeping all)"
        return text + "."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_stack_dialog.py -q`
Expected: all PASS (existing tests keep passing — they don't inspect column count or status wording; if `test_grading_fills_table`'s lambda signature lacks `strictness`, it still works since `grade()` passes none yet).

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/stack_dialog.py tests/ui/test_stack_dialog.py
git commit -m "feat(ui): verdict column, row tinting and human status line in stack dialog"
```

---

### Task 5: Dialog — strictness dropdown with override-preserving re-judge

**Files:**
- Modify: `nocturne/ui/stack_dialog.py`
- Test: `tests/ui/test_stack_dialog.py`

**Interfaces:**
- Consumes: `judge`, `STRICTNESS_K` from `nocturne.stacking.grade`; `_on_graded`/`_verdict_text`/`_tint_row`/`_selection_summary` from Task 4.
- Produces: `self.strictness_box` (QComboBox, items `["Relaxed", "Normal", "Strict"]`, default `"Normal"`); `self._user_touched: set[int]` (row indices manually toggled); `_rejudge()` method. `grade()` passes `strictness=` to the runner.

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/test_stack_dialog.py`:

```python
def test_strictness_rejudges_without_remeasuring(qtbot, tmp_path):
    for i in range(6):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    calls = []

    def runner(paths, on_progress=None, strictness="normal"):
        calls.append(strictness)
        return [_stats2(str(tmp_path / f"f{i}.fit"), 0.5, exposure=20.0)
                for i in range(6)]

    dlg._grade_runner = runner
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 6, timeout=2000)
    assert calls == ["normal"]
    dlg.strictness_box.setCurrentText("Strict")
    assert calls == ["normal"]          # measurement NOT re-run
    assert dlg.table.rowCount() == 6    # table re-judged in place


def test_manual_override_survives_rejudge(qtbot, tmp_path):
    for i in range(6):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": [
        _stats2(str(tmp_path / f"f{i}.fit"), 0.5) for i in range(6)
    ]
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 6, timeout=2000)
    # user manually unchecks row 2
    dlg.table.item(2, 0).setCheckState(Qt.CheckState.Unchecked)
    assert 2 in dlg._user_touched
    dlg.strictness_box.setCurrentText("Relaxed")
    # re-judge would keep everything, but the user's choice wins:
    assert dlg.table.item(2, 0).checkState() == Qt.CheckState.Unchecked
```

Add to that file's imports: `from PySide6.QtCore import Qt`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_stack_dialog.py -q`
Expected: FAIL with `AttributeError: ... no attribute 'strictness_box'`.

- [ ] **Step 3: Implement in `nocturne/ui/stack_dialog.py`**

1. Import the judge:

```python
from ..stacking.grade import grade_frames, judge
```

2. In `__init__` (after `self.kappa_box` setup) create the dropdown and the override set, and connect signals:

```python
        self.strictness_box = QComboBox()
        self.strictness_box.addItems(["Relaxed", "Normal", "Strict"])
        self.strictness_box.setCurrentText("Normal")
        self.strictness_box.currentTextChanged.connect(self._rejudge)
        self._user_touched: set[int] = set()
        self._updating_table = False
        self.table.itemChanged.connect(self._on_item_changed)
```

3. Add the strictness row to the form (before the Integration row):

```python
        strict_row = QHBoxLayout()
        strict_row.addWidget(self.strictness_box)
        strict_row.addWidget(QLabel("How picky the automatic frame selection is"))
        strict_row.addStretch(1)
        strict_wrap = QWidget()
        strict_wrap.setLayout(strict_row)
        form.addRow("Strictness", strict_wrap)
```

4. Track manual toggles:

```python
    def _on_item_changed(self, item) -> None:
        if self._updating_table or item.column() != 0:
            return
        self._user_touched.add(item.row())
        if self._stats:
            self.status.setText(self._sync_included_and_summarize())

    def _sync_included_and_summarize(self) -> str:
        for row in range(self.table.rowCount()):
            checked = self.table.item(row, 0).checkState() == Qt.CheckState.Checked
            self._stats[row].included = checked
        return self._selection_summary()
```

(Note: `_selection_summary` reads `s.included`, so keep `self._stats[row].included` in sync with the checkbox — that is what `_sync_included_and_summarize` does.)

5. Guard programmatic population — in `_on_graded` (and `_rejudge` below), wrap table writes:

```python
        self._updating_table = True
        try:
            ...existing population loop...
        finally:
            self._updating_table = False
```

Also reset `self._user_touched = set()` at the top of `_on_graded` (fresh grade = fresh slate).

6. `grade()` passes strictness to the runner:

```python
        strictness = self.strictness_box.currentText().lower()

        def work():
            return runner(paths, on_progress=lambda i, n, name:
                          self._signals.progress.emit(i, n, "grading"),
                          strictness=strictness)
```

7. The re-judge:

```python
    def _rejudge(self, _text=None) -> None:
        if not self._stats:
            return
        judge(self._stats, self.strictness_box.currentText().lower())
        self._updating_table = True
        try:
            for row, s in enumerate(self._stats):
                if row not in self._user_touched:
                    self.table.item(row, 0).setCheckState(
                        Qt.CheckState.Checked if s.included else Qt.CheckState.Unchecked)
                else:
                    s.included = (self.table.item(row, 0).checkState()
                                  == Qt.CheckState.Checked)
                self.table.item(row, 5).setText(self._verdict_text(s))
                self._tint_row(row, s)
        finally:
            self._updating_table = False
        self.status.setText(self._selection_summary())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_stack_dialog.py tests/stacking/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/stack_dialog.py tests/ui/test_stack_dialog.py
git commit -m "feat(ui): strictness knob re-judges instantly, preserving manual overrides"
```

---

### Task 6: Dialog — auto-derived master filename

**Files:**
- Modify: `nocturne/ui/stack_dialog.py`
- Test: `tests/ui/test_stack_dialog.py`

**Interfaces:**
- Consumes: `master_filename(target, count, exposure_s, total_s)` from Task 3; `_stats` with `target`/`exposure` fields.
- Produces: `_auto_output_path()` refreshes `output_edit` unless `self._output_user_edited` is True (set via `output_edit.textEdited` — fires on manual typing only, not `setText`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/test_stack_dialog.py`:

```python
def test_output_filename_derived_from_selection(qtbot, tmp_path):
    for i in range(3):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    stats = [_stats2(str(tmp_path / f"f{i}.fit"), 0.5, exposure=20.0)
             for i in range(3)]
    for s in stats:
        s.target = "NGC 7000"
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": stats
    dlg.folder_edit.setText(str(tmp_path))
    dlg.output_edit.setText("")          # nothing user-chosen
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 3, timeout=2000)
    assert dlg.output_edit.text() == str(tmp_path / "NGC7000_3x20s_1min.fits")


def test_user_edited_output_is_never_overwritten(qtbot, tmp_path):
    for i in range(3):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": [
        _stats2(str(tmp_path / f"f{i}.fit"), 0.5) for i in range(3)
    ]
    dlg.folder_edit.setText(str(tmp_path))
    dlg.output_edit.setText("keep-me.fits")
    dlg.output_edit.textEdited.emit("keep-me.fits")   # simulate manual typing
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 3, timeout=2000)
    assert dlg.output_edit.text() == "keep-me.fits"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_stack_dialog.py -q`
Expected: first new test FAILS (output stays empty / master.fits).

- [ ] **Step 3: Implement in `nocturne/ui/stack_dialog.py`**

1. Import: `from ..stacking.stacker import StackOptions, run_stack, master_filename` (extend the existing import line).
2. In `__init__`:

```python
        self._output_user_edited = False
        self.output_edit.textEdited.connect(self._mark_output_edited)
```

```python
    def _mark_output_edited(self, _text: str) -> None:
        self._output_user_edited = True
```

3. In `_browse_output`, set `self._output_user_edited = True` after a successful pick (a browsed path is a user choice).
4. Add the refresh and call it from the end of `_on_graded`, `_rejudge`, and `_on_item_changed`:

```python
    def _auto_output_path(self) -> None:
        if self._output_user_edited or not self._stats:
            return
        folder = self.folder_edit.text().strip()
        kept = [s for s in self._stats if s.included]
        exposures = [s.exposure for s in kept if s.exposure > 0]
        exposure = exposures[0] if exposures and max(exposures) == min(exposures) else 0.0
        target = next((s.target for s in kept if s.target), "")
        name = master_filename(target, len(kept), exposure,
                               sum(s.exposure for s in kept))
        self.output_edit.setText(os.path.join(folder, name))
```

(Keep only the second `kept = ...` line — shown twice above to flag the deliberate final form: kept frames are those with `included=True`, which `_sync_included_and_summarize`/`_rejudge` keep in sync with checkboxes.)

5. In `_browse_folder`, remove the old `master.fits` default (the auto path now handles it):

```python
    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder of subs")
        if path:
            self.folder_edit.setText(path)
            self.grade()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_stack_dialog.py -q`
Expected: all PASS. (`test_stack_calls_handoff_best_first` and friends must still pass; they set `output_edit` directly via `setText`, which does not fire `textEdited`, but they don't re-grade afterwards, so the text survives.)

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/stack_dialog.py tests/ui/test_stack_dialog.py
git commit -m "feat(ui): auto-derive descriptive master filename from the selection"
```

---

### Task 7: Dialog — autostretched frame preview pane

**Files:**
- Modify: `nocturne/ui/stack_dialog.py`
- Test: `tests/ui/test_stack_dialog.py`

**Interfaces:**
- Consumes: `load_sub` (`stacking/frames.py`), `autostretch(img: AstroImage) -> np.ndarray` (`nocturne/core/autostretch.py`), `run_async` (existing).
- Produces: `self.preview` (QLabel, fixed 300×220, right of the table); `self._preview_cache: dict[str, QPixmap]`; `_show_preview(row)` connected to `table.currentCellChanged`; `self._preview_loader` injectable for tests (defaults to `_load_preview_array`).

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/test_stack_dialog.py`:

```python
def test_row_selection_requests_preview_and_caches(qtbot, tmp_path):
    import numpy as np
    for i in range(2):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": [
        _stats2(str(tmp_path / f"f{i}.fit"), 0.5) for i in range(2)
    ]
    loads = []

    def fake_loader(path):
        loads.append(path)
        return np.zeros((40, 60, 3), dtype=np.float32)

    dlg._preview_loader = fake_loader
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 2, timeout=2000)
    dlg.table.setCurrentCell(0, 1)
    qtbot.waitUntil(lambda: dlg.preview.pixmap() is not None
                    and not dlg.preview.pixmap().isNull(), timeout=2000)
    assert loads == [str(tmp_path / "f0.fit")]
    dlg.table.setCurrentCell(1, 1)
    qtbot.waitUntil(lambda: len(loads) == 2, timeout=2000)
    dlg.table.setCurrentCell(0, 1)      # cached — no third load
    qtbot.wait(100)
    assert len(loads) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_stack_dialog.py::test_row_selection_requests_preview_and_caches -q`
Expected: FAIL with `AttributeError: ... no attribute '_preview_loader'`.

- [ ] **Step 3: Implement in `nocturne/ui/stack_dialog.py`**

1. Imports:

```python
import numpy as np

from PySide6.QtGui import QColor, QImage, QPixmap

from ..core.autostretch import autostretch
from ..stacking.frames import discover_subs, load_sub
```

2. In `__init__`, create the preview label and put the table + preview side by side (replace `root.addWidget(self.table)`):

```python
        self.preview = QLabel("Select a frame\nto preview it")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(300, 220)
        self.preview.setObjectName("framePreview")

        table_row = QHBoxLayout()
        table_row.addWidget(self.table, 1)
        table_row.addWidget(self.preview)
        root.addLayout(table_row)
```

3. Preview state in `__init__`:

```python
        self._preview_cache: dict[str, QPixmap] = {}
        self._preview_wanted = ""            # stale-result guard
        self._preview_loader = self._load_preview_array   # injectable for tests
        self.table.currentCellChanged.connect(
            lambda row, _c, _pr, _pc: self._show_preview(row))
```

4. The loader and the handler:

```python
    @staticmethod
    def _load_preview_array(path: str) -> np.ndarray:
        """Small autostretched RGB array for a sub (debayer + display stretch)."""
        img = load_sub(path)                       # normalized + debayered
        data = img.data
        step = max(1, data.shape[1] // 512)        # downsample for speed
        small = data[::step, ::step]
        from ..core.image import AstroImage
        return autostretch(AstroImage(small, is_linear=img.is_linear,
                                      metadata=dict(img.metadata)))

    def _show_preview(self, row: int) -> None:
        if not self._stats or not (0 <= row < len(self._stats)):
            return
        path = self._stats[row].path
        self._preview_wanted = path
        cached = self._preview_cache.get(path)
        if cached is not None:
            self.preview.setPixmap(cached)
            return
        loader = self._preview_loader

        def work():
            return path, loader(path)

        run_async(self._pool, work, self._on_preview, self._on_preview_error)

    def _on_preview(self, result) -> None:
        path, arr = result
        arr8 = (np.clip(arr, 0.0, 1.0) * 255).astype(np.uint8)
        if arr8.ndim == 2:
            arr8 = np.stack([arr8] * 3, axis=2)
        arr8 = np.ascontiguousarray(arr8)
        h, w = arr8.shape[:2]
        image = QImage(arr8.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        pix = QPixmap.fromImage(image).scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        if len(self._preview_cache) > 32:
            self._preview_cache.clear()            # simple bound; tiny pixmaps
        self._preview_cache[path] = pix
        if path == self._preview_wanted:
            self.preview.setPixmap(pix)

    def _on_preview_error(self, exc) -> None:
        self.preview.setText("Preview failed:\ncould not read frame")
```

Note: the preview deliberately does NOT use `_set_busy` — grading/stacking stay blocked from double-running, but a slow preview must never lock the Stack button.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_stack_dialog.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/stack_dialog.py tests/ui/test_stack_dialog.py
git commit -m "feat(ui): autostretched per-frame preview pane in stack dialog"
```

---

### Task 8: Registration-failure reporting on completion

**Files:**
- Modify: `nocturne/ui/stack_dialog.py`
- Test: `tests/ui/test_stack_dialog.py`

**Interfaces:**
- Consumes: `StackResult.rejected` (existing `list[(path, reason)]` from `stacker.run_stack` — reasons like `"registration failed: …"`, `"unreadable: …"`, `"dimension mismatch"`).
- Produces: `_stack_report(result) -> str` — completion text listing skipped frames by name; shown via the parent-visible message box before the dialog closes.

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/test_stack_dialog.py`:

```python
def test_stack_report_names_unregistered_frames(qtbot):
    from nocturne.stacking.stacker import StackResult
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    result = StackResult(
        image=None, used=["/x/a.fit", "/x/b.fit", "/x/c.fit"],
        rejected=[("/x/d.fit", "registration failed: no match"),
                  ("/x/e.fit", "unreadable: bad header")],
        frame_count=3, integration_seconds=60.0, output_path="/x/out.fits")
    text = dlg._stack_report(result)
    assert "3 frames" in text
    assert "d.fit" in text and "couldn't be aligned" in text
    assert "e.fit" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_stack_dialog.py::test_stack_report_names_unregistered_frames -q`
Expected: FAIL with `AttributeError: ... no attribute '_stack_report'`.

- [ ] **Step 3: Implement in `nocturne/ui/stack_dialog.py`**

1. Add `QMessageBox` to the PySide6.QtWidgets import list.
2. Add the report builder and rework `_on_stacked`:

```python
    @staticmethod
    def _stack_report(result) -> str:
        mins = result.integration_seconds / 60
        text = (f"Done — stacked {result.frame_count} frames"
                + (f" ({mins:.0f} minutes of light)" if mins >= 1 else "")
                + f" → {os.path.basename(result.output_path)}")
        aligned = [(p, r) for p, r in result.rejected
                   if r.startswith("registration failed")]
        other = [(p, r) for p, r in result.rejected
                 if not r.startswith("registration failed")]
        if aligned:
            names = ", ".join(os.path.basename(p) for p, _ in aligned)
            text += f"\n{len(aligned)} frame(s) couldn't be aligned and were skipped: {names}"
        if other:
            names = ", ".join(os.path.basename(p) for p, _ in other)
            text += f"\n{len(other)} frame(s) skipped: {names}"
        return text

    def _on_stacked(self, result) -> None:
        self._set_busy(False)
        report = self._stack_report(result)
        self.status.setText(report)
        if result.rejected:
            QMessageBox.information(self, "Stack finished", report)
        if self._on_master is not None:
            self._on_master(result.image)
        self.accept()  # hand off done — close the dialog (master is now in the editor)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_stack_dialog.py -q`
Expected: all PASS. (Existing `_on_stacked` tests, if any assert the old status wording, must be updated to the new "Done — stacked" phrasing — check `grep -n "rejected" tests/ui/test_stack_dialog.py` and align.)

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/stack_dialog.py tests/ui/test_stack_dialog.py
git commit -m "feat(ui): name unaligned frames in the stack completion report"
```

---

### Task 9: Full-suite check + real-data validation

**Files:**
- No production changes expected (fix regressions if found).
- Scratch: rerun of the grading diagnostic against the new judge.

- [ ] **Step 1: Full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS (was 393+ tests before this work).

- [ ] **Step 2: Real-data validation of the new judge**

Write and run a scratch script (do NOT commit) that mirrors the 2026-07-17 diagnostic:

```python
import sys
sys.path.insert(0, "/Volumes/Work/Code/Editor")
from nocturne.stacking.frames import discover_subs
from nocturne.stacking.grade import grade_frames

paths = [p for p in discover_subs("/Volumes/Work2/Images/Astro/NGC 7000_sub/lights")
         if "master" not in p.lower() and "NGC7000" not in p]
for strictness in ("relaxed", "normal", "strict"):
    stats = grade_frames(paths, strictness=strictness)
    kept = [s for s in stats if s.included]
    warned = [s for s in stats if s.warning]
    print(f"{strictness:8s}: kept {len(kept)}/{len(stats)}, {len(warned)} sky warnings")
    for s in stats:
        if not s.included:
            import os
            print("   REJECT", os.path.basename(s.path), "--", s.reason)
```

Expected at `normal` (from the 2026-07-17 diagnostic): roughly 180+/186 kept; the FWHM-3.54 frame and the 479-star frame rejected; the twilight block carries sky warnings but is KEPT. If results differ wildly, stop and investigate before proceeding.

- [ ] **Step 3: Launch the app and exercise the dialog by hand**

Run: `.venv/bin/python -m nocturne`, open Stack…, point at the NGC 7000 lights folder. Verify: verdict column reads sensibly, twilight rows amber, clicking rows shows previews, strictness switch is instant, status line counts minutes, output filename reads `NGC7000_<n>x20s_<m>min.fits`. (Screenshot for the session log.)

- [ ] **Step 4: Commit any fixes; update TODO.md**

Mark the grading redesign as shipped in `TODO.md` (add a line under "Done (recent)"), and leave the memory-runaway entry untouched.

```bash
git add -A && git commit -m "chore: stacking grading validation follow-ups"
```

---

## Self-Review Notes

- Spec coverage: engine (T1/T2), filename (T3/T6), verdict UI + status (T4), strictness + overrides (T5), preview (T7), registration reporting (T8), validation (T9). Under-5-frames note lives in `_selection_summary` (T4); measurement-failure verdict in T2 and skipped-in-statistics in T1.
- Type consistency checked: `FrameStats` field names (`reason`, `reason_code`, `warning`, `error`, `exposure`, `target`) used identically in T1/T2/T4/T5/T6; `master_filename(target, count, exposure_s, total_s)` identical in T3/T6; `_verdict_text`/`_tint_row`/`_selection_summary` defined T4, reused T5.
