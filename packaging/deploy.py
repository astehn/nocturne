"""Nocturne release automation. Pure helpers + orchestration; every subprocess
call routes through an injectable `run` so tests capture commands without
executing them. See docs/superpowers/specs/2026-07-25-deploy-skill-design.md."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


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
