"""The PHP test files must actually run every check they contain.

`site/tests/report_validate_test.php` printed its summary and called `exit()`
in the MIDDLE of the file, so every check below was dead code: it printed
nothing and could not fail. The notifier check had been passing by not running
since the day it was written, and it took three new checks producing no output
to notice (2026-09-22).

Those files are not collected by pytest — they are plain scripts run as
`php site/tests/<name>_test.php` — so nothing else would have said so.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SITE_TESTS = Path(__file__).parent.parent / "site" / "tests"
FILES = sorted(SITE_TESTS.glob("*_test.php"))


def _code_lines(path):
    """(lineno, text) for lines that are code, not comments or blank."""
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if line and not line.startswith(("//", "#", "*", "/*")):
            yield n, line


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_check_sits_after_the_exit(path):
    """Structural, and it reads the file rather than the output because a dead
    check produces no output to read — which is exactly why it hid."""
    exits = [n for n, line in _code_lines(path) if line.startswith("exit(")]
    checks = [n for n, line in _code_lines(path) if line.startswith("check(")]
    if not exits or not checks:
        return
    stranded = [n for n in checks if n > min(exits)]
    assert not stranded, (
        f"{path.name}: exit() at line {min(exits)} makes the checks at "
        f"{stranded} dead code — they print nothing and cannot fail")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_the_file_passes(path):
    """Runs it for real. `php` is not on every machine, so skip rather than
    fail when it is absent — a missing interpreter is not a broken site."""
    if shutil.which("php") is None:
        pytest.skip("php is not installed on this machine")
    r = subprocess.run(["php", str(path)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout, r.stdout
