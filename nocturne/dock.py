"""Keep the app's helper processes out of the macOS Dock.

Stacking registers frames in a process pool, and macOS SPAWNS rather than
forks, so every worker re-executes `sys.executable`. In the shipped .app that
is the app binary itself — and any process running a bundled executable checks
in with LaunchServices as a Foreground application and is given its own Dock
tile, with no window and no QApplication anywhere in it. Andreas ran a stack on
2026-09-17 and got ELEVEN Nocturne icons in his Dock: eight registration
workers, the `--stack-job` child, and the app.

Measured, not assumed: running the bundle as `--check-network`, which returns
long before QApplication is constructed, produces

    bundleID="com.nocturne.app"  pid = 53835  type="Foreground"

within a second of launch — one registration per process.

This is invisible from source. There `sys.executable` is a bare interpreter,
not a bundle; a pool with Qt imported in the workers and one without both
register nothing at all. So neither a dev run nor the test suite can observe
the symptom, and only the code SHAPE can be pinned — see
tests/test_dock.py::test_the_bundles_entry_point_leaves_the_dock, which follows
the freeze_support test next door for the same reason.

The cure is the documented one: transform the child into a UI-element process,
which is what a background helper is. Verified from source against a real Qt
process — `type="Foreground"` before the call, `type="UIElement"` after.

It REMOVES the tile, it does not prevent it. LaunchServices checks a bundled
process in at exec, before Python starts, so there is a window no Python code
can close. Timed against the built bundle on 2026-09-17:

    0.13 s   child checks in     type="Foreground"   (tile appears)
    0.51 s   this code runs      type="UIElement"    (tile goes)

So each child flashes a tile for about four tenths of a second. Eight workers
starting together flash together; the `--stack-job` child, which lives for the
whole stack, is a tile for that same 0.4 s and then gone. Andreas saw exactly
one brief extra icon on a background stack and called it fine.

Closing that window entirely would mean the children running a DIFFERENT
executable — a second, console-only binary in the bundle, with
multiprocessing.set_executable() and job_command() pointed at it. That is a
build-level change for four tenths of a second, and it was not taken.

An earlier note here claimed the fixed build "never registers". That was a
measurement artifact: the probe polled for ~0.2 s and stopped before the
process had checked in at all.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import sys

# ProcessApplicationTransformState. 4 is kProcessTransformToUIElementApplication
# — an app with no Dock tile and no menu bar, which is exactly what a worker is.
# NOT 2 (kProcessTransformToBackgroundApplication): that also detaches the
# process from the window server, and these children are the app binary, which
# has a QApplication compiled into it.
_TO_UI_ELEMENT = 4
_CURRENT_PROCESS = 2                     # kCurrentProcess, in the low word

# argv of a process that must not appear in the Dock. `--multiprocessing-fork`
# is what spawn passes a FROZEN child (multiprocessing.spawn.get_command_line);
# the other two are Nocturne's own headless modes, dispatched in __main__ before
# QApplication exists.
_HEADLESS_FLAGS = ("--multiprocessing-fork", "--stack-job", "--check-network")


def is_headless_child(argv, *, frozen: bool, platform: str) -> bool:
    """Should this process hide itself?

    Only when FROZEN: from source `sys.executable` is an interpreter, no tile is
    ever created, and transforming would be a no-op with a real cost — it is the
    main window's own process that runs the test suite.
    """
    return (platform == "darwin" and bool(frozen)
            and any(flag in argv for flag in _HEADLESS_FLAGS))


def _transform_to_ui_element() -> bool:
    """The Carbon call, isolated so a test can drive it in a subprocess.

    Returns whether the transform succeeded. Deprecated API, and the modern
    replacement (NSApplication.setActivationPolicy_) needs pyobjc, which this
    app does not ship and will not add for a Dock tile.
    """
    class _PSN(ctypes.Structure):
        _fields_ = [("high", ctypes.c_uint32), ("low", ctypes.c_uint32)]

    path = ctypes.util.find_library("ApplicationServices")
    if path is None:
        return False
    lib = ctypes.CDLL(path)
    lib.TransformProcessType.argtypes = [ctypes.POINTER(_PSN), ctypes.c_uint32]
    lib.TransformProcessType.restype = ctypes.c_int32
    return lib.TransformProcessType(ctypes.byref(_PSN(0, _CURRENT_PROCESS)),
                                    _TO_UI_ELEMENT) == 0     # noErr


def leave_the_dock(argv=None, *, frozen=None, platform=None) -> bool:
    """Take a helper process out of the Dock. Returns whether it did.

    Swallows everything: this is cosmetic, and a stack that has been running for
    two hours must not die because a Carbon symbol moved.
    """
    argv = sys.argv if argv is None else argv
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    platform = sys.platform if platform is None else platform
    if not is_headless_child(argv, frozen=frozen, platform=platform):
        return False
    try:
        return _transform_to_ui_element()
    except Exception:                    # noqa: BLE001 - never worth a crash
        return False
