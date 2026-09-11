"""A second `def` of the same name silently replaces the first.

Python rebinds without complaint and pytest reports nothing, so the earlier
definition becomes unreachable code that still LOOKS live — every caller gets
the later one whatever the file appears to say.

Found for real on 2026-09-09: `_stretched_window` was defined twice in
tests/ui/test_main_window.py, and the two were not equivalent. The first ran the
genuine Stretch step and asserted the result was non-linear; the second faked it
with a `_PrecomputedStep` carrying the UNSTRETCHED pixels relabelled
`is_linear=False`. Eighteen tests written to exercise the real pipeline were
quietly running against a stand-in, and the suite was green throughout. Removing
the fake left all 338 tests in that file passing, so it had never been needed.

The same class of problem as CLAUDE.md's note about `str.replace(old, new, 1)`
patching a duplicate of a line in a different function and reporting success.
"""
import ast
import collections
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SEARCHED = ("tests", "nocturne", "packaging")


def _shadowed(path: Path):
    """(name, [line, ...]) for every top-level def/class defined more than once.

    Top level only: a method redefined inside a class is the same mistake but
    `@property`/`@x.setter` pairs make that a nest of false positives, and the
    failure that motivated this was at module scope.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    seen = collections.defaultdict(list)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            seen[node.name].append(node.lineno)
    return [(name, lines) for name, lines in seen.items() if len(lines) > 1]


def _modules():
    for root in SEARCHED:
        base = ROOT / root
        if base.exists():
            yield from sorted(base.rglob("*.py"))


def test_no_module_defines_the_same_name_twice():
    offenders = []
    for path in _modules():
        for name, lines in _shadowed(path):
            offenders.append(
                f"{path.relative_to(ROOT)}: {name} defined at lines "
                f"{', '.join(str(n) for n in lines)} — only the last one is live")
    assert not offenders, (
        "a later definition silently replaces the earlier one:\n  "
        + "\n  ".join(offenders))


def test_the_guard_can_actually_see_a_duplicate(tmp_path):
    """Proves the detector works, so a green run means "none found" rather than
    "found nothing because it looks in the wrong place"."""
    p = tmp_path / "dupe.py"
    p.write_text("def a():\n    pass\n\n\ndef a():\n    pass\n")
    assert _shadowed(p) == [("a", [1, 5])]


def test_the_guard_ignores_a_single_definition(tmp_path):
    p = tmp_path / "fine.py"
    p.write_text("def a():\n    pass\n\n\ndef b():\n    pass\n")
    assert _shadowed(p) == []


def test_the_guard_actually_reads_files():
    """A path typo would make the sweep silently examine nothing."""
    assert sum(1 for _ in _modules()) > 50
