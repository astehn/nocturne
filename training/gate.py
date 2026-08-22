"""Do-no-harm gate: is the model worse than doing nothing, at ANY depth?

Every prior test on this project was RELATIVE ("closer to truth than the
noisy input was"). The 2026-08-22 prototype passed all of them, scored better
than two commercial competitors on its held-out target, and still broke a
real 405-frame M 8 master into green and magenta blotches -- because nothing
ever asked whether it was worse than leaving the image alone.

Checked PER DEPTH, never averaged. That regression was invisible in an
average: shallow depths improved so much they buried one deep-stack
regression. A gate that averages would have passed the exact model that
caused this.

The real M8 master has no ground truth of its own (it IS the deepest stack),
so training/tests/test_gate.py evaluates it with a self-referential chroma
proxy that only catches chroma-shaped damage -- see that file for what it
does and does not prove. The held-out-pair path (input_err/model_err against
real ground truth) is the check that generalises, stars included.
"""
from __future__ import annotations

from collections import namedtuple

DepthResult = namedtuple("DepthResult", "target depth input_err model_err")
GateResult = namedtuple("GateResult", "passed failures")


def check_no_harm(results, tolerance: float = 0.0) -> GateResult:
    """Fails if the model is further from truth than the input at ANY depth.

    `tolerance` stays 0.0 by default -- "slightly worse" is still worse. A
    caller may widen it deliberately (e.g. for a noisy proxy metric), but the
    default must never soften "worse than doing nothing" into "close enough."
    """
    results = list(results)
    if not results:
        # `passed` is the signal that authorises overwriting the model the app
        # ships. Granting it on an empty result set would ship a model that was
        # never measured against anything -- refuse instead of passing vacuously.
        return GateResult(passed=False, failures=["no held-out results to check"])
    failures = [
        f"{r.target} @ {r.depth} frames: model {r.model_err:.3e} vs input {r.input_err:.3e}"
        for r in results if r.model_err > r.input_err * (1.0 + tolerance)
    ]
    return GateResult(passed=not failures, failures=failures)
