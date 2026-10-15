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
    # The RC Astro PRODUCT each step uses, not the suite (2026-10-05). The
    # star-split steps use StarXTerminator to separate the stars.
    "deconvolution":  ("Deconvolution", "BlurXTerminator", "rcastro"),
    "noise_sharpen":  ("Noise Reduction", "NoiseXTerminator", "rcastro"),
    "star_reduction": ("Star Reduction", "StarXTerminator", "rcastro"),
    "saturation":     ("Saturation", "StarXTerminator", "rcastro"),
    "green_fringe":   ("De-green Stars", "StarXTerminator", "rcastro"),
    "narrowband":     ("Narrowband", "StarXTerminator", "rcastro"),
    "color_balance":  ("Colour Balance", "StarXTerminator", "rcastro"),
    "starless_levels": ("Starless Levels", "StarXTerminator", "rcastro"),
}

# What the fallback actually IS, verified against each step's apply() rather
# than assumed — the first draft of this file claimed Background falls back to a
# built-in gradient fit, and it does not: BackgroundStep.apply calls GraXpert
# unconditionally. Naming a fallback that does not exist is worse than naming
# none, because the whole point of the receipt is that it can be trusted.
#
# The star steps take their splitter from `steps/star_split.preferred_splitter`:
# StarX when RC-Astro is configured, StarNet2 when it is installed, and only
# then each step's own no-tool path. This said "free star split" whenever
# RC-Astro was missing — written before StarNet2 existed, so a summary told
# StarNet2 users the free split had run under log lines saying StarNet2
# (2026-10-14). `engine_for` asks the resolver; only the last rung,
# `_FALLBACKS`, is a fallback — and for two steps it is not a split at all.
SPLIT_STAGES = frozenset({"star_reduction", "saturation", "green_fringe",
                          "narrowband", "color_balance", "starless_levels"})
_FREE_SPLIT = "Nocturne (free star split)"
_FALLBACKS: dict[str, str] = {
    "color": "Nocturne (sky balance)",
    "deconvolution": "Nocturne (built-in sharpen)",
    "noise_sharpen": "Nocturne (built-in denoise)",
    "star_reduction": _FREE_SPLIT,
    "saturation": _FREE_SPLIT,
    "color_balance": _FREE_SPLIT,
    "starless_levels": _FREE_SPLIT,
    # GreenFringeStep without a splitter de-greens inside a star mask, and
    # NarrowbandStep renders the whole image: neither separates anything.
    "green_fringe": "Nocturne (star mask)",
    "narrowband": "Nocturne (whole image, no split)",
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


def _noise_note(settings, engine) -> EngineNote:
    """Noise Reduction has TWO external engines and an option naming the one
    asked for (else the settings' default). The first valid one in that order
    runs, as `NoiseSharpenStep.apply` does — the fixed "NoiseXTerminator" this
    used to answer was wrong for every GraXpert user. "free" is the built-in
    denoise CHOSEN (Auto Enhance records it), so it is not a fallback."""
    if engine == "free":
        return EngineNote("Noise Reduction", _FALLBACKS["noise_sharpen"], "")
    products = {"graxpert": ("GraXpert", graxpert_valid),
                "rcastro": ("NoiseXTerminator", rcastro_valid)}
    want = engine if engine in products else getattr(settings, "denoise_engine", "rcastro")
    if want not in products:
        want = "rcastro"
    order = [want] + [e for e in products if e != want]
    name = "Noise Reduction"
    for i, e in enumerate(order):
        label, valid = products[e]
        if valid(settings):
            reason = "" if i == 0 else f"{products[want][0]} is not configured in Settings"
            return EngineNote(name, label, reason)
    return EngineNote(name, _FALLBACKS["noise_sharpen"],
                      f"{products[want][0]} is not configured in Settings")


def _split_note(stage_id: str, settings) -> EngineNote:
    """The splitter the step will be handed, from the function that hands it."""
    from ..steps import star_split
    name, preferred, needs = _PREFERS[stage_id]
    tag = star_split.splitter_name(star_split.preferred_splitter(settings))
    if tag == "StarX":
        return EngineNote(name, preferred, "")
    if tag == "StarNet2":
        # A choice, not a degradation (2026-10-15): named, but never reported
        # as a fallback — that would nag about a paid tool nobody needs.
        return EngineNote(name, "StarNet2", "")
    return EngineNote(name, _FALLBACKS[stage_id], _NOT_CONFIGURED[needs])


def engine_for(stage_id: str, settings, engine: str | None = None) -> EngineNote | None:
    """What `make_step` will use for this stage, or None if it has no choice.

    None is the honest answer for a step with one implementation — Stretch does
    not have an engine, and inventing "Nocturne (built-in)" for it would pad the
    receipt with rows that carry no decision.
    """
    prefers = _PREFERS.get(stage_id)
    if prefers is None:
        return None
    if stage_id == "noise_sharpen":
        return _noise_note(settings, engine)
    if stage_id in SPLIT_STAGES:
        return _split_note(stage_id, settings)
    name, engine, needs = prefers
    if _NEEDS[needs](settings):
        return EngineNote(name, engine, "")
    if stage_id in _REQUIRED:
        return EngineNote(name, UNAVAILABLE, _NOT_CONFIGURED[needs])
    return EngineNote(name, _FALLBACKS.get(stage_id, BUILT_IN), _NOT_CONFIGURED[needs])


def notes_for(step_names, settings, engines: dict | None = None) -> list[EngineNote]:
    """Engine notes for the steps actually applied, in order, without repeats.

    Takes the NAMES from a history rather than stage ids, because that is what
    a project stores and what the provenance report already walks. `engines`
    maps a step name to the engine its RECORDED option asked for.
    """
    by_name = {name: sid for sid, (name, _e, _n) in _PREFERS.items()}
    out: list[EngineNote] = []
    seen: set[str] = set()
    for name in step_names:
        sid = by_name.get(name)
        if sid is None or name in seen:
            continue
        note = engine_for(sid, settings, (engines or {}).get(name))
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
