# Crop step rework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Overlay hidden by default → shows at detected content edges on image click → hidden after Apply; exterior dimming (no inside tint); selectable guides (thirds/center); live W×H readout; label/grouping polish. Display/interaction only.

**Architecture:** `ImageView` gains an explicit show/hide box state (crop *mode* ≠ box *visible*), a `drawForeground` override for exterior dimming + guides, and a `set_guides` setter; `MainWindow` wires click→show, Apply→hide, and the readout; the crop panel gains a Guides combo + size label and relabels. `core/crop.py` unchanged.

**Tech Stack:** Python, PySide6 (QGraphicsView/Scene), pytest-qt.

## Global Constraints

- Display/interaction only — never change `core/crop.py` or pixel data.
- Guide kinds: `"none"` (default), `"thirds"`, `"center"`.
- Exterior dim: black, alpha ≈ 120. Guides: translucent white/accent, thin.
- Keep the 8 handles + aspect-lock behaviour that already exist.
- Run tests via `.venv/bin/python -m pytest`. Reuse the `qtbot`/`qapp` fixtures and the `MainWindow(settings_path=...)` / `build_panel(_stage("crop"))` patterns already in the UI tests.

---

### Task 1: Overlay visibility model (hidden → click-to-show → hide-after-apply)

**Files:** Modify `nocturne/ui/image_view.py`, `nocturne/ui/main_window.py`, `nocturne/ui/step_panels.py`. Test: `tests/ui/test_image_view.py`, `tests/ui/test_main_window.py`.

**Interfaces produced:**
- `ImageView.set_crop_overlay(enabled, content_bounds=None, aspect_ratio=None)` — enables crop mode + stores `content_bounds`; does NOT create/show the box.
- `ImageView.show_crop_box()` (builds body+handles at stored bounds, emits `cropBoxShown`), `ImageView.hide_crop_box()`, `ImageView.crop_box_visible() -> bool`.
- Signal `cropBoxShown = Signal()`.
- `build_panel(..., on_guides_change=None)` and crop panel `apply_btn` starts disabled.

- [ ] **Step 1: Failing tests** (`tests/ui/test_image_view.py`):

```python
def test_crop_box_hidden_until_shown(qapp):
    from nocturne.ui.image_view import ImageView
    from PySide6.QtGui import QPixmap
    v = ImageView()
    v.set_image_pixmap(QPixmap(200, 100)) if hasattr(v, "set_image_pixmap") else None
    v.set_crop_overlay(True, content_bounds=(10, 90, 20, 180))
    assert v.crop_box_visible() is False
    v.show_crop_box()
    assert v.crop_box_visible() is True
    assert v.crop_bounds() == (10, 90, 20, 180)
    v.hide_crop_box()
    assert v.crop_box_visible() is False
```

(If `ImageView` needs a pixmap to compute bounds, set one via the existing image-setting method — inspect `set_image`/`_item.setPixmap`; use a `QPixmap(200,100)`.)

- [ ] **Step 2: Confirm fail** — `.venv/bin/python -m pytest tests/ui/test_image_view.py -q`.

- [ ] **Step 3: Implement in `image_view.py`.**
  - Add `cropBoxShown = Signal()` next to `cropBoxChanged`.
  - Add fields in `__init__`: `self._crop_mode = False`, `self._content_bounds = None`.
  - Refactor `set_crop_overlay(enabled, content_bounds=None, aspect_ratio=None)`: set `self._crop_mode = enabled`, `self._aspect = aspect_ratio`, `self._content_bounds = content_bounds`; toggle zoom pill; on `not enabled` → `_teardown_overlay()` + restore `ScrollHandDrag` + return. On enabled: set `NoDrag`, but **do not** build the body/handles here (leave the box hidden).
  - `show_crop_box()`: if `self._body is None`, build `_Body` + `_HANDLES` (as the old `set_crop_overlay` did); set bounds from `self._content_bounds` (fallback to full pixmap); `_position_handles()`; `self.viewport().update()`; `self.cropBoxShown.emit()`. Idempotent (no-op if already visible).
  - `hide_crop_box()`: `_teardown_overlay()`; `self.viewport().update()`.
  - `crop_box_visible() -> bool`: `return self._body is not None`.
  - `mousePressEvent(self, e)`: if `self._crop_mode and not self.crop_box_visible()` and the click position maps inside the image item, call `self.show_crop_box()`; then `super().mousePressEvent(e)`.

- [ ] **Step 4: Wire `main_window.py`.**
  - `_setup_crop_overlay`: when on crop stage, `set_crop_overlay(True, content_bounds=detect_content_bounds(self.project.current()), aspect_ratio=_ASPECT_RATIO.get(aspect_text))`; ensure the crop panel's `apply_btn` is disabled initially (box not shown yet).
  - Connect once (where the view is created): `self.image_view.cropBoxShown.connect(self._on_crop_box_shown)` → sets `self._panel.apply_btn.setEnabled(True)` when on crop stage.
  - `_apply_crop`: after committing the crop, call `self.image_view.hide_crop_box()`; the subsequent `_refresh`/`_setup_crop_overlay` recomputes content bounds and leaves Apply disabled again.

- [ ] **Step 5: Panel — Apply starts disabled.** In `step_panels.py` crop branch, add `on_guides_change=None` to `build_panel`'s signature (used next task), and set `apply_btn.setEnabled(False)` initially (main_window enables it on `cropBoxShown`). Keep `w.apply_btn = apply_btn`.

- [ ] **Step 6: Window test** (`tests/ui/test_main_window.py`): entering crop leaves the box hidden; simulating `cropBoxShown` enables Apply; `_apply_crop` hides the box. (Use a loaded synthetic image; call `image_view.show_crop_box()` / `hide_crop_box()` directly rather than synthesizing mouse events.)

- [ ] **Step 7: Run + commit** — `.venv/bin/python -m pytest tests/ui -q`; `git commit -m "feat(crop): overlay hidden by default, shows on image click, hides after apply"`.

---

### Task 2: Exterior dimming + guides (drop inside tint)

**Files:** Modify `nocturne/ui/image_view.py`, `nocturne/ui/step_panels.py`, `nocturne/ui/main_window.py`. Test: `tests/ui/test_image_view.py`, `tests/ui/test_step_panels.py`.

**Interfaces produced:** `ImageView.set_guides(kind: str)`; `build_panel` crop branch exposes `w.guides_box` (QComboBox) wired to `on_guides_change`.

- [ ] **Step 1: Failing tests** — `set_guides` stores kind and each kind draws without error:

```python
def test_set_guides_and_draw(qapp):
    from nocturne.ui.image_view import ImageView
    from PySide6.QtGui import QPixmap, QPainter, QImage
    v = ImageView()
    # set an image + show a box (reuse helper from Task 1's test setup)
    v.set_crop_overlay(True, content_bounds=(0, 100, 0, 200))
    v.show_crop_box()
    for kind in ("none", "thirds", "center"):
        v.set_guides(kind)
        assert v._guides == kind
        img = QImage(50, 50, QImage.Format.Format_ARGB32); p = QPainter(img)
        v.drawForeground(p, v.sceneRect()); p.end()   # must not raise
```

Panel test (`tests/ui/test_step_panels.py`):

```python
def test_crop_panel_has_guides_combo(qapp):
    seen = []
    w = build_panel(_stage("crop"), on_guides_change=lambda k: seen.append(k))
    assert hasattr(w, "guides_box")
    items = [w.guides_box.itemText(i) for i in range(w.guides_box.count())]
    assert items == ["None", "Rule of thirds", "Center cross"]
    w.guides_box.setCurrentText("Rule of thirds")
    assert seen and seen[-1] in ("thirds", "Rule of thirds")
```

- [ ] **Step 2: Confirm fail.**

- [ ] **Step 3: Implement `image_view.py`.**
  - `_Body`: change `setBrush` to `QBrush(Qt.BrushStyle.NoBrush)` (drop the alpha-40 tint); keep the accent outline.
  - `__init__`: `self._guides = "none"`.
  - `set_guides(kind)`: `self._guides = kind`; `self.viewport().update()`.
  - `drawForeground(self, painter, rect)`: if `self._crop_mode and self.crop_box_visible()`:
    - Get the crop rect in **viewport** coords (`self.mapFromScene(self._scene_rect()).boundingRect()`), operate in device coords via `painter.resetTransform()` (mirror the existing `drawBackground` pattern which saves/resets/restores).
    - Fill the four viewport regions outside the crop rect with `QColor(0,0,0,120)`.
    - If `self._guides != "none"`, draw thin `QColor(255,255,255,90)` lines inside the crop rect: `thirds` → x at left+w/3, left+2w/3 and y at top+h/3, top+2h/3; `center` → x at center, y at center.
    - save/restore painter state.

- [ ] **Step 4: Panel Guides combo.** In `step_panels.py` crop branch: add a `QLabel("Guides")` + `QComboBox` with items `["None", "Rule of thirds", "Center cross"]`; map selection → kind (`{"None":"none","Rule of thirds":"thirds","Center cross":"center"}`) and call `on_guides_change(kind)` on `currentTextChanged`. Assign `w.guides_box = combo`.

- [ ] **Step 5: Wire main_window.** Add `on_guides_change=self._on_guides_change` to the `build_panel(...)` call; implement `_on_guides_change(self, kind)` → `self.image_view.set_guides(kind)`.

- [ ] **Step 6: Run + commit** — `.venv/bin/python -m pytest tests/ui -q`; `git commit -m "feat(crop): dim exterior + composition guides; drop inside tint"`.

---

### Task 3: Live selection-size readout

**Files:** Modify `nocturne/ui/step_panels.py`, `nocturne/ui/main_window.py`. Test: `tests/ui/test_main_window.py`.

- [ ] **Step 1: Failing test** — `_update_crop_readout(0, 100, 0, 200)` sets the crop panel's size label to `"200 × 100 px"`; a hidden box shows `"—"`.

- [ ] **Step 2: Confirm fail.**

- [ ] **Step 3: Panel.** In the crop branch add `size = _desc_label("—")`; `lay.addWidget(size)`; `w.crop_size_label = size`.

- [ ] **Step 4: main_window.** Connect `self.image_view.cropBoxChanged.connect(self._update_crop_readout)` (once). `_update_crop_readout(self, t, b, l, r)`: if on crop stage and box visible, set `self._panel.crop_size_label.setText(f"{r-l} × {b-t} px")`. On `_setup_crop_overlay` and after apply, reset to `"—"`. Also refresh it in `_on_crop_box_shown`.

- [ ] **Step 5: Run + commit** — `git commit -m "feat(crop): live selection-size readout"`.

---

### Task 4: Labels + grouping polish (C4/C5)

**Files:** Modify `nocturne/ui/step_panels.py`. Test: `tests/ui/test_step_panels.py`.

- [ ] **Step 1: Failing test** — crop panel: Rotate button text contains `"↻"`; the unlink checkbox text is `"Neutral preview (for framing)"`; an "(applies instantly)" note is present among the panel's labels.

- [ ] **Step 2: Confirm fail.**

- [ ] **Step 3: Implement** in the crop branch:
  - Rotate button label → `"Rotate 90° ↻"`.
  - A small `_desc_label("Rotate / Flip apply instantly")` grouped with those three buttons (distinct from Apply Crop).
  - Unlink checkbox label → `"Neutral preview (for framing)"` (keep the existing sub-caption line).

- [ ] **Step 4: Run full suite + commit** — `.venv/bin/python -m pytest tests/ -q`; `git commit -m "polish(crop): rotate direction cue, clearer instant-vs-apply, plainer preview label"`.
