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

# What one slot of `ordered_results`' window ACTUALLY costs, end to end.
#
# Measured 2026-09-04 on 16 real M 16 subs at 8 workers, sigma-clip, four window
# values run interleaved (2, 4, 6, 10, twice each, to cancel drift and disk
# cache):
#
#     window  2 -> 4973 MB    window  6 -> 7751 MB
#     window  4 -> 6139 MB    window 10 -> 9100 MB
#
#     least squares: peak ~ 4128 MB + 520 MB * window, R^2 = 0.96
#
# 520 MB, not the 108 MB a queued frame retains: while the consumer holds
# `window` finished frames, the workers are concurrently building more, and
# their transients are resident too. Believing the 108 MB figure is what let the
# default sit at a size nobody had costed.
#
# NOT used as a cap — see plan_workers for why a second RAM budget there would be
# redundant. It is kept because it is the measurement that justifies the size of
# `window`, and this file's constants are required to carry their evidence.
_PER_SLOT_MB = 520

# Past this many frames in flight, more lookahead stops buying speed and only
# costs memory. Measured 2026-09-04 on 16 real M 16 subs, 3-5 repetitions each,
# peak resident of the largest process:
#
#   8 workers   window  5  7064 MB  12.4 s     4 workers   window 2  4870 MB  19.8 s
#               window  6  7792 MB  12.2 s                 window 3  5138 MB  16.1 s
#               window  7  8530 MB  12.1 s                 window 4  6102 MB  13.8 s
#               window  8  8992 MB  12.1 s                 window 6  6071 MB  12.9 s
#               window 10  9099 MB  12.1 s
#
# Two things that a single measurement would have got wrong:
#
# Memory stops rising once the window passes the worker count — windows 8 and 10
# are 74 MB apart, because slots beyond `workers` are rarely occupied. So the
# old default of workers + 2 was not itself the waste; the waste is that 8
# workers were given 10 slots when 6 run just as fast for 1.3 GB less.
#
# But the sweet spot is NOT a fraction of the worker count. At 4 workers,
# window 4 is 7% SLOWER than window 6 at identical memory: with fewer producers
# the consumer starves, and lookahead is what feeds it. A `window = workers`
# rule was tried and measured out for exactly this reason. Hence a cap on top of
# the old rule rather than a replacement for it.
#
# 6 is where both worker counts reach their best speed. Revisit it if the
# per-frame cost changes much — a larger sensor or a drizzle canvas moves the
# memory per slot, though not the point at which lookahead stops helping.
_WINDOW_CAP = 6

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
    window: int = 1         # frames `ordered_results` may hold; see plan_workers

    def describe(self) -> str:
        """One line for the log. The count is deliberately NOT a setting — nobody
        can answer "what should I set this to?" without the measurements above —
        so the log is the only place a slow stack can be diagnosed from."""
        return (f"{self.count} worker{'s' if self.count != 1 else ''} "
                f"({self.cores} performance cores, {self.ram_gb:.0f} GB RAM; "
                f"limited by {self.limiter}), window {self.window}")


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

    # How many frames may be in flight. Two facts set this, both measured above:
    #
    # More lookahead than workers buys NOTHING. At 8 workers, window 6 and
    # window 10 both stacked in 13.4 s, while window 10 cost 1.35 GB more. The
    # old default of workers + 2 was paying 1 GB for speed that was already
    # saturated. `count` slots is enough to keep every worker fed, which is the
    # only job this window has.
    #
    # How many frames may be in flight, which IS most of a stack's peak memory:
    # draining the frame generator with no accumulation at all still peaked at
    # 7774 MB of an 8930 MB stack, so the integrator is only ~13% of it.
    #
    # This is also how the window becomes RAM-aware, and it is the only way it
    # needs to be: `count` is already capped by the RAM budget above, so a second
    # budget check here would be a second computation of one fact. It WAS written
    # that way first and measured out — with _PER_SLOT_MB (520) against
    # _PER_WORKER_MB (500), a separate slot cap would bind only for total RAM
    # between about 11.8 and 12.1 GB. A safety net with a 0.3 GB opening is not a
    # safety net, it only reads like one.
    #
    # Floor of 2: at window 1 the consumer and the pool take strict turns and the
    # stack loses its parallelism (19.8 s at window 2 on 4 workers against 12.9 s
    # at 6, and below 2 it is worse). On a one-worker machine this floor beats
    # everything else — holding one finished frame while the lone worker builds
    # the next is still a pipeline, and costs one frame.
    window = max(2, min(count + 2, _WINDOW_CAP))
    if count == ram_cap and ram_cap < cpu_cap and ram_cap < _CEILING:
        limiter = "memory"
    elif count == _CEILING and cpu_cap >= _CEILING and ram_cap >= _CEILING:
        limiter = "ceiling"
    else:
        limiter = "cores"
    return WorkerPlan(count=count, limiter=limiter, cores=cores, ram_gb=ram_gb,
                      window=window)


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
    when the consumer is slower than the producers, and this project already has
    a ~396 GB stacking runaway in its history, so at most `window` results may be
    outstanding.

    A slot costs ~520 MB, NOT the 108 MB a finished frame retains: while the
    consumer holds `window` of them the workers are building more, and those
    transients are resident too. See `_PER_SLOT_MB` for the measurement.

    The default of workers + 2 keeps every worker fed while smoothing jitter.
    Lowering it to `workers` was tried on 2026-09-04 and measured WORSE — 7%
    slower on a 4-worker machine for 31 MB — so it stayed. Callers inside a
    stack pass `plan_workers().window`, which caps it at `_WINDOW_CAP`; that is
    where the memory is actually saved.

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
