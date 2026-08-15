"""The in-app help must describe the app that exists.

Written after a documentation audit found Share's topic still describing "an
optional caption band carrying your handle" long after the caption became fully
editable, and no topic at all for Trim or fullscreen. Help drifts silently:
nothing fails when a feature changes and its topic does not.

These tests are deliberately shallow — they check that a claim in the help has a
counterpart in the code, not that the prose is good. A shallow check that runs is
worth more than a thorough one nobody performs.
"""
import pathlib
import re

import pytest

pytest.importorskip("PySide6")
from nocturne.ui import help_content as h  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _src(rel):
    return (ROOT / rel).read_text()


def _body(topic_id):
    t = h.topic(topic_id)
    assert t is not None, f"no help topic {topic_id!r}"
    return t.body


def test_every_toolbar_tool_has_a_help_topic():
    """A tool the user can press with no topic explaining it is a documentation
    hole. Trim shipped that way."""
    ids = {t.id for t in h._TOPIC_LIST}
    for tool in ("plate-solve", "share", "upscale", "auto-enhance", "trim",
                 "stacking", "haoiii", "narrowband", "star_spikes", "recipes"):
        assert tool in ids, f"toolbar tool {tool!r} has no help topic"


def test_trim_help_matches_how_trim_actually_behaves():
    b = _body("trim")
    mw, td = _src("nocturne/ui/main_window.py"), _src("nocturne/ui/trim_dialog.py")
    assert "Apply Trim" in b and 'QPushButton("Apply Trim")' in td
    assert "stretched" in b and "_trim_act.setEnabled(stretched)" in mw
    # it claims the edit survives — that is the whole feature
    assert "history" in b or "edit survives" in b or "whole edit" in b


def test_stacking_help_names_the_real_controls():
    """The topic explained neither Strictness nor Integration, so a user faced
    with three strictness levels and two integration methods had nothing to
    choose on. Guard the names against the widgets that actually exist."""
    b = _body("stacking")
    sd = _src("nocturne/ui/stack_dialog.py")
    for label in ("Relaxed", "Normal", "Strict"):
        assert label in b, f"strictness level {label!r} not explained"
        assert label in sd, f"{label!r} is no longer a strictness option"
    assert "Sigma-clipped" in b and 'QRadioButton("Sigma-clipped")' in sd
    assert "Average" in b and "avg_radio" in sd
    for label in ("Low", "High"):
        assert label in b, f"kappa level {label!r} not explained"
    assert 'KAPPA = {"Low"' in sd and '"High"' in sd


def test_stacking_help_does_not_contradict_how_judging_works():
    """Three claims that are load-bearing and easy to get wrong. Each one
    describes behaviour a user would otherwise read as a bug — most of all the
    'count did not change' case, which is what prompted the topic."""
    b = _body("stacking")
    g = _src("nocturne/stacking/grade.py")
    # the cloud floor ignores strictness — the help says so, the code hardcodes it
    assert "half the usual" in b
    assert "star_floor = 0.5 * star_median" in g
    # a bright sky warns rather than rejects
    assert "warning" in b and "s.warning = WARN_SKY" in g
    # the gate is relative to the session, not an absolute number
    assert "session itself" in b or "relative to the night" in b
    assert "return median + k * mad" in g
    # roundness is judged separately from FWHM, and the help must say why
    assert "round" in b.lower() and "REASON_TRAILED" in g
    assert "1.00" in b and "1.3" in b


def test_fullscreen_help_names_the_real_keys():
    b = _body("fullscreen")
    mw = _src("nocturne/ui/main_window.py")
    assert "<b>F</b>" in b and "Key_F" in mw
    assert "Escape" in b and "Key_Escape" in mw


def test_share_help_lists_the_sizes_and_formats_that_exist():
    b, core = _body("share"), _src("nocturne/core/share.py")
    for px in ("1080", "2048", "4096"):
        assert px in b, f"help omits the {px} px option"
        assert px in core
    assert "PNG" in b and '("PNG", "png")' in core
    assert len(re.findall(r'\("(Small|Medium|Large)"', core)) == 3
    assert "three sizes" in b


def test_share_help_is_not_still_describing_the_old_fixed_caption():
    """It said "an optional caption band carrying your handle" for two releases
    after the caption became editable text with placement, colour and a band
    slider."""
    b = _body("share")
    assert "band carrying your handle" not in b
    for feature in ("below", "colour", "eyedropper"):
        assert feature in b.lower(), f"help does not mention {feature}"


def test_plate_solve_help_mentions_the_star_database():
    """The single most common reason a solve fails, and it is a separate download
    from ASTAP itself."""
    b = _body("plate-solve")
    assert "star database" in b
    assert "separate download" in b


def test_plate_solve_help_covers_the_object_list():
    b = _body("plate-solve")
    assert "Objects in field" in b or "list beside the image" in b
    assert "Density" in b
    assert "Re-solve" in b


def test_clipping_help_explains_the_import_baseline():
    """Without this the amber line looks broken on an already-crushed import."""
    b = _body("readout")
    assert "on import" in b
    assert "Show clipping" in b


def test_no_topic_is_an_empty_stub():
    for t in h._TOPIC_LIST:
        words = len(re.sub(r"<[^>]+>", " ", t.body).split())
        assert words >= 40, f"{t.id} is only {words} words — a stub, not a topic"
        assert t.summary.strip(), f"{t.id} has no summary"


def test_stacking_help_explains_the_framing_choice():
    """A checkbox with no explanation is a coin toss. The topic must name the
    control and say what turning it off costs and buys."""
    b = _body("stacking")
    sd = _src("nocturne/ui/stack_dialog.py")
    assert "Trim the ragged edges" in b
    assert 'QCheckBox("Trim the ragged edges")' in sd
    assert "noisier" in b, "the cost of keeping the edges is not stated"
    assert "crop later" in b or "put back" in b


def test_background_help_does_not_tell_you_to_pick_the_weaker_option():
    """It said "choose light for most images, strong when the gradient is heavy"
    while the code did the reverse — the options were labelled by correction
    strength and implemented as GraXpert's -smoothing, where a higher number is
    a stiffer model that removes LESS."""
    b = _body("background")
    src = _src("nocturne/steps/background.py")
    assert "light</b> for most images" not in b
    assert "Strong</b> is the ordinary choice" in b
    # strong must genuinely apply more of the correction than light
    amounts = {n: float(v) for n, v in
               re.findall(r'"(light|strong)": ([\d.]+)', src)}
    assert amounts["strong"] > amounts["light"], "the options are inverted again"
    assert amounts["light"] / amounts["strong"] == pytest.approx(0.5, abs=0.15), \
        "the help says light removes about half as much"
    assert "fills the frame" in b.lower(), "the case Light exists for is unexplained"


def test_stacking_help_explains_the_mosaic_option():
    """Shipped features with no help is a mistake this project has made twice —
    six features had none at v0.4.2, and Trim and Fullscreen had none at v0.10.0.
    Guard the mosaic wording against the control that actually exists."""
    b = _body("stacking")
    sd = _src("nocturne/ui/stack_dialog.py")
    assert "Stack as mosaic" in b, "the mosaic checkbox is not explained"
    assert "Stack as mosaic" in sd, "the checkbox label changed; update the help"
    assert "ASTAP" in b, "the help must say a mosaic needs ASTAP"
    assert "astap_valid" in sd, "the ASTAP gate is gone; update the help"
