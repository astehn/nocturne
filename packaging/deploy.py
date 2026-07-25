"""Nocturne release automation. Pure helpers + orchestration; every subprocess
call routes through an injectable `run` so tests capture commands without
executing them. See docs/superpowers/specs/2026-07-25-deploy-skill-design.md."""
from __future__ import annotations

import argparse
import datetime
import glob as _glob
import html as _html
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # repo root
SITE = ROOT / "site"
DIST = ROOT / "dist"

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_PREFIX_RE = re.compile(r"^(\w+)(\([^)]*\))?!?:\s*")   # conventional-commit prefix


def parse_version(s: str) -> tuple[int, int, int]:
    m = _VERSION_RE.match(s)
    if not m:
        raise ValueError(f"not a semantic version: {s!r}")
    return int(m[1]), int(m[2]), int(m[3])


def next_minor(s: str) -> str:
    major, minor, _ = parse_version(s)
    return f"{major}.{minor + 1}.0"


def set_version_files(root: Path, version: str) -> None:
    parse_version(version)  # guard: refuse to write a malformed version
    pyproject = root / "pyproject.toml"
    text, n = re.subn(r'(?m)^version = "[^"]*"',
                      f'version = "{version}"', pyproject.read_text(), count=1)
    if n != 1:
        raise ValueError(f"no version line found in {pyproject}")
    pyproject.write_text(text)
    init = root / "nocturne" / "__init__.py"
    text, n = re.subn(r'(?m)^__version__ = "[^"]*"',
                      f'__version__ = "{version}"', init.read_text(), count=1)
    if n != 1:
        raise ValueError(f"no __version__ line found in {init}")
    init.write_text(text)


@dataclass
class DeployConfig:
    repo: str
    ssh_host: str
    remote_path: str
    owner: str
    dir_mode: str
    file_mode: str
    include: list[str]
    exclude: list[str]
    download_path: str | None = None   # VPS path of the site's self-hosted download; refreshed each deploy if set


def load_config(path: Path) -> DeployConfig:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    try:
        gh, web = data["github"], data["website"]
        return DeployConfig(
            repo=gh["repo"],
            ssh_host=web["ssh_host"],
            remote_path=web["remote_path"],
            owner=web["owner"],
            dir_mode=web["dir_mode"],
            file_mode=web["file_mode"],
            include=list(web["include"]),
            exclude=list(web["exclude"]),
            download_path=web.get("download_path"),
        )
    except KeyError as e:
        raise ValueError(f"deploy config missing required key: {e}") from e


@dataclass
class Notes:
    headline: str
    added: list[str]
    changed: list[str]
    fixed: list[str]


def draft_notes_from_log(log_lines: list[str]) -> Notes:
    added: list[str] = []
    changed: list[str] = []
    fixed: list[str] = []
    for raw in log_lines:
        line = raw.strip()
        if not line:
            continue
        m = _PREFIX_RE.match(line)
        kind = (m[1].lower() if m else "")
        subject = line[m.end():] if m else line
        if kind == "feat":
            added.append(subject)
        elif kind == "fix":
            fixed.append(subject)
        else:
            changed.append(subject)
    return Notes(headline="", added=added, changed=changed, fixed=fixed)


def _sections(notes: Notes) -> list[tuple[str, list[str]]]:
    return [("Added", notes.added), ("Changed", notes.changed), ("Fixed", notes.fixed)]


def render_release_notes(notes: Notes) -> str:
    parts: list[str] = []
    if notes.headline:
        parts.append(notes.headline)
    for name, items in _sections(notes):
        if items:
            parts.append(f"### {name}\n" + "\n".join(f"- {i}" for i in items))
    return "\n\n".join(parts)


def render_changelog_md(version: str, date: datetime.date, notes: Notes) -> str:
    return f"## [{version}] — {date.isoformat()}\n\n{render_release_notes(notes)}"


def _human_date(date: datetime.date) -> str:
    return f"{date.day} {date:%B %Y}"


def render_changelog_html(version: str, date: datetime.date, notes: Notes) -> str:
    lines = ['<article class="release">',
             f"  <h2>{_html.escape(notes.headline or version)}</h2>",
             f'  <p class="when">{_human_date(date)}</p>']
    for name, items in _sections(notes):
        if items:
            lines.append(f"  <h3>{name}</h3>")
            lines.append("  <ul>")
            lines += [f"    <li>{_html.escape(i)}</li>" for i in items]
            lines.append("  </ul>")
    lines.append("</article>")
    return "\n".join(lines)


REQUIRED_EXCLUDES = ("config*.php", "db/", "uploads/")


def release_asset_name(version: str) -> str:
    return f"Nocturne-{version}.zip"


def _resolve_includes(config: DeployConfig, site_dir: Path) -> list[str]:
    sources: list[str] = []
    for pat in config.include:
        if pat.endswith("/"):                      # a directory: sync it recursively
            d = site_dir / pat.rstrip("/")
            if d.exists():
                sources.append(str(d))
        else:                                       # a file glob
            sources += sorted(_glob.glob(str(site_dir / pat)))
    return sources


def build_rsync_cmd(config: DeployConfig, site_dir: Path) -> list[str]:
    # SAFETY: this exclude guard is load-bearing even though `include` is an
    # allowlist. rsync applies --exclude filters to explicitly-named source
    # args too, so these excludes are the last line of defense if `include` is
    # ever misconfigured to match server state (config.php, db/, uploads/). Do
    # NOT remove this guard, and do NOT switch to --files-from (which does not
    # apply exclude filtering to its file list the same way) without replacing
    # this protection.
    missing = [e for e in REQUIRED_EXCLUDES if e not in config.exclude]
    if missing:
        raise ValueError(f"deploy config exclude is missing server-state guards: {missing}")
    cmd = ["rsync", "-av", "--rsync-path=sudo rsync"]
    cmd += [f"--exclude={e}" for e in config.exclude]
    cmd += _resolve_includes(config, site_dir)
    cmd.append(f"{config.ssh_host}:{config.remote_path}/")
    return cmd


def build_chown_cmd(config: DeployConfig) -> list[str]:
    import re as _re
    if not _re.match(r"^[\w.-]+:[\w.-]+$", config.owner):
        raise ValueError(f"invalid owner (want user:group): {config.owner!r}")
    for mode in (config.dir_mode, config.file_mode):
        if not _re.match(r"^[0-7]{3,4}$", mode):
            raise ValueError(f"invalid mode: {mode!r}")
    p = config.remote_path
    remote = (f"sudo chown -R {config.owner} {p} && "
              f"sudo find {p} -type d -exec chmod {config.dir_mode} {{}} + && "
              f"sudo find {p} -type f -exec chmod {config.file_mode} {{}} +")
    return ["ssh", config.ssh_host, remote]


def build_download_cmd(config: DeployConfig, asset: str) -> list[str] | None:
    """rsync the built release zip to the website's self-hosted download slot
    (as root via sudo), or None when no download_path is configured."""
    if not config.download_path:
        return None
    return ["rsync", "-av", "--rsync-path=sudo rsync",
            str(DIST / asset), f"{config.ssh_host}:{config.download_path}"]


def real_run(cmd: list[str], *, capture: bool = False) -> str:
    r = subprocess.run(cmd, check=True, text=True, capture_output=capture, cwd=ROOT)
    return (r.stdout or "") if capture else ""


def get_last_tag(run=real_run) -> str:
    return run(["git", "describe", "--tags", "--abbrev=0", "--match", "v*"],
               capture=True).strip()


def get_log_since(tag: str, run=real_run) -> list[str]:
    out = run(["git", "log", f"{tag}..HEAD", "--pretty=%s"], capture=True)
    return [ln for ln in out.splitlines() if ln.strip()]


def prepend_file(path: Path, block: str, anchor: str) -> None:
    lines = path.read_text().splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if anchor in ln:
            lines.insert(i, block + "\n\n")
            path.write_text("".join(lines))
            return
    raise ValueError(f"anchor {anchor!r} not found in {path}")


def preflight(config: DeployConfig, run=real_run) -> None:
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True).strip()
    if branch != "main":
        raise SystemExit(f"preflight: not on main (on {branch})")
    # tracked-only: stray untracked files (local junk, un-ignored build artifacts)
    # must not block a release — only uncommitted changes to tracked files do.
    if run(["git", "status", "--porcelain", "--untracked-files=no"], capture=True).strip():
        raise SystemExit("preflight: tracked files have uncommitted changes")
    run(["git", "fetch", "origin", "main"])
    if run(["git", "rev-list", "HEAD..origin/main", "--count"], capture=True).strip() != "0":
        raise SystemExit("preflight: behind origin/main — pull first")
    try:
        subprocess.run([".venv/bin/python", "-m", "pytest", "-q"], cwd=ROOT, check=True)
    except subprocess.CalledProcessError:
        raise SystemExit("preflight: tests failed")
    host = config.ssh_host
    for cmd, msg in [
        (["gh", "auth", "status"], "preflight: gh not authenticated"),
        (["ssh", "-o", "BatchMode=yes", host, "true"], f"preflight: cannot ssh to {host}"),
        (["ssh", host, "sudo", "-n", "true"],
         f"preflight: passwordless sudo not available on {host}"),
    ]:
        try:
            run(cmd)
        except subprocess.CalledProcessError:
            raise SystemExit(msg)


def _load_notes(path: Path) -> Notes:
    d = json.loads(path.read_text())
    return Notes(headline=d.get("headline", ""), added=d.get("added", []),
                 changed=d.get("changed", []), fixed=d.get("fixed", []))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="deploy")
    ap.add_argument("--config", default=str(ROOT / "packaging" / "deploy.local.toml"))
    ap.add_argument("--version")
    ap.add_argument("--notes-json")
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    config = load_config(Path(args.config))

    preflight(config, real_run)
    if args.preflight:
        print("preflight OK")
        return 0

    version = args.version or next_minor(get_last_tag().lstrip("v"))
    parse_version(version)   # reject a malformed --version before any build or mutation
    notes = _load_notes(Path(args.notes_json))
    today = datetime.date.today()
    md_block = render_changelog_md(version, today, notes)
    html_block = render_changelog_html(version, today, notes)
    asset = release_asset_name(version)

    if args.dry_run:
        print(f"[dry-run] version -> {version}")
        print(f"[dry-run] CHANGELOG.md prepend:\n{md_block}\n")
        print(f"[dry-run] site/changelog.html prepend:\n{html_block}\n")
        print(f"[dry-run] build: pyinstaller packaging/nocturne.spec -> dist/{asset}")
        print("[dry-run] remote plan:")
        print("  " + " ".join(["git", "commit/push", f"v{version}"]))
        print("  " + f"gh release create v{version} dist/{asset}")
        print("  " + " ".join(build_rsync_cmd(config, SITE)))
        dl = build_download_cmd(config, asset)
        if dl:
            print("  " + " ".join(dl))
        print("  " + " ".join(build_chown_cmd(config)))
        return 0

    # real pipeline: bump version first so the build embeds it; roll back on build failure
    set_version_files(ROOT, version)
    try:
        build_app(real_run)
        verify_build()
        zip_app(version, real_run)
    except BaseException:
        real_run(["git", "checkout", "--", "pyproject.toml", "nocturne/__init__.py"])
        raise
    prepend_file(ROOT / "CHANGELOG.md", md_block, anchor="## [")
    prepend_file(SITE / "changelog.html", html_block, anchor='<article class="release">')
    _remote_release(config, version, notes, asset, real_run)
    return 0


def build_app(run=real_run) -> None:
    run([".venv/bin/pyinstaller", "packaging/nocturne.spec", "--noconfirm",
         "--workpath", "build/pyi", "--distpath", "dist"])


def verify_build() -> None:
    exe = DIST / "Nocturne.app" / "Contents" / "MacOS" / "Nocturne"
    if not exe.exists() or exe.stat().st_size < 1_000_000:
        raise SystemExit("build verify: Nocturne.app executable missing or too small")


def zip_app(version: str, run=real_run) -> Path:
    out = DIST / release_asset_name(version)
    run(["ditto", "-c", "-k", "--keepParent", str(DIST / "Nocturne.app"), str(out)])
    return out


def _remote_release(config, version, notes, asset, run=real_run) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(render_release_notes(notes))
        notes_path = f.name
    steps = [
        ["git", "add", "pyproject.toml", "nocturne/__init__.py", "CHANGELOG.md", "README.md"],
        ["git", "commit", "-m", f"release: v{version}"],
        ["git", "push", "origin", "main"],
        ["git", "tag", f"v{version}"],
        ["git", "push", "origin", f"v{version}"],
        ["gh", "release", "create", f"v{version}", str(DIST / asset),
         "--title", f"Nocturne {version}", "--notes-file", notes_path],
        build_rsync_cmd(config, SITE),
    ]
    dl = build_download_cmd(config, asset)
    if dl:
        steps.append(dl)
    steps.append(build_chown_cmd(config))
    i = 0
    try:
        for i, cmd in enumerate(steps):
            print(f"[{i + 1}/{len(steps)}] {' '.join(cmd)}")
            run(cmd)
    except BaseException:
        print(f"\n!! remote release FAILED at step {i + 1}/{len(steps)}: {' '.join(steps[i])}")
        print(f"!! {i} of {len(steps)} step(s) already completed and CANNOT be auto-undone.")
        print("!! Do NOT blindly re-run deploy — it is not idempotent (changelogs would double-prepend).")
        print("!! Finish the remaining steps by hand:")
        for cmd in steps[i:]:
            print("    " + " ".join(cmd))
        print(f"!! (release notes preserved at {notes_path})")
        raise
    os.unlink(notes_path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
