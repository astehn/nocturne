"""Rebuild the deep-end reference master from the surviving subs.

The gate's only check that reaches the depth Andreas actually works at is
truth-free and compares against this one master — a held-out pair gate cannot
get there by construction, because at that depth the deepest stack IS the truth.
The 405-frame master it used died with Work2 on 2026-08-25.

Rebuilt from the 460 M8 subs recovered off the Seestar, so the depth CHANGES.
Any threshold calibrated against 405 frames has to be re-measured, not carried
over: sigma goes as roughly N^-0.46 on this archive (training/noise_floor.py),
so 460 frames is about 7% cleaner than 405 and a threshold tuned to the old one
would read as a small regression that is really just a better reference.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import paths  # noqa: E402
from check_splits import refuse_nas  # noqa: E402
from nocturne.core.export import save_fits  # noqa: E402
from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.stacking.coverage import full_coverage_bounds  # noqa: E402
from nocturne.stacking.frames import load_sub  # noqa: E402
from nocturne.stacking.integrate import sigma_clip_integrate  # noqa: E402
from nocturne.stacking.normalize import frame_stats, normalize_to  # noqa: E402
from nocturne.stacking.parallel import ordered_results  # noqa: E402
from nocturne.stacking.register import warp_with_validity  # noqa: E402
from nocturne.stacking.register_pool import register_frames  # noqa: E402


def build(folder: Path, out: Path, workers: int) -> int:
    refuse_nas(str(folder))
    frames = sorted(folder.glob("**/*.fit"))
    if len(frames) < 3:
        raise SystemExit(f"only {len(frames)} frames under {folder}")
    ref = str(frames[len(frames) // 2])
    ref_stats = frame_stats(load_sub(ref, normalize=False).data)

    t0 = time.time()
    tf = {ref: (np.eye(3), ref_stats)}
    for r in register_frames([str(f) for f in frames if str(f) != ref], ref, workers):
        if r.reason is None:
            tf[r.path] = (r.matrix, r.stats)
    used = [str(f) for f in frames if str(f) in tf]
    print(f"registered {len(used)}/{len(frames)} in {time.time()-t0:.0f}s", flush=True)

    def prepare(p):
        m, st = tf[p]
        return warp_with_validity(
            normalize_to(load_sub(p, normalize=False).data, st, ref_stats), m)

    def gen():
        yield from ordered_results(used, prepare, workers=workers)

    t0 = time.time()
    master, cov = sigma_clip_integrate(gen, 2.5)
    t, b, l, r = full_coverage_bounds(cov, len(used))
    master = master[t:b, l:r]
    print(f"integrated {len(used)} frames in {time.time()-t0:.0f}s -> {master.shape}",
          flush=True)

    peak = float(master.max()) or 1.0
    out.parent.mkdir(parents=True, exist_ok=True)
    save_fits(AstroImage(np.clip(master / peak, 0, 1).astype(np.float32), is_linear=True),
              str(out), header={"STACKCNT": len(used), "NSUBS": len(used)})
    print(f"wrote {out}  ({len(used)} frames)", flush=True)
    return len(used)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--folder", default=str(paths.ARCHIVE / "M 8_sub"))
    ap.add_argument("--out", default=str(paths.M8_MASTER))
    # 3, not the machine's 8. Registration workers hold a debayered frame each
    # (~100 MB, several times that at peak): eight of them took 61 GB of a 64 GB
    # machine on 2026-08-30 and made it unusable. plan_workers budgets 500 MB
    # per worker, which is 4-8x optimistic for this path.
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args(argv)
    n = build(Path(args.folder), Path(args.out), args.workers)
    if n != paths.M8_DEPTH:
        print(f"\nNOTE: built from {n} frames, paths.M8_DEPTH says {paths.M8_DEPTH}. "
              f"Update it, and re-measure any threshold calibrated against the old depth.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
