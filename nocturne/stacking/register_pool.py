"""Register frames against the reference, across processes.

Phase A is GIL-bound: `astroalign` does its triangle matching in Python, so
threads gave 1.22x on 8 workers where the integration phase gave 6.80x. It also
returns almost nothing — a 3x3 matrix and two short arrays, about 450 bytes —
so processes cost essentially no IPC here. That is the exact opposite of the
integration phase, where 95 MB per frame makes threads the only sane choice.

The reference luminance is loaded ONCE PER PROCESS by the initializer rather
than pickled with every task: it is several megabytes and sending it 265 times
would cost more than the work it enables.

This module must stay importable on its own and must NOT import Qt — a spawned
worker re-imports it, and dragging a GUI toolkit into a child process is both
slow and a good way to hang.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from .frames import load_sub, luminance
from .normalize import frame_stats
from .register import RegistrationError, find_transform


@dataclass(frozen=True)
class RegisterResult:
    """One frame's outcome. `reason` is None when it registered."""
    path: str
    matrix: np.ndarray | None = None
    exposure: float = 0.0
    stats: tuple | None = None
    reason: str | None = None


# Below this many frames a pool is not worth starting. Spawning costs about a
# second, and macOS spawn re-imports the module in every worker; on a handful of
# frames that is most of the work. Real stacks are hundreds of frames, so this
# only ever selects the serial path for tiny ones — which also keeps the test
# suite from paying pool startup on every small fixture (it took the stacking
# tests from 6 s to 37 s before this existed).
_MIN_FOR_POOL = 8

# Per-process reference, populated by _init. A module global rather than a
# closure because a spawned worker cannot receive closures.
_REF: dict = {}


def _init(ref_path: str) -> None:
    img = load_sub(ref_path, normalize=False)
    _REF["lum"] = luminance(img.data)
    _REF["shape"] = img.data.shape[:2]


def _register_one(path: str) -> RegisterResult:
    """The whole of the old Phase A loop body, for ONE frame.

    Every failure becomes a RegisterResult carrying the same wording the serial
    loop used — those strings reach the user in the stacking report — rather
    than an exception, so one bad frame cannot take the pool down with it.
    """
    try:
        sub = load_sub(path, normalize=False)
    except Exception as exc:                      # noqa: BLE001 - any read failure
        return RegisterResult(path, reason=f"unreadable: {exc}")
    if sub.data.shape[:2] != _REF["shape"]:
        return RegisterResult(path, reason="dimension mismatch")
    try:
        matrix = find_transform(luminance(sub.data), _REF["lum"])
    except RegistrationError as exc:
        return RegisterResult(path, reason=f"registration failed: {exc}")
    return RegisterResult(
        path,
        matrix=matrix,
        exposure=float(sub.metadata.get("exposure", 0.0) or 0.0),
        stats=frame_stats(sub.data),
    )


def _make_pool(workers: int, ref_path: str):
    """Separated so a test can make pool creation fail.

    The failure that matters cannot be reproduced in a test at all: macOS
    spawns rather than forks, so inside a PyInstaller bundle each worker
    re-imports the app. That fails only in the shipped .app. Hence the caller's
    fallback is unconditional.
    """
    from concurrent.futures import ProcessPoolExecutor
    return ProcessPoolExecutor(max_workers=workers, initializer=_init,
                               initargs=(ref_path,))


def _serial(paths, ref_path, on_progress, check_cancel) -> list:
    _init(ref_path)
    out = []
    for i, p in enumerate(paths, start=1):
        if check_cancel is not None:
            check_cancel()
        out.append(_register_one(p))
        if on_progress is not None:
            on_progress(i)
    return out


def register_frames(paths, ref_path: str, workers: int, *,
                    on_progress=None, check_cancel=None) -> list:
    """Register `paths` against `ref_path`, returning results IN PATH ORDER.

    Order is preserved so the caller's `used` list — and therefore the order the
    integration phase walks — is identical to the serial implementation's.

    Cancellation is checked between results, on the calling thread. It cannot
    reach into a child process: the ambient token lives in a `threading.local`
    and does not cross a process boundary at all.
    """
    paths = list(paths)
    if workers <= 1 or len(paths) < _MIN_FOR_POOL:
        return _serial(paths, ref_path, on_progress, check_cancel)

    try:
        pool = _make_pool(workers, ref_path)
    except Exception:                             # noqa: BLE001 - see _make_pool
        return _serial(paths, ref_path, on_progress, check_cancel)

    out = []
    try:
        with pool:
            # map keeps submission order, which is what makes `used` stable.
            for i, res in enumerate(pool.map(_register_one, paths), start=1):
                if check_cancel is not None:
                    check_cancel()
                out.append(res)
                if on_progress is not None:
                    on_progress(i)
    except Exception as exc:                      # noqa: BLE001
        from ..core.tasks import Cancelled
        if isinstance(exc, Cancelled):
            raise
        # A pool that dies mid-run (the bundle case) must not lose the stack.
        return _serial(paths, ref_path, on_progress, check_cancel)
    return out
