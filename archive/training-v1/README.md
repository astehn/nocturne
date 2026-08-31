# training-v1 — the injection/ladder denoise training system

Retired 2026-08-31, complete and working, and kept rather than deleted.

Nothing here runs as part of the app or the test suite. `pyproject.toml` collects
tests from `tests/` only, so this tree is inert. The layout mirrors the repo it
came from, so any file can be put back where it was by copying the subtree.

An exact restore point exists as a git tag:

    git checkout training-v1 -- training                # the whole thing
    git checkout training-v1 -- training/realism.py     # one file
    git show training-v1:training/gate.py               # just look

## Why it was retired

Not because it was broken — the final run passed its gate on every held-out
depth. It was retired because it rested on an assumption that turned out to be
false, and because 82 lines of model needed 10,600 lines of scaffolding to feed.

**The assumption: that a deep enough stack is clean enough to be "truth".**

It is not. Measured on the two deepest stacks in the archive — NGC 281 at 1116
frames and IC 1396A at 2034 — both are still visibly noisy. Stacking noise falls
as N^-0.46 with no floor in sight (`training/noise_floor.py` has the table), so
deeper always helps, but "less noisy" never becomes "clean". Training a model to
reproduce a noisy target teaches it that the target's noise is correct, which
caps the model at the target's noise floor.

The consequence is visible in the final run's own numbers. Each rung's measured
improvement tracks how much cleaner its target was than its input, and nothing
else:

| rung | target vs input | improvement |
|---|---|---|
| 1 → 128 | 9.32x cleaner | -21% |
| 16 → 128 | 2.60x cleaner | -21% |
| 64 → 112 | 1.29x cleaner | -12% |
| 112 → 64 | **0.77x — target NOISIER** | -6% |

The deepest rung, the one closest to real use, asked the model to reproduce an
image noisier than its input. The "performance falls off with depth" conclusion
drawn from this was wrong: it was measuring the dataset, not the model.

The replacement (Noise2Noise on disjoint half-stacks) needs no clean target at
any depth, which is the whole reason for the change.

## What is worth keeping from it

Measurements, mostly. These cost real time and are still true:

- `training/noise_floor.py` — does stacking noise floor out? No: sigma goes as
  N^-0.46 to 1024 frames. The table is in the docstring.
- `training/independence.py` — whether an injected noise field is independent of
  the target it is added to. It is NOT: measured on two separate groups, a field
  correlates with its own target 17-24x more than the null. Carries its own null
  control, which is the part worth copying if a similar probe is ever needed.
- `training/realism.py` — whether manufactured noise matches real sensor noise
  (autocorrelation to 0.1%, channel ratios to 0.0%). The manufactured noise was
  realistic; that was never the problem.
- `training/check_splits.py` — canonical target naming, and sky-position
  clustering that catches "MilkyWay_sub is M 17 shot again", which no list of
  names can.
- `nocturne/training/pairs.py` — a second, independent implementation of
  registration and stacking. Its existence alongside `nocturne/stacking/` is one
  of the reasons this grew: two stackers that had already drifted apart once.

## Lessons that are not in any file

- A gate can pass a useless model. This one did, honestly, because it compared
  against the only reference available and that reference was not truth.
- Four of five premises needed fixing when finally measured, and they had been
  in the spec as algebra for weeks. Algebra in a spec is a claim, not a check.
- The last night alone turned up three run-killing bugs, all in scaffolding:
  a target-name parser that collapsed "M 8_sub" to "M", an export that died on
  an import ordering, and a model card that named two held-out targets as
  training material. None of them were in the model.
