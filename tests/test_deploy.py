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
    assert '0.3.0' not in (tmp_path / "pyproject.toml").read_text()   # replaced, not appended


def test_set_version_files_raises_if_no_version_line(tmp_path):
    (tmp_path / "pyproject.toml").write_text('name = "nocturne"\n')  # no version line
    (tmp_path / "nocturne").mkdir()
    (tmp_path / "nocturne" / "__init__.py").write_text('__version__ = "0.3.0"\n')
    with pytest.raises(ValueError):
        deploy.set_version_files(tmp_path, "0.4.0")


def _write_config(tmp_path):
    p = tmp_path / "deploy.local.toml"
    p.write_text('''
[github]
repo = "astehn/nocturne"

[website]
ssh_host = "debian@vps-91763a81.vps.ovh.net"
remote_path = "/var/www/nocturne"
owner = "www-data:www-data"
dir_mode = "755"
file_mode = "644"
include = ["*.html", "styles.css", "main.js", "img/"]
exclude = ["img/_originals/", "config*.php", "db/", "uploads/"]
''')
    return p


def test_load_config_reads_all_fields(tmp_path):
    cfg = deploy.load_config(_write_config(tmp_path))
    assert cfg.repo == "astehn/nocturne"
    assert cfg.ssh_host == "debian@vps-91763a81.vps.ovh.net"
    assert cfg.remote_path == "/var/www/nocturne"
    assert cfg.owner == "www-data:www-data"
    assert cfg.dir_mode == "755" and cfg.file_mode == "644"
    assert "img/" in cfg.include
    assert "db/" in cfg.exclude


def test_load_config_missing_key_raises(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text('[website]\nssh_host = "x"\n')
    with pytest.raises(ValueError):
        deploy.load_config(p)
