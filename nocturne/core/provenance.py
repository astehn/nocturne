"""Human-readable Markdown provenance report: capture header + the ordered edit
pipeline as a narrative (with headline choices) plus a full-parameter detail
section. Pure — pass `date`/`app_version` in. Reuses recipe serialization so it
never re-parses step options."""
from __future__ import annotations

import datetime
import re

from ..recipe import _NAME_TO_STAGE, serialize_option
from .fits_io import format_integration, resolve_integration
from .instrument import DEFAULT_INSTRUMENT, identify

# dict-option steps whose headline choice is a single field of the serialized dict
_HEADLINE_FIELD = {
    "Color": "method",
    "Background": "engine",
    "Noise Reduction": "engine",
    "Narrowband": "palette",
}

_FAILED = object()   # sentinel: this step's option could not be serialized


def _serialize(name: str, option):
    """Normalize a recorded option to a JSON-friendly value (scalar / dict /
    list), matching how the project store persists it. Native objects
    (CropParams/ColorSettings/…) go through serialize_option."""
    if option is None or isinstance(option, (int, float, str, bool, dict)):
        return option
    if isinstance(option, (list, tuple)):
        return list(option)
    return serialize_option(_NAME_TO_STAGE.get(name, name), option)


def _headline(name: str, ser) -> str:
    if ser is _FAILED or ser is None:
        return ""
    if isinstance(ser, bool):
        return str(ser)
    if isinstance(ser, (int, float, str)):
        return f"{ser}"
    if isinstance(ser, dict):
        if name == "Colour Balance":
            # Not a single field: which of the three tonal ranges were moved.
            from .color_balance import describe
            return describe(ser)
        field = _HEADLINE_FIELD.get(name)
        if field and ser.get(field) not in (None, ""):
            return f"{ser[field]}"
    return ""   # lists / unmapped dicts -> name only


def _render_params(ser) -> list[str]:
    if isinstance(ser, dict):
        return [f"- {k}: {v}" for k, v in ser.items()]
    if isinstance(ser, list):
        return [f"- values: {', '.join(str(v) for v in ser)}"]
    return []


def _human_date(date: datetime.date) -> str:
    return f"{date.day} {date:%B %Y}"


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>])")


def _md_escape(s) -> str:
    """Escape Markdown/inline specials in free-text metadata (e.g. a FITS OBJECT
    name typed by the user) so it can't corrupt the report's structure."""
    return _MD_SPECIAL.sub(r"\\\1", str(s).replace("\n", " ").replace("\r", " "))


def _capture_lines(metadata: dict) -> list[str]:
    out: list[str] = []
    target = metadata.get("target") or metadata.get("target_solved")
    if target:
        out.append(f"- Target: {_md_escape(target)}")
    integ = resolve_integration(metadata)
    if integ is not None and integ.total_s is not None:
        s = format_integration(integ.total_s)
        if integ.frames is not None and integ.per_sub_s is not None:
            s += f" ({integ.frames} × {integ.per_sub_s:g}s)"
        out.append(f"- Total integration: {s}")
    # This used to print the S30 Pro's sensor unconditionally, which made the
    # report state a falsehood on anyone else's data — in the one document
    # meant to be an authoritative record of how the image was made. Say what
    # the file says, and mark it when we are only assuming.
    if (cam := identify(metadata)) is not None:
        out.append(f"- Camera: {cam.sensor} ({cam.name})")
    else:
        out.append(f"- Camera: {DEFAULT_INSTRUMENT.sensor} (assumed — no camera in the file)")
    if metadata.get("date"):
        out.append(f"- Captured: {_md_escape(str(metadata['date']).split('T')[0])}")
    if metadata.get("target_solved"):
        out.append(f"- Plate solve: {_md_escape(metadata['target_solved'])} (solved)")
    return out


def build_report(entries, metadata, *, app_version: str, date: datetime.date) -> str:
    ser_entries = []
    for name, option in entries:
        try:
            ser_entries.append((name, _serialize(name, option)))
        except Exception:
            ser_entries.append((name, _FAILED))

    lines = ["# Nocturne processing report", ""]
    lines.append("## Capture")
    lines += _capture_lines(metadata)
    lines.append("")

    lines.append("## Processing steps")
    lines.append("")
    if not ser_entries:
        lines.append("_No processing steps applied._")
    else:
        for i, (name, ser) in enumerate(ser_entries, 1):
            h = _headline(name, ser)
            lines.append(f"{i}. {name}" + (f" — {h}" if h else ""))
    lines.append("")

    blocks = []
    for i, (name, ser) in enumerate(ser_entries, 1):
        if ser is _FAILED:
            blocks.append((i, name, ["- (parameters unavailable)"]))
        elif isinstance(ser, (dict, list)):
            blocks.append((i, name, _render_params(ser)))
    if blocks:
        lines.append("## Parameters")
        lines.append("")
        for i, name, body in blocks:
            lines.append(f"### {i}. {name}")
            lines += body
            lines.append("")

    lines.append("---")
    lines.append(f"Nocturne {app_version} · report generated {_human_date(date)}")
    return "\n".join(lines).rstrip() + "\n"
