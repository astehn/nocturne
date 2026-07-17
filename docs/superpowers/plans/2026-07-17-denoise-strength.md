# Denoise Preset Recalibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the under-denoising of the Noise Reduction step by recalibrating the RC-Astro NoiseXTerminator strengths to evidence-based values, without changing the free TV fallback.

**Architecture:** Split the single `_LEVELS` strength map in `noise_sharpen.py` into two path-specific maps — `_NXT_LEVELS` (recalibrated) for the NoiseX path and `_TV_LEVELS` (unchanged) for the free fallback — so the two denoisers are decoupled.

**Tech Stack:** Python 3.13 (`.venv/bin/python`), pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-denoise-strength-design.md`

## Global Constraints

- Run tests with `.venv/bin/python -m pytest <path> -q` from `/Volumes/Work/Code/Editor`.
- NoiseX strengths (exact): `_NXT_LEVELS = {"light": 0.75, "medium": 0.90, "strong": 0.95}`.
- TV fallback strengths stay exactly as today: `_TV_LEVELS = {"light": 0.4, "medium": 0.7, "strong": 0.9}`.
- No CLI flag changes (plain `--denoise <strength>`); `RCAstro.denoise` / `reduce_noise` signatures untouched.
- Recipes serialize the option label (e.g. `"medium"`), not the number — do not change option strings.
- Commit with trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Recalibrate NoiseX strengths, decouple the fallback map

**Files:**
- Modify: `nocturne/steps/noise_sharpen.py`
- Test: `tests/steps/test_new_steps.py`

**Interfaces:**
- Consumes: `RCAstro.denoise(img, strength, *, runner)` and `reduce_noise(img, strength)` (both unchanged).
- Produces: module maps `_NXT_LEVELS` and `_TV_LEVELS` in `noise_sharpen.py`; `NoiseSharpenStep.apply` routes NoiseX vs fallback to the respective map. Option labels (`light`/`medium`/`strong`) unchanged.

- [ ] **Step 1: Write/extend the failing tests**

In `tests/steps/test_new_steps.py`, replace `test_noise_sharpen_uses_rcastro_when_present` with a version that asserts the exact strength, and add a fallback-strength test. (The existing `test_noise_sharpen_fallback_changes_image` stays.)

```python
def test_noise_sharpen_rcastro_strength_per_preset():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    calls = []

    def fake(args):
        calls.append(args)
        write_temp_fits(img, args[args.index("-o") + 1])

    def denoise_strength(option):
        calls.clear()
        step = NoiseSharpenStep(rcastro=RCAstro("/fake/rc-astro"))
        step._runner = fake
        step.apply(img, option)
        args = calls[0]
        assert args[args.index("--no-banner") + 1] == "nxt"   # denoise product
        return float(args[args.index("--denoise") + 1])

    assert denoise_strength("light") == 0.75
    assert denoise_strength("medium") == 0.90
    assert denoise_strength("strong") == 0.95


def test_noise_sharpen_fallback_strength_unchanged():
    from nocturne.steps import noise_sharpen as ns
    assert ns._TV_LEVELS == {"light": 0.4, "medium": 0.7, "strong": 0.9}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/steps/test_new_steps.py -q`
Expected: FAIL — `test_noise_sharpen_rcastro_strength_per_preset` sees the old 0.7/0.9 values (medium assertion fails), and `_TV_LEVELS` does not exist yet (`AttributeError`).

- [ ] **Step 3: Implement in `nocturne/steps/noise_sharpen.py`**

Replace the `_LEVELS` constant and the `apply` body:

```python
_NXT_LEVELS = {"light": 0.75, "medium": 0.90, "strong": 0.95}  # RC-Astro NoiseXTerminator --denoise
_TV_LEVELS = {"light": 0.4, "medium": 0.7, "strong": 0.9}      # free TV fallback (unchanged)
```

```python
    def apply(self, img: AstroImage, option: str) -> AstroImage:
        if self._rc is not None:
            return self._rc.denoise(img, _NXT_LEVELS[option], runner=self._runner)
        return reduce_noise(img, _TV_LEVELS[option])
```

(Remove the old `_LEVELS` definition and the `dn = _LEVELS[option]` line.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/steps/test_new_steps.py -q`
Expected: all PASS.

- [ ] **Step 5: Run the broader step + recipe + pipeline suites**

Run: `.venv/bin/python -m pytest tests/steps/ tests/test_recipe.py tests/ui/test_pipeline.py -q`
Expected: all PASS (no other test asserts on the old strength numbers).

- [ ] **Step 6: Commit**

```bash
git add nocturne/steps/noise_sharpen.py tests/steps/test_new_steps.py
git commit -m "fix(denoise): recalibrate NoiseX presets to 0.75/0.90/0.95, decouple free fallback"
```

---

### Task 2: Full suite + real-data recipe-replay validation

**Files:** none expected (fix regressions if found); scratch driver only.

- [ ] **Step 1: Full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 2: Replay the user's recipe with the new presets**

Write a scratch script (do NOT commit) that loads the NGC 7000 master
(`/Volumes/Work2/Images/Astro/NGC 7000_sub/lights/NGC7000_182x20s_61min.fits`),
replays `~/Desktop/Noise.json` (color → stretch 0.5 → noise "medium") via
`nocturne.batch.apply_recipe` with real `Settings()` (RC-Astro active), and:
- saves a centre crop of the result to the scratchpad;
- runs sep star detection on the denoised result vs the undenoised
  stretched base and prints both counts.

Expected: the medium result now uses NoiseX 0.90; the crop is visibly clean
(matches the PixInsight-quality reference); star count does not drop vs base
(the sweep showed it rises). Present the crop.

- [ ] **Step 3: Update TODO / close out**

In `TODO.md`, mark the denoise strength issue resolved under "Done (recent)"
and note the residual open denoising ideas (dual-track starless architecture
for stretch/detail; free-TV-fallback calibration) as deferred. Commit.

```bash
git add TODO.md && git commit -m "docs: record denoise preset recalibration"
```

---

## Self-Review Notes

- Spec coverage: recalibration + decouple (Task 1); recipe-label safety is
  covered because option strings are untouched (asserted implicitly by the
  passing recipe suite in Task 1 Step 5 and the replay in Task 2); validation
  (Task 2).
- Type consistency: `_NXT_LEVELS`/`_TV_LEVELS` names used identically in the
  impl and the `_TV_LEVELS` test; strengths 0.75/0.90/0.95 match the Global
  Constraints and the per-preset test.
- No placeholders; the only real code change is two dict literals + a 3-line
  `apply`.
