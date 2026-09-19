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
exclude = ["img/_originals/", "config*.php", "db/", "uploads/", "*.fits", "*.fit"]
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
exclude = ["config*.php", "db/", "uploads/", "*.fits", "*.fit"]
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
exclude = ["config*.php", "db/", "uploads/", "*.fits", "*.fit"]
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
exclude = ["config*.php", "db/", "uploads/", "*.fits", "*.fit"]
download_path = "/srv/other/App.zip"
''')
    with pytest.raises(ValueError):
        deploy.load_config(p)


# --- generated site: the release must write to the SOURCE ---------------------

def test_release_prepends_the_changelog_entry_to_the_source_not_the_output():
    """site/changelog.html is generated from site/_src/changelog.html. Writing the
    release entry to the generated file would be erased by generate_site() moments
    later — the note would vanish silently, and only on a real release."""
    import inspect
    src = inspect.getsource(deploy.main)
    assert 'prepend_file(SITE_SRC / "changelog.html"' in src
    assert 'prepend_file(SITE / "changelog.html"' not in src
    # ...and the release path must regenerate AFTER that prepend, not before.
    # rindex, not index: generate_site() also appears earlier in the --site-only
    # branch, which is a different code path.
    assert src.index('prepend_file(SITE_SRC / "changelog.html"') < src.rindex("generate_site(")


def test_generate_site_runs_both_generators_through_the_injectable_runner():
    calls = []
    deploy.generate_site(run=lambda cmd, **kw: calls.append(cmd))
    joined = [" ".join(c) for c in calls]
    assert any("build_site.py" in c for c in joined), joined
    assert any("make_sitemap.py" in c for c in joined), joined
    assert joined.index([c for c in joined if "build_site.py" in c][0]) < \
           joined.index([c for c in joined if "make_sitemap.py" in c][0]), \
        "the sitemap must be generated from the freshly built pages"


def test_site_only_publishes_without_the_release_preflight(tmp_path, monkeypatch):
    """A copy edit must not be blocked by a dirty tree or an out-of-sync tag —
    those gates exist for cutting a release, which this is not."""
    cfg_path = _write_config(tmp_path)
    ran = []
    monkeypatch.setattr(deploy, "real_run", lambda cmd, **kw: ran.append(cmd) or "")
    monkeypatch.setattr(deploy, "generate_site", lambda run=None: ran.append(["GENERATE"]))
    monkeypatch.setattr(deploy, "preflight",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("preflight ran")))
    rc = deploy.main(["--config", str(cfg_path), "--site-only"])
    assert rc == 0
    assert ["GENERATE"] == ran[0], "generation happens before any upload"
    assert any("rsync" in c[0] for c in ran[1:]), ran


def test_site_only_dry_run_uploads_nothing(tmp_path, monkeypatch):
    cfg_path = _write_config(tmp_path)
    ran = []
    monkeypatch.setattr(deploy, "real_run", lambda cmd, **kw: ran.append(cmd) or "")
    monkeypatch.setattr(deploy, "generate_site", lambda run=None: None)
    rc = deploy.main(["--config", str(cfg_path), "--site-only", "--dry-run"])
    assert rc == 0
    assert ran == [], "a dry run must not execute rsync"


# --- sample data upload ------------------------------------------------------
# The site rsync excludes *.fits as a guard against pushing astro data into the
# web root by accident. Sample masters are published deliberately, so they get
# their own explicit step rather than a hole in that guard.

def _samples_config(**over):
    from deploy import DeployConfig
    base = dict(repo="a/b", ssh_host="user@vps", remote_path="/var/www/n",
                owner="www-data:www-data", dir_mode="755", file_mode="644",
                include=["*.html"],
                exclude=["config*.php", "db/", "uploads/", "*.fits", "*.fit"],
                samples_path="/var/www/n/data/samples")
    base.update(over)
    return DeployConfig(**base)


def test_samples_are_not_smuggled_into_the_site_rsync(tmp_path):
    """The exclusion is the point. Sample masters are STAGED inside site/, so
    without this the main rsync would sweep 190 MB of FITS into the web root
    alongside the deliberate upload that puts them in the right place."""
    from deploy import build_rsync_cmd
    cmd = build_rsync_cmd(_samples_config(), tmp_path)
    assert "--exclude=*.fits" in cmd and "--exclude=*.fit" in cmd


def test_deploy_refuses_to_run_without_the_fits_guard(tmp_path):
    """Asserting the flag is present only reflects the config handed in. This
    asserts the guard is MANDATORY — that a config which drops it is rejected
    rather than quietly publishing astro data."""
    from deploy import build_rsync_cmd
    for dropped in ("*.fits", "*.fit"):
        exclude = [e for e in ("config*.php", "db/", "uploads/", "*.fits", "*.fit")
                   if e != dropped]
        with pytest.raises(ValueError, match="guards"):
            build_rsync_cmd(_samples_config(exclude=exclude), tmp_path)


def test_samples_command_uploads_the_staged_directory(tmp_path):
    from deploy import build_samples_cmd
    d = tmp_path / "samples"
    d.mkdir()
    (d / "NGC7000_163x20s_54min.fits").write_bytes(b"x" * 32)
    cmd = build_samples_cmd(_samples_config(), d)
    assert cmd is not None
    assert cmd[0] == "rsync" and "--rsync-path=sudo rsync" in cmd
    assert cmd[-1] == "user@vps:/var/www/n/data/samples/"
    # large files that never change in place — a re-deploy must not re-send them
    assert "--size-only" in cmd


def test_samples_command_is_skipped_when_nothing_is_staged(tmp_path):
    from deploy import build_samples_cmd
    empty = tmp_path / "empty"
    empty.mkdir()
    assert build_samples_cmd(_samples_config(), empty) is None
    assert build_samples_cmd(_samples_config(), tmp_path / "missing") is None
    assert build_samples_cmd(_samples_config(samples_path=None), empty) is None


def test_samples_path_must_sit_inside_remote_path(tmp_path):
    """Same rule as download_path, and for the same reason: the post-upload
    chown recurses remote_path only, so anything outside it would be left
    owned by the SSH user and unreadable to the web server."""
    from deploy import load_config
    cfg = tmp_path / "d.toml"
    cfg.write_text('''
[github]
repo = "a/b"
[website]
ssh_host = "user@vps"
remote_path = "/var/www/n"
owner = "www-data:www-data"
dir_mode = "755"
file_mode = "644"
include = ["*.html"]
exclude = ["config*.php", "db/", "uploads/", "*.fits", "*.fit"]
samples_path = "/somewhere/else"
''')
    with pytest.raises(ValueError, match="samples_path"):
        load_config(cfg)


# --- the bundle must be able to do HTTPS (added 2026-08-31) ------------------

class _FakeRun:
    """Stands in for subprocess.run, recording how it was called."""

    def __init__(self, returncode, out=""):
        self.returncode, self.out, self.calls = returncode, out, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        import types
        return types.SimpleNamespace(returncode=self.returncode,
                                     stdout=self.out, stderr="")


def test_a_bundle_with_no_usable_certificates_is_refused(tmp_path):
    """Exit 2 from --check-network means HTTPS cannot work on ANY machine. That
    build must not ship: the update check and SPCC both fail quiet, so users see
    nothing at all — which is how this went unnoticed for months."""
    run = _FakeRun(2, "usable CA path: False")
    with pytest.raises(SystemExit, match="NO USABLE CA BUNDLE"):
        deploy._verify_bundle_https(tmp_path / "Nocturne", run=run)


def test_an_unreachable_network_only_warns(tmp_path, capsys):
    """Exit 1 means the certificates are fine and the request failed anyway —
    no network, captive portal, GitHub down. Not a build defect, and a release
    must not hinge on the connection at the moment it is cut."""
    deploy._verify_bundle_https(tmp_path / "Nocturne", run=_FakeRun(1, "URLError"))
    assert "could not reach the network" in capsys.readouterr().out


def test_a_healthy_bundle_passes_silently(tmp_path, capsys):
    deploy._verify_bundle_https(tmp_path / "Nocturne", run=_FakeRun(0, "https probe: OK"))
    assert capsys.readouterr().out == ""


def test_the_build_machines_certificate_environment_is_stripped(tmp_path, monkeypatch):
    """THE point of the check. Leaving SSL_CERT_FILE in place would let the
    bundle borrow the build machine's Homebrew cert store and report success for
    a build that cannot do HTTPS anywhere else — which is exactly the invisible
    failure being guarded against."""
    monkeypatch.setenv("SSL_CERT_FILE", "/opt/homebrew/etc/openssl@3/cert.pem")
    monkeypatch.setenv("SSL_CERT_DIR", "/opt/homebrew/etc/openssl@3/certs")
    run = _FakeRun(0)
    deploy._verify_bundle_https(tmp_path / "Nocturne", run=run)
    env = run.calls[0][1]["env"]
    assert "SSL_CERT_FILE" not in env and "SSL_CERT_DIR" not in env


def test_a_self_test_that_cannot_run_does_not_break_the_release(tmp_path, capsys):
    """A missing binary or a timeout is a broken check, not a broken build."""

    def boom(*a, **k):
        raise OSError("no such file")

    deploy._verify_bundle_https(tmp_path / "Nocturne", run=boom)
    assert "could not run" in capsys.readouterr().out


# --- the Linux build host (added with the port, 2026-09-18) ------------------

def _linux_config(tmp_path):
    """A config with BOTH a download slot and a Linux build host.

    `_write_config` has no download_path, so build_download_cmd returns None
    there — fine for the tests that predate this, and useless for these, which
    are about where two artifacts land.
    """
    cfg = _write_config(tmp_path)
    with open(cfg, "a") as f:
        f.write('download_path = "/var/www/nocturne/download/Nocturne.zip"\n'
                '\n[linux]\nssh_host = "builder@10.0.0.9"\n'
                'repo_path = "/home/builder/nocturne"\n')
    return deploy.load_config(cfg)


def test_the_linux_build_checks_out_the_tag_it_is_building(tmp_path):
    """The artifact must be the TAGGED source, not whatever the build host had
    lying around. That is why the build cannot run before the tag is pushed, and
    it is the whole reason the step sits where it does in the sequence."""
    cmds = deploy.build_linux_cmds(_linux_config(tmp_path), "0.35.0")
    build, fetch = cmds
    assert build[:2] == ["ssh", "builder@10.0.0.9"]
    assert "build_linux.sh v0.35.0" in build[2]
    assert fetch[0] == "scp"
    assert fetch[1].endswith("Nocturne-0.35.0-linux-x86_64.tar.gz")


def test_linux_without_config_refuses_rather_than_guessing(tmp_path):
    """No build host configured is a mistake to report, not a default to invent
    — and it must surface BEFORE the version bump, since nothing in the remote
    sequence can be undone."""
    plain = deploy.load_config(_write_config(tmp_path))
    with pytest.raises(ValueError, match="ssh_host"):
        deploy.build_linux_cmds(plain, "0.35.0")


def test_the_two_artifacts_do_not_overwrite_each_other(tmp_path):
    """`download_path` names the macOS file exactly, so the site can link one
    stable URL. The Linux tarball lands BESIDE it under its own name — pointing
    both at the same path would publish a tarball called Nocturne.zip."""
    cfg = _linux_config(tmp_path)
    mac = deploy.build_download_cmd(cfg, "Nocturne-0.35.0.zip")
    linux_name = deploy.linux_asset_name("0.35.0")
    lin = deploy.build_download_cmd(cfg, linux_name, remote_name=linux_name)
    assert mac[-1] != lin[-1]
    assert mac[-1].endswith("/Nocturne.zip")
    assert lin[-1].endswith("/" + linux_name)
    # same directory, so one chown covers both
    assert mac[-1].rsplit("/", 1)[0] == lin[-1].rsplit("/", 1)[0]


def test_one_release_carries_both_assets(tmp_path, monkeypatch):
    """Not two `gh release` calls: a failure between them would leave a
    published release missing a platform, which users would find before we did.
    """
    seen = []
    cfg = _linux_config(tmp_path)
    notes = deploy.Notes("h", ["a"], [], [])
    deploy._remote_release(cfg, "0.35.0", notes, "Nocturne-0.35.0.zip",
                           run=lambda cmd, **k: seen.append(cmd),
                           linux_asset=deploy.linux_asset_name("0.35.0"))
    releases = [c for c in seen if c[:3] == ["gh", "release", "create"]]
    assert len(releases) == 1, "exactly one release call"
    assets = [a for a in releases[0] if a.endswith((".zip", ".tar.gz"))]
    assert len(assets) == 2, assets

    # and the build must precede the release, or there is nothing to attach
    build_at = next(i for i, c in enumerate(seen) if c[0] == "ssh" and "build_linux" in c[-1])
    release_at = seen.index(releases[0])
    tag_at = next(i for i, c in enumerate(seen) if c[:2] == ["git", "tag"])
    assert tag_at < build_at < release_at


def test_a_mac_only_release_is_completely_unchanged(tmp_path):
    """The flag is opt-in. Without it, not one command differs — a release must
    not start depending on a laptop being awake."""
    cfg = _linux_config(tmp_path)
    notes = deploy.Notes("h", ["a"], [], [])
    plain, with_flag = [], []
    deploy._remote_release(cfg, "0.35.0", notes, "Nocturne-0.35.0.zip",
                           run=lambda cmd, **k: plain.append(cmd))
    deploy._remote_release(cfg, "0.35.0", notes, "Nocturne-0.35.0.zip",
                           run=lambda cmd, **k: with_flag.append(cmd),
                           linux_asset=deploy.linux_asset_name("0.35.0"))
    assert not any("build_linux" in " ".join(c) for c in plain)
    # ssh build, scp fetch, and TWO rsyncs of the one tarball: its versioned
    # name (what the downloads page links) and Nocturne-linux.tar.gz (the stable
    # name the homepage button links, mirroring Nocturne.zip for macOS).
    assert len(with_flag) == len(plain) + 4


def test_the_downloads_page_is_rebuilt_after_the_release_and_before_the_upload(tmp_path):
    """Ordering IS the guarantee. Refreshed from GitHub after the release exists,
    the page lists what GitHub actually serves — so it can neither advertise a
    file that was never published nor miss one that was. Rebuilt before the
    rsync, or the upload would carry yesterday's table."""
    seen = []
    cfg = _linux_config(tmp_path)
    deploy._remote_release(cfg, "0.35.0", deploy.Notes("h", ["a"], [], []),
                           "Nocturne-0.35.0.zip", run=lambda cmd, **k: seen.append(cmd))
    def at(pred):
        return next(i for i, c in enumerate(seen) if pred(c))
    release = at(lambda c: c[:3] == ["gh", "release", "create"])
    refresh = at(lambda c: any("build_downloads.py" in a for a in c))
    rebuild = at(lambda c: any("build_site.py" in a for a in c))
    # the SITE rsync: the one carrying pages. Identified by a .html argument
    # rather than by sitemap.xml, which this fixture's include list omits — the
    # first version of this test looked for it and died with StopIteration.
    upload = at(lambda c: c[0] == "rsync" and any(a.endswith(".html") for a in c))
    assert release < refresh < rebuild < upload


def test_the_linux_tarball_also_lands_under_a_stable_name(tmp_path):
    """The homepage needs a URL that does not change every release.

    macOS has had one since the beginning (download/Nocturne.zip); Linux had
    only its versioned filename, so the homepage's Linux button had to point at
    the downloads PAGE while macOS got a one-click download. Same file, copied
    twice — the versioned name is what the downloads page links, and it must
    keep existing.
    """
    cfg = _linux_config(tmp_path)
    notes = deploy.Notes("h", ["a"], [], [])
    cmds = []
    deploy._remote_release(cfg, "0.35.0", notes, "Nocturne-0.35.0.zip",
                           run=lambda cmd, **k: cmds.append(cmd),
                           linux_asset=deploy.linux_asset_name("0.35.0"))
    dests = [c[-1] for c in cmds if c and c[0] == "rsync"]
    assert any(d.endswith("/download/Nocturne-0.35.0-linux-x86_64.tar.gz") for d in dests), \
        "the versioned name is what the downloads page links"
    assert any(d.endswith("/download/Nocturne-linux.tar.gz") for d in dests), \
        "and the stable name is what the homepage button links"
