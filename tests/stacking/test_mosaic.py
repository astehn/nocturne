

def test_the_astap_preflight_agrees_with_settings(tmp_path):
    """Andreas, 2026-09-04: Settings showed a green "✓ ASTAP found" for
    /Applications/ASTAP.app while the mosaic run refused the SAME path with
    "no runnable solver" — one dialog apart.

    A macOS .app is a DIRECTORY. `is_tool` resolves it to the executable inside
    before checking; check_astap rolled its own isfile/X_OK on the raw path and
    saw a directory. A preflight that exists to fail fast must not fail fast on
    a false negative.
    """
    from nocturne.settings import is_tool
    from nocturne.stacking.mosaic import check_astap

    # A macOS-style bundle: a directory whose executable lives inside it.
    app = tmp_path / "ASTAP.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    exe = macos / "ASTAP"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)

    assert is_tool(str(app)) is True, "the fixture is not a valid bundle"
    check_astap(str(app))          # must NOT raise


def test_the_astap_preflight_still_refuses_what_it_should(tmp_path):
    """The fix must not turn the gate off. Fixing a false negative by accepting
    everything would be worse than the bug — a mosaic would stack every panel
    and then fail at the solve, which is what the check exists to prevent."""
    import pytest
    from nocturne.stacking.mosaic import check_astap
    for bad in ("", str(tmp_path / "nope"), str(tmp_path)):
        with pytest.raises(ValueError, match="no runnable solver"):
            check_astap(bad)
    doc = tmp_path / "notes.md"          # a file, but not executable
    doc.write_text("not a solver")
    with pytest.raises(ValueError, match="no runnable solver"):
        check_astap(str(doc))


def test_the_solver_is_built_from_the_resolved_binary():
    """Even past the check, ASTAP(bundle_path) would exec a directory — errno
    13. Every other caller in the app resolves first; this one did not."""
    from pathlib import Path
    src = (Path(__file__).parents[2] / "nocturne" / "stacking" / "mosaic.py").read_text()
    body = src.split("def _astap_solver")[1].split("\ndef ")[0]
    assert "ASTAP(resolve_binary(" in body, "the solver is built from an unresolved path"
