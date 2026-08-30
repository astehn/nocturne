"""Premise 5: are the noise field D and the target M actually independent?

MEASURED 2026-08-30 on the first two groups built, before the first training run.
THE ANSWER IS NO, in both, with the same sign.

  IC 1396A, 26 tiles       mean      sd    max|r|      M 16, 31 tiles
  field vs OWN target    -0.0449  0.1528   0.4591      -0.0317  0.0579  0.2090
  field vs OTHER target  -0.0003  0.0068   0.0262      -0.0004  0.0026  0.0086
  |field| vs OWN target  +0.3718  0.1793   0.8121      +0.2347  0.1117  0.5586

Row two is the NULL: what this estimator returns when the two really are
independent. It is tight. A field correlates with its own target 17-24x more
strongly than that, so the large values are not an artefact of both images being
spatially correlated — which was the first explanation tried, and wrong. Without
the null, "violation" and "artefact" were a coin flip, and that coin is exactly
how the 2026-08-23 probe read 0.78 and said proceed while counting starlight.

Row three is expected and must not be mistaken for the violation: corr(|D|, M)
is strongly POSITIVE because shot noise grows with signal, so the field's
AMPLITUDE should track intensity. That part is the realism the design wants.

WHY IT MATTERS. The design argues that adding scaled D back to M cannot
reintroduce M's own noise, because cov(D,M) = (var A - var B) / 2sqrt2 = 0. That
holds only if the halves are statistically identical. They are not, and the
correlation is consistently NEGATIVE: the injected field partly CANCELS the
target's noise where the target is bright. That is a structured relationship
between noise and scene, and a model can learn it instead of learning to denoise.

MECHANISM, partly identified, and the two groups point the same way. The halves
are integrated with autocrop=False, so where half A covers a pixel and half B
does not, A-B leaves SCENE rather than noise. Restricting tile 000002 to fully
covered pixels takes it from -0.349 to -0.006. And IC 1396A is 2.6x worse than
M 16 while being the only group combined across nights (2026-08-11..08-26 against
a single 08-09): more nights means more dithering and field rotation between the
halves, so more of the frame where their coverage disagrees. That is the
mechanism predicting its own gradient, which is the best evidence for it so far.

It is still not the whole story: raising the coverage threshold across all tiles
does not clear it until 0.999, where only 9% of pixels survive. If this needs
fixing, the shape of the fix is to integrate both halves to a COMMON full-coverage
crop rather than each to its own.

STATUS: known, measured, and accepted for the first run rather than fixed. The
effect is bounded, the gate still judges against real held-out pairs, and holding
would cost a night. IF THAT RUN DISAPPOINTS, THIS IS THE FIRST THING TO SUSPECT.
"""
import glob
import sys

import numpy as np

DEFAULT_GLOB = ("/Volumes/Work/AstroTraining/datasets/inject_v1/injection/"
                "*/tile_*.npz")


def corr(a, b) -> float:
    a = np.asarray(a, np.float64).ravel()
    b = np.asarray(b, np.float64).ravel()
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else float("nan")


def measure(tiles):
    """(matched, null, amplitude) correlation samples.

    `null` is the whole point: each field is also correlated against a DIFFERENT
    tile's target, where the true answer is known to be independence. Read the
    matched numbers only against it.
    """
    data = []
    for t in tiles:
        with np.load(t) as rec:
            data.append((rec["target"].copy(), rec["fields"].copy()))
    matched, null, amplitude = [], [], []
    for i, (M, F) in enumerate(data):
        other = data[(i + max(1, len(data) // 3)) % len(data)][0]
        for k in range(F.shape[0]):
            matched.append(corr(F[k], M))
            amplitude.append(corr(np.abs(F[k]), M))
            if other.shape == F[k].shape:
                null.append(corr(F[k], other))
    return np.array(matched), np.array(null), np.array(amplitude)


def report(matched, null, amplitude, out=print) -> bool:
    def line(name, a):
        out(f"  {name:<34}{a.mean():>+9.4f}{a.std():>9.4f}{np.abs(a).max():>10.4f}{len(a):>6}")

    out(f"  {'':<34}{'mean':>9}{'sd':>9}{'max|r|':>10}{'n':>6}")
    line("field vs ITS OWN target", matched)
    line("field vs ANOTHER tile's target", null)
    line("|field| vs its own target", amplitude)
    out("")
    # The null sets the scale. Anything the matched distribution does that the
    # null cannot is a real dependence.
    independent = np.abs(matched).max() <= max(4 * np.abs(null).max(), 0.05)
    out("INDEPENDENT: matched values sit within what the null produces"
        if independent else
        f"NOT INDEPENDENT: matched reaches {np.abs(matched).max():.4f} where the "
        f"null tops out at {np.abs(null).max():.4f}")
    out("shot noise tracks intensity, as intended" if amplitude.mean() > 0.02
        else "WARNING: field amplitude does not track intensity — noise looks synthetic")
    return independent


def main(argv=None) -> int:
    pattern = (argv or sys.argv[1:] or [DEFAULT_GLOB])[0]
    tiles = sorted(glob.glob(pattern))
    if len(tiles) < 2:
        print(f"need at least 2 tiles, found {len(tiles)} at {pattern}")
        return 2
    print(f"{len(tiles)} tiles\n")
    return 0 if report(*measure(tiles)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
