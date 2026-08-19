"""Registering frames across processes.

Phase A is GIL-bound in astroalign — measured 1.22x on 8 threads against 3.98x
on 8 processes — and returns only a 3x3 matrix plus a few statistics (~450
bytes), so processes cost almost nothing in IPC here. The opposite of Phase B,
where 95 MB arrays make threads the only sane choice.
"""
import numpy as np
import pytest
from skimage.transform import SimilarityTransform, warp

from nocturne.stacking import register_pool
from tests.stacking.synthetic import make_star_field, write_color_fits


@pytest.fixture
def force_pool(monkeypatch):
    """Make the tests that are ABOUT the pool actually use it.

    `register_frames` falls back to serial below _MIN_FOR_POOL frames, because
    spawning costs about a second and tiny stacks should not pay it. Adding that
    threshold silently made every test here take the serial path — the fallback
    test passed with the fallback deleted outright. Any test whose subject is
    the pool must lower the threshold explicitly.
    """
    monkeypatch.setattr(register_pool, "_MIN_FOR_POOL", 2)


def _subs(tmp_path, n=5, seed=4):
    base = make_star_field(n_stars=40, seed=seed)
    paths = []
    for i in range(n):
        t = SimilarityTransform(translation=(i * 0.4, -i * 0.4))
        f = warp(base, t.inverse, order=1, preserve_range=True).astype(np.float32)
        p = tmp_path / f"s{i}.fit"
        write_color_fits(p, f, exptime=10.0)
        paths.append(str(p))
    return paths


def test_results_are_returned_in_path_order(tmp_path, force_pool):
    """`used` must be identical to the serial implementation's, and the
    integration phase then walks it in that order."""
    paths = _subs(tmp_path)
    out = register_pool.register_frames(paths[1:], paths[0], workers=3)
    assert [r.path for r in out] == paths[1:]


def test_a_frame_of_the_wrong_size_is_rejected_with_the_old_reason(tmp_path, force_pool):
    """The rejection reasons are shown to the user in the stacking report, so
    they must not drift when the loop moves into a worker."""
    paths = _subs(tmp_path, n=4)
    odd = make_star_field(shape=(60, 60), n_stars=10, seed=1)
    p = tmp_path / "odd.fit"
    write_color_fits(p, odd, exptime=10.0)
    out = register_pool.register_frames(paths[1:] + [str(p)], paths[0], workers=2)
    bad = [r for r in out if r.reason]
    assert len(bad) == 1
    assert bad[0].reason == "dimension mismatch"


def test_an_unreadable_frame_is_rejected_not_fatal(tmp_path, force_pool):
    paths = _subs(tmp_path, n=4)
    junk = tmp_path / "junk.fit"
    junk.write_bytes(b"not a fits file")
    out = register_pool.register_frames(paths[1:] + [str(junk)], paths[0], workers=2)
    bad = [r for r in out if r.reason]
    assert len(bad) == 1 and bad[0].reason.startswith("unreadable")
    assert sum(1 for r in out if r.matrix is not None) == 3


def test_one_worker_uses_the_serial_path_and_agrees_with_the_pool(tmp_path, force_pool):
    """The serial path is also the FALLBACK when a pool cannot start, so it must
    produce the same answers rather than merely similar ones."""
    paths = _subs(tmp_path, n=5, seed=7)
    serial = register_pool.register_frames(paths[1:], paths[0], workers=1)
    pooled = register_pool.register_frames(paths[1:], paths[0], workers=3)
    assert [r.path for r in serial] == [r.path for r in pooled]
    for a, b in zip(serial, pooled):
        assert a.reason == b.reason
        if a.matrix is None:
            assert b.matrix is None
        else:
            assert np.allclose(a.matrix, b.matrix, atol=1e-9)


def test_it_falls_back_to_serial_when_the_pool_cannot_start(tmp_path, monkeypatch, force_pool):
    """A user whose stack will not run is worse off than one whose stack is slow.

    The real hazard is macOS spawn inside a PyInstaller bundle — the app
    re-importing itself — which fails ONLY in the shipped .app and not in any
    test. So the fallback must be unconditional, not conditional on a check we
    can make here.
    """
    def explode(*a, **k):
        raise OSError("no processes for you")
    monkeypatch.setattr(register_pool, "_make_pool", explode)
    paths = _subs(tmp_path, n=4)
    out = register_pool.register_frames(paths[1:], paths[0], workers=3)
    assert [r.path for r in out] == paths[1:]
    assert all(r.matrix is not None for r in out), "fallback must still register"


def test_progress_counts_each_frame_once_in_order(tmp_path, force_pool):
    paths = _subs(tmp_path, n=6)
    seen = []
    register_pool.register_frames(paths[1:], paths[0], workers=3,
                                  on_progress=lambda i: seen.append(i))
    assert seen == [1, 2, 3, 4, 5]


def test_cancelling_stops_early(tmp_path, force_pool):
    """Cancellation cannot reach into a child process, so it is checked between
    results on the driving thread — the one that owns the token."""
    from nocturne.core.tasks import Cancelled
    paths = _subs(tmp_path, n=8)
    calls = {"n": 0}
    def cancel_after_two():
        calls["n"] += 1
        if calls["n"] > 2:
            raise Cancelled()
    with pytest.raises(Cancelled):
        register_pool.register_frames(paths[1:], paths[0], workers=2,
                                      check_cancel=cancel_after_two)


def test_a_tiny_stack_does_not_pay_for_a_process_pool(tmp_path, monkeypatch):
    """Spawning costs about a second and macOS re-imports the module in every
    worker. On a handful of frames that is most of the work, so the serial path
    is both faster AND simpler — no pool to fail."""
    started = {"n": 0}
    def counting(*a, **k):
        started["n"] += 1
        raise AssertionError("a pool must not be started for a tiny stack")
    monkeypatch.setattr(register_pool, "_make_pool", counting)
    paths = _subs(tmp_path, n=5)
    out = register_pool.register_frames(paths[1:], paths[0], workers=8)
    assert started["n"] == 0
    assert all(r.matrix is not None for r in out)


def test_the_bundles_entry_point_calls_freeze_support():
    """The packaged app spawns workers, and macOS spawn re-executes the bundle —
    without freeze_support() that is the app relaunching itself, a window per
    worker, recursively.

    Checks the file the PyInstaller SPEC NAMES, resolved from the spec rather
    than hardcoded, and inspects the AST rather than the text. Both of those are
    scars:

    * The first version read nocturne/__main__.py, which is NOT what the bundle
      runs — the entry script merely imports main() from it, so everything under
      that module's `if __name__ == "__main__"` is dead code in the app. The
      test passed while the shipped bundle had no protection at all. Only
      building the bundle found it.
    * The second version searched the source text for "freeze_support()", which
      matched the entry point's own DOCSTRING. Deleting the actual call left the
      test green.

    So: find a real Call node, to multiprocessing.freeze_support, inside the
    `if __name__ == "__main__"` block, before main().
    """
    import ast
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[2]
    spec = (root / "packaging" / "nocturne.spec").read_text()
    m = re.search(r'SCRIPT\s*=\s*os\.path\.join\(SPECPATH,\s*"([^"]+)"\)', spec)
    assert m, "could not find the entry script in nocturne.spec"
    entry = root / "packaging" / m.group(1)
    assert entry.exists(), entry

    tree = ast.parse(entry.read_text())
    guard = [n for n in tree.body
             if isinstance(n, ast.If) and "__main__" in ast.dump(n.test)]
    assert guard, f"{entry.name} has no `if __name__ == \"__main__\"` block"

    calls = [n for n in ast.walk(guard[0]) if isinstance(n, ast.Call)]
    names = [ast.unparse(c.func) for c in calls]
    assert any(n.endswith("freeze_support") for n in names), (
        f"{entry.name} is what the bundle runs and it never CALLS "
        f"freeze_support() — spawned workers will relaunch the whole app. "
        f"calls found: {names}"
    )
    fz = next(i for i, n in enumerate(names) if n.endswith("freeze_support"))
    mn = next((i for i, n in enumerate(names) if n == "main"), len(names))
    assert fz < mn, "freeze_support() must be called before main()"
