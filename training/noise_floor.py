"""Does stacking noise keep falling as 1/sqrt(N), or does it floor?

MEASURED 2026-08-30 on IC 1396A, 1024 frames, before any training was started:

       N      sigma   gain   1/sqrt(N)   shortfall
      16   7.865273   1.00        1.00          0%
      32   5.562465   1.41        1.41          0%
      64   3.985754   1.97        2.00          1%
     128   2.984022   2.64        2.83          7%
     256   2.235483   3.52        4.00         12%
     512   1.616345   4.87        5.66         14%
    1024   1.148327   6.85        8.00         14%

It does not floor. The shortfall appears between 64 and 256 and then stops
growing; per doubling the last two legs are 1.38x and 1.41x against an ideal
1.414, so the deep end scales almost perfectly and the 14% is a fixed loss taken
in the middle, not a ceiling.

Fitted, sigma is proportional to N^-0.46, so a 2535-frame target is about 2.5x
cleaner than the 350-frame stack a user actually shoots. That is the number the
injection design needs: n2n_v2 failed because at depth its "cleaner picture" was
NOISIER than its input and the lesson was empty. Here there is 2.5x of headroom
to teach with.

If it floors, the injection premise has no headroom: a 2535-frame target is no
cleaner than the 350-frame stack the user already has, the lesson is empty, and
the model learns to do nothing -- which is exactly how n2n_v2 failed.

ONE pass. Warp each frame once into a running sum and snapshot at each rung; the
first version re-warped every frame for every rung and took 30 minutes doing
twice the necessary work.
"""
import glob, sys, time
sys.path.insert(0, "/Volumes/Work/Code/Editor")
sys.path.insert(0, "/Volumes/Work/Code/Editor/training")
import numpy as np
from noise import estimate_sigma
from nocturne.stacking.frames import load_sub
from nocturne.stacking.normalize import frame_stats, normalize_to
from nocturne.stacking.parallel import ordered_results, plan_workers
from nocturne.stacking.register_pool import register_frames
from nocturne.stacking.register import warp_with_validity

def main():
    FOLDER, MAX_N = sys.argv[1], int(sys.argv[2])
    RUNGS = [n for n in (16, 32, 64, 128, 256, 512, 1024, 2048) if n <= MAX_N]

    paths = sorted(glob.glob(f"{FOLDER}/**/*.fit", recursive=True))[:MAX_N]
    ref = paths[0]
    ref_stats = frame_stats(load_sub(ref, normalize=False).data)
    plan = plan_workers()
    print(f"{len(paths)} frames, {plan.count} workers", flush=True)

    t0 = time.perf_counter()
    results = register_frames(paths[1:], ref, plan.count)
    tf = {ref: (np.eye(3), ref_stats)}
    for r in results:
        if r.reason is None:
            tf[r.path] = (r.matrix, r.stats)
    order = [p for p in paths if p in tf]
    print(f"registered {len(order)}/{len(paths)} in {time.perf_counter()-t0:.0f}s", flush=True)

    def prepare(p):
        m, st = tf[p]
        return warp_with_validity(normalize_to(load_sub(p, normalize=False).data, st, ref_stats), m)

    total = count = None
    t0 = time.perf_counter()
    print(f"\n{'N':>6}{'sigma':>12}{'measured gain':>15}{'1/sqrt(N) says':>16}{'shortfall':>11}", flush=True)
    base = None
    for i, out in enumerate(ordered_results(order, prepare, workers=plan.count), start=1):
        data, valid = out
        if total is None:
            total = np.zeros_like(data, dtype=np.float64)
            count = np.zeros(data.shape[:2], dtype=np.float32)
        total += data * valid[..., None]
        count += valid
        if i in RUNGS:
            full = count >= i * 0.9
            if full.sum() < 10000:
                print(f"{i:>6}   too little full-coverage area yet", flush=True); continue
            mean = np.where(count[..., None] > 0, total / np.maximum(count, 1)[..., None], 0)
            ys, xs = np.where(full)
            crop = mean[ys.min():ys.max(), xs.min():xs.max()]
            s = estimate_sigma(crop.astype(np.float32))
            if base is None:
                base, base_n = s, i
            gain, pred = base / s, np.sqrt(i / base_n)
            print(f"{i:>6}{s:>12.6f}{gain:>15.2f}{pred:>16.2f}{100*(1-gain/pred):>10.0f}%", flush=True)
    print(f"\nintegration pass: {time.perf_counter()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
