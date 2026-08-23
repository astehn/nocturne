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

import numpy as np
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


def test_background_help_explains_the_model_view():
    """A control with no help is a control the user must guess at, and this one
    exists to be interpreted rather than merely pressed."""
    b = _body("background")
    sp = _src("nocturne/ui/step_panels.py")
    assert "Show what was removed" in b, "the model toggle is not explained"
    assert "Show what was removed" in sp, "the label changed; update the help"
    assert "shape of your object" in b.lower(), "the failure it detects is not described"


def test_the_colour_balance_help_names_the_real_controls():
    """Help drifts silently — it has done on three consecutive releases, and
    v0.13.0 nearly shipped telling users to check background extraction with a
    control that cannot show what they needed to see."""
    from nocturne.core.color_balance import TONES
    from nocturne.core.mask import BAND_PRESETS
    from nocturne.ui.help_content import TOPICS
    body = TOPICS["color_balance"].body.lower()
    for name in BAND_PRESETS:
        assert name.lower() in body, f"preset {name!r} is not in the help"
    for tone in TONES:
        assert tone in body, f"tone {tone!r} is not in the help"
    for word in ("preserve luminosity", "strength", "feather", "show the mask"):
        assert word in body, f"{word!r} is not in the help"
    assert "dims everything else" in body, (
        "the help still describes the bare greyscale mask the view no longer shows")


def test_the_colour_balance_help_covers_invert_and_the_scale_bar():
    """Both were added after the first draft of the topic. Help has drifted on
    three consecutive releases; a control the help does not mention is a control
    a beginner will not find."""
    from nocturne.ui.help_content import TOPICS
    body = TOPICS["color_balance"].body.lower()
    assert "invert" in body, "the invert toggle is not documented"
    assert "black-to-white" in body, "the scale bar under the histogram is not explained"


def test_the_colour_balance_help_explains_that_ranges_are_independent():
    """The whole point of the per-range change: someone who does not know the
    ranges are remembered will keep applying one at a time."""
    from nocturne.ui.help_content import TOPICS
    body = TOPICS["color_balance"].body.lower()
    assert "each range keeps its own" in body, "per-range independence is not explained"


def test_colour_help_names_the_tint_controls_that_exist():
    """The Color topic described only calibration and Remove Green.

    Two sliders were added to that panel and the help would happily have gone on
    describing the old one — the exact drift this file exists to catch. Pin the
    slider labels to the widgets, so renaming one fails here.
    """
    b = _body("color")
    sp = _src("nocturne/ui/step_panels.py")
    for label in ("Green ←→ Magenta", "Cool ←→ Warm", "Apply Tint"):
        assert label in b, f"the help never mentions {label!r}"
        assert label in sp, f"{label!r} is no longer in the Color panel"


def test_colour_help_gets_the_order_of_operations_right():
    """Calibrate, then nudge, then de-green. This is the order Andreas asked
    for, it is what PROCESSING_ORDER does, and the help must not describe a
    different one — a user following the wrong order re-runs the calibration and
    wonders why their tint vanished.
    """
    from nocturne.ui.pipeline import PROCESSING_ORDER
    b = _body("color")
    assert (PROCESSING_ORDER.index("color")
            < PROCESSING_ORDER.index("tint")
            < PROCESSING_ORDER.index("remove_green"))
    # the prose must present them in that same order
    assert b.index("1 — Calibrate") < b.index("2 — Nudge") < b.index("3 — Remove Green")


def test_colour_help_does_not_claim_nocturne_creates_the_magenta():
    """It is the sensor's, measured: a raw sub is already +0.041 on a
    (R+B)/2 - G axis and the master +0.037. Saying otherwise would send users
    hunting for a stacking fault that is not there."""
    b = _body("color")
    assert "camera, not the stacking" in b or "sensor, not" in b


def test_the_export_help_explains_the_colour_space_control():
    """A control with no explanation is a control nobody uses correctly — and
    this one has a counter-intuitive property (a wider space adds no colour)
    that a user will otherwise assume the opposite of."""
    b = _body("export")
    sp = _src("nocturne/ui/step_panels.py")
    for label in ("sRGB", "Display P3", "Adobe RGB"):
        assert label in b, f"the help never mentions {label!r}"
    assert "Colour space" in sp, "the panel no longer has the control"
    assert "does <i>not</i> add colour" in b or "not</i> add colour" in b, (
        "the help must say plainly that a wider space adds no colour")
    assert "16-bit TIFF only" in b, "the 8-bit restriction is unexplained"


def test_haoiii_help_describes_the_tool_that_actually_shipped():
    """The topic said Ha/OIII "separates a dualband master into individual Ha
    and OIII masters, for people who want to build a palette by hand in another
    tool". Every clause of that is wrong: it takes a FOLDER OF RAW SUBS, not a
    master; it stacks them; it writes ONE colour master; and that master opens
    in Nocturne rather than going off to another program."""
    b = _body("haoiii")
    hd = _src("nocturne/ui/haoiii_dialog.py")
    mw = _src("nocturne/ui/main_window.py")
    assert "individual <b>Ha</b> and <b>OIII</b> masters" not in b
    assert "another tool" not in b, "the topic still sends the user elsewhere"
    # the controls the dialog really has
    # pinned to the addRow that BUILDS each row: the folder label also appears
    # in the file-chooser title, so a looser check survives half a rename.
    assert "Folder of raw subs" in b and 'form.addRow("Folder of raw subs"' in hd
    assert "Extract" in b and 'QPushButton("Extract")' in hd
    assert "Integration" in b and 'form.addRow("Integration"' in hd
    assert "Output" in b and 'form.addRow("Output"' in hd
    assert "HaOIII_master.fits" in b and "HaOIII_master.fits" in hd
    for ext in ("<b>.fit</b>", "<b>.fits</b>", "<b>.fts</b>"):
        assert ext in b, f"the help does not list {ext}"
    for pattern in ('"*.fit"', '"*.fits"', '"*.fts"'):
        assert pattern in hd, f"{pattern} is no longer discovered; update the help"
    # and it hands the finished master back to the app
    assert "opens in Nocturne" in b and '"Ha/OIII master"' in mw


def test_haoiii_help_gets_the_channel_mapping_right():
    """Ha is the red-filtered sites; OIII is the green AND blue ones averaged.
    A user who believes OIII is "the blue channel" will misread every result,
    and the mapping is one line of code away from changing."""
    from nocturne.stacking.haoiii import extract_cfa_planes
    b = _body("haoiii")
    assert "Ha on the red-filtered ones, OIII on the green and blue ones" in b
    assert "Ha in red and OIII in green and blue" in b

    def cfa(red, green, blue):
        # RGGB: (0,0)=R, (0,1)=G, (1,0)=G, (1,1)=B
        frame = np.zeros((8, 8), np.float32)
        frame[0::2, 0::2] = red
        frame[0::2, 1::2] = green
        frame[1::2, 0::2] = green
        frame[1::2, 1::2] = blue
        return frame

    ha, oiii = extract_cfa_planes(cfa(1.0, 0.0, 0.0), "RGGB")
    assert ha.mean() == pytest.approx(1.0, abs=1e-3), "Ha is not the red sites"
    assert oiii.mean() == pytest.approx(0.0, abs=1e-3), "red is leaking into OIII"
    # green-only and blue-only must each give HALF: OIII is their average, so a
    # green-only or blue-only OIII would read 1.0 or 0.0 here.
    assert extract_cfa_planes(cfa(0.0, 1.0, 0.0), "RGGB")[1].mean() == pytest.approx(0.5, abs=1e-3)
    assert extract_cfa_planes(cfa(0.0, 0.0, 1.0), "RGGB")[1].mean() == pytest.approx(0.5, abs=1e-3)


def test_haoiii_help_explains_why_the_master_is_not_red():
    """The extractor rescales OIII to Ha's median AND spread before combining,
    so the master is far less red than a plain stack of the same subs. Told
    nothing, a user reads that as a fault in the extraction."""
    from nocturne.stacking.haoiii import renorm_oiii
    b = _body("haoiii")
    assert "less red" in b and "matched to the Ha" in b
    assert "same brightness and contrast as the Ha" in b
    rng = np.random.default_rng(7)
    ha = np.clip(0.5 + 0.05 * rng.standard_normal((64, 64)), 0, 1).astype(np.float32)
    oiii = np.clip(0.02 + 0.004 * rng.standard_normal((64, 64)), 0, 1).astype(np.float32)
    out = renorm_oiii(ha, oiii)

    def mad(x):
        return float(np.median(np.abs(x - np.median(x))))

    assert float(np.median(out)) == pytest.approx(float(np.median(ha)), abs=0.02), \
        "OIII is no longer lifted to Ha's brightness"
    assert mad(out) == pytest.approx(mad(ha), rel=0.15), \
        "OIII is no longer matched to Ha's contrast"
    assert float(np.median(oiii)) < 0.1, "fixture no longer has a faint OIII to lift"


def test_haoiii_help_does_not_borrow_controls_the_dialog_lacks():
    """It sits next to Stacking in the contents and grades with the same code,
    which makes it easy to describe controls it does not have. It has no
    Strictness selector and no framing checkbox, and it refuses fewer than
    three frames."""
    import inspect

    from nocturne.stacking.coverage import full_coverage_bounds
    from nocturne.stacking.grade import grade_frames
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    from nocturne.ui.haoiii_dialog import KAPPA
    b = _body("haoiii")
    hd = _src("nocturne/ui/haoiii_dialog.py")

    assert "no <b>Strictness</b> setting here" in b
    assert "strictness" not in hd.lower(), "the dialog gained a Strictness control"
    assert inspect.signature(grade_frames).parameters["strictness"].default == "normal"

    assert "no framing choice" in b
    assert "QCheckBox" not in hd, "the dialog gained a checkbox the help ignores"
    assert inspect.signature(full_coverage_bounds).parameters["frac"].default == 0.9

    assert "at least three frames" in b
    assert "at least 3 frames to extract" in hd
    with pytest.raises(ValueError):
        run_haoiii_extract(HaOIIIOptions("average", 2.5, ["a.fit", "b.fit"], "/x.fits"))

    for level in KAPPA:
        assert level in b, f"kappa level {level!r} is not explained"
    # "Low rejection keeps more" is only true while a low setting is the WIDER
    # threshold. Swap the two and the help would be advising the opposite.
    assert KAPPA["Low"] > KAPPA["High"], "the kappa labels are inverted"
    assert "<b>Low</b> rejection keeps more" in b


def test_narrowband_help_names_every_control_the_dialog_shows():
    """Four of the seven controls — Green blend, Saturation, Brightness and the
    Reset button — were absent from the topic entirely, and the two that were
    named were named without a value or a default. Pin each row label to the
    widget that draws it."""
    from nocturne.core.narrowband import PALETTES, _combine
    from nocturne.recipe import _NAME_TO_STAGE
    from nocturne.ui.narrowband_dialog import PALETTES as UI_PALETTES
    b = _body("narrowband")
    nd = _src("nocturne/ui/narrowband_dialog.py")

    # two palette lists, one truth: the help is checked against the core one
    assert list(UI_PALETTES) == list(PALETTES), "the dialog and the engine disagree"
    ha = np.linspace(0.1, 0.9, 64).reshape(8, 8).astype(np.float32)
    oiii = np.linspace(0.9, 0.1, 64).reshape(8, 8).astype(np.float32)
    for palette in PALETTES:
        assert palette in b, f"palette {palette!r} is not described"
        _combine(ha, oiii, palette, 0.6)          # must be a palette that renders
    with pytest.raises(ValueError):
        _combine(ha, oiii, "SHO", 0.6)            # the help says SHO is not available
    assert "no sulfur" in b

    for row in ("OIII boost", "Green blend", "Protect background", "Saturation",
                "Brightness"):
        assert row in b, f"the help never mentions {row!r}"
        assert f'controls.addRow("{row}"' in nd, f"{row!r} is no longer a control"
    assert "Preserve lightness" in b and 'QCheckBox("Preserve lightness' in nd
    assert "Reset" in b and 'QPushButton("Reset")' in nd
    assert "Apply" in b and 'QPushButton("Apply")' in nd
    assert "StarXTerminator" in b and "rcastro_valid" in nd
    assert "stretched" in b and "Narrowband works on the " in _src("nocturne/ui/main_window.py")
    assert "Recipes and Batch" in b and _NAME_TO_STAGE["Narrowband"] == "narrowband"


def test_narrowband_help_quotes_the_defaults_the_dialog_opens_with(qtbot):
    """Every default in the topic is a number a user will compare against what
    is on screen. Read them off a real dialog rather than trusting the dataclass
    — NarrowbandParams defaults lightness_preserve to True and the dialog
    deliberately opens it OFF, so the two disagree by design."""
    from nocturne.core.image import AstroImage
    from nocturne.settings import Settings
    from nocturne.ui.narrowband_dialog import NarrowbandDialog
    b = _body("narrowband")
    d = NarrowbandDialog(Settings(), AstroImage(np.zeros((8, 8, 3), np.float32),
                                                is_linear=False))
    qtbot.addWidget(d)
    p = d._params()

    assert p.palette == "HOO" and "Start here" in b
    assert p.oiii_boost == 1.0 and d.oiii_val.text() == "×1.00"
    assert "OIII boost — the key control (default ×1.00)" in b
    assert p.brightness == 1.0 and d.bright_val.text() == "×1.00"
    assert "Brightness (default ×1.00)" in b
    assert p.blend_amount == 0.6 and d.blend_val.text() == "0.60"
    assert "Green blend — HOO only (default 0.60)" in b
    assert p.protect_background == 0.4 and d.protect_val.text() == "40%"
    assert "Protect background (default 40%)" in b
    assert p.saturation == 0.5 and d.sat_val.text() == "0.50"
    assert "Saturation (default 0.50)" in b
    assert d.lightness_check.isChecked() is False
    assert "Preserve lightness — off by default" in b

    d.oiii_slider.setValue(d.oiii_slider.maximum())
    assert d.oiii_val.text() == "×2.00", "the OIII boost range moved"
    assert "toward ×2.00" in b


def test_narrowband_help_warns_that_green_blend_is_inert_outside_hoo():
    """The control the user is most likely to read as broken: it is live in HOO
    and does nothing at all in the other two palettes, because only HOO builds a
    synthetic green."""
    from nocturne.core.narrowband import _combine
    b = _body("narrowband")
    assert "It does nothing in Pseudo-SHO or Pseudo-bicolor." in b
    rng = np.random.default_rng(11)
    ha = rng.random((16, 16)).astype(np.float32)
    oiii = rng.random((16, 16)).astype(np.float32)

    def differs(palette):
        low = _combine(ha, oiii, palette, 0.0)
        high = _combine(ha, oiii, palette, 1.0)
        return any(not np.allclose(x, y) for x, y in zip(low, high))

    assert differs("HOO"), "Green blend no longer does anything in HOO either"
    assert not differs("Pseudo-SHO"), "Pseudo-SHO now uses the blend; update the help"
    assert not differs("Pseudo-bicolor"), "Pseudo-bicolor now uses the blend; update the help"


def test_narrowband_help_describes_the_palettes_and_the_green_cap_correctly():
    """Which gas lands in which channel is the whole content of a palette. And
    green is clamped in two of the three — the help says which, and says why the
    third is left alone."""
    from nocturne.core.narrowband import _combine
    b = _body("narrowband")
    rng = np.random.default_rng(13)
    ha = rng.random((16, 16)).astype(np.float32)
    oiii = rng.random((16, 16)).astype(np.float32)

    r, g, bl = _combine(ha, oiii, "Pseudo-bicolor", 0.6)
    assert np.allclose(r, ha) and np.allclose(bl, ha), \
        "Pseudo-bicolor no longer puts hydrogen in red AND blue"
    assert np.allclose(g, oiii), "Pseudo-bicolor's green is no longer the real oxygen"
    assert "hydrogen in red and blue, oxygen in green" in b

    for palette in ("HOO", "Pseudo-SHO"):
        r, g, bl = _combine(ha, oiii, palette, 1.0)
        assert np.all(g <= (r + bl) / 2.0 + 1e-6), f"{palette} lost its green cap"
    # and the cap is a real constraint, not a coincidence of the fixture
    r, g, bl = _combine(ha, oiii, "HOO", 1.0, scnr=False)
    assert np.any(g > (r + bl) / 2.0 + 1e-6)
    assert "capped at the average of red and blue" in b
    assert "Pseudo-bicolor's green is the real oxygen" in b


def test_narrowband_help_gets_the_direction_of_the_two_headline_sliders_right():
    """Both could be described backwards and still read plausibly. Higher OIII
    boost must lift the oxygen further; higher Protect background must leave
    MORE of the sky alone."""
    from nocturne.core.narrowband import nebula_mask, normalize_to_reference
    b = _body("narrowband")
    rng = np.random.default_rng(17)
    ha = np.clip(0.45 + 0.08 * rng.standard_normal((96, 96)), 0, 1).astype(np.float32)
    oiii = np.clip(0.08 + 0.02 * rng.standard_normal((96, 96)), 0, 1).astype(np.float32)
    levels = [float(normalize_to_reference(oiii, ha, 1.0, boost).mean())
              for boost in (0.3, 1.0, 2.0)]
    assert levels[0] < levels[1] < levels[2], "OIII boost no longer runs upward"
    assert float(oiii.mean()) < levels[1], "×1.00 no longer lifts the oxygen at all"
    assert "×1.00 is not &quot;off&quot;" in b
    assert "Drop it below ×1.00 to pull the oxygen back down" in b

    rgb = np.dstack([ha, oiii, oiii])
    masks = [float(nebula_mask(rgb, p).mean()) for p in (0.0, 0.4, 1.0)]
    assert masks[0] > masks[1] > masks[2], "Protect background is inverted"
    assert "a higher setting protects more" in b


def test_dualband_help_sends_you_to_the_right_tool_for_what_you_have():
    """The overview topic said the Ha/OIII tool "splits a dualband master into
    separate Ha and OIII masters, so you can combine them ... in your tool of
    choice". It takes raw subs, not a master; it produces one file, not two; and
    Nocturne finishes the job itself. Troubleshooting repeated the same claim."""
    b = _body("dualband")
    tb = _body("troubleshooting")
    hd = _src("nocturne/ui/haoiii_dialog.py")
    mw = _src("nocturne/ui/main_window.py")
    for wrong in ("separate Ha and OIII masters", "tool of choice", "splits a dualband master"):
        assert wrong not in b, f"the topic still claims {wrong!r}"
        assert wrong not in tb, f"troubleshooting still claims {wrong!r}"
    assert "split it into Ha and OIII channels" not in tb

    # Route 1 is the Narrowband tool, on the stretched master
    assert "Narrowband" in b and 'load_icon("narrowband"' in mw
    assert "after the stretch" in b and "Narrowband works on the " in mw
    # Route 2 is the Ha/OIII tool, on the raw subs, producing ONE master
    assert "raw subs" in b and 'form.addRow("Folder of raw subs"' in hd
    assert "<b>single</b> master" in b and "not two files" in b
    assert '"Ha/OIII master"' in mw, "the extractor no longer hands a master back"
    for route in ("Route 1", "Route 2"):
        assert route in b


def test_dualband_help_agrees_with_both_engines_about_which_gas_is_where():
    """Two separate extractors, one claim: Ha is red, OIII is green AND blue.
    The topic is the only place a user is told this, and it is the assumption
    under every palette."""
    from nocturne.core.image import AstroImage
    from nocturne.core.narrowband import extract_ha_oiii
    from nocturne.stacking.haoiii import extract_cfa_planes
    b = _body("dualband")
    assert "Ha on the red ones, OIII on the green and blue ones" in b
    assert "hydrogen from red, oxygen from green and blue" in b

    # Route 1: out of a finished colour image
    rgb = np.zeros((8, 8, 3), np.float32)
    rgb[..., 0], rgb[..., 1], rgb[..., 2] = 1.0, 0.4, 0.6
    ha, oiii = extract_ha_oiii(AstroImage(rgb, is_linear=False))
    assert ha.mean() == pytest.approx(1.0, abs=1e-6), "Ha is no longer the red channel"
    assert oiii.mean() == pytest.approx(0.5, abs=1e-6), \
        "OIII is no longer the average of green and blue"

    # Route 2: out of the raw Bayer grid, same convention
    cfa = np.zeros((8, 8), np.float32)
    cfa[0::2, 0::2] = 1.0                      # RGGB red sites
    cfa[0::2, 1::2] = cfa[1::2, 0::2] = 0.4    # green sites
    cfa[1::2, 1::2] = 0.6                      # blue site
    ha2, oiii2 = extract_cfa_planes(cfa, "RGGB")
    assert ha2.mean() == pytest.approx(1.0, abs=1e-3)
    assert oiii2.mean() == pytest.approx(0.5, abs=1e-3)


def test_dualband_help_is_right_that_sho_is_unavailable_and_names_the_real_palettes():
    from nocturne.core.narrowband import PALETTES, _combine
    b = _body("dualband")
    ha = np.linspace(0.1, 0.9, 64).reshape(8, 8).astype(np.float32)
    oiii = np.linspace(0.9, 0.1, 64).reshape(8, 8).astype(np.float32)
    with pytest.raises(ValueError):
        _combine(ha, oiii, "SHO", 0.6)
    assert "SHO is not offered anywhere in Nocturne" in b
    for palette in PALETTES:
        assert f"<b>{palette}</b>" in b, f"the topic does not name the {palette!r} palette"


def test_dualband_help_is_honest_that_auto_enhance_applies_no_palette():
    """A user who taps Auto Enhance on dualband data and gets a red-gold image
    needs to know that is the design, not a failure to detect narrowband."""
    from nocturne.core.auto_enhance import build_auto_plan, detect_data_type
    from nocturne.core.image import AstroImage
    from nocturne.settings import Settings
    b = _body("dualband")
    assert "no palette in <b>Auto " in b and "red-gold" in b
    img = AstroImage(np.full((32, 32, 3), 0.3, np.float32), is_linear=True,
                     metadata={"filter": "LP"})
    stages = [stage for stage, _ in build_auto_plan(img, Settings())]
    assert stages, "the auto plan is empty; this test proves nothing"
    assert "narrowband" not in stages, "Auto Enhance now applies a palette; update the help"
    # and the topic's LP / IRCUT reading of the header
    assert "<b>LP</b>" in b and "<b>IRCUT</b>" in b
    assert detect_data_type({"filter": "LP"}) == "dualband"
    assert detect_data_type({"filter": "IRCUT"}) == "broadband"
    assert "FILTER" in _src("nocturne/core/fits_io.py")


def test_recipes_help_lists_what_a_recipe_can_and_cannot_hold():
    """The topic named no step at all, so nobody could tell what "the steps you
    applied" covers. Every stepper step must be named, and the two that are
    silently dropped must be named as dropped — Save Recipe warns about exactly
    these two."""
    from nocturne.recipe import _NAME_TO_STAGE, uncaptured_step_names
    from nocturne.ui.pipeline import ENHANCE_NAMES, STEP_NAME
    b = _body("recipes")
    for name in STEP_NAME.values():
        assert name in b, f"the topic never mentions the {name!r} step"
    for name in ("Crop", "Rotate", "Flip", "Narrowband", "Colour Balance"):
        assert name in b
    assert len(ENHANCE_NAMES) == 10 and "all ten <b>Enhancements</b>" in b
    assert not uncaptured_step_names([(n, "") for n in ENHANCE_NAMES]), \
        "the taps are no longer captured; the help says they are"

    every = [(n, "") for n in list(_NAME_TO_STAGE) + list(ENHANCE_NAMES)
             + ["Star Spikes", "Trim"]]
    assert uncaptured_step_names(every) == ["Star Spikes", "Trim"], \
        "the set of steps a recipe drops changed; the help names these two"
    assert "<b>Star Spikes</b> and <b>Trim</b>" in b
    assert "can’t include" in b
    assert "can't include" in _src("nocturne/ui/main_window.py"), \
        "Save Recipe no longer warns; the help promises it does"


def test_recipes_help_is_right_that_a_replayed_crop_is_re_detected():
    """A recipe stores the aspect, never the box. Batch re-detects the content
    rectangle per image, so a recipe cannot reproduce a composition — the help
    now says so, and this proves it."""
    from nocturne.batch import apply_recipe
    from nocturne.core.crop import CropParams, detect_content_bounds
    from nocturne.core.image import AstroImage
    from nocturne.recipe import Recipe, serialize_option
    from nocturne.settings import Settings
    b = _body("recipes")
    assert "it does not keep the box you dragged" in b
    assert "content rectangle" in b

    stored = serialize_option("crop", CropParams(bounds=(5, 20, 5, 20), aspect="1:1"))
    assert "bounds" not in stored, "the recipe now stores bounds; the help is stale"
    assert stored["aspect"] == "1:1"

    data = np.zeros((40, 40, 3), np.float32)
    data[8:32, 6:30] = 0.5                       # content inset in a black border
    img = AstroImage(data, is_linear=True)
    out = apply_recipe(img, Recipe(steps=[{"stage": "crop", "option":
                                           serialize_option("crop", CropParams(
                                               bounds=(5, 20, 5, 20)))}]),
                       Settings())
    top, bottom, left, right = detect_content_bounds(img)
    assert out.data.shape[:2] == (bottom - top, right - left), \
        "the replayed crop is no longer the detected content rectangle"


def test_recipes_help_is_right_about_the_files_batch_reads_and_writes(qtbot, tmp_path):
    """Only FITS is picked up, and only from the folder itself. A user pointing
    Batch at a folder of TIFFs gets "0/0" and no explanation."""
    from nocturne.batch import _EXPORTERS
    from nocturne.settings import Settings
    from nocturne.ui.batch_dialog import BatchDialog
    b = _body("recipes")
    d = BatchDialog(Settings())
    qtbot.addWidget(d)

    for row in ("Recipe", "Input folder", "Output folder", "Format"):
        assert f'form.addRow("{row}"' in _src("nocturne/ui/batch_dialog.py")
        assert f"<b>{row}</b>" in b, f"the topic never names the {row!r} row"
    assert [d.format_box.itemText(i) for i in range(d.format_box.count())] == \
        list(_EXPORTERS), "the format list moved"
    for fmt in _EXPORTERS:
        assert f"<b>{fmt}</b>" in b or fmt in b

    for name in ("a.fit", "b.fits", "c.fts", "d.tiff", "e.png", "f.jpg"):
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "g.fits").write_bytes(b"")
    d.input_edit.setText(str(tmp_path))
    found = {pathlib.Path(p).name for p in d._input_files()}
    assert found == {"a.fit", "b.fits", "c.fts"}, \
        "Batch's input patterns changed; the help says FITS only, this folder only"
    for ext in ("<b>.fit</b>", "<b>.fits</b>", "<b>.fts</b>"):
        assert ext in b
    assert "0/0" in b and "Done — {ok}/{len(results)} succeeded" in \
        _src("nocturne/ui/batch_dialog.py")


def test_recipes_help_warns_that_batch_overwrites_by_input_name(tmp_path):
    """The output is the input's stem plus the format's extension, written with
    no prompt — so FITS output into the input folder destroys the master. The
    help says give the output its own folder; this is why."""
    from nocturne.batch import run_batch
    from nocturne.core.export import save_fits
    from nocturne.core.image import AstroImage
    from nocturne.recipe import Recipe
    from nocturne.settings import Settings
    b = _body("recipes")
    assert "<b>Give the output its own folder</b>" in b
    src = tmp_path / "in"
    src.mkdir()
    save_fits(AstroImage(np.full((16, 16, 3), 0.3, np.float32), is_linear=True),
              str(src / "m42.fits"))
    before = (src / "m42.fits").read_bytes()
    results = run_batch(Recipe(steps=[{"stage": "levels", "option": [0.0, 1.0, 1.0]}]),
                        [str(src / "m42.fits")], str(src), "FITS", Settings())
    assert results[0]["ok"], results[0]["message"]
    assert (src / "m42.fits").read_bytes() != before, \
        "run_batch no longer overwrites the input; the help warns that it does"


def test_recipes_help_explains_why_a_whole_batch_can_fail_identically():
    """Batch has no per-stage resilience: a step whose external tool is missing
    fails the entire file, with an OS-level message. Every file then fails the
    same way, which reads as broken data."""
    from nocturne.batch import run_batch
    from nocturne.core.export import save_fits
    from nocturne.core.image import AstroImage
    from nocturne.recipe import Recipe
    from nocturne.settings import Settings
    import tempfile
    b = _body("recipes")
    assert "that step cannot be skipped" in b and "<b>Settings</b>" in b
    d = tempfile.mkdtemp()
    path = pathlib.Path(d) / "m42.fits"
    save_fits(AstroImage(np.full((16, 16, 3), 0.3, np.float32), is_linear=True), str(path))
    results = run_batch(Recipe(steps=[{"stage": "background", "option": "strong"}]),
                        [str(path)], d, "TIFF", Settings())      # nothing installed
    assert results[0]["ok"] is False, \
        "a missing GraXpert no longer fails the file; the help says it does"
    assert not (pathlib.Path(d) / "m42.tiff").exists(), "a failed file wrote output anyway"


def _planted_star_field(seed=3):
    """A small frame SEP can actually find stars in: real noise (so
    Background.globalrms is meaningful) plus four planted, warm-coloured stars
    of decreasing brightness."""
    rng = np.random.default_rng(seed)
    h, w = 160, 200
    data = rng.normal(0.05, 0.004, (h, w, 3)).astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    for y, x, b in [(40, 50, 0.9), (80, 140, 0.6), (120, 70, 0.45), (30, 160, 0.35)]:
        g = np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / (2 * 1.8 ** 2)).astype(np.float32)
        data += g[:, :, None] * np.array([b, b * 0.7, b * 0.5], np.float32)
    from nocturne.core.image import AstroImage
    return AstroImage(np.clip(data, 0, 1).astype(np.float32), is_linear=False)


def test_star_spikes_help_quotes_the_sliders_the_dialog_opens_with(qtbot):
    """Four sliders, and the old topic gave a default or a range for none of
    them. Read them off a real dialog: Length opening at zero is the whole
    'nothing happened' story."""
    from nocturne.ui.star_spikes_dialog import StarSpikesDialog
    b = _body("star_spikes")
    sd = _src("nocturne/ui/star_spikes_dialog.py")
    d = StarSpikesDialog(_planted_star_field())
    qtbot.addWidget(d)

    rows = {"Length (off → long)": (d.length_slider, d.length_val),
            "Intensity (faint → full)": (d.intensity_slider, d.intensity_val),
            "Number of stars": (d.stars_slider, d.stars_val),
            "Rotation": (d.angle_slider, d.angle_val)}
    for label in rows:
        assert f'_row("{label}"' in sd, f"{label!r} is no longer a row"
        assert f"<b>{label}</b>" in b, f"the topic never names the {label!r} slider"

    assert (d.length_slider.minimum(), d.length_slider.maximum()) == (0, 100)
    assert d.length_slider.value() == 0 and d.length_val.text() == "0.00"
    assert "default <b>0.00</b>, range 0.00 to 1.00" in b
    assert (d.intensity_slider.minimum(), d.intensity_slider.maximum()) == (0, 100)
    assert d.intensity_slider.value() == 100 and d.intensity_val.text() == "100%"
    assert "default <b>100%</b>, range 0 to 100%" in b
    assert (d.stars_slider.minimum(), d.stars_slider.maximum()) == (0, 50)
    assert d.stars_slider.value() == 6 and d.stars_val.text() == "6"
    assert "default <b>6</b>, range 0 to 50" in b
    assert (d.angle_slider.minimum(), d.angle_slider.maximum()) == (0, 90)
    assert d.angle_slider.value() == 0 and d.angle_val.text() == "0°"
    assert "default <b>0°</b>, range 0 to 90°" in b

    assert "Double-click" in b and "Double-click to reset" in _src("nocturne/ui/reset_slider.py")
    assert 'QPushButton("Apply")' in sd and 'QPushButton("Close")' in sd
    assert "<b>Apply</b>" in b and "<b>Close</b>" in b
    assert "stretched" in b and "Star Spikes works on the " in _src("nocturne/ui/main_window.py")


def test_star_spikes_help_is_right_that_the_dialog_opens_drawing_nothing(qtbot):
    """The topic's headline reassurance. Prove it as an assert-UNCHANGED: the
    render at the opening slider positions must equal the image that went in."""
    from nocturne.core.star_spikes import add_spikes, detect_stars
    from nocturne.ui.star_spikes_dialog import StarSpikesDialog
    b = _body("star_spikes")
    assert "opens with this at zero, which means no spikes at all" in b
    img = _planted_star_field()
    stars = detect_stars(img.data)
    assert len(stars) >= 4, "the fixture has no stars; the rest proves nothing"

    d = StarSpikesDialog(img)
    qtbot.addWidget(d)
    np.testing.assert_array_equal(d.result().data, np.clip(img.data, 0.0, 1.0))

    # ... and the two other ways to draw nothing that the topic names
    np.testing.assert_array_equal(
        add_spikes(img, stars, 1.0, 0, 0.0, 1.0).data, np.clip(img.data, 0.0, 1.0))
    np.testing.assert_array_equal(
        add_spikes(img, stars, 1.0, 6, 0.0, 0.0).data, np.clip(img.data, 0.0, 1.0))
    assert "At 0 nothing is drawn" in b and "At 0% nothing is drawn" in b
    # and with no stars found, nothing is drawn at any setting
    np.testing.assert_array_equal(
        add_spikes(img, [], 1.0, 6, 0.0, 1.0).data, np.clip(img.data, 0.0, 1.0))
    assert "no stars the detector recognises" in b


def test_star_spikes_help_gets_the_geometry_and_the_blend_right():
    """Three claims with numbers in them: arms reach 8% of the short edge, the
    rotation range stops at 90° because the cross repeats there, and the screen
    blend can only add light."""
    from nocturne.core.star_spikes import _MAX_LEN_FRAC, add_spikes, detect_stars
    b = _body("star_spikes")
    img = _planted_star_field()
    base = np.clip(img.data, 0.0, 1.0)
    stars = detect_stars(img.data)

    assert f"about <b>{_MAX_LEN_FRAC:.0%}</b> of your image" in b
    one = add_spikes(img, stars, 1.0, 1, 0.0, 1.0)          # brightest star only
    ys, xs = np.nonzero(np.abs(one.data - base).max(axis=2) > 1e-4)
    reach = np.hypot(ys - stars[0].y, xs - stars[0].x).max()
    cap = _MAX_LEN_FRAC * min(img.data.shape[:2])
    assert 0.8 * cap <= reach <= cap + 1.5, f"arm reach {reach:.1f} is not {cap:.1f}px"

    full = add_spikes(img, stars, 1.0, 4, 0.0, 1.0)
    assert np.allclose(full.data, add_spikes(img, stars, 1.0, 4, 90.0, 1.0).data), \
        "90° is no longer the same picture as 0°; the help explains the range that way"
    assert not np.allclose(full.data, add_spikes(img, stars, 1.0, 4, 45.0, 1.0).data)
    assert "the four arms are 90° apart" in b

    assert (full.data >= base - 1e-6).all(), "the blend now darkens; the help says it cannot"
    assert "<b>screen-blended</b>" in b and "never darkens" in b
    assert float(add_spikes(img, stars, 1.0, 4, 0.0, 0.5).data.sum()) < float(full.data.sum())


def test_star_spikes_help_is_honest_that_a_recipe_drops_it():
    """It is one of the two steps Save Recipe warns it must leave out, so a
    batch of the same recipe comes back without spikes."""
    from nocturne.recipe import uncaptured_step_names
    b = _body("star_spikes")
    assert uncaptured_step_names([("Star Spikes", "")]) == ["Star Spikes"], \
        "recipes now record Star Spikes; the help says they cannot"
    assert "<b>recipe cannot record</b>" in b and "Trim is the" in b
    assert '_PrecomputedStep("Star Spikes"' in _src("nocturne/ui/main_window.py")


def _upscale_dialog(qtbot, **kw):
    from nocturne.core.image import AstroImage
    from nocturne.settings import Settings
    from nocturne.ui.upscale_dialog import UpscaleDialog
    data = np.full((60, 60, 3), 0.1, np.float32)
    data[30, 30] = 1.0
    meta = {"target": "M42", "source_label": "m42.fits"}
    d = UpscaleDialog(AstroImage(data, is_linear=False, metadata=meta), meta, Settings(), **kw)
    qtbot.addWidget(d)
    return d


def test_upscale_help_names_the_controls_the_dialog_shows(qtbot):
    """The topic mentioned three of the seven controls and no numbers. Engine,
    the fixed scale, the status line and the disabled-until-run pair were all
    missing."""
    from nocturne.ui.upscale_dialog import SCALE
    b = _body("upscale")
    ud = _src("nocturne/ui/upscale_dialog.py")
    d = _upscale_dialog(qtbot)

    assert SCALE == 2 and "<b>2×</b>" in b
    assert [d._engine_box.itemText(i) for i in range(d._engine_box.count())] == \
        [e.name for e in d._engines]
    assert d._engine_box.count() == 1 and d._engine.name == "Lanczos", \
        "a second engine shipped; the help says there is nothing to decide"
    assert "<b>Engine</b> currently offers one choice, <b>Lanczos</b>" in b
    for label, text in (("<b>Upscale</b>", 'QPushButton("Upscale")'),
                        ("<b>Compare</b>", 'QCheckBox("Compare")'),
                        ("<b>Export…</b>", 'QPushButton("Export…")'),
                        ("<b>Open as copy</b>", 'QPushButton("Open as copy")')):
        assert label in b, f"the topic never names {label}"
        assert text in ud, f"{text} is no longer a control"
    assert "crop box" in b and "aspect_ratio=None" in ud   # free-form box, as the help says

    assert d._export_btn.isEnabled() is False and d._open_copy_btn.isEnabled() is False
    assert "stay disabled until you have run <b>Upscale</b> once" in b
    d._run_upscale()
    assert d._export_btn.isEnabled() and d._open_copy_btn.isEnabled()
    assert d._result.data.shape == (120, 120, 3), "the scale is no longer 2×"
    assert "120×120" in d.status.text() and "reports the new size in pixels" in b
    assert "Stretch your image first" in b
    assert "Upscale works on the " in _src("nocturne/ui/main_window.py"), \
        "the stretch gate went; the help still sends people to stretch first"


def test_upscale_help_is_right_that_open_as_copy_starts_a_new_project(qtbot, tmp_path):
    """The surprise the old topic hid behind "keep editing it as a new project":
    the edit history does not come with it. Prove it on a real MainWindow."""
    from astropy.io import fits
    from nocturne.core.image import AstroImage
    from nocturne.ui.main_window import MainWindow
    b = _body("upscale")
    assert "<b>your edit history is gone</b>" in b and "<b>save your project first</b>" in b

    path = tmp_path / "stack.fits"
    fits.PrimaryHDU((np.random.rand(3, 24, 24) * 1000).astype(np.uint16)).writeto(str(path))
    win = MainWindow(settings_path=str(tmp_path / "settings.json"), check_updates=False)
    win._async_enabled = False
    qtbot.addWidget(win)
    win.open_fits(str(path))
    win.project.record_precomputed("Stretch", "", win.project.current())
    assert win.project.can_undo() and win.project.entries(), "no history to lose"

    result = AstroImage(np.full((48, 48, 3), 0.2, np.float32), is_linear=False)
    win._open_upscaled(result)
    assert win.project.can_undo() is False, "Open as copy kept the history; the help says it does not"
    assert list(win.project.entries()) == []
    assert win.current_stage_id() == "load", "the stepper no longer returns to Import & assess"
    np.testing.assert_array_equal(win.project.current().data, result.data)


def test_upscale_help_describes_the_sidecar_file_that_is_actually_written(qtbot, tmp_path):
    """The .txt beside the export is the topic's one verifiable promise. Check
    the default filename and the sentence the file ends on."""
    from nocturne.core.upscale import upscale_filename
    b = _body("upscale")
    d = _upscale_dialog(qtbot)
    d._run_upscale()
    d._save_runner = lambda img, path: None
    d._do_export(str(tmp_path / "out.jpg"))
    report = (tmp_path / "out.txt").read_text()

    assert upscale_filename("m42.fits", 2) == "m42_2x.jpg" and "yourfile_2x.jpg" in b
    for claim in ("Lanczos", "2×", "m42.fits", "M42"):
        assert claim in report, f"the sidecar no longer records {claim!r}"
    assert "presentation derivative — enlarged, no synthesized detail" in report
    assert "presentation derivative — enlarged, no synthesized detail" in b
    assert "JPEG (*.jpg);;PNG (*.png);;TIFF (*.tiff)" in _src("nocturne/ui/upscale_dialog.py")
    assert "JPEG, PNG or TIFF" in b


def test_upscale_help_is_right_that_stars_never_go_through_the_engine():
    """The layered claim: the engine enlarges the starless layer, the stars are
    always resampled deterministically. A fake engine that erases its input must
    still leave the stars standing."""
    from nocturne.core.image import AstroImage
    from nocturne.core.upscale import LanczosEngine, upscale_crop
    b = _body("upscale")
    assert "the stars themselves are always enlarged by the deterministic" in b

    class _Erasing:
        name = "Erasing"

        def available(self):
            return True

        def upscale(self, img, scale):
            out = LanczosEngine().upscale(img, scale)
            return AstroImage(np.zeros_like(out.data), is_linear=out.is_linear,
                              metadata=dict(out.metadata))

        def provenance(self):
            return {"engine": self.name, "kind": "test", "fabricates": True}

    data = np.full((40, 40, 3), 0.05, np.float32)
    yy, xx = np.mgrid[0:40, 0:40]
    data += (np.exp(-((yy - 20) ** 2 + (xx - 20) ** 2) / 2.0)[:, :, None]
             * np.float32(0.9))
    img = AstroImage(np.clip(data, 0, 1).astype(np.float32), is_linear=False)
    out = upscale_crop(img, None, _Erasing(), scale=2)
    assert out.data.shape == (80, 80, 3)
    assert out.data.max() > 0.3, "the star layer went through the engine and was erased"
    assert out.metadata["upscale"]["scale"] == 2
