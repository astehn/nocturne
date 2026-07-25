import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
import deploy  # noqa: E402


def test_parse_version_ok():
    assert deploy.parse_version("0.3.0") == (0, 3, 0)


def test_parse_version_rejects_malformed():
    for bad in ("0.3", "v0.3.0", "1.2.3.4", "a.b.c", ""):
        with pytest.raises(ValueError):
            deploy.parse_version(bad)


def test_next_minor_bumps_minor_zeroes_patch():
    assert deploy.next_minor("0.3.0") == "0.4.0"
    assert deploy.next_minor("1.2.9") == "1.3.0"


def test_set_version_files_writes_both(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        'name = "nocturne"\nversion = "0.3.0"\ndescription = "x"\n')
    (tmp_path / "nocturne").mkdir()
    (tmp_path / "nocturne" / "__init__.py").write_text('__version__ = "0.3.0"\n')
    deploy.set_version_files(tmp_path, "0.4.0")
    assert 'version = "0.4.0"' in (tmp_path / "pyproject.toml").read_text()
    assert '__version__ = "0.4.0"' in (tmp_path / "nocturne" / "__init__.py").read_text()
