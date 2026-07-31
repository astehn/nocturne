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


import datetime


def test_draft_notes_categorizes_by_prefix():
    n = deploy.draft_notes_from_log([
        "feat(ui): add close project",
        "fix: correct crop math",
        "chore: bump deps",
        "docs: tweak readme",
    ])
    assert n.added == ["add close project"]
    assert n.fixed == ["correct crop math"]
    assert n.changed == ["bump deps", "tweak readme"]
    assert n.headline == ""


def test_render_release_notes_skips_empty_sections():
    n = deploy.Notes(headline="A calmer build", added=["X"], changed=[], fixed=["Y"])
    md = deploy.render_release_notes(n)
    assert md.startswith("A calmer build")
    assert "### Added" in md and "- X" in md
    assert "### Fixed" in md and "- Y" in md
    assert "### Changed" not in md


def test_render_changelog_md_has_dated_header():
    n = deploy.Notes(headline="h", added=["X"], changed=[], fixed=[])
    md = deploy.render_changelog_md("0.4.0", datetime.date(2026, 7, 25), n)
    assert md.startswith("## [0.4.0] — 2026-07-25")
    assert "### Added" in md


def test_render_changelog_html_is_escaped_article():
    n = deploy.Notes(headline="Colour & light", added=["a < b"], changed=[], fixed=[])
    html = deploy.render_changelog_html("0.4.0", datetime.date(2026, 7, 25), n)
    assert html.lstrip().startswith('<article class="release">')
    assert "<h2>Colour &amp; light</h2>" in html
    assert '<p class="when">25 July 2026</p>' in html
    assert "<li>a &lt; b</li>" in html
    assert html.rstrip().endswith("</article>")


def test_render_changelog_html_names_the_version_even_when_a_headline_exists():
    # Regression: the version used to be the `headline or version` fallback, so a
    # release with a headline -- i.e. every real release -- published without one.
    n = deploy.Notes(headline="Colour & light", added=["a"], changed=[], fixed=[])
    html = deploy.render_changelog_html("0.4.0", datetime.date(2026, 7, 25), n)
    assert '<p class="ver">v0.4.0</p>' in html
    assert html.index('class="ver"') < html.index("<h2>"), \
        "the version must lead the entry, not trail the prose"


def _cfg(tmp_path):
    return deploy.load_config(_write_config(tmp_path))


def test_release_asset_name():
    assert deploy.release_asset_name("0.4.0") == "Nocturne-0.4.0.zip"


def test_build_rsync_cmd_is_safe(tmp_path):
    site = tmp_path / "site"
    (site / "img" / "_originals").mkdir(parents=True)
    for f in ("index.html", "styles.css", "main.js", "config.php"):
        (site / f).write_text("x")
    (site / "img" / "shot.jpg").write_text("x")
    cmd = deploy.build_rsync_cmd(_cfg(tmp_path), site)
    assert not any(a.startswith("--del") for a in cmd)   # no --delete / --delete-after / --del
    assert "--rsync-path=sudo rsync" in cmd
    # every configured exclude is present
    for e in _cfg(tmp_path).exclude:
        assert f"--exclude={e}" in cmd
    # allowlisted assets are sources; server state is not
    joined = " ".join(cmd)
    assert "index.html" in joined and "styles.css" in joined
    assert f"{str(site / 'img')}" in joined       # img dir synced
    assert "config.php" not in joined             # server state never a source
    assert cmd[-1] == "debian@vps-91763a81.vps.ovh.net:/var/www/nocturne/"


def test_build_rsync_cmd_refuses_without_required_exclude(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('''
[github]
repo = "r"
[website]
ssh_host = "h"
remote_path = "/p"
owner = "www-data:www-data"
dir_mode = "755"
file_mode = "644"
include = ["*.html"]
exclude = ["img/_originals/"]
''')  # missing db/, uploads/, config*.php
    with pytest.raises(ValueError):
        deploy.build_rsync_cmd(deploy.load_config(p), tmp_path)


def test_build_chown_cmd(tmp_path):
    cmd = deploy.build_chown_cmd(_cfg(tmp_path))
    assert cmd[0] == "ssh"
    assert cmd[1] == "debian@vps-91763a81.vps.ovh.net"
    remote = cmd[2]
    assert "sudo chown -R www-data:www-data /var/www/nocturne" in remote
    assert "-type d -exec chmod 755" in remote
    assert "-type f -exec chmod 644" in remote
    assert "/var/www/nocturne" in remote and remote.count("/var/www/nocturne") == 3


def test_rsync_excludes_survive_colliding_include(tmp_path):
    # even if include is misconfigured to match server state, the exclude filter
    # for it must still be in the argv (rsync applies it to named sources)
    p = tmp_path / "c.toml"
    p.write_text('''
[github]
repo = "r"
[website]
ssh_host = "h"
remote_path = "/p"
owner = "www-data:www-data"
dir_mode = "755"
file_mode = "644"
include = ["*.php"]
exclude = ["config*.php", "db/", "uploads/"]
''')
    site = tmp_path / "site"; site.mkdir()
    (site / "config.php").write_text("secret")
    cmd = deploy.build_rsync_cmd(deploy.load_config(p), site)
    assert "--exclude=config*.php" in cmd


def test_rsync_skips_missing_include_dir(tmp_path):
    site = tmp_path / "site"; site.mkdir()   # no img/ subdir present
    cmd = deploy.build_rsync_cmd(_cfg(tmp_path), site)   # config includes "img/"
    assert not any(a == str(site / "img") for a in cmd)  # missing dir skipped, no crash


def test_build_chown_cmd_rejects_bad_owner(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.owner = "rm -rf /"
    with pytest.raises(ValueError):
        deploy.build_chown_cmd(cfg)


import json


class RecordingRunner:
    """Captures commands; returns canned stdout for read-only queries."""
    def __init__(self, outputs=None):
        self.calls = []
        self.outputs = outputs or {}
    def __call__(self, cmd, *, capture=False):
        self.calls.append(cmd)
        for key, out in self.outputs.items():
            if key in " ".join(cmd):
                return out
        return ""


def test_prepend_file_inserts_before_anchor(tmp_path):
    f = tmp_path / "CHANGELOG.md"
    f.write_text("# Changelog\n\npreamble\n\n## [0.3.0] — 2026-07-23\nold\n")
    deploy.prepend_file(f, "## [0.4.0] — 2026-07-25\nnew", anchor="## [")
    text = f.read_text()
    assert text.index("[0.4.0]") < text.index("[0.3.0]")
    assert "preamble" in text


def test_dry_run_prints_plan_and_does_not_mutate(tmp_path, capsys, monkeypatch):
    # minimal fake repo tree
    (tmp_path / "pyproject.toml").write_text('version = "0.3.0"\n')
    (tmp_path / "nocturne").mkdir()
    (tmp_path / "nocturne" / "__init__.py").write_text('__version__ = "0.3.0"\n')
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [0.3.0] — 2026-07-23\nx\n")
    site = tmp_path / "site"; site.mkdir()
    (site / "changelog.html").write_text('<div class="wrap prose">\n<article class="release">old</article>\n</div>')
    cfg = _write_config(tmp_path)
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"headline": "h", "added": ["X"], "changed": [], "fixed": []}))
    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    monkeypatch.setattr(deploy, "SITE", site)
    monkeypatch.setattr(deploy, "preflight", lambda c, run: None)
    rc = deploy.main(["--config", str(cfg), "--version", "0.4.0",
                      "--notes-json", str(notes), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "0.4.0" in out
    assert "rsync" in out and "gh release create" in out   # remote plan printed
    # nothing actually changed:
    assert 'version = "0.3.0"' in (tmp_path / "pyproject.toml").read_text()


def test_preflight_aborts_when_not_on_main(tmp_path):
    def fake_run(cmd, *, capture=False):
        if "rev-parse" in cmd:
            return "feature-x\n"
        return ""
    with pytest.raises(SystemExit):
        deploy.preflight(_cfg(tmp_path), run=fake_run)


def test_preflight_aborts_on_gh_auth_failure(tmp_path, monkeypatch):
    import subprocess as sp
    monkeypatch.setattr(deploy.subprocess, "run", lambda *a, **k: None)  # skip real pytest
    def fake_run(cmd, *, capture=False):
        if "rev-parse" in cmd:
            return "main\n"
        if "rev-list" in cmd:
            return "0\n"
        if cmd[:3] == ["gh", "auth", "status"]:
            raise sp.CalledProcessError(1, cmd)
        return ""
    with pytest.raises(SystemExit):
        deploy.preflight(_cfg(tmp_path), run=fake_run)


def test_remote_release_order_and_commands(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "site").mkdir()
    r = RecordingRunner()
    notes = deploy.Notes(headline="h", added=["X"], changed=[], fixed=[])
    import unittest.mock as mock
    with mock.patch.object(deploy, "SITE", tmp_path / "site"):
        deploy._remote_release(cfg, "0.4.0", notes, "Nocturne-0.4.0.zip", r)
    flat = [" ".join(c) for c in r.calls]
    # order: commit -> push -> tag -> push tag -> gh release -> rsync -> chown
    idx = lambda frag: next(i for i, s in enumerate(flat) if frag in s)
    assert idx("git commit") < idx("git push origin main")
    assert idx("git push origin main") < idx("git tag v0.4.0")
    assert idx("git tag v0.4.0") < idx("git push origin v0.4.0")
    assert idx("git push origin v0.4.0") < idx("gh release create v0.4.0")
    assert idx("gh release create v0.4.0") < idx("rsync")
    assert idx("rsync") < idx("ssh")   # chown is the final ssh
    assert idx("git add") < idx("git commit")
    # never commits site/
    assert not any("site/" in s and "git add" in s for s in flat)
    # gh uploads the asset
    assert any("Nocturne-0.4.0.zip" in s for s in flat)


def test_build_failure_rolls_back_version(tmp_path, monkeypatch):
    import subprocess as sp
    (tmp_path / "pyproject.toml").write_text('version = "0.3.0"\n')
    (tmp_path / "nocturne").mkdir()
    (tmp_path / "nocturne" / "__init__.py").write_text('__version__ = "0.3.0"\n')
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [0.3.0] — 2026-07-23\nx\n")
    sp.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    sp.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
           cwd=tmp_path, check=True)
    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    monkeypatch.setattr(deploy, "preflight", lambda c, run: None)
    monkeypatch.setattr(deploy, "build_app",
                        lambda run=None: (_ for _ in ()).throw(SystemExit("boom")))
    cfg = _write_config(tmp_path)
    notes = tmp_path / "n.json"
    notes.write_text('{"headline":"h","added":["X"],"changed":[],"fixed":[]}')
    with pytest.raises(SystemExit):
        deploy.main(["--config", str(cfg), "--version", "0.4.0", "--notes-json", str(notes)])
    assert '0.3.0' in (tmp_path / "pyproject.toml").read_text()          # bump rolled back
    assert '0.4.0' not in (tmp_path / "pyproject.toml").read_text()
    assert '0.3.0' in (tmp_path / "nocturne" / "__init__.py").read_text()


def _cfg_with_download(tmp_path):
    p = tmp_path / "cdl.toml"
    p.write_text('''
[github]
repo = "astehn/nocturne"
[website]
ssh_host = "debian@VPS"
remote_path = "/var/www/nocturne"
owner = "www-data:www-data"
dir_mode = "755"
file_mode = "644"
include = ["*.html"]
exclude = ["config*.php", "db/", "uploads/"]
download_path = "/var/www/nocturne/download/Nocturne.zip"
''')
    return deploy.load_config(p)


def test_download_path_optional_in_config(tmp_path):
    assert _cfg(tmp_path).download_path is None
    assert _cfg_with_download(tmp_path).download_path == "/var/www/nocturne/download/Nocturne.zip"


def test_build_download_cmd_absent_and_present(tmp_path):
    assert deploy.build_download_cmd(_cfg(tmp_path), "Nocturne-0.4.0.zip") is None
    cmd = deploy.build_download_cmd(_cfg_with_download(tmp_path), "Nocturne-0.4.0.zip")
    assert "--rsync-path=sudo rsync" in cmd
    assert not any(a.startswith("--del") for a in cmd)
    assert any("Nocturne-0.4.0.zip" in a for a in cmd)
    assert cmd[-1] == "debian@VPS:/var/www/nocturne/download/Nocturne.zip"


def test_remote_release_uploads_binary_before_chown(tmp_path):
    import unittest.mock as mock
    (tmp_path / "site").mkdir()
    r = RecordingRunner()
    notes = deploy.Notes(headline="h", added=["X"], changed=[], fixed=[])
    with mock.patch.object(deploy, "SITE", tmp_path / "site"):
        deploy._remote_release(_cfg_with_download(tmp_path), "0.4.0", notes, "Nocturne-0.4.0.zip", r)
    flat = [" ".join(c) for c in r.calls]
    dl_idx = next(i for i, s in enumerate(flat) if "download/Nocturne.zip" in s and "Nocturne-0.4.0.zip" in s)
    chown_idx = next(i for i, s in enumerate(flat) if "chown" in s)
    assert dl_idx < chown_idx


def test_remote_release_skips_binary_upload_when_unset(tmp_path):
    import unittest.mock as mock
    (tmp_path / "site").mkdir()
    r = RecordingRunner()
    notes = deploy.Notes(headline="h", added=["X"], changed=[], fixed=[])
    with mock.patch.object(deploy, "SITE", tmp_path / "site"):
        deploy._remote_release(_cfg(tmp_path), "0.4.0", notes, "Nocturne-0.4.0.zip", r)
    assert not any("download/" in " ".join(c) for c in r.calls)


def test_download_path_outside_remote_path_rejected(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text('''
[github]
repo = "r"
[website]
ssh_host = "h"
remote_path = "/var/www/nocturne"
owner = "www-data:www-data"
dir_mode = "755"
file_mode = "644"
include = ["*.html"]
exclude = ["config*.php", "db/", "uploads/"]
download_path = "/srv/other/App.zip"
''')
    with pytest.raises(ValueError):
        deploy.load_config(p)
