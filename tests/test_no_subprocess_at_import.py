"""A packaged app must not spawn processes just to start up.

colour_demosaicing runs `git describe` in its __init__ to decorate a version
string, inside a bare except. On a developer's machine that fails silently. On
a Mac without the Xcode command line tools, /usr/bin/git is a stub whose only
purpose is to pop the system "install the developer tools?" dialog — so a
downloaded copy of Nocturne 0.11.1 asked its user to install a compiler before
it would open a photograph.

The exception being caught is exactly why this needs a test: nothing fails, no
log line appears, and the only symptom is a dialog on a machine the developer
does not have.
"""
import subprocess

import pytest


def _fresh_import(monkeypatch, calls_sink):
    """Re-import for real, not just reload.

    colour_demosaicing's __init__ runs once per process, so a plain
    importlib.reload of fits_io re-executes the `from ... import` line without
    re-running the package that does the git call. Whichever test ran first
    consumed the only observable chance — which made the second test incapable
    of failing, exactly the kind of guard that looks like protection and is
    not. Purging both from sys.modules forces the real thing.
    """
    import sys
    for name in list(sys.modules):
        if name.startswith(("colour_demosaicing", "nocturne.core.fits_io")):
            monkeypatch.delitem(sys.modules, name, raising=False)
    import importlib
    importlib.import_module("nocturne.core.fits_io")
    return calls_sink


def _spy_subprocess(monkeypatch):
    calls = []
    for name in ("check_output", "run", "Popen", "call", "check_call"):
        real = getattr(subprocess, name)

        def make(_real=real):
            def spy(cmd, *args, **kwargs):
                first = cmd[0] if isinstance(cmd, (list, tuple)) and cmd else cmd
                if isinstance(first, str):
                    calls.append(first.rsplit("/", 1)[-1])
                return _real(cmd, *args, **kwargs)
            return spy

        monkeypatch.setattr(subprocess, name, make())
    return calls


def test_importing_the_image_loader_spawns_nothing(monkeypatch):
    """fits_io is imported at startup by almost everything, so anything it runs
    on import runs before the window appears."""
    calls = _fresh_import(monkeypatch, _spy_subprocess(monkeypatch))
    assert calls == [], f"importing fits_io spawned: {calls}"


def test_git_is_never_invoked_at_import(monkeypatch):
    """Named separately from the blanket check because git is the one that has
    a user-visible consequence, and because the fix is easy to remove by
    accident when someone tidies the import."""
    calls = _fresh_import(monkeypatch, _spy_subprocess(monkeypatch))
    assert "git" not in calls, (
        "something ran git during import — on a Mac without the Xcode command "
        "line tools that pops the installer dialog before the app can start")


def test_the_suppressor_only_blocks_git(monkeypatch):
    """The guard denies one command, not every subprocess. Blocking more would
    break GraXpert, ASTAP and RC-Astro, which are the point of the app."""
    from nocturne.core.fits_io import _import_demosaicing
    seen = []
    real = subprocess.check_output

    def recording(cmd, *a, **k):
        seen.append(cmd)
        return b""

    monkeypatch.setattr(subprocess, "check_output", recording)
    _import_demosaicing()
    # the patch must be removed again, so ordinary calls still work
    subprocess.check_output(["echo", "still-working"])
    assert ["echo", "still-working"] in seen


def test_the_demosaic_function_survives_the_suppression():
    """Suppressing the version lookup must not cost us the function we import
    the package for."""
    import numpy as np
    from nocturne.core.fits_io import demosaicing_CFA_Bayer_bilinear
    out = demosaicing_CFA_Bayer_bilinear(np.zeros((8, 8), np.float32), "GRBG")
    assert out.shape == (8, 8, 3)
