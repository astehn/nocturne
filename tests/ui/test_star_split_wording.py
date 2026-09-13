"""The app says "separating stars", never "removing stars".

Andreas, 2026-09-12, after a morning using the app: several tools said
"Removing stars…" when what actually happens is a SPLIT that keeps both layers
— and other tools already said "Separating stars…", so it read as
inconsistency on top of being wrong. His wording, and it is the correct one.

A guard rather than a one-time fix because this is copy, and copy drifts: the
same phrase was correct in six places and wrong in four for weeks, and nothing
in the suite could tell. Scanning string CONSTANTS (via ast) rather than raw
text is what makes it usable — comments and this file's own prose can discuss
the old wording without tripping it.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2] / "nocturne"
# "remove_stars" is the RCAstro METHOD name and is not user-facing; the guard
# looks for the words as prose, which is why it matches on a following space.
_BANNED = ("removing stars", "remove stars", "removes stars")


def _offending_strings():
    bad = []
    for path in sorted(_ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:                     # pragma: no cover - nothing here has one
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                low = node.value.lower()
                if any(phrase in low for phrase in _BANNED):
                    bad.append(f"{path.relative_to(_ROOT.parent)}:{node.lineno}: "
                               f"{node.value.strip()[:70]!r}")
    return bad


def test_no_user_facing_string_says_removing_stars():
    bad = _offending_strings()
    assert not bad, (
        "these strings say the split REMOVES stars; it separates them and keeps "
        "both layers:\n  " + "\n  ".join(bad))


def test_the_two_dialogs_that_were_wrong_say_separating():
    """Names the specific sites, so deleting the scan above cannot silently
    take the fix with it."""
    from nocturne.ui import color_balance_dialog, narrowband_dialog
    for mod in (color_balance_dialog, narrowband_dialog):
        assert mod._SPLIT_MSG.startswith("Separating stars"), mod.__name__


def test_the_guard_has_teeth():
    """Proves the scan can actually fail — a regression test that passes on its
    first run has not been shown to work."""
    tree = ast.parse('x = "Removing stars…"')
    found = [n.value for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and any(p in n.value.lower() for p in _BANNED)]
    assert found == ["Removing stars…"]
