"""The block a support ticket opens with.

Andreas reads every ticket alone: *"i need as much valuable information as
possible so that i can actually act on it."* The point of this is that he
should not have to open a log to learn the basics -- Alvaro's entire ticket
(2026-09-22) is answerable from five lines.

Qt-free: this is core/.
"""
from __future__ import annotations

from ..settings import is_tool, resolve_binary
from ..tools.probe import VERSION_ARGV, tool_version

_NAMES = {"graxpert_path": "GraXpert", "rcastro_path": "RC-Astro",
          "starnet_path": "StarNet2", "astap_path": "ASTAP"}


def summary_block(app_version: str, os_line: str, screen: str, settings,
                  *, failure: str = "", steps=(), version_probe=tool_version) -> str:
    lines = [f"Nocturne {app_version} · {os_line} · {screen}"]
    tools = []
    for field, name in _NAMES.items():
        path = getattr(settings, field, "") or ""
        if not path:
            tools.append(f"{name} not set")
            continue
        resolved = resolve_binary(path)
        if not is_tool(resolved):
            tools.append(f"{name} SET BUT NOT RUNNABLE")
            continue
        # "" is a real answer: which tools are INSTALLED is itself the
        # diagnostic, version or not. ASTAP has no probe that exits (measured
        # 2026-09-22: `-h` hung for 60 s), and omitting it would hide the fact
        # that it is there.
        version = version_probe(resolved, VERSION_ARGV.get(field, []))
        tools.append(f"{name} {version or '(version unknown)'}")
    lines.append(" · ".join(tools))
    if failure:
        lines.append(f"Failed at: {failure}")
    if steps:
        lines.append("Last steps: " + ", ".join(steps))
    return "\n".join(lines)
