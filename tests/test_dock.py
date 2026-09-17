"""The Dock-tile guard for helper processes. See nocturne/dock.py for the why."""
import ast
import pathlib
import re
import subprocess
import sys

import pytest

from nocturne.dock import is_headless_child, leave_the_dock

FROZEN = dict(frozen=True, platform="darwin")


@pytest.mark.parametrize("flag", ["--multiprocessing-fork", "--stack-job",
                                  "--check-network"])
def test_every_headless_mode_hides(flag):
    assert is_headless_child(["Nocturne", flag], **FROZEN)


def test_the_app_itself_keeps_its_tile():
    """The one thing this must never do. Transforming the main process would
    take Nocturne out of the Dock entirely — a worse bug than the one it fixes.
    """
    assert not is_headless_child(["Nocturne"], **FROZEN)
    assert not is_headless_child(["Nocturne", "--no-splash"], **FROZEN)


def test_only_frozen_and_only_macos():
    """From source there is no tile to remove: `sys.executable` is an
    interpreter, not a bundle. Verified by A/B on 2026-09-17 — a pool with Qt
    imported in the workers and one without both registered nothing.
    """
    argv = ["Nocturne", "--stack-job", "/tmp/job.json"]
    assert not is_headless_child(argv, frozen=False, platform="darwin")
    assert not is_headless_child(argv, frozen=True, platform="win32")
    assert not is_headless_child(argv, frozen=True, platform="linux")


def test_the_suite_is_never_transformed():
    """Called with no arguments, in this very process, it must decline. If the
    gate were wrong this would flip pytest itself to a UI-element process —
    which is exactly the accident the `frozen` half of the gate prevents.
    """
    assert leave_the_dock() is False


def test_a_failing_transform_does_not_raise(monkeypatch):
    """A stack that has been running two hours must not die over a Dock tile."""
    import nocturne.dock as dock
    monkeypatch.setattr(dock, "_transform_to_ui_element",
                        lambda: (_ for _ in ()).throw(OSError("symbol gone")))
    assert dock.leave_the_dock(["Nocturne", "--stack-job"], **FROZEN) is False


@pytest.mark.skipif(sys.platform != "darwin", reason="Carbon call is macOS-only")
def test_the_carbon_call_really_moves_the_process_type():
    """The only test that touches the real API, and it runs in a SUBPROCESS.

    Calling it here would transform the test runner for the rest of the session.
    The child asks LaunchServices what it is before and after, so this pins the
    OBSERVED effect — a bare `== 0` return would pass against a call that did
    nothing at all.
    """
    script = (
        "import os, subprocess, sys, time\n"
        "from PySide6.QtWidgets import QApplication\n"
        "from nocturne.dock import _transform_to_ui_element\n"
        "def kind():\n"
        "    out = subprocess.run(['lsappinfo', 'info', str(os.getpid())],\n"
        "                         capture_output=True, text=True).stdout\n"
        "    return 'UIElement' if 'type=\"UIElement\"' in out else (\n"
        "           'Foreground' if 'type=\"Foreground\"' in out else 'none')\n"
        "app = QApplication(sys.argv)\n"      # registers this process with LS
        "app.processEvents(); time.sleep(1)\n"
        "before = kind()\n"
        "ok = _transform_to_ui_element()\n"
        "time.sleep(1); app.processEvents()\n"
        "print(before, kind(), ok)\n"
    )
    env = {**dict(__import__("os").environ)}
    env.pop("QT_QPA_PLATFORM", None)      # offscreen never registers with LS
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True,
                          text=True, timeout=120, env=env)
    assert proc.returncode == 0, proc.stderr
    before, after, ok = proc.stdout.strip().split()
    if before == "none":
        pytest.skip("this machine did not register the child with LaunchServices")
    assert (before, after, ok) == ("Foreground", "UIElement", "True")


def test_the_bundles_entry_point_leaves_the_dock():
    """Checks the file the SPEC NAMES, and inspects the AST.

    Both halves are inherited scars from the freeze_support test next door
    (tests/stacking/test_register_pool.py): nocturne/__main__.py is NOT what the
    bundle runs, and a text search matches docstrings, so deleting the real call
    left that test green. Order matters here too — a spawned worker never
    returns from freeze_support(), so a call placed after it would protect
    nothing.
    """
    entry = _entry_script()
    tree = ast.parse(entry.read_text())
    guard = [n for n in tree.body
             if isinstance(n, ast.If) and ast.unparse(n.test) == "__name__ == '__main__'"]
    assert guard, f"{entry.name} has no `if __name__ == \"__main__\"` block"

    calls = [ast.unparse(n.func) for n in ast.walk(guard[0]) if isinstance(n, ast.Call)]
    assert "leave_the_dock" in calls, f"{entry.name} never calls leave_the_dock()"
    assert calls.index("leave_the_dock") < calls.index("multiprocessing.freeze_support"), \
        "leave_the_dock() must run BEFORE freeze_support(), which a worker never returns from"


def _entry_script() -> pathlib.Path:
    """The file the SPEC names. Not nocturne/__main__.py — see the test above."""
    root = pathlib.Path(__file__).resolve().parents[1]
    spec = (root / "packaging" / "nocturne.spec").read_text()
    m = re.search(r'SCRIPT\s*=\s*os\.path\.join\(SPECPATH,\s*"([^"]+)"\)', spec)
    assert m, "could not find the entry script in nocturne.spec"
    return root / "packaging" / m.group(1)


def test_the_entry_point_imports_the_gui_after_freeze_support():
    """A pool worker must not build the GUI it will never use.

    macOS spawn re-runs this file from the top in every worker, so a module-level
    `from nocturne.__main__ import main` — which pulls in QApplication, QIcon and
    MainWindow — was executed by all eight of them before freeze_support() told
    them what they were. Measured 2026-09-17: 69 MB and ~0.5 s each, 551 MB
    across a stack, held by processes with no window.

    Two things to hold, and the second is the one that bites: the import must be
    INSIDE the __main__ guard (module level runs in every worker), and it must
    come AFTER freeze_support() (which exits, so a worker never reaches it).
    """
    tree = ast.parse(_entry_script().read_text())

    module_level = [n for n in tree.body if isinstance(n, ast.ImportFrom)
                    and n.module == "nocturne.__main__"]
    assert not module_level, \
        "nocturne.__main__ is imported at module level — every spawned worker pays for it"

    guard = [n for n in tree.body
             if isinstance(n, ast.If) and ast.unparse(n.test) == "__name__ == '__main__'"]
    assert guard, "entry point has no `if __name__ == \"__main__\"` block"

    imports = [n for n in ast.walk(guard[0]) if isinstance(n, ast.ImportFrom)
               and n.module == "nocturne.__main__"]
    assert imports, "the entry point never imports main()"

    freeze = [n for n in ast.walk(guard[0]) if isinstance(n, ast.Call)
              and ast.unparse(n.func) == "multiprocessing.freeze_support"]
    assert freeze, "the entry point never calls freeze_support()"

    assert imports[0].lineno > freeze[0].lineno, (
        "the GUI import must come AFTER freeze_support(), or workers import Qt "
        "before they learn they are workers")
