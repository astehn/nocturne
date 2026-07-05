# One-Press Colourise Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-press "Colourise" button at the Stretch step that turns a linear dualband master into finished narrowband colour (StarX-cached, auto Foraxx, stars screened back), preserved by later steps, with the manual sliders kept behind "Advanced…".

**Architecture:** Colourise runs the existing `compose(starless, stars, PaletteParams())` engine on the linear image and records a `"Colourise"` history step at the **stretch position**; the truncation model treats `"Colourise"` as equivalent to `"Stretch"` so later steps preserve it. StarX star-removal is cached. The existing `PaletteDialog` becomes "Advanced…", seeded with the cached layers.

**Tech Stack:** Python 3.13 (`.venv`), PySide6 (Qt), pytest-qt (`QT_QPA_PLATFORM=offscreen`), NumPy.

## Global Constraints

- Use `.venv/bin/python` / `.venv/bin/pytest`; system python is 3.9 and will fail. Qt tests: prefix `QT_QPA_PLATFORM=offscreen`. Tests set `win._async_enabled = False` for deterministic apply.
- Colourise records a history step named exactly `"Colourise"` at the **stretch position** (same predecessors as Apply Stretch). Later steps preserve it: wherever `STEP_NAME["stretch"]` ("Stretch") is in a step's `preceding` set, also add `"Colourise"`.
- One press uses **default `PaletteParams()`** — no sliders. Output is stretched (`is_linear=False`).
- StarX via `RCAstro.remove_stars(img, runner=self._rc_runner)`, gated on `rcastro_valid(self.settings)`; if unavailable, whole-image fallback (`starless=base, stars=None` → `render_nebula`). Star layers cached and reused by Advanced.
- Do NOT add `"colourise"` to `PROCESSING_ORDER`/`STEP_NAME` (keeps recipes unaffected; Colourise recipe-capture is a deferred follow-up).
- Commit co-author trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Known flake: `test_sharpen_changes_image_and_keeps_shape` — rerun alone if it trips.

---

### Task 1: Seed PaletteDialog with pre-computed star layers

**Files:**
- Modify: `seestar_processor/ui/palette_dialog.py` (`__init__` ~30-42, `start` ~123)
- Test: `tests/ui/test_palette_dialog.py`

**Interfaces:**
- Produces: `PaletteDialog(settings, base, parent=None, on_apply=None, starless=None, stars=None)`. When `starless` is provided, `start()` skips StarX and renders from the given layers.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_palette_dialog.py`:

```python
def test_palette_dialog_seeded_skips_starx(qtbot):
    calls = []
    dlg = PaletteDialog(Settings(), _color(), starless=_color(1), stars=_color(2))
    qtbot.addWidget(dlg)
    dlg._starx_runner = lambda img: (calls.append(1), (img, img))[1]
    dlg._async = False
    dlg.start()                                   # seeded -> must NOT run StarX
    assert calls == []
    assert dlg._starless is not None
    assert not dlg.preview.pixmap().isNull()      # rendered from seeded layers
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_palette_dialog.py -q -k seeded`
Expected: FAIL (`__init__` has no `starless`/`stars` kwargs).

- [ ] **Step 3: Add seeding**

In `seestar_processor/ui/palette_dialog.py`, change the constructor signature and the two `self._starless`/`self._stars` initializers:

```python
    def __init__(self, settings, base: AstroImage, parent=None, on_apply=None,
                 starless=None, stars=None) -> None:
```
and (replacing `self._starless = None` / `self._stars = None`):
```python
        self._starless = starless
        self._stars = stars
```

At the very top of `start()`, short-circuit when seeded:
```python
    def start(self) -> None:
        if self._starless is not None:            # seeded with pre-computed layers
            self._cache_previews()
            self._render_preview()
            return
        if not self._starx_enabled:
            ...                                    # (unchanged from here down)
```

- [ ] **Step 4: Run to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_palette_dialog.py -q`
Expected: PASS (seeded test + all existing dialog tests).

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/palette_dialog.py tests/ui/test_palette_dialog.py
git commit -m "feat: PaletteDialog accepts pre-computed star layers (seeding)"
```

---

### Task 2: Colourise engine, history preservation, star cache, Advanced wiring (main_window)

**Files:**
- Modify: `seestar_processor/ui/main_window.py` (imports; `apply_current` ~330; `_open_palette`/`_record_palette` ~184-199 → replace; toolbar palette action ~213; `_done_ids` ~583; add new handlers)
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `PaletteDialog(..., starless=, stars=)` (Task 1); `compose`/`render_nebula`/`PaletteParams` from `core.palette`.
- Produces: `MainWindow._colourise()`, `_record_colourise(result)`, `_open_advanced_palette()`, `_colourise_starx(base)`, `_remove_stars(img)`, `_stretch_preceding()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_main_window.py` (uses this file's existing `_window` / `_make_fits`; `AstroImage`/`np` already imported):

```python
def test_colourise_records_and_is_stretched(qtbot, tmp_path):
    win = _window(qtbot, tmp_path); win._async_enabled = False
    win.open_fits(_make_fits(tmp_path))
    win._colourise()                                   # no RC-Astro -> whole-image colour
    names = [n for n, _ in win.project.entries()]
    assert names[-1] == "Colourise"
    assert win.project.current().is_linear is False


def test_colourise_preserved_after_later_step(qtbot, tmp_path):
    win = _window(qtbot, tmp_path); win._async_enabled = False
    win.open_fits(_make_fits(tmp_path))
    win._colourise()
    win._go_to_id("saturation")
    win.apply_current(0.6)
    names = [n for n, _ in win.project.entries()]
    assert "Colourise" in names and "Saturation" in names
    assert names.index("Colourise") < names.index("Saturation")


def test_colourise_marks_stretch_done(qtbot, tmp_path):
    win = _window(qtbot, tmp_path); win._async_enabled = False
    win.open_fits(_make_fits(tmp_path))
    win._colourise()
    assert "stretch" in win._done_ids()


def test_colourise_caches_star_removal(qtbot, tmp_path, monkeypatch):
    import seestar_processor.ui.main_window as mw
    win = _window(qtbot, tmp_path); win._async_enabled = False
    win.open_fits(_make_fits(tmp_path))
    monkeypatch.setattr(mw, "rcastro_valid", lambda s: True)
    calls = []
    def fake_remove(img):
        calls.append(1)
        half = AstroImage(img.data * 0.5, is_linear=True)
        return half, half
    win._remove_stars = fake_remove
    win._colourise()
    win._colourise()                                   # same base -> cache hit
    assert calls == [1]                                # StarX ran once
    assert [n for n, _ in win.project.entries()][-1] == "Colourise"


def test_open_advanced_palette_requires_image(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._open_advanced_palette()                       # no project -> guarded, no crash
    assert "Open or stack" in win._status.text()


def test_record_colourise_adds_history_step(qtbot, tmp_path):
    win = _window(qtbot, tmp_path); win._async_enabled = False
    win.open_fits(_make_fits(tmp_path))
    win._record_colourise(AstroImage(np.zeros((12, 12, 3), np.float32), is_linear=False))
    assert [n for n, _ in win.project.entries()][-1] == "Colourise"
```

Also **delete** the old `test_open_palette_requires_image` and `test_record_palette_adds_history_step` (replaced above).

- [ ] **Step 2: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q -k "colourise or advanced_palette"`
Expected: FAIL (`_colourise`/`_record_colourise`/`_open_advanced_palette` don't exist).

- [ ] **Step 3: Add the palette import**

In `seestar_processor/ui/main_window.py`, add near the other `..core` imports:
```python
from ..core.palette import PaletteParams, compose, render_nebula
```

- [ ] **Step 4: Add the stretch-preceding helper and preservation rule**

Add a helper method (near `_leading_kept`):
```python
    def _stretch_preceding(self) -> set:
        """Names of the steps that precede the reveal (stretch) position — the
        predecessors a Colourise or Apply-Stretch preserves."""
        return set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index("stretch")]
        }
```

In `apply_current`, after the `preceding = ...` block and before `target = ...`, add:
```python
        if STEP_NAME["stretch"] in preceding:
            preceding.add("Colourise")   # Colourise occupies the stretch position
```

- [ ] **Step 5: Add star removal + cache + the Colourise handler**

Add these methods (near `_open_palette`, which you replace below). Initialise the cache field in `__init__` (near `self._async_enabled = True`): `self._colourise_layers = None`.

```python
    def _remove_stars(self, img):
        rc = RCAstro(resolve_binary(self.settings.rcastro_path))
        return rc.remove_stars(img, runner=self._rc_runner)

    def _colourise_starx(self, base):
        sig = (base.data.shape, float(base.data.mean()), float(base.data.std()))
        if self._colourise_layers is not None and self._colourise_layers[0] == sig:
            return self._colourise_layers[1], self._colourise_layers[2]
        if rcastro_valid(self.settings):
            starless, stars = self._remove_stars(base)
        else:
            starless, stars = base, None
        self._colourise_layers = (sig, starless, stars)
        return starless, stars

    def _colourise(self) -> None:
        if self.project is None or self._busy:
            return
        self.project.jump_back(
            self._leading_kept(self.project.entries(), self._stretch_preceding()))
        base = self.project.current()
        if not base.is_color:
            self._status.setText("Colourise needs a colour image.")
            self._refresh()
            return
        self._status.setText("")
        self._set_busy(True)

        def work():
            starless, stars = self._colourise_starx(base)
            if stars is None:
                return render_nebula(starless, PaletteParams())
            return compose(starless, stars, PaletteParams())

        def done(result):
            self.project.run_step(_PrecomputedStep("Colourise", result), "")
            self.log_panel.append_entry(
                format_log_entry("Colourise", "", rms_delta(base, result)))
            self._set_busy(False)
            self._refresh()

        def err(exc):
            self._set_busy(False)
            self._status.setText(f"Colourise failed: {exc}")

        if self._async_enabled:
            run_async(self._pool, work, done, err)
        else:
            try:
                done(work())
            except Exception as exc:  # mirror the async error path
                err(exc)
```

- [ ] **Step 6: Replace `_open_palette`/`_record_palette` with the Advanced + record handlers**

Replace the existing `_open_palette` and `_record_palette` methods with:
```python
    def _open_advanced_palette(self) -> None:
        if self.project is None:
            self._status.setText("Open or stack an image first.")
            return
        self.project.jump_back(
            self._leading_kept(self.project.entries(), self._stretch_preceding()))
        base = self.project.current()
        if not base.is_color:
            self._status.setText("Palette needs a colour image.")
            return
        starless, stars = self._colourise_starx(base)    # reuse cache
        from .palette_dialog import PaletteDialog
        PaletteDialog(self.settings, base, self, on_apply=self._record_colourise,
                      starless=starless, stars=stars).exec()

    def _record_colourise(self, result) -> None:
        self.project.jump_back(
            self._leading_kept(self.project.entries(), self._stretch_preceding()))
        self.project.run_step(_PrecomputedStep("Colourise", result), "")
        self._status.setText("")
        self.log_panel.append_entry(format_log_entry("Colourise", "", None))
        self._refresh()
```

- [ ] **Step 7: Remove the toolbar Palette action**

In `_build_toolbar`, delete the line:
```python
        tb.addAction(load_icon("palette", ACCENT), "Palette…", self._open_palette)
```
(The palette is now reached from the Stretch panel — wired in Task 3.)

- [ ] **Step 8: Mark the stretch stage done after Colourise**

In `_done_ids`, after the `STEP_NAME` loop, add:
```python
        if "Colourise" in applied:
            done.add("stretch")
```

- [ ] **Step 9: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q`
Expected: PASS (new colourise/advanced tests + all existing).

- [ ] **Step 10: Commit**

```bash
git add seestar_processor/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat: one-press Colourise engine + history preservation + Advanced wiring"
```

---

### Task 3: Stretch-panel buttons, narrowband Color tip, panel wiring

**Files:**
- Modify: `seestar_processor/ui/step_panels.py` (`build_panel` signature; `stretch` branch ~160-182; `auto` branch tip)
- Modify: `seestar_processor/ui/main_window.py` (`_rebuild_panel` `build_panel(...)` call ~562)
- Test: `tests/ui/test_step_panels.py`

**Interfaces:**
- Consumes: `MainWindow._colourise` / `_open_advanced_palette` (Task 2).
- Produces: stretch panel attrs `colourise_btn`, `advanced_btn`; `build_panel(..., on_colourise=None, on_palette_advanced=None)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_step_panels.py` (add `from PySide6.QtWidgets import QLabel` at the top if absent):

```python
def test_stretch_panel_has_colourise_and_advanced(qtbot):
    cols, advs = [], []
    w = build_panel(_stage("stretch"),
                    on_colourise=lambda: cols.append(1),
                    on_palette_advanced=lambda: advs.append(1))
    qtbot.addWidget(w)
    assert hasattr(w, "colourise_btn") and hasattr(w, "advanced_btn")
    w.colourise_btn.click(); w.advanced_btn.click()
    assert cols == [1] and advs == [1]
    w.apply_btn.click()          # Apply Stretch still works (no crash)


def test_color_panel_has_narrowband_tip(qtbot):
    from PySide6.QtWidgets import QLabel
    w = build_panel(_stage("color"))
    qtbot.addWidget(w)
    texts = [c.text().lower() for c in w.findChildren(QLabel)]
    assert any("skip" in t and ("narrowband" in t or "dualband" in t) for t in texts)
```

- [ ] **Step 2: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_step_panels.py -q -k "colourise or narrowband"`
Expected: FAIL (`build_panel` has no `on_colourise`; no `colourise_btn`; no tip).

- [ ] **Step 3: Add the params to `build_panel`**

In `seestar_processor/ui/step_panels.py`, add to the `build_panel` signature (after `on_export=None,`):
```python
    on_colourise=None,
    on_palette_advanced=None,
```

- [ ] **Step 4: Add the narrowband tip to the Color (`auto`) panel**

In the `elif stage.kind == "auto":` branch, immediately after the existing `_desc_label("Automatic background neutralization and white balance.")`, add:
```python
        lay.addWidget(_desc_label(
            "Dualband / narrowband image? Skip this — colour is applied later by Colourise."))
```

- [ ] **Step 5: Add the Colourise + Advanced buttons to the stretch panel**

Replace the `elif stage.kind == "stretch":` branch with:
```python
    elif stage.kind == "stretch":
        lay.addWidget(_desc_label("Brighten the faint detail so the target appears."))
        slider = ResetSlider(50)
        target = QComboBox()
        target.addItems(list(STRETCH_TARGET_DEFAULTS))
        target.currentTextChanged.connect(
            lambda t: slider.setValue(STRETCH_TARGET_DEFAULTS[t])
        )
        apply_btn = QPushButton("Apply Stretch")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(slider.value() / 100.0))
        colourise_btn = QPushButton("Colourise (dualband → colour)")
        colourise_btn.setObjectName("primary")
        colourise_btn.setEnabled(apply_enabled)
        if on_colourise is not None:
            colourise_btn.clicked.connect(lambda: on_colourise())
        advanced_btn = QPushButton("Advanced…")
        advanced_btn.setEnabled(apply_enabled)
        if on_palette_advanced is not None:
            advanced_btn.clicked.connect(lambda: on_palette_advanced())
        lay.addWidget(QLabel("Target"))
        lay.addWidget(target)
        lay.addWidget(QLabel("Aggressiveness (gentle → punchy)"))
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        lay.addWidget(_desc_label(
            "Dualband (Ha/OIII) image? Press Colourise for one-press colour."))
        lay.addWidget(colourise_btn)
        lay.addWidget(advanced_btn)
        w.target_box = target
        w.stretch_slider = slider
        w.apply_btn = apply_btn
        w.colourise_btn = colourise_btn
        w.advanced_btn = advanced_btn
```

- [ ] **Step 6: Wire the callbacks in `_rebuild_panel`**

In `seestar_processor/ui/main_window.py`, in the `build_panel(...)` call inside `_rebuild_panel`, add (alongside `on_remove_green=...`):
```python
            on_colourise=self._colourise,
            on_palette_advanced=self._open_advanced_palette,
```

- [ ] **Step 7: Run the panel tests + full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_step_panels.py -q`
Then: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass (rerun the known sharpen flake alone if it trips).

- [ ] **Step 8: Commit**

```bash
git add seestar_processor/ui/step_panels.py seestar_processor/ui/main_window.py \
        tests/ui/test_step_panels.py
git commit -m "feat: Colourise + Advanced buttons on the Stretch step; narrowband Color tip"
```

---

## Self-Review

- **Spec coverage:** one-press engine (T2 `_colourise`), StarX cache (T2 `_colourise_starx`), history preservation (T2 apply_current + done_ids), stretch-position recording (T2), Advanced seeded dialog (T1 seeding + T2 `_open_advanced_palette`), stretch-panel buttons (T3), Color-step tip (T3), whole-image fallback (T2) — all covered. Recipe capture is explicitly out of scope per the spec.
- **Placeholder scan:** none — complete code in every step.
- **Type consistency:** `_colourise`/`_record_colourise`/`_open_advanced_palette`/`_colourise_starx`/`_remove_stars`/`_stretch_preceding`, `"Colourise"` step name, `colourise_btn`/`advanced_btn`, and `PaletteDialog(..., starless=, stars=)` are used identically across tasks and tests.
- **Green-at-boundary:** T1 additive (dialog kwargs default None). T2 replaces `_open_palette`/`_record_palette` and their two tests together, adds handlers, removes toolbar action — suite green at T2 end. T3 wires panel to T2 handlers — green at T3 end.
- **Bug fixes verified:** preservation (bug 1) covered by `test_colourise_preserved_after_later_step`; stars screened via `compose` on the one-press path and the seeded Advanced path (bug 2) — `_colourise_starx` supplies real `stars` so `compose` runs.
