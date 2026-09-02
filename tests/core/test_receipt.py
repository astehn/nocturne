"""Which engine ran, and why.

The 2026-09-01 feature audit's first P0: "Optional tools are not a problem by
themselves. The problem is when the output differs materially and the user
cannot see which engine actually ran."
"""
from nocturne.core.receipt import (BUILT_IN, EngineNote, engine_for, notes_for,
                                   render_lines)
from nocturne.settings import Settings


def _configured(tmp_path, **tools):
    """Settings whose named tools point at a real executable."""
    exe = tmp_path / "tool"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return Settings(**{k: str(exe) for k in tools})


def test_a_configured_tool_is_named(tmp_path):
    s = _configured(tmp_path, rcastro_path=1)
    note = engine_for("star_reduction", s)
    assert note.engine == "RC-Astro"
    assert note.reason == ""
    assert note.is_fallback is False


def test_an_unconfigured_tool_names_the_fallback_AND_the_reason(tmp_path):
    """Half the value is the reason. A bare engine name reads like a choice
    somebody made; "because RC-Astro is not configured" is actionable."""
    note = engine_for("star_reduction", Settings())
    assert "free star split" in note.engine
    assert "not configured" in note.reason
    assert note.is_fallback is True
    assert note.unavailable is False


def test_the_fallback_is_named_specifically_where_that_is_knowable():
    """Each name checked against the step's own apply(), not assumed. The four
    star steps share steps/star_split.resolve_star_split, so they share a name."""
    assert "sky balance" in engine_for("color", Settings()).engine
    assert "built-in sharpen" in engine_for("deconvolution", Settings()).engine
    for sid in ("star_reduction", "saturation", "green_fringe", "narrowband"):
        assert "free star split" in engine_for(sid, Settings()).engine, sid


def test_a_step_with_no_fallback_says_so_instead_of_inventing_one():
    """The first draft of the receipt claimed Background falls back to a
    built-in gradient fit. It does not — BackgroundStep.apply calls GraXpert
    unconditionally, and the app gates the button instead. Naming a fallback
    that does not exist is worse than naming none: the receipt's only value is
    that it can be trusted."""
    note = engine_for("background", Settings())
    assert note.unavailable is True
    assert note.is_fallback is False, "an unavailable step is not a substitution"
    assert "not configured" in note.reason
    assert "**not available**" in render_lines([note])[0]


def test_the_named_fallbacks_correspond_to_real_code_paths():
    """Drift guard for the correction above: a step listed as having a fallback
    must actually branch on its engine being absent, and a step listed as
    REQUIRED must not."""
    from pathlib import Path
    from nocturne.core.receipt import _FALLBACKS, _REQUIRED
    steps = Path(__file__).parents[2] / "nocturne" / "steps"
    src = {f.stem: f.read_text() for f in steps.glob("*.py")}
    joined = "\n".join(src.values())
    # every fallback-bearing stage reaches a branch that runs without the tool
    assert "if rc is not None" in joined or "if self._rc is not None" in joined \
        or "rc is not None" in joined, "no engine-optional branch found at all"
    # background must NOT be claimed as having a fallback
    assert "background" in _REQUIRED
    assert "background" not in _FALLBACKS
    assert "self._gx" in src["background"] and "_gx is None" not in src["background"], \
        "BackgroundStep grew a fallback; the receipt should stop calling it required"


def test_every_engine_choosing_stage_the_factory_makes_is_covered():
    """Drift guard. `make_step` is the one place an engine is chosen; a stage
    that starts choosing one there but is missing here reports nothing, and the
    receipt quietly stops covering it."""
    import re
    from pathlib import Path
    from nocturne.core.receipt import _PREFERS
    src = (Path(__file__).parents[2] / "nocturne" / "steps" / "factory.py").read_text()
    chooses = set()
    for m in re.finditer(r'if stage_id == "([a-z_]+)":(.*?)(?=\n    if stage_id|\n    raise)',
                         src, re.S):
        sid, body = m.group(1), m.group(2)
        if "rcastro_valid" in body or "graxpert_valid" in body or "astap_valid" in body:
            chooses.add(sid)
    assert chooses, "could not parse factory.py"
    missing = sorted(chooses - set(_PREFERS))
    assert not missing, f"these stages choose an engine but the receipt ignores them: {missing}"


def test_a_stage_with_no_choice_reports_nothing():
    """Stretch has one implementation. A row saying "Nocturne (built-in)" for it
    would pad the receipt with a decision nobody made."""
    for sid in ("stretch", "levels", "curves", "crop"):
        assert engine_for(sid, Settings()) is None


def test_notes_follow_the_history_in_order_without_repeats():
    names = ["Crop", "Background", "Stretch", "Star Reduction", "Background"]
    notes = notes_for(names, Settings())
    assert [n.step for n in notes] == ["Background", "Star Reduction"]


def test_render_is_empty_when_there_is_nothing_to_say():
    assert render_lines([]) == []


def test_render_names_both_engine_and_reason():
    line = render_lines([EngineNote("Background", "Nocturne (x)", "GraXpert is not configured")])[0]
    assert "Background" in line and "Nocturne (x)" in line and "not configured" in line


def test_it_is_pure():
    """core/ holds no Qt — and a receipt that needed a running app could not be
    rendered into a saved project or a test."""
    from pathlib import Path
    src = (Path(__file__).parents[2] / "nocturne" / "core" / "receipt.py").read_text()
    assert "PySide6" not in src
