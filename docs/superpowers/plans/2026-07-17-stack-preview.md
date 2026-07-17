# Stack Dialog Judgeable Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stack dialog's 300×220 thumbnail with a full-resolution, colour-neutral, pan/zoomable preview (reusing the editor's `ImageView`) inside a resizable splitter layout, so users can judge frame verdicts.

**Architecture:** A new `FramePreview` composite widget (ImageView + message overlay) handles display; the dialog keeps loading/caching (async loader now returns full-res unlinked-stretched arrays; cache becomes a 4-entry LRU of QImages). A `QSplitter` lets table and preview trade space; the dialog opens 1100×700.

**Tech Stack:** Python 3.13 (`.venv/bin/python`), numpy, PySide6, pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-07-17-stack-preview-design.md`

## Global Constraints

- Run tests with `.venv/bin/python -m pytest <path> -q` from `/Volumes/Work/Code/Editor`.
- The editor's display stretch (`autostretch` / `linked_stretch`) must NOT change behaviour — `unlinked_stretch` is additive.
- The preview must never touch `_set_busy` (Stack button stays usable during loads); the `_preview_wanted` stale-result guard semantics stay as they are.
- Preview cache: LRU, exactly 4 entries, storing full-res `QImage`s.
- Placeholder text stays exactly `"Select a frame\nto preview it"`; error text stays exactly `"Preview failed:\ncould not read frame"`.
- Commit after every task with trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: `unlinked_stretch` in core/autostretch.py

**Files:**
- Modify: `nocturne/core/autostretch.py`
- Test: `tests/core/test_autostretch.py`

**Interfaces:**
- Consumes: existing private helpers `_stretch_params(c, target)`, `_apply_params(c, shadow, m)`, `linked_stretch(data, target)`, module constant `_TARGET_BG` (0.25).
- Produces: `unlinked_stretch(data: np.ndarray, target: float = _TARGET_BG) -> np.ndarray` — per-channel stretch for 3-channel input; 2D input delegates to `linked_stretch`. Later tasks import it as `from ..core.autostretch import unlinked_stretch`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/core/test_autostretch.py`:

```python
import numpy as np

from nocturne.core.autostretch import _TARGET_BG, linked_stretch, unlinked_stretch


def _cast_image(offsets=(0.05, 0.12, 0.4), seed=0):
    """Synthetic linear frame with a strong per-channel sky offset (blue cast)."""
    rng = np.random.default_rng(seed)
    base = rng.normal(0.0, 0.004, size=(64, 64)).astype(np.float32)
    return np.stack([np.clip(base + o, 0.0, 1.0) for o in offsets], axis=2)


def test_unlinked_stretch_neutralizes_cast():
    out = unlinked_stretch(_cast_image())
    meds = [float(np.median(out[..., c])) for c in range(3)]
    for m in meds:
        assert abs(m - _TARGET_BG) < 0.02      # every channel hits the target bg


def test_linked_stretch_keeps_cast_for_contrast():
    # sanity: the linked stretch (editor display) preserves the imbalance,
    # proving unlinked is doing the neutralizing, not the test fixture
    out = linked_stretch(_cast_image(), _TARGET_BG)
    meds = [float(np.median(out[..., c])) for c in range(3)]
    assert max(meds) - min(meds) > 0.1


def test_unlinked_stretch_2d_delegates_to_linked():
    mono = _cast_image()[..., 0]
    np.testing.assert_allclose(unlinked_stretch(mono),
                               linked_stretch(mono, _TARGET_BG))


def test_unlinked_stretch_constant_channel_does_not_crash():
    img = _cast_image()
    img[..., 2] = 0.0                          # dead channel
    out = unlinked_stretch(img)
    assert np.isfinite(out).all()
    assert out.shape == img.shape
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/core/test_autostretch.py -q`
Expected: FAIL with `ImportError: cannot import name 'unlinked_stretch'`.

- [ ] **Step 3: Implement**

Add to `nocturne/core/autostretch.py` after `linked_stretch`:

```python
def unlinked_stretch(data: np.ndarray, target: float = _TARGET_BG) -> np.ndarray:
    """Per-channel display stretch: each channel independently stretched so its
    own median hits `target`. Neutralizes a uniform sky-colour cast (twilight,
    moon, light pollution) — the Siril-style preview stretch. Display-only;
    the editor keeps the colour-faithful linked_stretch."""
    if data.ndim == 2:
        return linked_stretch(data, target)
    out = np.empty_like(data, dtype=np.float32)
    for ch in range(data.shape[2]):
        shadow, m = _stretch_params(data[..., ch], target)
        out[..., ch] = _apply_params(data[..., ch], shadow, m)
    return np.clip(out, 0.0, 1.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/core/test_autostretch.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/core/autostretch.py tests/core/test_autostretch.py
git commit -m "feat(core): unlinked per-channel autostretch for cast-neutral previews"
```

---

### Task 2: `FramePreview` composite widget

**Files:**
- Create: `nocturne/ui/frame_preview.py`
- Test: `tests/ui/test_frame_preview.py`

**Interfaces:**
- Consumes: `ImageView` from `nocturne/ui/image_view.py` (`set_image(qimage)`, `fit()`; it auto-fits on first image / size change and keeps zoom-pan between same-size images — desirable for blink review).
- Produces (Task 3 relies on these exact names):
  - `FramePreview(QWidget)` with `view: ImageView` attribute;
  - `show_image(qimage: QImage) -> None` — hides overlay, displays image;
  - `show_message(text: str) -> None` — shows centred overlay text;
  - `clear() -> None` — placeholder state (`"Select a frame\nto preview it"`);
  - `has_image() -> bool` — True after `show_image`, False after `clear()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/test_frame_preview.py`:

```python
import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QImage  # noqa: E402
from nocturne.ui.frame_preview import FramePreview  # noqa: E402


def _qimage(w=32, h=24):
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def test_starts_with_placeholder(qtbot):
    fp = FramePreview()
    qtbot.addWidget(fp)
    assert not fp.has_image()
    assert "Select a frame" in fp.overlay.text()
    assert fp.overlay.isVisibleTo(fp)


def test_show_image_hides_overlay(qtbot):
    fp = FramePreview()
    qtbot.addWidget(fp)
    fp.show_image(_qimage())
    assert fp.has_image()
    assert not fp.overlay.isVisibleTo(fp)


def test_show_message_over_image_then_clear(qtbot):
    fp = FramePreview()
    qtbot.addWidget(fp)
    fp.show_image(_qimage())
    fp.show_message("Preview failed:\ncould not read frame")
    assert "Preview failed" in fp.overlay.text()
    assert fp.overlay.isVisibleTo(fp)
    fp.clear()
    assert not fp.has_image()
    assert "Select a frame" in fp.overlay.text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_frame_preview.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'nocturne.ui.frame_preview'`.

- [ ] **Step 3: Implement**

Create `nocturne/ui/frame_preview.py`:

```python
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from .image_view import ImageView

PLACEHOLDER = "Select a frame\nto preview it"


class FramePreview(QWidget):
    """A pan/zoomable frame preview (ImageView) with a message overlay for
    the empty and error states. Display only — loading/caching is the
    owner's job."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.view = ImageView(self)
        self.overlay = QLabel(PLACEHOLDER, self)
        self.overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay.setObjectName("previewOverlay")
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(self.view, 0, 0)
        grid.addWidget(self.overlay, 0, 0)
        self._has_image = False

    def show_image(self, qimage: QImage) -> None:
        self.view.set_image(qimage)
        self.overlay.hide()
        self._has_image = True

    def show_message(self, text: str) -> None:
        self.overlay.setText(text)
        self.overlay.show()

    def clear(self) -> None:
        self.view.set_image(QImage())          # blank the scene
        self.view._item.setPixmap(QPixmap())   # drop the pixmap entirely
        self._has_image = False
        self.show_message(PLACEHOLDER)

    def has_image(self) -> bool:
        return self._has_image
```

Note on `clear()`: `ImageView.set_image` wraps `QPixmap.fromImage`; a null
QImage yields a null pixmap but `set_image` also records size-change state —
resetting `_item`'s pixmap directly guarantees a blank scene. This is the one
place we touch an `ImageView` private; keep the comment.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_frame_preview.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/frame_preview.py tests/ui/test_frame_preview.py
git commit -m "feat(ui): FramePreview widget — pan/zoom ImageView with message overlay"
```

---

### Task 3: Dialog integration — full-res unlinked previews with 4-entry LRU

**Files:**
- Modify: `nocturne/ui/stack_dialog.py`
- Test: `tests/ui/test_stack_dialog.py`

**Interfaces:**
- Consumes: `FramePreview` (Task 2: `show_image`/`show_message`/`clear`/`has_image`), `unlinked_stretch` (Task 1).
- Produces: `self.preview` is now a `FramePreview`; `self._preview_cache` is an `OrderedDict[str, QImage]` LRU capped at `PREVIEW_CACHE_LIMIT = 4` (module constant in `stack_dialog.py`). Loader `_load_preview_array` returns a FULL-RES float array.

- [ ] **Step 1: Adapt existing preview tests and add LRU test (failing first)**

In `tests/ui/test_stack_dialog.py`:

1. In `test_row_selection_requests_preview_and_caches`, replace the wait condition
   `dlg.preview.pixmap() is not None and not dlg.preview.pixmap().isNull()` with
   `dlg.preview.has_image()`.
2. In `test_regrade_resyncs_preview_to_new_row_data`, replace any
   `dlg.preview.pixmap()` waits the same way (check the test body; the load
   assertions on `loads` stay unchanged).
3. Add:

```python
def test_preview_cache_is_lru_of_four(qtbot, tmp_path):
    import numpy as np
    paths = []
    for i in range(6):
        p = tmp_path / f"f{i}.fit"
        p.write_text("x")
        paths.append(str(p))
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda ps, on_progress=None, strictness="normal": [
        _stats2(p, 0.5) for p in paths
    ]
    loads = []

    def fake_loader(path):
        loads.append(path)
        return np.zeros((8, 8, 3), dtype=np.float32)

    dlg._preview_loader = fake_loader
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 6, timeout=2000)
    for row in range(5):                       # visit rows 0..4 -> 5 loads
        dlg.table.setCurrentCell(row, 1)
        qtbot.waitUntil(lambda r=row: len(loads) == r + 1, timeout=2000)
    assert len(dlg._preview_cache) == 4        # LRU capped
    dlg.table.setCurrentCell(0, 1)             # row 0 was evicted -> reloads
    qtbot.waitUntil(lambda: len(loads) == 6, timeout=2000)
    dlg.table.setCurrentCell(4, 1)             # row 4 still cached -> no load
    qtbot.wait(100)
    assert len(loads) == 6
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `.venv/bin/python -m pytest tests/ui/test_stack_dialog.py -q`
Expected: `test_preview_cache_is_lru_of_four` FAILS (old cache holds >4 / `has_image` missing → AttributeError on adapted tests).

- [ ] **Step 3: Implement in `nocturne/ui/stack_dialog.py`**

1. Imports: add `from collections import OrderedDict` (stdlib, top group);
   change `from ..core.autostretch import autostretch` to
   `from ..core.autostretch import unlinked_stretch`; add
   `from .frame_preview import FramePreview`. Remove the now-unused
   `AstroImage` import if nothing else uses it (check).
2. Module constant after `KAPPA`:

```python
PREVIEW_CACHE_LIMIT = 4   # full-res QImages (~24 MB each) — small LRU
```

3. In `__init__`, replace the QLabel preview block with:

```python
        self.preview = FramePreview()
        self.preview.setMinimumSize(300, 220)
```

   and the cache init with:

```python
        self._preview_cache: OrderedDict[str, QImage] = OrderedDict()
```

4. Replace `_load_preview_array` (full resolution, neutral colour):

```python
    @staticmethod
    def _load_preview_array(path: str) -> np.ndarray:
        """Full-res, cast-neutral RGB array for a sub. Unlinked stretch so the
        sky lands neutral grey whatever the LP/twilight cast; full resolution
        so 1:1 zoom shows real star shapes."""
        return unlinked_stretch(load_sub(path).data)
```

5. `_show_preview`: cached branch becomes:

```python
        cached = self._preview_cache.get(path)
        if cached is not None:
            self._preview_cache.move_to_end(path)
            self.preview.show_image(cached)
            return
```

6. `_on_preview`: drop the label scaling; store the full-res QImage in the LRU:

```python
    def _on_preview(self, result) -> None:
        path, arr = result
        arr8 = (np.clip(arr, 0.0, 1.0) * 255).astype(np.uint8)
        if arr8.ndim == 2:
            arr8 = np.stack([arr8] * 3, axis=2)
        arr8 = np.ascontiguousarray(arr8)
        h, w = arr8.shape[:2]
        image = QImage(arr8.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self._preview_cache[path] = image
        self._preview_cache.move_to_end(path)
        while len(self._preview_cache) > PREVIEW_CACHE_LIMIT:
            self._preview_cache.popitem(last=False)
        if path == self._preview_wanted:
            self.preview.show_image(image)
```

7. `_on_preview_error`: `self.preview.show_message("Preview failed:\ncould not read frame")` (keep the `path == self._preview_wanted` guard).
8. `_resync_preview` else-branch becomes:

```python
        else:
            self._preview_wanted = ""
            self.preview.clear()
```

(`QPixmap` may now be unused in stack_dialog.py — remove it from the import if so.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/ tests/stacking/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/stack_dialog.py tests/ui/test_stack_dialog.py
git commit -m "feat(ui): full-res cast-neutral pan/zoom preview in stack dialog"
```

---

### Task 4: Layout polish — splitter, sizing, columns, tooltips

**Files:**
- Modify: `nocturne/ui/stack_dialog.py`
- Test: `tests/ui/test_stack_dialog.py`

**Interfaces:**
- Consumes: `self.preview` (`FramePreview`, Task 3), `self.table`.
- Produces: `self.splitter: QSplitter` (horizontal, table left / preview right).

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/test_stack_dialog.py`:

```python
def test_splitter_holds_table_and_preview(qtbot):
    from PySide6.QtWidgets import QSplitter
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    assert isinstance(dlg.splitter, QSplitter)
    assert dlg.splitter.count() == 2
    assert dlg.splitter.widget(0) is dlg.table
    assert dlg.splitter.widget(1) is dlg.preview


def test_dialog_opens_roomy_and_resizable(qtbot):
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    assert (dlg.width(), dlg.height()) == (1100, 700)
    assert (dlg.minimumWidth(), dlg.minimumHeight()) == (800, 500)


def test_cells_carry_tooltips(qtbot, tmp_path):
    for i in range(3):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": [
        _stats2(str(tmp_path / f"f{i}.fit"), 0.5) for i in range(3)
    ]
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 3, timeout=2000)
    item = dlg.table.item(0, 5)
    assert item.toolTip() == item.text() != ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_stack_dialog.py -q`
Expected: FAIL with `AttributeError: ... no attribute 'splitter'`.

- [ ] **Step 3: Implement in `nocturne/ui/stack_dialog.py`**

1. Imports: add `QHeaderView, QSplitter` to the QtWidgets import list.
2. In `__init__`, replace `self.setMinimumWidth(560)` with:

```python
        self.setMinimumSize(800, 500)
        self.resize(1100, 700)
```

3. After the table is created, configure its header:

```python
        hdr = self.table.horizontalHeader()
        for col in (0, 2, 3, 4):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        for col in (1, 5):                    # File and Verdict share the slack
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
```

4. Replace the `table_row` QHBoxLayout block with:

```python
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(self.preview)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)   # preview absorbs extra width
        self.splitter.setSizes([600, 500])
        self.splitter.setChildrenCollapsible(False)
```

   and `root.addLayout(table_row)` with `root.addWidget(self.splitter, 1)`
   (stretch 1 so the splitter absorbs extra height too).
5. In `_on_graded`'s population loop, set a tooltip on every created item —
   after each `self.table.setItem(row, N, item_expr)` group, or by building
   items via a small helper:

```python
        def _cell(text: str) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setToolTip(text)
            return it
```

   used for columns 1–5 (`_cell(os.path.basename(s.path))`, `_cell(str(s.star_count))`,
   `_cell(f"{s.fwhm:.1f}")`, `_cell(f"{s.background:.3f}")`,
   `_cell(self._verdict_text(s))`). The Use checkbox item (column 0) stays as-is.
6. In `_rejudge`, when the verdict text is updated, also refresh its tooltip:

```python
                item5 = self.table.item(row, 5)
                item5.setText(self._verdict_text(s))
                item5.setToolTip(item5.text())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/stack_dialog.py tests/ui/test_stack_dialog.py
git commit -m "feat(ui): stack dialog splitter layout, roomy default size, column sizing, tooltips"
```

---

### Task 5: Full suite + real-data GUI validation

**Files:** none expected (fix regressions if found); scratch driver only.

- [ ] **Step 1: Full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS (~450 tests).

- [ ] **Step 2: Offscreen GUI drive on the real dataset**

Scratch script (scratchpad, not committed): instantiate `StackDialog` under
`QT_QPA_PLATFORM=offscreen`, grade `/Volumes/Work2/Images/Astro/NGC 7000_sub/lights`,
then: select a "Stars softer…" rejected row, wait for `dlg.preview.has_image()`,
screenshot the dialog (`dlg.grab().save(...)`) at fit; call
`dlg.preview.view.actual_size()` (1:1) and screenshot again; assert channel
medians of the displayed QImage are within ~10 levels of each other (cast gone);
drag check via `dlg.splitter.setSizes([300, 800])` + screenshot; verify
`dlg._preview_cache` length never exceeds 4 after visiting 6 rows.

- [ ] **Step 3: Present screenshots + findings, update TODO.md**

Mark the preview rework shipped under "Done (recent)" in `TODO.md`; note any
deviations found during the drive.

```bash
git add TODO.md && git commit -m "docs: record stack preview rework in TODO"
```

---

## Self-Review Notes

- Spec §1→Task 2/3 (ImageView reuse via FramePreview, overlay states), §2→Task 1,
  §3→Task 3 (full-res, LRU-4 QImages), §4→Task 4, §5 error handling→Tasks 2/3
  (overlay + guards unchanged), §6 testing→each task + Task 5 manual validation.
- Type consistency: `FramePreview.show_image(QImage)`/`show_message(str)`/`clear()`/
  `has_image()` defined in Task 2, consumed identically in Tasks 3/5;
  `unlinked_stretch(data, target=_TARGET_BG)` defined Task 1, consumed Task 3;
  `PREVIEW_CACHE_LIMIT = 4` defined and used only in Task 3 (test asserts via
  `len(dlg._preview_cache)`).
- Spec's "File column Stretch … Verdict takes remaining width" is implemented as
  both columns sharing Stretch mode (Qt supports multiple stretch sections) —
  recorded here as the deliberate resolution of that wording.
