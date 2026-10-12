"""A stand-in for an installed tool that `settings.is_tool` accepts.

On macOS/Linux a tool is a file with the execute bit; on Windows every file has
it, so `is_tool` decides by extension (PATHEXT) instead. The stand-in therefore
gets an ".exe" there. Use the RETURNED path: on Windows it is not the one passed.
Nothing here is ever run — a test that runs a tool fakes the runner.
"""
import sys
from pathlib import Path


def fake_tool(path, body: str = "#!/bin/sh\n") -> Path:
    p = Path(path)
    if sys.platform == "win32" and not p.suffix:
        p = p.with_suffix(".exe")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    p.chmod(0o755)
    return p
