"""How many workers a stack may use, and a bounded ordered thread pool.

Stacking pinned ONE core of fourteen. The per-frame work in the integration
phase — FITS read, demosaic, sky normalisation, warp — is nearly all C that
releases the GIL, so threads parallelise it almost linearly. Measured on real
M 45 subs: 2.06x on 2 threads, 3.98x on 4, 6.80x on 8.

The worker count is DERIVED, never hardcoded. A number tuned to a 14-core/64 GB
desktop would swap a MacBook Air, and a number safe for the Air would waste the
desktop.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
from dataclasses import dataclass

# Measured on a real 3840x2160 frame: 108 MB retained per QUEUED frame (warped
# 100 MB + validity mask 8 MB) and a ~285 MB transient peak while one is being
# computed. With a window of 2 frames per worker that is ~500 MB each.
_PER_WORKER_MB = 500

# Diminishing returns, measured: 6.80x at 8 threads against 6.42x at 12. This
# machine's 14 logical CPUs are 10 performance + 4 efficiency cores, and past
# the performance cores the work lands on the slower ones and adds contention.
_CEILING = 8

# Left for macOS and the rest of the app. The stack is not the only thing
# running, and a machine that swaps is far slower than one that used fewer
# workers.
_RESERVE_GB = 4.0

# Half of what is left after the reserve. Conservative on purpose: the small
# machine path cannot currently be tested (no Air available), so it is reasoned
# from measured per-frame costs rather than observed.
_BUDGET_FRACTION = 0.5


def _sysctl_int(name: str) -> int | None:
    """Read an integer sysctl through libc — NOT by shelling out.

    An import-time subprocess is what made a downloaded Nocturne ask its user to
    install the Xcode command line tools (0.11.1), and this runs at the start of
    every stack.
    """
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"))
        val = ctypes.c_int64(0)
        size = ctypes.c_size_t(8)
        if libc.sysctlbyname(name.encode(), ctypes.byref(val),
                             ctypes.byref(size), None, 0) != 0:
            return None
        return int(val.value)
    except Exception:
        return None


def _performance_cores() -> int:
    """Performance cores, falling back gracefully off Apple Silicon."""
    for key in ("hw.perflevel0.logicalcpu", "hw.physicalcpu"):
        n = _sysctl_int(key)
        if n and n > 0:
            return n
    return max(1, (os.cpu_count() or 2) // 2)


def _total_ram_bytes() -> int:
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (ValueError, OSError, AttributeError):
        return 8 * 1024 ** 3       # assume a modest machine rather than a huge one


@dataclass(frozen=True)
class WorkerPlan:
    count: int
    limiter: str            # "cores" | "memory" | "ceiling"
    cores: int
    ram_gb: float

    def describe(self) -> str:
        """One line for the log. The count is deliberately NOT a setting — nobody
        can answer "what should I set this to?" without the measurements above —
        so the log is the only place a slow stack can be diagnosed from."""
        return (f"{self.count} worker{'s' if self.count != 1 else ''} "
                f"({self.cores} performance cores, {self.ram_gb:.0f} GB RAM; "
                f"limited by {self.limiter})")


def plan_workers() -> WorkerPlan:
    cores = max(0, _performance_cores())
    ram = _total_ram_bytes()
    ram_gb = ram / 1024 ** 3

    # -1 rather than -2: during a stack the interface thread is essentially idle
    # and the work is C-heavy, so one spare core is enough headroom.
    cpu_cap = max(1, cores - 1)
    budget_mb = max(0.0, ram_gb - _RESERVE_GB) * 1024 * _BUDGET_FRACTION
    ram_cap = max(1, int(budget_mb // _PER_WORKER_MB))

    count = max(1, min(cpu_cap, ram_cap, _CEILING))
    if count == ram_cap and ram_cap < cpu_cap and ram_cap < _CEILING:
        limiter = "memory"
    elif count == _CEILING and cpu_cap >= _CEILING and ram_cap >= _CEILING:
        limiter = "ceiling"
    else:
        limiter = "cores"
    return WorkerPlan(count=count, limiter=limiter, cores=cores, ram_gb=ram_gb)


def ordered_results(items, fn, workers: int, window: int | None = None):
    """Yield ``fn(item)`` for each item, IN ITEM ORDER, computed concurrently.

    Two properties matter more than the speed:

    **Order.** Results are yielded in item order, never as they finish.

    Note what this is and is NOT justified by. It was introduced on the theory
    that the integrators' streaming accumulation is order-dependent in floating
    point and that reordering would change a master's last bits. MEASURED, that
    is false at realistic scales: average and sigma-clip integration of 300
    frames spanning a million-fold magnitude range gave bit-identical results
    reversed and shuffled. The float64 intermediates absorb it.

    Ordering is kept anyway, because it costs nothing and buys reproducibility
    BY CONSTRUCTION rather than by luck — a future change to the accumulator's
    dtype, a different integrator, or far more frames could each make the order
    matter, and none of those would announce themselves. Do not delete it on the
    grounds that a test still passes without it.

    **Bounded lookahead.** `executor.map` and `Pool.imap` buffer without limit
    when the consumer is slower than the producers. Each buffered frame here is
    108 MB and this project already has a ~396 GB stacking runaway in its
    history, so at most `window` results may be outstanding. The default,
    workers + 2, is enough to keep every worker fed while smoothing jitter
    without holding twice the frames in memory.

    Cancellation is the CALLER's job, from the thread that owns the token:
    `core.tasks` keeps the ambient token in a `threading.local`, so a worker
    thread sees `current() is None` and a check inside `fn` would silently do
    nothing. Closing this generator stops feeding the pool.
    """
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor

    workers = max(1, int(workers))
    window = max(1, int(window if window is not None else workers + 2))
    pending: deque = deque()
    with ThreadPoolExecutor(max_workers=workers,
                            thread_name_prefix="nocturne-stack") as pool:
        try:
            for item in items:
                pending.append(pool.submit(fn, item))
                if len(pending) >= window:
                    yield pending.popleft().result()
            while pending:
                yield pending.popleft().result()
        finally:
            # Reached on exhaustion, on an exception, and when the consumer
            # abandons the generator (GeneratorExit) — which is what a cancelled
            # stack does. Drop what has not started; the pool's own shutdown
            # waits for what has.
            for f in pending:
                f.cancel()
            pending.clear()
