from __future__ import annotations

import re
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


# How to ask each tool its version, keyed by the Settings field.
#
# MEASURED 2026-09-22 on Andreas's machine:
#   GraXpert -v        -> "GraXpert version: 3.0.2 release: Umbriel"   instant
#   StarNet2 --version -> "starnet2  version: 2.5.2"                   instant
#   ASTAP    -h        -> TIMED OUT AFTER 60 SECONDS
#
# ASTAP is listed with an EMPTY argv rather than omitted: that is the
# difference between "we know it cannot be probed" and "somebody forgot".
VERSION_ARGV: dict[str, list[str]] = {
    "graxpert_path": ["-v"],
    "rcastro_path": ["--no-banner", "--help"],
    "starnet_path": ["--version"],
    "astap_path": [],
}

# Seconds. NOT probe_binary's 60: this runs while a person waits for a dialog
# to open, and one unprobeable tool must not cost them a minute.
VERSION_TIMEOUT = 3.0


def tool_version(path: str, argv: list[str], *,
                 timeout: float = VERSION_TIMEOUT, runner=None) -> str:
    """The tool's version line, or "" if it cannot be had quickly.

    "" is a real answer and the caller must render it as "version unknown"
    rather than omitting the tool: which tools are INSTALLED is itself the
    diagnostic, version or not.
    """
    if not path or not argv:
        return ""
    runner = runner or _default_runner_t
    try:
        code, out, err = runner([path, *argv], timeout=timeout)
    except Exception:                              # noqa: BLE001 - diagnostic
        return ""
    if code != 0:
        return ""
    return _version_line(out, err)


def _version_line(*texts: str) -> str:
    """The line that looks like a version, else the first non-empty one.

    MEASURED 2026-09-22. GraXpert and StarNet2 answer on their first line, so
    `_first_line` was enough for them — but RC-Astro 2.6.9 prints

        Astronomical image processing tools
        Version 2.6.9 (build 727, ga2033f5b, 2026-09-08)

    and the first line is a DESCRIPTION. Reporting it would have put
    "Astronomical image processing tools" in every ticket from every RC-Astro
    user: plausible-looking and useless, which is the worst kind of wrong in a
    diagnostic.

    The fallback matters as much as the match. An unrecognised banner still
    identifies the build, and WHICH TOOLS ARE INSTALLED is itself the answer to
    most tickets — Alvaro's turned on his not having RC-Astro at all.
    """
    lines = [_strip_preamble(ln.strip())
             for text in texts for ln in text.splitlines() if ln.strip()]
    for line in lines:
        if "version" in line.lower():
            return line
    return lines[0] if lines else ""


# A python-logging preamble: "2026-09-22 18:21:11,063 MainProcess root INFO   ".
# GraXpert 3.0.2 answers `-v` with one, putting fifty characters of its own log
# framing in front of the four that matter (measured 2026-09-22). Anchored on a
# full date AND a clock so a version that merely starts with a year is safe.
_PREAMBLE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[.,]?\d*\s+\S+\s+\S+\s+\w+\s+")


def _strip_preamble(line: str) -> str:
    return _PREAMBLE.sub("", line).strip()


def _default_runner_t(argv: list[str], timeout: float):
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr
