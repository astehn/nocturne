from __future__ import annotations

import subprocess


def _default_runner(argv: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout, proc.stderr


def _first_line(*texts: str) -> str:
    for text in texts:
        for line in text.splitlines():
            if line.strip():
                return line.strip()
    return ""


def probe_binary(path: str, args: list[str], *, runner=None) -> tuple[bool, str]:
    """Run `[path, *args]`; return (ok, message). ok=True on exit 0 with the
    first non-empty output line; otherwise (False, error message)."""
    runner = runner or _default_runner
    try:
        code, out, err = runner([path, *args])
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if code == 0:
        return True, _first_line(out, err) or "OK"
    return False, _first_line(err, out) or f"exited with code {code}"
