# GraXpert AI Denoise + Engine Choice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire GraXpert AI denoise into the Noise Reduction step as a choosable engine (global default + per-image override) with graceful fallback.

**Architecture:** Fix the `GraXpert.denoise` CLI (verified `-strength`), give `NoiseSharpenStep` both tool handles and an engine-resolution rule (chosen → other → TV), add a `denoise_engine` setting + Settings dropdown, and a Noise-panel "Engine" dropdown (shown only when both are installed). The applied option becomes `{"engine","level"}`, captured by recipes via the existing pass-through.

**Tech Stack:** Python, PySide6, pytest/pytest-qt. GraXpert 3.0.2 CLI (`-cmd denoising … -strength <0-1>`), RC-Astro NoiseXTerminator, skimage TV fallback.

## Global Constraints

- **GraXpert denoise CLI (verified against GraXpert 3.0.2):** `graxpert -cli -cmd denoising <in> -output <out> -strength <0-1>`. The denoising parser REJECTS `-smoothing` (that flag is background-extraction only). Do not force `-gpu`.
- **Engine resolution rule (exact):** chosen engine installed → use it; else the OTHER installed engine → use it; else TV fallback. Chosen = per-image panel override, or (if "Default") the `denoise_engine` setting. Default engine when both installed = **RC-Astro**.
- **Preset strengths:** NoiseX `{light:0.75, medium:0.90, strong:0.95}` (unchanged); GraXpert `{light:0.5, medium:0.7, strong:0.9}` (starting point, calibrated by the user later); TV `{light:0.4, medium:0.7, strong:0.9}` (unchanged).
- **Option format:** `{"engine": "rcastro"|"graxpert", "level": "light|medium|strong"}`; a legacy bare-string level (`"medium"`) must still work (engine `None` → auto-resolve, preferring RC-Astro).
- **Backward compatibility:** existing `NoiseSharpenStep(rcastro=...)` call sites and existing noise tests must keep working (graxpert defaults to `None`).
- Keep the full suite green. Stage only named files (pre-existing untracked files exist: icon.png, logo.png, site.zip — never `git add -A`).

---

### Task 1: Fix `GraXpert.denoise` CLI flag

**Files:**
- Modify: `nocturne/tools/graxpert.py`
- Test: `tests/tools/test_graxpert.py` (create if absent; otherwise add to the existing GraXpert test file)

**Interfaces:**
- Produces: `GraXpert.denoise(img, strength, *, runner=run_cli)` builds `-cmd denoising … -strength <s>`; `GraXpert.background_extraction(...)` still builds `-smoothing`.

- [ ] **Step 1: Write the failing test**

Create `tests/tools/test_graxpert.py`:

```python
from nocturne.core.image import AstroImage
from nocturne.tools.base import write_temp_fits
from nocturne.tools.graxpert import GraXpert
import numpy as np


def _capture():
    calls = []

    def fake(args):
        calls.append(args)
        # write an output file where GraXpert would (out + ".fits") so _find_output succeeds
        out = args[args.index("-output") + 1]
        write_temp_fits(AstroImage(np.zeros((4, 4), np.float32)), out + ".fits")
    return calls, fake


def test_denoise_uses_strength_not_smoothing():
    img = AstroImage(np.random.rand(4, 4).astype(np.float32))
    calls, fake = _capture()
    GraXpert("/fake/graxpert").denoise(img, 0.7, runner=fake)
    args = calls[0]
    assert args[args.index("-cmd") + 1] == "denoising"
    assert "-strength" in args and args[args.index("-strength") + 1] == "0.7"
    assert "-smoothing" not in args


def test_background_extraction_still_uses_smoothing():
    img = AstroImage(np.random.rand(4, 4).astype(np.float32))
    calls, fake = _capture()
    GraXpert("/fake/graxpert").background_extraction(img, 0.3, runner=fake)
    args = calls[0]
    assert args[args.index("-cmd") + 1] == "background-extraction"
    assert "-smoothing" in args and args[args.index("-smoothing") + 1] == "0.3"
    assert "-strength" not in args
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/tools/test_graxpert.py -q`
Expected: FAIL — denoise currently emits `-smoothing`.

- [ ] **Step 3: Implement — make the strength flag per-command**

In `nocturne/tools/graxpert.py`, change the two public methods and `_run` to pass the correct flag:

```python
    def background_extraction(
        self, img: AstroImage, strength: float, *, runner=run_cli
    ) -> AstroImage:
        return self._run("background-extraction", "-smoothing", img, strength, runner)

    def denoise(self, img: AstroImage, strength: float, *, runner=run_cli) -> AstroImage:
        return self._run("denoising", "-strength", img, strength, runner)

    def _run(self, command: str, strength_flag: str, img: AstroImage,
             strength: float, runner) -> AstroImage:
        tmp = tempfile.mkdtemp(prefix="gx_")
        in_fits = os.path.join(tmp, "in.fits")
        out_fits = os.path.join(tmp, "out.fits")
        try:
            write_temp_fits(img, in_fits)
            # `-cli` is mandatory; `-output` is the base output filename; the
            # strength flag differs per command: background-extraction uses
            # `-smoothing`, denoising uses `-strength` (GraXpert 3.x).
            runner([
                self.binary_path, "-cli", "-cmd", command,
                in_fits, "-output", out_fits, strength_flag, str(strength),
            ])
            produced = out_fits if os.path.exists(out_fits) else self._find_output(tmp, in_fits)
            result = read_fits_array(produced)
            result.is_linear = img.is_linear
            return result
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/tools/test_graxpert.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (existing count + 2). Note: `tests/steps/test_new_steps.py::test_background_light_calls_graxpert` must still pass (background keeps `-smoothing`).

- [ ] **Step 6: Commit**

```bash
git add nocturne/tools/graxpert.py tests/tools/test_graxpert.py
git commit -m "fix(graxpert): denoise uses -strength (verified GraXpert 3.0.2), not -smoothing"
```

---

### Task 2: Engine resolution in `NoiseSharpenStep` + factory

**Files:**
- Modify: `nocturne/steps/noise_sharpen.py`
- Modify: `nocturne/steps/factory.py`
- Test: `tests/steps/test_new_steps.py` (add matrix + recipe round-trip tests)

**Interfaces:**
- Consumes: `GraXpert.denoise` (Task 1); `nocturne.core.noise.reduce_noise`; `nocturne.settings.graxpert_valid`.
- Produces: `NoiseSharpenStep(rcastro=None, graxpert=None)`, `apply(img, option)` where option is `{"engine","level"}` or a legacy level string; `parse_noise_option(option) -> (engine, level)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/steps/test_new_steps.py`:

```python
def test_noise_engine_resolution_matrix():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.steps.noise_sharpen import NoiseSharpenStep

    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))

    class FakeRC:
        def __init__(self): self.called = False
        def denoise(self, image, strength, runner=None):
            self.called = True; return image

    class FakeGX:
        def __init__(self): self.called = False
        def denoise(self, image, strength, runner=None):
            self.called = True; return image

    def run(option, rc, gx):
        r, g = (FakeRC() if rc else None), (FakeGX() if gx else None)
        NoiseSharpenStep(r, g).apply(img, option)
        return (r.called if r else False), (g.called if g else False)

    # both installed -> honour the chosen engine
    assert run({"engine": "rcastro", "level": "medium"}, True, True) == (True, False)
    assert run({"engine": "graxpert", "level": "medium"}, True, True) == (False, True)
    # legacy bare string / no engine -> prefer RC-Astro
    assert run("medium", True, True) == (True, False)
    # only the OTHER engine installed -> fall back to it
    assert run({"engine": "rcastro", "level": "medium"}, False, True) == (False, True)
    assert run({"engine": "graxpert", "level": "medium"}, True, False) == (True, False)


def test_noise_neither_engine_falls_back_to_tv():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.steps.noise_sharpen import NoiseSharpenStep
    rng = np.random.default_rng(0)
    img = AstroImage(np.clip(0.5 + rng.normal(0, 0.1, (24, 24, 3)), 0, 1).astype(np.float32))
    out = NoiseSharpenStep(None, None).apply(img, {"engine": "graxpert", "level": "strong"})
    assert out.data.shape == img.data.shape
    assert not np.allclose(out.data, img.data)          # TV changed the image


def test_noise_graxpert_strength_per_preset():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.steps.noise_sharpen import NoiseSharpenStep
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    seen = {}

    class FakeGX:
        def denoise(self, image, strength, runner=None):
            seen["s"] = strength; return image

    for level, expected in (("light", 0.5), ("medium", 0.7), ("strong", 0.9)):
        NoiseSharpenStep(None, FakeGX()).apply(img, {"engine": "graxpert", "level": level})
        assert seen["s"] == expected


def test_noise_recipe_option_round_trips():
    from nocturne.recipe import serialize_option, deserialize_option
    opt = {"engine": "graxpert", "level": "strong"}
    back = deserialize_option("noise_sharpen", serialize_option("noise_sharpen", opt))
    assert back == opt
    assert deserialize_option("noise_sharpen", serialize_option("noise_sharpen", "medium")) == "medium"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/steps/test_new_steps.py -k noise -q`
Expected: FAIL — `NoiseSharpenStep` takes one arg / no `parse` behaviour yet.

- [ ] **Step 3: Implement the step**

Replace the body of `nocturne/steps/noise_sharpen.py`:

```python
from __future__ import annotations

from ..core.image import AstroImage
from ..core.noise import reduce_noise
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.graxpert import GraXpert
from ..tools.rcastro import RCAstro

_NXT_LEVELS = {"light": 0.75, "medium": 0.90, "strong": 0.95}  # RC-Astro NoiseXTerminator
_GX_LEVELS = {"light": 0.5, "medium": 0.7, "strong": 0.9}      # GraXpert AI denoise (calibrate)
_TV_LEVELS = {"light": 0.4, "medium": 0.7, "strong": 0.9}      # free TV fallback


def parse_noise_option(option) -> tuple[str | None, str]:
    """Return (engine, level). option is {"engine","level"} (engine in
    {"rcastro","graxpert"}) or a legacy bare level string (engine None)."""
    if isinstance(option, dict):
        return option.get("engine"), option.get("level", "medium")
    return None, (option if option in _TV_LEVELS else "medium")


class NoiseSharpenStep(Step):
    """Post-stretch denoise. Engine = chosen (RC-Astro NoiseXTerminator or
    GraXpert AI); falls back to the other installed engine, then to free TV."""

    name = "Noise Reduction"

    def __init__(self, rcastro: RCAstro | None = None,
                 graxpert: GraXpert | None = None) -> None:
        self._rc = rcastro
        self._gx = graxpert
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["light", "medium", "strong"]

    def default_option(self) -> str:
        return "medium"

    def apply(self, img: AstroImage, option) -> AstroImage:
        engine, level = parse_noise_option(option)
        order = ["graxpert", "rcastro"] if engine == "graxpert" else ["rcastro", "graxpert"]
        for e in order:
            if e == "rcastro" and self._rc is not None:
                return self._rc.denoise(img, _NXT_LEVELS[level], runner=self._runner)
            if e == "graxpert" and self._gx is not None:
                return self._gx.denoise(img, _GX_LEVELS[level], runner=self._runner)
        return reduce_noise(img, _TV_LEVELS[level])
```

- [ ] **Step 4: Wire both tools in the factory**

In `nocturne/steps/factory.py`: add `graxpert_valid` to the settings import (it already imports `rcastro_valid, resolve_binary`), and replace the `noise_sharpen` case:

```python
    if stage_id == "noise_sharpen":
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        gx = GraXpert(resolve_binary(settings.graxpert_path)) if graxpert_valid(settings) else None
        step = NoiseSharpenStep(rc, gx)
        step._runner = rc_runner
        return step
```

(`GraXpert` is already imported in factory.py for the background step; ensure `graxpert_valid` is imported from `..settings`.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/steps/test_new_steps.py -k noise -q`
Expected: PASS. Confirm the pre-existing noise tests (`test_noise_sharpen_rcastro_strength_per_preset`, `test_noise_sharpen_fallback_changes_image`, `test_noise_sharpen_fallback_strength_unchanged`) still pass — they call `NoiseSharpenStep(rcastro=...)` with a bare-string option, which the new signature and `parse_noise_option` still support.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add nocturne/steps/noise_sharpen.py nocturne/steps/factory.py tests/steps/test_new_steps.py
git commit -m "feat(noise): engine resolution (NoiseX / GraXpert / TV) with fallback + presets"
```

---

### Task 3: `denoise_engine` setting + Settings dialog dropdown

**Files:**
- Modify: `nocturne/settings.py`
- Modify: `nocturne/ui/settings_dialog.py`
- Test: `tests/` settings test (add to the existing settings test file; create `tests/test_settings.py` if none) + `tests/ui/test_settings_dialog.py` (add or create)

**Interfaces:**
- Produces: `Settings.denoise_engine: str = "rcastro"`; `SettingsDialog.result_settings()` returns it; a `denoise_box` combo with items `["RC-Astro", "GraXpert"]`.

- [ ] **Step 1: Write the failing tests**

Add a settings-persistence test (in the existing settings test module, e.g. `tests/test_settings.py`):

```python
def test_denoise_engine_persists(tmp_path):
    from nocturne.settings import Settings, save_settings, load_settings
    p = str(tmp_path / "s.json")
    save_settings(Settings(graxpert_path="g", rcastro_path="r", base_dir="d",
                           denoise_engine="graxpert"), p)
    assert load_settings(p).denoise_engine == "graxpert"


def test_denoise_engine_defaults_to_rcastro(tmp_path):
    from nocturne.settings import Settings, save_settings, load_settings
    p = str(tmp_path / "s.json")
    save_settings(Settings(), p)                 # no engine set
    assert load_settings(p).denoise_engine == "rcastro"
```

Add a dialog test (`tests/ui/test_settings_dialog.py`):

```python
import pytest
pytest.importorskip("PySide6")
from nocturne.settings import Settings                       # noqa: E402
from nocturne.ui.settings_dialog import SettingsDialog       # noqa: E402


def test_dialog_round_trips_denoise_engine(qtbot):
    d = SettingsDialog(Settings(denoise_engine="graxpert"))
    qtbot.addWidget(d)
    assert d.denoise_box.currentText() == "GraXpert"
    assert d.result_settings().denoise_engine == "graxpert"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_settings.py tests/ui/test_settings_dialog.py -q`
Expected: FAIL — no `denoise_engine` field / `denoise_box`.

- [ ] **Step 3: Add the settings field**

In `nocturne/settings.py`, add the field to the dataclass (after `base_dir`) and to `load_settings`:

```python
@dataclass
class Settings:
    graxpert_path: str = ""
    rcastro_path: str = ""
    base_dir: str = ""
    denoise_engine: str = "rcastro"
```

```python
    return Settings(
        graxpert_path=data.get("graxpert_path", ""),
        rcastro_path=data.get("rcastro_path", ""),
        base_dir=data.get("base_dir", ""),
        denoise_engine=data.get("denoise_engine", "rcastro"),
    )
```

`save_settings` uses `json.dump(asdict(s), ...)`, so the new dataclass field serialises automatically — no change to `save_settings` needed.

- [ ] **Step 4: Add the dropdown to the Settings dialog**

In `nocturne/ui/settings_dialog.py`, import `QComboBox`, build the combo in `__init__`, add a form row, and include it in `result_settings`:

```python
        from PySide6.QtWidgets import QComboBox  # (or add to the top import block)
        self.denoise_box = QComboBox()
        self.denoise_box.addItems(["RC-Astro", "GraXpert"])
        self.denoise_box.setCurrentText(
            "GraXpert" if settings.denoise_engine == "graxpert" else "RC-Astro")
```

Add the row after the RC-Astro path row:

```python
        form.addRow("Preferred denoise engine", self.denoise_box)
```

Update `result_settings`:

```python
    def result_settings(self) -> Settings:
        return Settings(
            graxpert_path=self._gx.text().strip(),
            rcastro_path=self._rc.text().strip(),
            base_dir=self._dir.text().strip(),
            denoise_engine=("graxpert" if self.denoise_box.currentText() == "GraXpert"
                            else "rcastro"),
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_settings.py tests/ui/test_settings_dialog.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add nocturne/settings.py nocturne/ui/settings_dialog.py tests/test_settings.py tests/ui/test_settings_dialog.py
git commit -m "feat(settings): denoise_engine preference + Settings dropdown"
```

---

### Task 4: Noise panel engine dropdown + main_window wiring

**Files:**
- Modify: `nocturne/ui/step_panels.py` (Noise panel dropdown + option builder)
- Modify: `nocturne/ui/main_window.py` (pass choices into `build_panel`; log formatting)
- Test: `tests/ui/test_step_panels.py` (add; create if needed) + `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `Settings.denoise_engine` (Task 3); `parse_noise_option` semantics (Task 2); `graxpert_valid`/`rcastro_valid`.
- Produces: `build_panel(..., denoise_engine_choices=None, denoise_default_engine="rcastro")`; the noise panel's Apply calls `on_apply({"engine": <resolved>, "level": <level>})`; `w.engine_box` when the dropdown is shown.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_step_panels.py`:

```python
import pytest
pytest.importorskip("PySide6")
from nocturne.ui.pipeline import path_stages                # noqa: E402
from nocturne.ui.step_panels import build_panel             # noqa: E402


def _noise_stage():
    return next(s for s in path_stages() if s.id == "noise_sharpen")


def test_noise_engine_dropdown_shown_when_both_installed(qtbot):
    captured = []
    w = build_panel(_noise_stage(), on_apply=captured.append,
                    denoise_engine_choices=["Default", "RC-Astro", "GraXpert"],
                    denoise_default_engine="rcastro")
    qtbot.addWidget(w)
    assert hasattr(w, "engine_box")
    w.engine_box.setCurrentText("GraXpert")
    w.option_box.setCurrentText("strong")
    w.apply_btn.click()
    assert captured == [{"engine": "graxpert", "level": "strong"}]


def test_noise_default_choice_uses_setting(qtbot):
    captured = []
    w = build_panel(_noise_stage(), on_apply=captured.append,
                    denoise_engine_choices=["Default", "RC-Astro", "GraXpert"],
                    denoise_default_engine="graxpert")
    qtbot.addWidget(w)
    # "Default" resolves to the passed default engine
    w.engine_box.setCurrentText("Default")
    w.option_box.setCurrentText("medium")
    w.apply_btn.click()
    assert captured == [{"engine": "graxpert", "level": "medium"}]


def test_noise_no_dropdown_when_not_both_installed(qtbot):
    captured = []
    w = build_panel(_noise_stage(), on_apply=captured.append,
                    denoise_engine_choices=None, denoise_default_engine="rcastro")
    qtbot.addWidget(w)
    assert not hasattr(w, "engine_box")
    w.option_box.setCurrentText("light")
    w.apply_btn.click()
    assert captured == [{"engine": "rcastro", "level": "light"}]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py -k noise -q`
Expected: FAIL — `build_panel` has no `denoise_engine_choices` kwarg.

- [ ] **Step 3: Add the kwargs + dropdown + option builder**

In `nocturne/ui/step_panels.py` `build_panel`, add two keyword params (near `option_default`):

```python
    denoise_engine_choices: list | None = None,
    denoise_default_engine: str = "rcastro",
```

In the `stage.kind == "process"` branch, after `box` is built and before `apply_btn` is wired, add the engine dropdown and an option builder. Replace the existing `if on_apply is not None: apply_btn.clicked.connect(lambda: on_apply(box.currentText()))` block with:

```python
        engine_box = None
        if stage.id == "noise_sharpen" and denoise_engine_choices:
            engine_box = QComboBox()
            engine_box.addItems(denoise_engine_choices)   # ["Default","RC-Astro","GraXpert"]
            lay.addWidget(QLabel("Engine"))
            lay.addWidget(engine_box)
            w.engine_box = engine_box

        def _noise_apply_option():
            level = box.currentText()
            if stage.id != "noise_sharpen":
                return level                              # background / deconvolution: bare level
            if engine_box is not None:
                sel = engine_box.currentText()
                engine = (denoise_default_engine if sel == "Default"
                          else "graxpert" if sel == "GraXpert" else "rcastro")
            else:
                engine = denoise_default_engine
            return {"engine": engine, "level": level}

        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(_noise_apply_option()))
```

Keep the existing `lay.addWidget(QLabel("Strength")); lay.addWidget(box); lay.addWidget(apply_btn); lay.addWidget(note)` ordering (Engine appears above Strength).

- [ ] **Step 4: Pass choices from main_window + format the log**

In `nocturne/ui/main_window.py` `_rebuild_panel`, compute the choices and pass them into `build_panel`:

```python
        both_denoise = graxpert_valid(self.settings) and rcastro_valid(self.settings)
        denoise_choices = ["Default", "RC-Astro", "GraXpert"] if both_denoise else None
```

Add these two kwargs to the `build_panel(...)` call (alongside `option_default=`):

```python
            denoise_engine_choices=denoise_choices,
            denoise_default_engine=self.settings.denoise_engine,
```

In `_log_step`, add a readable branch for the dict option (before the `elif isinstance(option, float)` branch):

```python
        elif stage_id == "noise_sharpen" and isinstance(option, dict):
            label = f"{option.get('level', 'medium')} ({option.get('engine') or 'auto'})"
```

(`graxpert_valid` is already imported in main_window.py — it's used for the background gate.)

- [ ] **Step 5: Add a main_window integration test**

Add to `tests/ui/test_main_window.py` (uses the file's `_window`/`_make_fits`/`_go_to_id` helpers):

```python
def test_noise_records_engine_dict_option(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.6)
    win._go_to_id("noise_sharpen")
    win.apply_current({"engine": "graxpert", "level": "medium"})   # simulate panel option
    names = [n for n, _ in win.project.entries()]
    assert "Noise Reduction" in names
    # the recorded option is the dict, so a recipe captures the engine
    from nocturne.recipe import recipe_from_entries
    steps = recipe_from_entries(win.project.entries())
    ns = [s for s in steps.steps if s["stage"] == "noise_sharpen"]
    assert ns and ns[0]["option"] == {"engine": "graxpert", "level": "medium"}
```

Note: `apply_current` runs the real step. With neither GraXpert nor RC-Astro configured in the test settings, `NoiseSharpenStep` falls back to TV — the apply still succeeds and records the dict option, which is what this test checks.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py tests/ui/test_main_window.py -k "noise" -q`
Expected: PASS.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add nocturne/ui/step_panels.py nocturne/ui/main_window.py tests/ui/test_step_panels.py tests/ui/test_main_window.py
git commit -m "feat(noise): Engine dropdown in the Noise panel + main_window wiring + log label"
```

---

## After all tasks

- Whole-branch review (opus): engine-resolution correctness (the full fallback matrix), the verified GraXpert CLI, recipe portability (a GraXpert recipe on an RC-Astro-only machine falls back), no regression to Background (still `-smoothing`) or existing noise tests.
- **User real-data validation:** GraXpert AI denoise vs NoiseXTerminator vs TV on NGC 7000; **calibrate `_GX_LEVELS`** so light/medium/strong feel right; confirm the Engine dropdown + global default behave.
- Then `superpowers:finishing-a-development-branch`.

## Help / docs (fold into Task 4 if time; else TODO)

- Update the Noise Reduction help topic to mention the two AI engines + the free fallback and the Engine selector. Non-blocking.
