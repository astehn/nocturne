"""Measure what a stack actually produces, repeatably, on real sessions.

    .venv/bin/python scripts/benchmark_stacking.py --corpus scripts/corpus.json
    .venv/bin/python scripts/benchmark_stacking.py --corpus … --limit 40 --out r.json

Developer tool, NOT shipped. FQA-009 from the 2026-09-01 feature audit: without
a fixed corpus and a repeatable measurement, a change to stacking can only be
argued about. With one, it can state its before and after.

WHAT IT MEASURES, and why each

  half_light_px   Half-light radius of a PSF stacked from every isolated star,
                  4x oversampled. This is THE sharpness number. It is not
                  sep's FWHM, and that is deliberate — see compare_masters.py,
                  which records the two metrics that failed before this one:
                  sep's isophotal FWHM grows with signal-to-noise, so a deeper
                  stack measures broader for reasons unrelated to sharpness
                  (that error produced a false "stacking degrades stars 11%"
                  claim), and per-star gaussian fits yielded usable results for
                  2.4% of stars on undersampled data.
  stars           Detected sources. More is better at equal sharpness — it is
                  depth. On its own it is not, because noise detects too.
  background_rms  The noise floor the detection ran against.
  seconds, peak_rss_*, output_mb
                  The cost. A change that improves sharpness by 2% and takes
                  three times as long is a trade, not a win, and the report
                  should make that visible rather than leave it to be noticed.

WHAT IT DOES NOT DO

No reference outputs from Siril or PixInsight. The audit asks for those and
they are worth having, but a corpus that must be regenerated in another
application before this can run would not get run. This measures Nocturne
against Nocturne, which is what a before/after needs.

SAFETY: it reads the session folders and writes only into --workdir. It never
writes to the source folders, which on this machine hold the only copies of
several nights.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import threading
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402


def measure_master(path: str) -> dict:
    """Sharpness, depth and noise for one master. Pure measurement, no stacking.

    Split out so a master produced any other way — by an older build, by Siril,
    by hand — can be measured with the identical code path.
    """
    import compare_masters as cm

    lum = cm._load_lum(path)
    sub, objs, rms = cm._detect(lum)
    isolated = [i for i in range(len(objs)) if cm._isolated(objs, i)]
    psf, used = cm.stack_at(sub, objs["x"][isolated], objs["y"][isolated], rms)
    return {
        "width": int(lum.shape[1]),
        "height": int(lum.shape[0]),
        "stars": int(len(objs)),
        "psf_stars": int(used),
        "half_light_px": round(float(cm.half_light(psf)), 4),
        "background_rms": float(f"{rms:.3e}"),
        "output_mb": round(os.path.getsize(path) / 1e6, 1),
    }


class _PeakRSS:
    """Peak resident memory of this process and its children, sampled.

    NOT `resource.getrusage`. That reports a high-water mark which never
    decreases for the life of the process, so in a run of five sessions every
    session after the first inherits the largest earlier peak — measured
    2026-09-04: 10694, 10698, 10699, 10699 MB across four sessions of quite
    different sizes, which is the same number wearing four hats. It also missed
    a 192 MB allocation entirely, because untouched pages are not resident.

    Sampling `ps` costs 2.8 ms. Children matter: registration runs in a process
    pool, and on a large session that pool is most of the memory.

    TWO numbers, because one would mislead. Measured on a 20-frame M 16 stack:
    11 processes at ~1.16 GB each, summing to 10.4 GB — but most of each
    worker's RSS is the same interpreter and numpy pages counted eleven times,
    so the sum is NOT what the machine needs. The truth lies between the sum
    and the largest single process, and both are reported so a reader can see
    the spread rather than trust a single confident-looking figure.
    """

    def __init__(self, interval: float = 0.4) -> None:
        self._interval = interval
        self.peak_kb = 0          # summed across the tree; overstates shared pages
        self.largest_kb = 0       # the biggest single process
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> int:
        try:
            out = subprocess.run(["ps", "-o", "pid=,ppid=,rss=", "-A"],
                                 capture_output=True, text=True, timeout=5).stdout
        except Exception:                       # noqa: BLE001 — a metric, not the work
            return 0, 0
        rows, mine = {}, os.getpid()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                pid, ppid, rss = (int(p) for p in parts)
                rows[pid] = (ppid, rss)
        # This process and anything descended from it.
        total, largest, seen = 0, 0, set()
        stack = [mine]
        while stack:
            pid = stack.pop()
            if pid in seen or pid not in rows:
                continue
            seen.add(pid)
            total += rows[pid][1]
            largest = max(largest, rows[pid][1])
            stack.extend(k for k, (pp, _r) in rows.items() if pp == pid)
        return total, largest

    def _observe(self) -> None:
        total, largest = self._sample()
        self.peak_kb = max(self.peak_kb, total)
        self.largest_kb = max(self.largest_kb, largest)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self._observe()

    def __enter__(self):
        self._observe()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._observe()
        return False

    @property
    def mb(self) -> float:
        """Summed across the process tree. Comparable between runs; NOT the
        machine's real footprint — see the class docstring."""
        return round(self.peak_kb / 1000.0, 1)

    @property
    def largest_mb(self) -> float:
        return round(self.largest_kb / 1000.0, 1)


def run_session(session: dict, workdir: str, limit: int | None) -> dict:
    """Stack one session and measure the result."""
    from nocturne.stacking.stacker import StackOptions, run_stack

    folder = session["folder"]
    subs = sorted(glob.glob(os.path.join(folder, "*.fit")) +
                  glob.glob(os.path.join(folder, "*.fits")))
    subs = [p for p in subs if "_master" not in os.path.basename(p).lower()]
    if limit:
        subs = subs[:limit]
    if len(subs) < 3:
        return {"name": session["name"], "error": f"only {len(subs)} subs found in {folder}"}

    out = os.path.join(workdir, f"{session['name'].replace(' ', '_')}.fits")
    opts = StackOptions(method=session.get("method", "sigma_clip"),
                        kappa=session.get("kappa", 3.0),
                        include=subs, output_path=out,
                        autocrop=session.get("autocrop", False))
    t0 = time.time()
    try:
        with _PeakRSS() as peak:
            res = run_stack(opts)
    except Exception as exc:                       # a corpus entry may be bad data
        return {"name": session["name"], "error": f"{type(exc).__name__}: {exc}"}
    elapsed = time.time() - t0

    row = {
        "name": session["name"],
        "method": opts.method,
        "subs_offered": len(subs),
        "frames_used": len(res.used),
        "frames_rejected": len(res.rejected),
        "seconds": round(elapsed, 1),
        "seconds_per_frame": round(elapsed / max(1, len(res.used)), 2),
        "peak_rss_sum_mb": peak.mb,
        "peak_rss_largest_mb": peak.largest_mb,
    }
    row.update(measure_master(out))
    return row


def load_corpus(path: str) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    return data["sessions"] if isinstance(data, dict) else data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", required=True, help="JSON describing the sessions")
    ap.add_argument("--out", default="", help="write the report here (default: stdout)")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap subs per session — the point of the skeleton is that "
                         "it can be run in minutes, not that it is exhaustive")
    ap.add_argument("--workdir", default="", help="where masters are written "
                                                  "(default: a temp dir)")
    ap.add_argument("--only", default="", help="run one session by name")
    args = ap.parse_args(argv)

    sessions = load_corpus(args.corpus)
    if args.only:
        sessions = [s for s in sessions if s["name"] == args.only]
        if not sessions:
            print(f"no session named {args.only!r}", file=sys.stderr)
            return 2
    workdir = args.workdir or tempfile.mkdtemp(prefix="nocturne-bench-")
    os.makedirs(workdir, exist_ok=True)

    rows = []
    for i, session in enumerate(sessions, 1):
        print(f"[{i}/{len(sessions)}] {session['name']}…", flush=True, file=sys.stderr)
        row = run_session(session, workdir, args.limit or None)
        rows.append(row)
        note = row.get("error") or (f"{row['frames_used']} frames, "
                                    f"{row['seconds']}s, hl={row['half_light_px']}px, "
                                    f"peak {row['peak_rss_largest_mb']}-"
                                    f"{row['peak_rss_sum_mb']} MB")
        print(f"      {note}", flush=True, file=sys.stderr)

    from nocturne import __version__
    report = {
        "app_version": __version__,
        "limit": args.limit or None,
        "workdir": workdir,
        "sessions": rows,
    }
    text = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
