"""The project must build from a clean checkout, not only in an old venv.

`pip install -e ".[dev]"` failed on the first Linux machine, 2026-09-18:

    error: Multiple top-level packages discovered in a flat-layout:
           ['archive', 'training', 'nocturne', 'packaging']

Nothing about Linux caused it. setuptools auto-discovery walks the repo root and
refuses to guess between four importable trees; the Mac venv never saw it because
that install predates the trees that now collide. Every fresh clone would have
hit it — a contributor, a CI runner, a new machine.
"""
import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def test_the_distribution_says_what_it_contains():
    """Without this, setuptools guesses — and refuses, because it cannot."""
    find = _pyproject()["tool"]["setuptools"]["packages"]["find"]
    assert find["include"] == ["nocturne*"]


def test_the_dev_trees_are_not_part_of_the_distribution():
    """`training` must never ship: the app's venv has no torch BY DESIGN, and an
    installed training package would invite an import that cannot work. `archive`
    is the retired system and `packaging` is build scripts run by path —
    tests/test_deploy.py puts that directory on sys.path itself rather than
    relying on an install.
    """
    from setuptools import find_packages
    shipped = set(find_packages(include=_pyproject()["tool"]["setuptools"]["packages"]["find"]["include"]))
    for tree in ("training", "archive", "packaging"):
        if (ROOT / tree / "__init__.py").exists() or (ROOT / tree).is_dir():
            assert tree not in shipped, f"{tree} would be installed alongside the app"
    assert "nocturne" in shipped


def test_every_app_subpackage_is_included():
    """A subpackage missing from the wheel is an ImportError at runtime that no
    test in this repo would see, because the tests import from the source tree."""
    from setuptools import find_packages
    shipped = set(find_packages(include=["nocturne*"]))
    on_disk = {
        ".".join(p.relative_to(ROOT).parts[:-1])
        for p in (ROOT / "nocturne").rglob("__init__.py")
    }
    assert on_disk <= shipped, f"not shipped: {sorted(on_disk - shipped)}"
