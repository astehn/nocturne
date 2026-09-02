"""Which engine actually ran, and why.

Several steps have two implementations: an external tool when it is configured,
and a built-in fallback when it is not. Both produce a picture, the results
differ materially, and until now nothing recorded which one you got. From the
outside a GraXpert background and the built-in one are the same log line.

That is the gap the 2026-09-01 feature audit called P0 and put first:

    "Optional tools are not a problem by themselves. The problem is when the
     output differs materially and the user cannot see which engine actually
     ran."

This module answers it for the steps whose engine is chosen in
`steps/factory.make_step`, which is the one place that decision is made. It is
PURE — it reads the same settings the factory reads and reports what the factory
will do, so it can be rendered into a provenance report, a project, or a test
without running anything or constructing a step.

**It reports what would run NOW, not what ran THEN.** Nothing in a history
records the tool configuration in force when a step was applied, so a report
produced after RC-Astro was uninstalled describes the free split even for a
step that StarXTerminator actually performed. The report says so rather than
implying otherwise; recording the engine at apply time is the fuller fix and is
a larger change than this one.

Deliberately NOT a general event log. A receipt that records everything is a
receipt nobody reads; this records the one fact a user cannot otherwise recover.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..settings import astap_valid, graxpert_valid, rcastro_valid

BUILT_IN = "Nocturne (built-in)"

# stage id -> (user-facing step name, preferred engine, what it needs)
_PREFERS: dict[str, tuple[str, str, str]] = {
    "background":     ("Background", "GraXpert", "graxpert"),
    "color":          ("Color", "ASTAP + Gaia", "astap"),
    "deconvolution":  ("Deconvolution", "RC-Astro", "rcastro"),
    "noise_sharpen":  ("Noise Reduction", "RC-Astro", "rcastro"),
    "star_reduction": ("Star Reduction", "RC-Astro", "rcastro"),
    "saturation":     ("Saturation", "RC-Astro", "rcastro"),
    "green_fringe":   ("Remove Green Fringe", "RC-Astro", "rcastro"),
    "narrowband":     ("Narrowband", "RC-Astro", "rcastro"),
}

# What the fallback actually IS, verified against each step's apply() rather
# than assumed — the first draft of this file claimed Background falls back to a
# built-in gradient fit, and it does not: BackgroundStep.apply calls GraXpert
# unconditionally. Naming a fallback that does not exist is worse than naming
# none, because the whole point of the receipt is that it can be trusted.
#
# The four star steps share `steps/star_split.resolve_star_split`: StarX when
# RC-Astro is configured, the free SEP split otherwise. So they share a caveat.
_FREE_SPLIT = "Nocturne (free star split)"
_FALLBACKS: dict[str, str] = {
    "color": "Nocturne (sky balance)",
    "deconvolution": "Nocturne (built-in sharpen)",
    "noise_sharpen": "Nocturne (built-in denoise)",
    "star_reduction": _FREE_SPLIT,
    "saturation": _FREE_SPLIT,
    "green_fringe": _FREE_SPLIT,
    "narrowband": _FREE_SPLIT,
}

# Steps with NO fallback: without the tool they cannot run at all, and the app
# gates the button rather than substituting something.
_REQUIRED = {"background"}

UNAVAILABLE = ""     # EngineNote.engine when the step cannot run

_NEEDS = {"graxpert": graxpert_valid, "rcastro": rcastro_valid, "astap": astap_valid}

_NOT_CONFIGURED = {
    "graxpert": "GraXpert is not configured in Settings",
    "rcastro": "RC-Astro is not configured in Settings",
    "astap": "ASTAP is not configured in Settings",
}


@dataclass(frozen=True)
class EngineNote:
    """One step's engine, and why it is that one."""

    step: str        # the name the user sees in their history
    engine: str      # what actually ran; "" when the step cannot run at all
    reason: str      # "" when the preferred engine ran; why not, otherwise

    @property
    def is_fallback(self) -> bool:
        """A different engine ran. NOT true when the step could not run — that
        is `unavailable`, and conflating the two would report a substitution
        that never happened."""
        return bool(self.reason) and self.engine != UNAVAILABLE

    @property
    def unavailable(self) -> bool:
        return self.engine == UNAVAILABLE


def engine_for(stage_id: str, settings) -> EngineNote | None:
    """What `make_step` will use for this stage, or None if it has no choice.

    None is the honest answer for a step with one implementation — Stretch does
    not have an engine, and inventing "Nocturne (built-in)" for it would pad the
    receipt with rows that carry no decision.
    """
    prefers = _PREFERS.get(stage_id)
    if prefers is None:
        return None
    name, engine, needs = prefers
    if _NEEDS[needs](settings):
        return EngineNote(name, engine, "")
    if stage_id in _REQUIRED:
        return EngineNote(name, UNAVAILABLE, _NOT_CONFIGURED[needs])
    return EngineNote(name, _FALLBACKS.get(stage_id, BUILT_IN), _NOT_CONFIGURED[needs])


def notes_for(step_names, settings) -> list[EngineNote]:
    """Engine notes for the steps actually applied, in order, without repeats.

    Takes the NAMES from a history rather than stage ids, because that is what
    a project stores and what the provenance report already walks.
    """
    by_name = {name: sid for sid, (name, _e, _n) in _PREFERS.items()}
    out: list[EngineNote] = []
    seen: set[str] = set()
    for name in step_names:
        sid = by_name.get(name)
        if sid is None or name in seen:
            continue
        note = engine_for(sid, settings)
        if note is not None:
            seen.add(name)
            out.append(note)
    return out


def render_lines(notes) -> list[str]:
    """Markdown bullets for the provenance report, or [] when nothing applies."""
    lines = []
    for n in notes:
        if n.unavailable:
            lines.append(f"- {n.step}: **not available** — {n.reason}")
        else:
            lines.append(f"- {n.step}: **{n.engine}**"
                         + (f" — {n.reason}" if n.reason else ""))
    return lines
