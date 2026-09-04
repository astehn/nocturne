"""How many workers to run, and the bounded ordered pool that runs them."""
import pytest

from nocturne.stacking import parallel


def _plan(monkeypatch, perf, ram_gb):
    monkeypatch.setattr(parallel, "_performance_cores", lambda: perf)
    monkeypatch.setattr(parallel, "_total_ram_bytes", lambda: int(ram_gb * 1024**3))
    return parallel.plan_workers()


def test_a_big_machine_is_capped_by_diminishing_returns(monkeypatch):
    """14 logical CPUs here are 10 performance + 4 efficiency, and Phase B
    measured 6.80x at 8 threads but 6.42x at 12 — past the performance cores the
    work lands on efficiency cores and gets SLOWER. Hence a ceiling."""
    p = _plan(monkeypatch, perf=10, ram_gb=64)
    assert p.count == 8
    assert p.limiter == "ceiling"


def test_a_small_laptop_is_capped_by_its_cores(monkeypatch):
    """A 4-performance-core Air must not be handed 8 workers just because the
    developer's machine can take them."""
    p = _plan(monkeypatch, perf=4, ram_gb=8)
    assert p.count == 3
    assert p.limiter == "cores"


def test_memory_caps_a_machine_with_many_cores_and_little_ram(monkeypatch):
    """The backstop. Each worker costs ~500 MB (108 MB per queued frame plus a
    ~285 MB transient), so cores alone would happily swap a small machine."""
    p = _plan(monkeypatch, perf=16, ram_gb=8)
    assert p.limiter == "memory"
    assert p.count < 8


def test_never_returns_less_than_one(monkeypatch):
    for perf, ram in ((1, 64), (10, 1), (1, 1), (0, 0)):
        p = _plan(monkeypatch, perf=perf, ram_gb=ram)
        assert p.count >= 1, (perf, ram)


def test_a_single_worker_means_todays_serial_behaviour(monkeypatch):
    p = _plan(monkeypatch, perf=2, ram_gb=8)
    assert p.count == 1


def test_the_plan_explains_itself_for_the_log(monkeypatch):
    """A slow stack must be diagnosable from the log alone — the count is not
    exposed in Settings, so the log is the only place the reason can appear."""
    p = _plan(monkeypatch, perf=10, ram_gb=64)
    assert "8" in p.describe()
    assert "core" in p.describe().lower()
    assert "GB" in p.describe()


def test_probes_work_on_this_machine_without_monkeypatching():
    """The real probes must not raise. They use ctypes/sysconf rather than a
    subprocess: an import-time subprocess is what popped the Xcode installer on
    0.11.1, and this runs at the start of every stack."""
    cores = parallel._performance_cores()
    ram = parallel._total_ram_bytes()
    assert isinstance(cores, int) and cores >= 1
    assert isinstance(ram, int) and ram > 0
    assert parallel.plan_workers().count >= 1


# ------------------------------------------------------- ordered bounded pool

def test_results_come_out_in_order_even_when_workers_finish_out_of_order():
    """THE determinism requirement.

    sigma_clip_integrate accumulates with a streaming weighted Welford pass,
    which is order-dependent in floating point. If frames arrive in a different
    order the master differs in its last bits, and then Saved Projects stop
    reproducing pixel-exactly. Workers may run in any order; the CONSUMER must
    not see them that way.

    The sleeps invert the natural completion order, so a pool that yields
    'whatever finished first' fails this.
    """
    import time
    def slow_first(i):
        time.sleep(0.05 if i == 0 else 0.0)
        return i
    got = list(parallel.ordered_results(range(8), slow_first, workers=4))
    assert got == list(range(8))


def test_it_does_not_run_ahead_of_the_consumer():
    """Memory is bounded by refusing to run ahead.

    executor.map and Pool.imap buffer UNBOUNDEDLY when the consumer is slower
    than the producers. Each buffered frame here is 108 MB, and this project
    already has a ~396 GB stacking runaway in its history. At most `window`
    items may be outstanding.
    """
    submitted = []
    def track(i):
        submitted.append(i)
        return i
    gen = parallel.ordered_results(range(100), track, workers=2, window=4)
    consumed = 0
    for _ in range(10):
        next(gen)
        consumed += 1
        assert len(submitted) - consumed <= 4, (
            f"ran {len(submitted) - consumed} ahead of the consumer, window is 4"
        )
    gen.close()


def test_an_exception_in_a_worker_reaches_the_caller():
    def boom(i):
        if i == 3:
            raise ValueError("frame 3 is bad")
        return i
    gen = parallel.ordered_results(range(8), boom, workers=3)
    with pytest.raises(ValueError, match="frame 3 is bad"):
        list(gen)


def test_one_worker_is_exactly_serial():
    order = []
    def note(i):
        order.append(i)
        return i
    got = list(parallel.ordered_results(range(6), note, workers=1))
    assert got == list(range(6))
    assert order == list(range(6)), "one worker must not reorder the work itself"


def test_abandoning_the_generator_does_not_leave_work_running():
    """The user cancels a stack far more often than they let it finish."""
    import time
    started, finished = [], []
    def slow(i):
        started.append(i)
        time.sleep(0.02)
        finished.append(i)
        return i
    gen = parallel.ordered_results(range(200), slow, workers=2, window=4)
    next(gen)
    gen.close()
    time.sleep(0.1)
    assert len(started) < 50, "closing the generator must stop feeding the pool"


# --- the in-flight window ----------------------------------------------------
#
# Peak memory is dominated by frames in flight, not by the integrator: draining
# the frame generator with NO accumulation still peaked at 7774 MB of an 8930 MB
# stack (16 real M 16 subs, 8 workers, 2026-09-04). So what this window is set
# to IS the memory footprint, and it is worth guarding.


def test_lookahead_is_capped_however_many_workers_there_are(monkeypatch):
    """The whole saving. At 8 workers, window 6 stacks in 12.2 s and window 10
    in 12.1 s — indistinguishable — but window 10 costs 1.3 GB more. Past ~6
    frames in flight the extra lookahead is bought and never used."""
    # The literal 6, deliberately NOT parallel._WINDOW_CAP. Asserting against the
    # constant is what the first version of this test did, and it was vacuous:
    # raising the cap to 10 moved the assertion with it and the test still
    # passed. 6 is the measured value, so 6 is what the test holds.
    for perf, ram in ((10, 64), (16, 128), (32, 256)):
        p = _plan(monkeypatch, perf=perf, ram_gb=ram)
        assert p.window <= 6, (perf, ram, p)


def test_a_machine_with_few_workers_still_gets_lookahead(monkeypatch):
    """The cap must not become a rule that starves small machines.

    Measured at 4 workers: window 4 took 13.8 s and window 6 took 12.9 s at the
    SAME memory (6102 vs 6071 MB). With fewer producers the consumer starves and
    lookahead is what feeds it, so the window must be allowed to exceed the
    worker count. A `window = workers` rule was written first and this is the
    measurement that rejected it.
    """
    p = _plan(monkeypatch, perf=5, ram_gb=64)
    assert p.count == 4
    assert p.window > p.count, (
        f"{p.count} workers got only {p.window} slots — measured 7% slower")


def test_a_small_machine_gets_a_smaller_window(monkeypatch):
    """It is RAM-aware through the worker count, which is already RAM-capped —
    deliberately not through a second budget of its own."""
    big = _plan(monkeypatch, perf=16, ram_gb=128)
    small = _plan(monkeypatch, perf=16, ram_gb=4)
    assert small.window < big.window, (small, big)


def test_the_window_never_drops_to_one(monkeypatch):
    """At window 1 the consumer and the pool take strict turns and the stack is
    effectively serial — measured 19.8 s at window 2 against 12.9 s at 6 on four
    workers, and below 2 it is worse. Better to spend 500 MB than lose the pool.
    """
    # Note this floor cannot fire under the CURRENT rule — `count` is at least 1,
    # so count + 2 is at least 3. It is kept because it is one edit away from
    # mattering: any rule that subtracts from the worker count puts a
    # single-worker machine straight through it.
    for perf, ram in ((1, 1), (0, 0), (16, 1), (1, 64)):
        p = _plan(monkeypatch, perf=perf, ram_gb=ram)
        assert p.window >= 2, (perf, ram, p)


def test_the_window_is_in_the_log_line(monkeypatch):
    """Same reason as the worker count: it is not a setting, so a stack that
    swaps can only be diagnosed from the log."""
    p = _plan(monkeypatch, perf=10, ram_gb=64)
    assert "window" in p.describe().lower(), p.describe()
    assert str(p.window) in p.describe()
