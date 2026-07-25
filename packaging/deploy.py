"""Nocturne release automation. Pure helpers + orchestration; every subprocess
call routes through an injectable `run` so tests capture commands without
executing them. See docs/superpowers/specs/2026-07-25-deploy-skill-design.md."""
from __future__ import annotations

import datetime
import glob as _glob
import html as _html
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

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
    missing = [e for e in REQUIRED_EXCLUDES if e not in config.exclude]
    if missing:
        raise ValueError(f"deploy config exclude is missing server-state guards: {missing}")
    cmd = ["rsync", "-av", "--rsync-path=sudo rsync"]
    cmd += [f"--exclude={e}" for e in config.exclude]
    cmd += _resolve_includes(config, site_dir)
    cmd.append(f"{config.ssh_host}:{config.remote_path}/")
    return cmd


def build_chown_cmd(config: DeployConfig) -> list[str]:
    p = config.remote_path
    remote = (f"sudo chown -R {config.owner} {p} && "
              f"sudo find {p} -type d -exec chmod {config.dir_mode} {{}} + && "
              f"sudo find {p} -type f -exec chmod {config.file_mode} {{}} +")
    return ["ssh", config.ssh_host, remote]
