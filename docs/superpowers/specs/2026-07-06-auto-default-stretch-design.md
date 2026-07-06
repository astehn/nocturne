# Auto Default Stretch — Design

**Date:** 2026-07-06
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — building under standing authorization.

## Motivation

The processing pipeline is Import → Crop → Background → Color → Deconvolution →
**Stretch** → Levels → … → Export. The steps after Stretch operate in display space
(0..1) and assume the data has actually been stretched. But nothing forces the user to
apply Stretch: they can jump ahead (Next, or clicking a later step in the stepper) while
the image is still **linear** (pixel values ~0.003). On such data, Levels' black-point
subtraction clips the whole frame to black (already guarded against, but as a dead-end),
and the other finishing steps produce poor results.

The terms "Stretch" and "Colourise" are also ambiguous to a new user, so requiring an
explicit choice before the finishing steps is a poor experience.

**Key reframing (PixInsight analogy):** Nocturne's live preview already behaves like
PixInsight's Screen Transfer Function (STF) — it auto-stretches the linear data *for
display only*, which is why a linear image looks fine on screen. What's missing is
committing that stretch to the **data** so the finishing steps have real stretched pixels.
So: when the user leaves Stretch without committing, **auto-commit a real default stretch
that matches what the preview already shows.**

## Decisions (from discussion)

- **Trigger:** when navigating to **any post-stretch _processing_ step** (Levels,
  Saturation, Noise Reduction, Local Contrast, Star Reduction, Enhancements) while the
  current image is still **linear**, first auto-commit a default Stretch, then land on the
  target. Fires for Next *and* stepper jumps, forward or backward. Navigation is funnelled
  through the single `_go_to(index)` method, so the whole feature lives there.
- **Default amount = 0.5** (mid-slider). `core/stretch.py` documents this as the value tuned
  so "what you preview is what you get" — the committed result matches the preview, so the
  image barely changes on screen; only the *data* becomes real.
- **Not Colourise.** The auto-default is a plain Stretch. Colourise is a heavy, opinionated
  transform (runs StarX, several seconds, needs RC-Astro) and stays a deliberate choice the
  user makes on the Stretch view. It cleanly replaces an auto-stretch later (it occupies the
  same stretch position).
- **Export is excluded.** Jumping straight to Export does **not** force a stretch —
  exporting a linear file (a clean base for external tools) is legitimate, and an output
  action should not silently transform data.
- **The Levels-on-linear guard stays** as a belt-and-suspenders safety net (added in a
  prior fix). With auto-stretch it should essentially never fire.
- **Committed as a normal, undoable "Stretch" history entry**, logged as "Stretch (auto)"
  so it is visible. Existing truncation logic treats it identically to a manual stretch.

## Architecture / changes

### `ui/pipeline.py`

Add a set naming the post-stretch processing stages that require a stretched image
(everything after `stretch` in the path except `export`):

```python
POST_STRETCH_IDS = frozenset({
    "levels", "saturation", "noise_sharpen", "local_contrast",
    "star_reduction", "enhancements",
})
```

(These are exactly the `_IN_APP_TAIL` stages minus `export`. Defined as a literal set
rather than derived, so the intent — and the Export exclusion — is explicit.)

### `ui/main_window.py`

**New `_ensure_stretched()`** — commit a default Stretch at the stretch position, mirroring
the manual Stretch apply path (same predecessor truncation), synchronous (pure NumPy, no
worker needed):

```python
def _ensure_stretched(self) -> None:
    """Commit a default Stretch (amount 0.5) at the stretch position, so the
    post-stretch finishing steps have real stretched data. Idempotent-ish: the
    caller only invokes this when the current image is still linear."""
    preceding = set(GEOMETRY_NAMES) | {
        STEP_NAME[sid]
        for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index("stretch")]
    }
    self.project.jump_back(self._leading_kept(self.project.entries(), preceding))
    base = self.project.current()
    result = self._step_for("stretch").apply(base, "")   # "" -> default amount 0.5
    self.project.run_step(_PrecomputedStep("Stretch", result), "")
    self.log_panel.append_entry(format_log_entry("Stretch", "auto", rms_delta(base, result)))
```

**Hook into `_go_to(index)`** — before switching stages, auto-stretch when needed:

```python
def _go_to(self, index: int) -> None:
    if not (0 <= index < len(self._stages)) or not self._stages[index].enabled:
        return
    if (self.project is not None
            and self._stages[index].id in POST_STRETCH_IDS
            and self.project.current().is_linear):
        self._ensure_stretched()
    self._stage = index
    self._status.setText("")
    ...
```

Import `POST_STRETCH_IDS` from `.pipeline`.

### Interaction with the Levels guard

The prior `apply_current` guard (refuse Levels when `current().is_linear`) remains. After
this change the guard becomes unreachable in normal flow (you cannot land on Levels linear),
but it stays as defense-in-depth.

## Data flow

User clicks Next / a later step → `_go_to(target)` → if the target is a post-stretch
processing step and `current()` is linear → `_ensure_stretched()` truncates history to the
stretch predecessors, applies the default Stretch, records a "Stretch" entry (logged
"Stretch (auto)") → the image is now non-linear → `_go_to` lands on the target step, whose
finishing operation now has real stretched data. Undo removes the auto-stretch (back to
linear); a subsequent forward navigation re-applies it.

## Error handling

- Guarded on `self.project is not None`; stages are disabled without a project anyway.
- Already-stretched or already-colourised images have `is_linear == False`, so the trigger
  is skipped — no double stretch.
- Mono images stretch fine (`linked_stretch` handles 2D).
- `apply_stretch` is pure NumPy and cannot invoke an external tool, so no async / busy
  handling is required inside navigation.
- Backward navigation to a post-stretch step while linear also auto-stretches (same rule),
  which is correct — those steps still need stretched data.

## Testing

- **pipeline** (`tests/ui/test_pipeline.py`): `POST_STRETCH_IDS` is exactly
  `{"levels","saturation","noise_sharpen","local_contrast","star_reduction","enhancements"}`;
  it excludes `"export"` and `"stretch"` and every pre-stretch id.
- **main_window** (`tests/ui/test_main_window.py`):
  - Navigating from a linear state to `levels` auto-commits a "Stretch" entry, the image
    becomes non-linear, and applying Levels then succeeds (records "Levels").
  - Navigating to a pre-stretch step (`background`) does **not** add a Stretch entry.
  - Navigating to `export` from a linear state does **not** add a Stretch entry (Export
    excluded); the image stays linear.
  - An already-stretched image is not double-stretched: navigate `stretch` → apply → go to
    `saturation`; history has exactly one "Stretch".
  - Undo after an auto-stretch returns the image to linear.
  - The auto-stretch log entry reads "Stretch (auto)".
- Full suite green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`).

## Verification (by eye)

Open a linear master → without touching Stretch, click a later step (or Next past Stretch):
the image is committed to its previewed stretch (barely any visible change) and the log
shows "Stretch (auto)"; Levels and the other finishing steps now behave normally. Jumping
straight to Export from a linear state exports the linear data unchanged. Undo peels the
auto-stretch back to linear.
