"""The in-app help must describe the app that exists.

Written after a documentation audit found Share's topic still describing "an
optional caption band carrying your handle" long after the caption became fully
editable, and no topic at all for Trim or fullscreen. Help drifts silently:
nothing fails when a feature changes and its topic does not.

These tests are deliberately shallow — they check that a claim in the help has a
counterpart in the code, not that the prose is good. A shallow check that runs is
worth more than a thorough one nobody performs.
"""
import sys
import pathlib
import re

import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.ui import help_content as h  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


# Any real program will do as a stand-in tool path; /bin/echo does not exist
# on Windows, where is_tool also wants an extension.
_RUNNABLE = sys.executable


def _src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


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


def test_crop_and_trim_help_name_exactly_the_shape_controls_that_exist(qtbot):
    """The dropdowns became shape buttons on 2026-10-10. Every control the two
    topics name is one the panel or dialog has, by its own label, and the old
    names are gone."""
    import numpy as np
    from nocturne.core.crop import GUIDES
    from nocturne.core.image import AstroImage
    from nocturne.ui.pipeline import path_stages
    from nocturne.ui.step_panels import build_panel
    from nocturne.ui.trim_dialog import TrimDialog
    crop = build_panel(next(s for s in path_stages() if s.id == "crop"))
    trim = TrimDialog(AstroImage(np.zeros((20, 30, 3), np.float32), is_linear=False))
    qtbot.addWidget(crop); qtbot.addWidget(trim)
    for topic, picker, guides in (("crop", crop.shape_picker, crop.guides_box),
                                  ("trim", trim.shape_picker, trim.guides_box)):
        b = _body(topic)
        for gone in ("Aspect ratio", "Rule of thirds", "Center cross", "Rotate 90"):
            assert gone not in b, f"{topic} help still names {gone!r}"
        assert "<b>Shape</b>" in b and "<b>Portrait</b>" in b
        assert picker.orientation.text() == "Portrait"
        assert "Free" in b and "Original" in b
        assert picker.labels()[:2] == ["Free", "Original"]
        for g in GUIDES[1:]:
            assert f"<b>{g}</b>" in b, f"{topic} help never names the {g} guide"
        assert [x.text() for x in guides.buttons()] == GUIDES
    b = _body("crop")
    for name in picker.labels()[2:]:
        assert name in b, f"the crop help never lists {name}"
    for btn in (crop.rotate_btn, crop.flip_h_btn, crop.flip_v_btn):
        assert f"<b>{btn.text().replace(chr(176), '&deg;')}</b>" in b, btn.text()
    assert "3:2 becomes 2:3" in crop.shape_picker.orientation.toolTip()
    assert "<b>Portrait</b>, turns the chosen shape: it makes 3:2 into" in b
    from PySide6.QtWidgets import QLabel
    assert any("APPLY INSTANTLY" in lb.text() for lb in crop.findChildren(QLabel)), \
        "the help says the heading says so"


def test_share_has_no_free_shape_and_upscale_has_one(qtbot):
    """Share frames the whole picture to a shape (no Free); Upscale Crop's box
    was always free to drag, so it keeps Free and opens on it."""
    b_share, b_up = _body("share"), _body("upscale")
    d = _upscale_dialog(qtbot)
    assert d.shape_picker.labels()[0] == "Free" and d.shape_picker.ratio() is None
    assert "no Free button" in b_share and "<b>Free</b> (any shape you drag, where it opens)" in b_up
    assert "<b>Portrait</b>" in b_share and "<b>Portrait</b>" in b_up
    # Review M5: the compare pane is "Before", so "Original" names one thing here.
    from PySide6.QtWidgets import QLabel
    panes = [lb.text() for lb in d._pair.findChildren(QLabel)]
    assert "Before" in panes and "Original" not in panes
    assert "<b>Before</b>" in b_up


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


def test_share_help_names_every_preset_that_ships():
    """A named look the help never mentions is a look nobody finds."""
    from nocturne.core.presets import PRESETS
    b = _body("share")
    for preset in PRESETS:
        assert f"<b>{preset.name}</b>" in b, \
            f"preset {preset.name!r} is offered but not explained"
    assert PRESETS[0].name == "Scrim" and "the default" in b


def test_share_help_says_data_keeps_todays_look_and_the_preset_agrees():
    """The one promise to an existing user: their exports need not change."""
    from nocturne.core.presets import preset_by_name
    b, data = _body("share"), preset_by_name("Data")
    assert data.treatment == "band" and data.colour == "#ffffff"
    assert "solid band" in b.lower() and "white" in b.lower()


def test_share_help_names_every_treatment_and_counts_the_anchors_right():
    from nocturne.ui.plate_render import ANCHORS, TREATMENTS
    b = _body("share")
    for label, _key in TREATMENTS:
        assert f"<b>{label}</b>" in b, f"treatment {label!r} exists but the help omits it"
    assert len(ANCHORS) == 9 and "nine positions" in b


def test_share_help_names_the_type_that_is_actually_bundled():
    """The claim is that an export looks the same on any machine. It holds only
    for families that ship — a family merely requested substitutes in silence."""
    from nocturne.ui.fonts import FONT_DIR, PLATE_FAMILIES
    b = _body("share")
    for _label, family in PLATE_FAMILIES:
        assert f"<b>{family}</b>" in b, f"{family} is offered in Share but not named in the help"
    assert len(list(FONT_DIR.glob("*.ttf"))) == len(PLATE_FAMILIES)
    assert "looks the same" in b and "installed" in b


def test_share_help_describes_the_three_slots_the_dialog_actually_has():
    b, sd = _body("share"), _src("nocturne/ui/share_dialog.py")
    for attr in ("_designation_edit", "_common_edit", "_credit_edit"):
        assert attr in sd, f"{attr} is gone; the help still promises three slots"
    for slot in ("<b>object</b>", "<b>common name</b>", "<b>credit</b>"):
        assert slot in b, f"help does not describe the {slot} slot"
    assert "\u21ba" in b and 'QPushButton("\u21ba")' in sd


def test_share_help_says_where_the_two_title_lines_come_from():
    """Solve first, OBJECT header second, catalogue for the colloquial name."""
    b, plate = _body("share"), _src("nocturne/core/plate.py")
    assert "plate solve" in b.lower() and "target_designation" in plate
    assert "OBJECT" in b and 'metadata.get("target")' in plate
    assert "catalogue" in b and "common_name_for(desig)" in plate


def test_share_help_promises_wrapping_and_the_renderer_wraps():
    """The regression the plate exists to kill: the old caption elided, and a
    real IC 1396A export lost its date and handle to an ellipsis in silence."""
    b = _body("share")
    pr, sd = _src("nocturne/ui/plate_render.py"), _src("nocturne/ui/share_dialog.py")
    assert "wrap" in b.lower() and "status line" in b
    assert "def _wrap(" in pr
    assert "elidedText" not in pr, "the renderer elides again; the help says it wraps"
    # The message must describe WRAPPING, not loss: the flag is set on any
    # second line, so "will not fit" told the user text had been dropped when
    # nothing had — and contradicted this very topic, which says "wrap".
    assert "has wrapped to a second line" in sd
    # Check the STRING THE USER SEES, not the file: the first version of this
    # assertion searched the whole source and tripped on the comments explaining
    # the very fix it was guarding.
    from nocturne.ui.share_dialog import ShareDialog
    import inspect
    shown = inspect.getsource(ShareDialog._show_status)
    assert "will not fit" not in shown, "the status line claims text was lost again"


def test_share_help_explains_the_matte_default_under_annotations():
    """A default that overrules nothing once the user has chosen — the help has
    to say both halves or the dropdown looks broken."""
    b, sd = _body("share"), _src("nocturne/ui/share_dialog.py")
    assert "Matte" in b and "annotations" in b.lower()
    assert '"matte" if self._annotations_on' in sd
    assert "steps aside" in b and "if self._placement_touched" in sd


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


def test_clipping_help_describes_the_readout_that_ships():
    """The help names the two arrows, the per-number amber, the tooltip
    qualifiers and the toggle beside the numbers — each checked against the
    code that draws them, so a later redesign has to update both."""
    b = _body("readout")
    sp = _src("nocturne/ui/side_panel.py")
    mw = _src("nocturne/ui/main_window.py")
    assert "▼" in b and "▲" in b and '("▼"' in sp and '("▲"' in sp
    assert "crushed to black" in b and "Crushed to black" in sp
    assert "blown to white" in b and "Blown to white" in sp
    assert "only that number, never the" in b and "WARNING" in sp
    assert "crushed on import" in b and "on import" in mw
    assert "scattered noise" in b.lower() and "Scattered noise, not lost detail" in mw
    assert "beside the numbers" in b and 'QPushButton("Show clipping")' in sp
    assert "The clipping line" not in b and "Tick <b>Show clipping" not in b


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
    """The Color topic described only calibration and De-green Sky.

    Two sliders were added to that panel and the help would happily have gone on
    describing the old one — the exact drift this file exists to catch. Pin the
    slider labels to the widgets, so renaming one fails here.
    """
    b = _body("color")
    sp = _src("nocturne/ui/step_panels.py")
    # "Apply Color", not "Apply Tint": since 2026-09-25 (consistent panels) the
    # step shows ONE Apply that commits the method and the tint together; the
    # tint's own button still exists but is hidden, so naming it sends the
    # user looking for a button they cannot see.
    for label in ("Green ←→ Magenta", "Cool ←→ Warm", "Apply Color"):
        assert label in b, f"the help never mentions {label!r}"
        assert label in sp, f"{label!r} is no longer in the Color panel"
    assert "Apply Tint" not in b, "the help names the hidden Apply Tint button"


def test_colour_help_gets_the_order_of_operations_right():
    """Calibrate, then nudge. This is the order Andreas asked for, it is what
    PROCESSING_ORDER does, and the help must not describe a different one — a
    user following the wrong order re-runs the calibration and wonders why
    their tint vanished.
    """
    from nocturne.ui.pipeline import PROCESSING_ORDER
    b = _body("color")
    assert PROCESSING_ORDER.index("color") < PROCESSING_ORDER.index("tint")
    # the prose must present them in that same order
    assert b.index("1 — Calibrate") < b.index("2 — Nudge")


def test_remove_green_help_sits_after_stretch_and_says_why():
    """De-green Sky moved off the Color panel onto its own stage, right after
    Stretch — the whole point being that the green cast it fixes is CREATED by
    the stretch, so judging whether you need it before Stretch has run is
    judging a problem that does not exist yet. Guard both the order and the
    topic's own explanation of it.
    """
    from nocturne.ui.pipeline import PROCESSING_ORDER
    assert PROCESSING_ORDER.index("stretch") < PROCESSING_ORDER.index("remove_green")
    b = _body("remove_green")
    assert "after" in b.lower() and "stretch" in b.lower()
    assert "created" in b.lower() or "creates" in b.lower()
    # Color's own topic must point forward to the new home, not still teach it
    color_b = _body("color")
    assert "3 — De-green Sky" not in color_b
    assert "De-green Sky" in color_b


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
    assert "<b>Combine</b>" in b and 'add_group("Combine"' in hd
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
    # Green-only and blue-only must each land strictly between 0 and 1: OIII is a
    # combination of the two, so a green-only or blue-only OIII would read 1.0 or
    # 0.0 here. They are combined by SNR rather than evenly — green comes from
    # twice the sites and measures the line better — so green carries the larger
    # share, but blue must still count for something.
    from nocturne.stacking.haoiii import _OIII_GREEN_WEIGHT as W
    green_only = extract_cfa_planes(cfa(0.0, 1.0, 0.0), "RGGB")[1].mean()
    blue_only = extract_cfa_planes(cfa(0.0, 0.0, 1.0), "RGGB")[1].mean()
    assert green_only == pytest.approx(W / (W + 1.0), abs=1e-3)
    assert blue_only == pytest.approx(1.0 / (W + 1.0), abs=1e-3)
    assert 0.0 < blue_only < green_only < 1.0, (
        "OIII must draw on both, with green weighted higher")
    assert green_only + blue_only == pytest.approx(1.0, abs=1e-3), (
        "the weights must be a proper average, not a gain")


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
    which makes it easy to describe controls it does not have. Strictness and the
    framing checkbox were exactly that for a while — described as absent, then
    added — so pin each one to the widget that draws it, in both directions."""
    import inspect

    from nocturne.stacking.coverage import full_coverage_bounds
    from nocturne.stacking.grade import grade_frames
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    from nocturne.ui.haoiii_dialog import KAPPA
    b = _body("haoiii")
    hd = _src("nocturne/ui/haoiii_dialog.py")

    assert "strictness_box" in hd, "the dialog lost its Strictness control"
    assert "<b>Strictness</b>" in b, "Strictness is not described"
    assert inspect.signature(grade_frames).parameters["strictness"].default == "normal"

    assert "crop_check" in hd, "the dialog lost its trim checkbox"
    assert "<b>Trim the ragged edges</b>" in b, "the trim checkbox is not described"
    # frac=0.9 is why the help says NEARLY every frame, not every frame
    assert inspect.signature(full_coverage_bounds).parameters["frac"].default == 0.9
    assert "nearly every frame covered" in b

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
    from nocturne.core.image import AstroImage
    from nocturne.core.narrowband import (OFFERED_PALETTES, PALETTES, RETIRED_PALETTES,
                                          NarrowbandParams, _combine, render)
    from nocturne.recipe import _NAME_TO_STAGE
    from nocturne.ui.narrowband_dialog import PALETTES as UI_PALETTES
    b = _body("narrowband")
    nd = _src("nocturne/ui/narrowband_dialog.py")

    # two palette lists, one truth: the help is checked against the core one
    assert list(UI_PALETTES) == list(OFFERED_PALETTES), "the dialog and the engine disagree"
    ha = np.linspace(0.1, 0.9, 64).reshape(8, 8).astype(np.float32)
    oiii = np.linspace(0.9, 0.1, 64).reshape(8, 8).astype(np.float32)
    img = AstroImage(np.stack([ha, oiii, oiii], axis=2), is_linear=False)
    for palette in OFFERED_PALETTES:
        assert palette in b, f"palette {palette!r} is not described"
    for palette in PALETTES:   # retired ones too: old projects replay them
        render(img, NarrowbandParams(palette=palette))
    for palette in RETIRED_PALETTES:
        assert palette not in b, f"retired palette {palette!r} is still in the help"
    with pytest.raises(ValueError):
        _combine(ha, oiii, "SHO", 0.6)            # the help says SHO is not available
    assert "no sulfur" in b

    for row in ("Oxygen strength", "Green blend", "Protect background", "Saturation",
                "Brightness"):
        assert row in b, f"the help never mentions {row!r}"
        assert f'controls.addRow("{row}"' in nd, f"{row!r} is no longer a control"
    assert "Preserve lightness" in b and 'QCheckBox("Preserve lightness' in nd
    assert "Reset" in b and 'QPushButton("Reset")' in nd
    assert "Apply" in b and 'QPushButton("Apply")' in nd
    # Both tools, because both work since 2026-09-18 — the help said only
    # StarXTerminator, which stopped being true the hour StarNet2 landed.
    assert "StarXTerminator" in b and "StarNet2" in b
    assert "preferred_splitter" in nd
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
    from nocturne.core.narrowband import GOLD_BLUE
    b = _body("narrowband")
    d = NarrowbandDialog(Settings(), AstroImage(np.zeros((8, 8, 3), np.float32),
                                                is_linear=False))
    qtbot.addWidget(d)
    p = d._params()

    assert p.palette == GOLD_BLUE and f"<b>{GOLD_BLUE}</b> — the dialog opens on this one" in b
    assert p.oxygen_strength == 0.60 and d.oxygen_val.text() == "60%"
    assert p.protect_background == 0.2 and d.protect_val.text() == "20%"
    assert "Oxygen strength (default 60% in SHO-style, ×0.85 in the others)" in b
    assert "Protect background (default 20% in SHO-style, 40% in the others)" in b
    assert p.brightness == 1.0 and d.bright_val.text() == "×1.00"
    assert "Brightness (default ×1.00)" in b
    assert p.blend_amount == 0.6 and d.blend_val.text() == "0.60"
    assert "Green blend — HOO only (default 0.60)" in b
    assert p.saturation == 0.85 and d.sat_val.text() == "0.85"
    assert "Saturation — HOO and Pseudo-SHO (default 0.85)" in b
    assert (p.gold_strength, p.blue_strength) == (1.0, 1.0)
    assert d.gold_val.text() == d.blue_val.text() == "100%"
    assert "Gold and Blue — SHO-style only (default 100%)" in b
    d.gold_slider.setValue(0)
    d.blue_slider.setValue(d.blue_slider.maximum())
    assert (d.gold_val.text(), d.blue_val.text()) == ("0%", "200%")
    assert "0% leaves that colour grey, and 200% doubles it" in b
    # Measured on his frames (review 2026-10-10): Gold 200% gives x1.1-1.7 of
    # the 100% chroma; the fixture below reads inside that band.
    assert "between about 1.1 and 1.7 times as strong" in b
    assert "keeps its colour rather than turning orange" in b
    assert d.lightness_check.isChecked() is False
    assert "Preserve lightness — off by default" in b

    # the others, reached by switching with nothing touched
    d.palette_box.setCurrentText("HOO")
    p = d._params()
    assert p.oxygen_strength == 0.85 and d.oxygen_val.text() == "×0.85"
    assert p.protect_background == 0.4 and d.protect_val.text() == "40%"

    d.oxygen_slider.setValue(d.oxygen_slider.maximum())
    assert d.oxygen_val.text() == "×2.00", "the oxygen strength range moved"
    assert "toward ×2.00" in b


def test_narrowband_help_warns_that_green_blend_is_inert_outside_hoo():
    """The control the user is most likely to read as broken: it is live in HOO
    and does nothing at all in the other two palettes, because only HOO builds a
    synthetic green."""
    from nocturne.core.image import AstroImage
    from nocturne.core.narrowband import (GOLD_BLUE, OFFERED_PALETTES, PALETTES_USING_BLEND,
                                          NarrowbandParams, _combine, render)
    b = _body("narrowband")
    # The slider is greyed out there now, so the help must say THAT rather than
    # "the slider moves and the picture does not", which stopped being true.
    assert "greyed out in Pseudo-SHO and SHO-style (gold and blue)" in b
    for palette in OFFERED_PALETTES:
        if palette not in PALETTES_USING_BLEND:
            assert palette in b, f"the help must name {palette} as one where it is inert"
    rng = np.random.default_rng(11)
    ha = rng.random((16, 16)).astype(np.float32)
    oiii = rng.random((16, 16)).astype(np.float32)

    def differs(palette):
        low = _combine(ha, oiii, palette, 0.0)
        high = _combine(ha, oiii, palette, 1.0)
        return any(not np.allclose(x, y) for x, y in zip(low, high))

    assert differs("HOO"), "Green blend no longer does anything in HOO either"
    assert not differs("Pseudo-SHO"), "Pseudo-SHO now uses the blend; update the help"
    img = AstroImage(np.stack([ha, oiii, oiii], axis=2), is_linear=False)
    lo, hi = (render(img, NarrowbandParams(palette=GOLD_BLUE, blend_amount=a)).data
              for a in (0.0, 1.0))
    assert np.array_equal(lo, hi), "SHO-style now uses the blend; update the help"


def test_narrowband_help_is_right_about_gold_and_blue_and_lightness(qtbot):
    """Preserve lightness is greyed for SHO-style because that palette always
    keeps the picture's lightness — measured, not trusted — and the help says
    what a palette switch does to the sliders, which the dialog decides."""
    from nocturne.core.image import AstroImage
    from nocturne.core.narrowband import GOLD_BLUE, NarrowbandParams, render
    from nocturne.settings import Settings
    from nocturne.ui.narrowband_dialog import NarrowbandDialog
    b = _body("narrowband")
    assert "Greyed out in <b>SHO-style (gold and blue)</b>" in b
    rng = np.random.default_rng(3)
    img = AstroImage(rng.random((24, 24, 3)).astype(np.float32), is_linear=False)
    off, on = (render(img, NarrowbandParams(palette=GOLD_BLUE, lightness_preserve=v)).data
               for v in (False, True))
    assert np.array_equal(off, on), "SHO-style now honours Preserve lightness; update the help"
    assert "no sulfur" in b and "SHO-style" in b

    # Gold and Blue: each scales its own colour — 0% grey, 200% double —
    # and neither moves the line between them (only Oxygen strength does).
    assert "It is not shown in <b>SHO-style (gold and blue)</b>" in b
    assert "that is <b>Oxygen strength</b>'s job alone" in b
    assert "never the other colour" in b
    from nocturne.core.narrowband import _srgb_to_oklab
    ha = np.full((60, 120), 0.05, np.float32); oiii = np.full((60, 120), 0.04, np.float32)
    ha[10:50, 5:55], oiii[10:50, 5:55] = 0.75, 0.10
    ha[10:50, 65:115], oiii[10:50, 65:115] = 0.10, 0.75
    framed = AstroImage(np.stack([ha, oiii, oiii], axis=2), is_linear=False)

    def lab_of(**kw):
        out = render(framed, NarrowbandParams(palette=GOLD_BLUE, protect_background=0.0,
                                              **kw), has_stars=False)
        return _srgb_to_oklab(out.data[15:45])

    def chroma(lab, cols):
        return float(np.hypot(lab[:, cols, 1], lab[:, cols, 2]).mean())
    gold_side, blue_side = slice(10, 50), slice(70, 110)
    base = lab_of()
    assert (base[:, gold_side, 2] > 0.01).all() and (base[:, blue_side, 2] < -0.01).all()
    for g, bl in ((0.0, 2.0), (2.0, 0.0), (0.5, 0.5), (2.0, 2.0)):
        lab = lab_of(gold_strength=g, blue_strength=bl)
        for cols, k, want_sign in ((gold_side, g, 1), (blue_side, bl, -1)):
            ratio = chroma(lab, cols) / chroma(base, cols)
            if cols is gold_side and k == 2.0:
                # bright gold is near sRGB's edge already at 100% (x1.25 since
                # 2026-10-10) and is fitted back without a hue change: it grows
                # a little, far less than 2x, and stays the same gold
                assert 1.03 < ratio < 1.75, (g, bl, ratio)
                hue = np.degrees(np.arctan2(lab[:, cols, 2], lab[:, cols, 1]))
                hue0 = np.degrees(np.arctan2(base[:, cols, 2], base[:, cols, 1]))
                assert abs(float(np.median(hue - hue0))) < 1.0, "gold turned another colour"
            else:
                assert abs(ratio - k) < 0.05, (g, bl, ratio)
            if k > 0:      # still on its own side: no gas moved
                assert (np.sign(lab[:, cols, 2]) == want_sign).all(), (g, bl)
    oxy = [float((lab_of(oxygen_strength=o)[..., 2] < -1e-3).mean()) for o in (0.6, 1.4)]
    assert oxy == sorted(oxy) and oxy[1] >= oxy[0], "Oxygen strength should still move the line"

    assert "leaves one you have moved where you put it" in b
    d = NarrowbandDialog(Settings(), img)
    qtbot.addWidget(d)
    d.oxygen_slider.setValue(130)
    d.palette_box.setCurrentText("HOO")
    assert d.oxygen_slider.value() == 130 and d.protect_slider.value() == 40


def test_narrowband_help_describes_the_palettes_and_the_green_cap_correctly():
    """Which gas lands in which channel is the whole content of a palette, and
    green is clamped in HOO and Pseudo-SHO — the help says so. Pseudo-bicolor
    is retired, so the help no longer describes it at all."""
    from nocturne.core.narrowband import _combine
    b = _body("narrowband")
    rng = np.random.default_rng(13)
    ha = rng.random((16, 16)).astype(np.float32)
    oiii = rng.random((16, 16)).astype(np.float32)

    assert "bicolor" not in b.lower(), "a retired palette is still in the help"

    for palette in ("HOO", "Pseudo-SHO"):
        r, g, bl = _combine(ha, oiii, palette, 1.0)
        assert np.all(g <= (r + bl) / 2.0 + 1e-6), f"{palette} lost its green cap"
    # and the cap is a real constraint, not a coincidence of the fixture
    r, g, bl = _combine(ha, oiii, "HOO", 1.0, scnr=False)
    assert np.any(g > (r + bl) / 2.0 + 1e-6)
    assert "capped at the average of red and blue" in b


def test_narrowband_help_gets_the_direction_of_the_two_headline_sliders_right():
    """Both could be described backwards and still read plausibly. Higher OIII
    boost must lift the oxygen further; higher Protect background must leave
    MORE of the sky alone."""
    from nocturne.core.narrowband import nebula_mask, normalize_to_reference
    b = _body("narrowband")
    rng = np.random.default_rng(17)
    ha = np.clip(0.45 + 0.08 * rng.standard_normal((96, 96)), 0, 1).astype(np.float32)
    oiii = np.clip(0.08 + 0.02 * rng.standard_normal((96, 96)), 0, 1).astype(np.float32)
    # The direction lives in oxygen_strength now; matching is undistorted and
    # takes no look parameter at all.
    from nocturne.core.narrowband import brightness
    matched = normalize_to_reference(oiii, ha, 1.0)
    levels = [float(brightness(matched, s).mean()) for s in (0.3, 1.0, 2.0)]
    assert levels[0] < levels[1] < levels[2], "Oxygen strength no longer runs upward"
    assert float(oiii.mean()) < float(matched.mean()), \
        "matching no longer lifts the oxygen to the hydrogen's level"
    assert "×1.00 is the matched point" in b
    assert "Below ×1.00 leans toward hydrogen" in b

    rgb = np.dstack([ha, oiii, oiii])
    masks = [float(nebula_mask(rgb, p).mean()) for p in (0.0, 0.4, 1.0)]
    assert masks[0] > masks[1] > masks[2], "Protect background is inverted"
    assert "higher setting protects more" in b     # sentence case may vary


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
        "OIII is no longer the even average of green and blue"

    # Route 2: out of the raw Bayer grid. Same convention — Ha from red, OIII
    # from green AND blue — but the two are combined by SNR here, not evenly,
    # because at the CFA stage we know green came from twice as many sites and
    # measures the line better. Narrowband sees an already-interpolated image
    # and keeps the even split; whether it should is an open question in TODO.
    from nocturne.stacking.haoiii import _OIII_GREEN_WEIGHT as W
    cfa = np.zeros((8, 8), np.float32)
    cfa[0::2, 0::2] = 1.0                      # RGGB red sites
    cfa[0::2, 1::2] = cfa[1::2, 0::2] = 0.4    # green sites
    cfa[1::2, 1::2] = 0.6                      # blue site
    ha2, oiii2 = extract_cfa_planes(cfa, "RGGB")
    assert ha2.mean() == pytest.approx(1.0, abs=1e-3)
    assert oiii2.mean() == pytest.approx((W * 0.4 + 0.6) / (W + 1.0), abs=1e-3)
    # both sites must still reach it — "OIII is the blue channel" is the error
    # this guard exists to catch
    assert 0.4 < oiii2.mean() < 0.6, "OIII must draw on green AND blue"


def test_dualband_help_is_right_that_sho_is_unavailable_and_names_the_real_palettes():
    from nocturne.core.narrowband import OFFERED_PALETTES, _combine
    b = _body("dualband")
    ha = np.linspace(0.1, 0.9, 64).reshape(8, 8).astype(np.float32)
    oiii = np.linspace(0.9, 0.1, 64).reshape(8, 8).astype(np.float32)
    with pytest.raises(ValueError):
        _combine(ha, oiii, "SHO", 0.6)
    assert "SHO is not offered anywhere in Nocturne" in b
    for palette in OFFERED_PALETTES:
        assert f"<b>{palette}</b>" in b, f"the topic does not name the {palette!r} palette"


def test_dualband_help_says_which_auto_enhance_preset_applies_a_palette():
    """A user who taps Auto Enhance on dualband data and gets a red-gold image
    needs to know that is the design, and that Gold and blue is the preset
    that finishes with the palette."""
    from nocturne.core.auto_enhance import build_auto_plan, detect_data_type
    from nocturne.core.image import AstroImage
    from nocturne.settings import Settings
    b = _body("dualband")
    assert "no palette in <b>Auto " not in b
    assert "Natural and Vivid presets leave dualband data red-gold" in b
    assert "<b>Gold and blue</b> preset, offered only on LP data" in b
    img = AstroImage(np.full((32, 32, 3), 0.3, np.float32), is_linear=True,
                     metadata={"filter": "LP"})
    for preset in ("natural", "vivid"):
        stages = [stage for stage, _ in build_auto_plan(img, Settings(), preset=preset)]
        assert stages and "narrowband" not in stages, f"{preset} now applies a palette"
    assert [s for s, _ in build_auto_plan(img, Settings(), preset="gold_blue")][-1] == "narrowband"
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
    from nocturne.ui.pipeline import ENHANCE_NAMES, PROCESSING_ORDER, STEP_NAME
    b = _body("recipes")
    # Every step the help must name — PROCESSING_ORDER rather than
    # path_stages(), which would drop `tint`: a real, documented control that
    # is part of the Colour step rather than a stage of its own.
    for stage in PROCESSING_ORDER:
        assert STEP_NAME[stage] in b, \
            f"the topic never mentions the {STEP_NAME[stage]!r} step"
    for name in ("Crop", "Rotate", "Flip", "Narrowband", "Colour Balance"):
        assert name in b
    # Pinned to the REGISTRY, not to a hard-coded number: the help said "all
    # ten" while the panel shipped eleven, and a literal 10 on both sides let
    # that agree with itself and disagree with the app.
    _WORDS = {10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen"}
    assert f"all {_WORDS[len(ENHANCE_NAMES)]} <b>Enhancements</b>" in b, \
        f"the help does not say there are {len(ENHANCE_NAMES)} enhancements"
    assert not uncaptured_step_names([(n, "") for n in ENHANCE_NAMES]), \
        "the taps are no longer captured; the help says they are"

    every = [(n, "") for n in list(_NAME_TO_STAGE) + list(ENHANCE_NAMES)
             + ["Star Spikes", "Starless Levels", "Trim"]]
    assert uncaptured_step_names(every) == ["Star Spikes", "Starless Levels", "Trim"], \
        "the set of steps a recipe drops changed; the help names these three"
    assert "<b>Star Spikes</b>, <b>Starless Levels</b> and <b>Trim</b>" in b
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
    """Only FITS is picked up, and only from the folder itself. Pointing Batch at
    a folder of TIFFs used to get "0/0" and no explanation; it is now refused
    before the run, and the help has to describe THAT, not the old report."""
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
    assert "0/0" not in b, "the help still promises a 0/0 report Batch no longer gives"
    assert "stops before it starts" in b, "the help never says the run is refused"
    assert "No images to process in" in _src("nocturne/ui/batch_dialog.py"), \
        "the refusal the help describes is not the one the dialog shows"


def test_recipes_help_warns_that_an_existing_output_is_overwritten(tmp_path):
    """The output is the input's stem plus the format's extension, written with
    no prompt over whatever is already there — which is why the help says to
    give the output a folder of its own."""
    from nocturne.batch import run_batch
    from nocturne.core.export import save_fits
    from nocturne.core.image import AstroImage
    from nocturne.recipe import Recipe
    from nocturne.settings import Settings
    b = _body("recipes")
    assert "<b>Give the output a folder of its own</b>" in b
    assert "overwritten without asking" in b
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    save_fits(AstroImage(np.full((16, 16, 3), 0.3, np.float32), is_linear=True),
              str(src / "m42.fits"))
    (out / "m42.tiff").write_bytes(b"stale")
    before = (out / "m42.tiff").read_bytes()
    results = run_batch(Recipe(steps=[{"stage": "levels", "option": [0.0, 1.0, 1.0]}]),
                        [str(src / "m42.fits")], str(out), "TIFF", Settings())
    assert results[0]["ok"], results[0]["message"]
    assert (out / "m42.tiff").read_bytes() != before, \
        "batch no longer overwrites an existing output; the help says it does"

    # ... and the one collision that IS refused, per file, master untouched
    master = (src / "m42.fits").read_bytes()
    results = run_batch(Recipe(steps=[{"stage": "levels", "option": [0.0, 1.0, 1.0]}]),
                        [str(src / "m42.fits")], str(src), "FITS", Settings())
    assert results[0]["ok"] is False and "overwrite the source" in results[0]["message"]
    assert (src / "m42.fits").read_bytes() == master, "the source master was written over"
    assert "refuses outright is writing over the source itself" in b


def test_recipes_help_explains_why_a_whole_batch_can_fail_identically(tmp_path):
    """Batch has no per-stage resilience: a step whose external tool is missing
    fails the entire file, with an OS-level message. Every file then fails the
    same way, which reads as broken data. The complement matters as much — the
    tool-backed steps that DO fall back must not be blamed for it."""
    from nocturne.batch import run_batch
    from nocturne.core.export import save_fits
    from nocturne.core.image import AstroImage
    from nocturne.recipe import Recipe, missing_tools
    from nocturne.settings import Settings
    b = _body("recipes")
    assert "it fails the whole file, not just" in b and "<b>Settings</b>" in b
    save_fits(AstroImage(np.full((16, 16, 3), 0.3, np.float32), is_linear=True),
              str(tmp_path / "m42.fits"))
    results = run_batch(Recipe(steps=[{"stage": "background", "option": "strong"}]),
                        [str(tmp_path / "m42.fits")], str(tmp_path), "TIFF",
                        Settings())              # nothing installed
    assert results[0]["ok"] is False, \
        "a missing GraXpert no longer fails the file; the help says it does"
    assert not (tmp_path / "m42.tiff").exists(), "a failed file wrote output anyway"

    # every OTHER tool-backed step survives without its tool, on the free
    # fallbacks — the help says so, and a gate must never widen past this
    for stage, option in (("saturation", [0.5, 0.2]), ("green_fringe", 1.0),
                          ("noise_sharpen", "strong"), ("star_reduction", 0.3),
                          ("local_contrast", 0.15)):
        r = run_batch(Recipe(steps=[{"stage": stage, "option": option}]),
                      [str(tmp_path / "m42.fits")], str(tmp_path), "TIFF", Settings())
        assert r[0]["ok"], f"{stage} no longer falls back: {r[0]['message']}"
    assert "fall back to Nocturne’s own free" in b


def test_recipes_help_is_right_that_run_is_gated_on_the_recipe(qtbot, tmp_path):
    """The help promises a greyed-out Run naming the missing tool. Gated on the
    RECIPE, not on the Batch button: a recipe needing nothing must stay runnable
    with nothing installed, or the gate punishes people for a step they never
    used."""
    from nocturne.recipe import Recipe, save_recipe
    from nocturne.settings import Settings
    from nocturne.ui.batch_dialog import BatchDialog
    b = _body("recipes")
    assert "<b>Run is greyed out</b>" in b
    needs_gx, plain = tmp_path / "bg.json", tmp_path / "plain.json"
    save_recipe(Recipe(steps=[{"stage": "background", "option": "strong"},
                              {"stage": "stretch", "option": 0.3}]), str(needs_gx))
    save_recipe(Recipe(steps=[{"stage": "stretch", "option": 0.3}]), str(plain))

    d = BatchDialog(Settings())                  # nothing installed
    qtbot.addWidget(d)
    assert d.run_btn.isEnabled(), "Batch is gated as a whole; only the recipe may gate it"

    d.recipe_edit.setText(str(needs_gx))
    assert d.run_btn.isEnabled() is False
    assert "GraXpert" in d.status.text() and "GraXpert" in d.run_btn.toolTip()
    ran = []
    d._batch_runner = lambda *a, **k: ran.append(True) or []
    d.output_edit.setText(str(tmp_path))
    d.run()                     # bypassing the button, as a shortcut or a script would
    assert ran == [], "a blocked recipe still started a run"

    d.recipe_edit.setText(str(plain))            # needs nothing -> runnable
    # The status line is no longer empty for a runnable recipe: since 2026-09-02
    # it says what the recipe WILL do, because "not blocked" is not the same as
    # "will do what you saved". What matters here is that nothing blocks it.
    assert d.run_btn.isEnabled()
    assert "GraXpert" not in d.status.text() and "cannot run" not in d.status.text()
    assert "Only a step that <i>cannot run at all</i> stops you" in b

    bad = tmp_path / "notes.json"                # not a recipe at all
    bad.write_text("this is not json", encoding="utf-8")
    d.recipe_edit.setText(str(bad))
    assert d.run_btn.isEnabled() is False and "isn't a Nocturne recipe" in d.status.text()

    d.recipe_edit.setText(str(plain))            # and it recovers
    assert d.run_btn.isEnabled()


def test_missing_tools_names_only_the_step_that_cannot_run_at_all():
    """The pre-flight check behind gating Batch's Run button. It must stay
    narrow: a recipe that merely WOULD BE better with RC-Astro has to remain
    runnable, or the gate stops being a fact and becomes an opinion."""
    from nocturne.recipe import Recipe, missing_tools
    from nocturne.settings import Settings
    bare = Settings()
    assert missing_tools(Recipe(steps=[{"stage": "background", "option": "strong"}]),
                         bare) == ["GraXpert"]
    assert missing_tools(Recipe(steps=[{"stage": "background", "option": "off"}]),
                         bare) == [], "an off Background needs no tool"
    assert missing_tools(Recipe(steps=[{"stage": "background", "option": "strong"}]),
                         Settings(graxpert_path=_RUNNABLE)) == []
    for stage in ("saturation", "green_fringe", "noise_sharpen", "star_reduction",
                  "deconvolution", "narrowband", "stretch", "levels", "curves"):
        assert missing_tools(Recipe(steps=[{"stage": stage, "option": ""}]), bare) == [], \
            f"{stage} is not a hard requirement; it falls back to a free implementation"
    # one entry per tool, however many steps ask for it
    assert missing_tools(Recipe(steps=[{"stage": "background", "option": "strong"},
                                       {"stage": "background", "option": "light"}]),
                         bare) == ["GraXpert"]


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
    qtbot.waitUntil(lambda: d._stars is not None, timeout=8000)   # detection is async

    rows = {"Length (off → long)": (d.length_slider, d.length_val),
            "Intensity (faint → full)": (d.intensity_slider, d.intensity_val),
            "Number of stars": (d.stars_slider, d.stars_val),
            "Rotation": (d.angle_slider, d.angle_val)}
    for label in rows:
        assert f'_row("{label}"' in sd, f"{label!r} is no longer a row"
        assert f"<b>{label}</b>" in b, f"the topic never names the {label!r} slider"

    # ...and every OTHER row too, read off the source rather than this list.
    # Two sliders were added and the whole suite stayed green while the help said
    # nothing about them, which is the same hole the narrowband guard had.
    import re
    for label in re.findall(r'_row\(\s*"([^"]+)"', sd):
        assert f"<b>{label}</b>" in b, f"the topic never names the {label!r} slider"

    assert (d.length_slider.minimum(), d.length_slider.maximum()) == (0, 100)
    assert d.length_slider.value() == 0 and d.length_val.text() == "0.00"
    assert "default <b>0.00</b>, range 0.00 to 1.00" in b
    assert (d.intensity_slider.minimum(), d.intensity_slider.maximum()) == (0, 100)
    assert d.intensity_slider.value() == 100 and d.intensity_val.text() == "100%"
    assert "default <b>100%</b>, range 0 to 100%" in b
    # The star count's ceiling is _MAX_STARS, but the dialog lowers it to however
    # many stars this image actually has — so read the ceiling from the constant
    # and the instance's own max from the fixture, which holds only a few.
    from nocturne.core.star_spikes import _MAX_STARS
    assert d.stars_slider.minimum() == 0
    assert d.stars_slider.maximum() == min(_MAX_STARS, len(d._stars))
    assert d.stars_slider.value() == min(6, d.stars_slider.maximum())
    assert f"default <b>6</b>, range 0 to {_MAX_STARS}" in b
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
    """Every control the topic names is one the dialog has, and every number it
    quotes is formatted from the constant, not copied."""
    from nocturne.core.share import ASPECTS
    from nocturne.core.upscale import (MAX_OUTPUT_MP, RAM_SHARE, TIGHTEN_DEFAULT,
                                       upscale_limit_mp)
    from nocturne.ui.upscale_dialog import SCALE
    b = _body("upscale")
    d = _upscale_dialog(qtbot)

    assert SCALE == 2 and "<b>twice the size</b>" in b
    for label, widget in (("Upscale 2\u00d7", d.upscale_btn), ("Side by side", d.mode_side),
                          ("Wipe", d.mode_wipe), ("Change crop", d.change_crop_btn),
                          ("Cancel", d.cancel_btn), ("Export\u2026", d._export_btn),
                          ("Open as copy", d._open_copy_btn)):
        assert f"<b>{label}</b>" in b, f"the topic never names {label}"
        assert label in widget.text(), f"{label!r} is no longer a control"
    for name in ("Shape", "Size", "Navigator", "Star tightening"):
        assert f"<b>{name}</b>" in b
    for shape, _r in ASPECTS:
        assert shape in d.shape_buttons
        assert shape in b, f"the topic never lists the {shape} shape"
    # The limit follows the machine's memory: every figure the help quotes is
    # the one the code computes for that memory.
    assert f"<b>{round(RAM_SHARE * 100)}% of the installed memory</b>" in b
    assert f"<b>{MAX_OUTPUT_MP} megapixels</b> at most" in b
    for gb in (8, 16, 32):
        assert f"up to about {upscale_limit_mp(gb * 2**30)}&nbsp;MP" in b, gb
    assert upscale_limit_mp(16 * 2**30) >= 34, "16 GB must fit a whole S30 Pro frame (33 MP)"
    assert TIGHTEN_DEFAULT == 0.35 and "the default is 0.35" in b
    assert d.tighten_slider.value() == round(TIGHTEN_DEFAULT * 100)
    assert "Enlarging adds <b>no detail</b>" in b

    assert d._export_btn.isEnabled() is False and d._open_copy_btn.isEnabled() is False
    assert "stay disabled until you have run <b>Upscale</b> once" in b
    d._run_upscale()
    assert d._export_btn.isEnabled() and d._open_copy_btn.isEnabled()
    assert d._result.data.shape == (120, 120, 3), "the scale is no longer 2x"
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
    assert "<b>your edit history is gone</b>" in b and "<b>save first</b>" in b
    assert "Nocturne asks first and offers" in b, \
        "the app now prompts before discarding unsaved edits; the help must say so"

    path = tmp_path / "stack.fits"
    fits.PrimaryHDU((np.random.rand(3, 24, 24) * 1000).astype(np.uint16)).writeto(str(path))
    win = MainWindow(settings_path=str(tmp_path / "settings.json"), check_updates=False, telemetry=False)
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
    report = (tmp_path / "out.txt").read_text(encoding="utf-8")

    assert upscale_filename("m42.fits", 2) == "m42_2x.jpg" and "yourfile_2x.jpg" in b
    for claim in ("Lanczos", "2×", "m42.fits", "M42", "Star tightening: 0.35"):
        assert claim in report, f"the sidecar no longer records {claim!r}"
    assert "the crop and the star tightening" in b
    assert report.rstrip().endswith("presentation derivative — enlarged, no synthesized detail."), \
        "the help says the file ENDS on that sentence"
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


@pytest.fixture
def _no_nr_models(monkeypatch):
    from nocturne.core import nr_models
    monkeypatch.setattr(nr_models, "available", lambda: [])


def test_auto_enhance_help_lists_the_plan_that_is_actually_built(_no_nr_models):
    """The topic said "background, colour, stretch, and finishing polish" and
    quoted not one value. Pin every stage and every constant to build_auto_plan,
    per preset, including the stages that depend on what is installed."""
    from nocturne.core.auto_enhance import (
        AUTO_BACKGROUND_STRENGTH, AUTO_DECONVOLUTION, AUTO_DENOISE_STRONG, AUTO_GREEN_FRINGE,
        AUTO_LOCAL_CONTRAST, AUTO_SATURATION_AMOUNT, AUTO_SATURATION_NEBULA,
        AUTO_SATURATION_NEBULA_DUALBAND, AUTO_STAR_REDUCTION, AUTO_STRETCH_AMOUNT,
        GOLD_BLUE_STAR_REDUCTION, VIVID_LOCAL_CONTRAST, VIVID_SATURATION,
        VIVID_STAR_REDUCTION, VIVID_STRETCH_AMOUNT, build_auto_plan)
    from nocturne.core.image import AstroImage
    from nocturne.core.levels import _BLACK_SIGMA
    from nocturne.settings import Settings
    from nocturne.steps.noise_sharpen import FREE
    from nocturne.ui.pipeline import STEP_NAME
    from nocturne.ui.step_panels import STRETCH_DEFAULT
    b = _body("auto-enhance")
    img = AstroImage(np.full((32, 32, 3), 0.3, np.float32), is_linear=True)
    lp = AstroImage(img.data, is_linear=True, metadata={"filter": "LP"})

    # Auto Enhance runs from the user's crop, so the plan it uses omits crop.
    plan = dict(build_auto_plan(img, Settings(), include_crop=False))
    assert list(plan) == ["color", "stretch", "levels", "saturation", "green_fringe",
                          "noise_sharpen", "local_contrast", "star_reduction"], "the plan changed"
    for stage in plan:
        assert f"<b>{STEP_NAME[stage]}</b>" in b, f"the topic never names {STEP_NAME[stage]!r}"

    # Every number below is FORMATTED FROM the constant, never compared to a
    # copy of it: asserting plan["stretch"] == AUTO_STRETCH_AMOUNT passes happily
    # while both move away from the prose, which is the failure this file exists
    # to catch.
    assert plan["stretch"]["amount"] == AUTO_STRETCH_AMOUNT   # versioned dict since 2026-10-11
    assert AUTO_STRETCH_AMOUNT == STRETCH_DEFAULT / 100.0, (
        "the help says these are the same; make them so, or reword it")
    assert f"<b>{AUTO_STRETCH_AMOUNT:.2f}</b>, the same as the manual" in b
    assert plan["saturation"] == (AUTO_SATURATION_AMOUNT, AUTO_SATURATION_NEBULA)
    assert f"<b>{AUTO_SATURATION_AMOUNT:.2f}</b> with a light " \
           f"<b>{AUTO_SATURATION_NEBULA:.2f}</b> nebula boost " \
           f"(<b>{AUTO_SATURATION_NEBULA_DUALBAND:.2f}</b> on dual-band data)" in b
    assert dict(build_auto_plan(lp, Settings(), include_crop=False))["saturation"] == \
        (AUTO_SATURATION_AMOUNT, AUTO_SATURATION_NEBULA_DUALBAND)
    assert plan["local_contrast"] == AUTO_LOCAL_CONTRAST
    assert f"<b>{AUTO_LOCAL_CONTRAST:.2f}</b>, a light" in b
    assert plan["star_reduction"] == AUTO_STAR_REDUCTION
    assert f"<b>Star Reduction</b> at <b>{AUTO_STAR_REDUCTION:.2f}</b>" in b
    assert plan["green_fringe"] == AUTO_GREEN_FRINGE == 1.0 and "De-green Stars</b> on" in b
    assert plan["noise_sharpen"]["level"] == AUTO_DENOISE_STRONG
    assert f"at <i>{AUTO_DENOISE_STRONG}</i>, always" in b
    assert plan["noise_sharpen"]["engine"] == FREE        # nothing installed: built-in
    assert "else Nocturne\u2019s own built-in denoise" in b
    assert f"median minus {_BLACK_SIGMA} " in b

    # Vivid
    vivid = dict(build_auto_plan(img, Settings(), include_crop=False, preset="vivid"))
    assert list(vivid) == list(plan)
    assert vivid["stretch"]["amount"] == VIVID_STRETCH_AMOUNT
    assert f"Vivid uses <b>{VIVID_STRETCH_AMOUNT:.2f}</b>" in b
    assert vivid["saturation"] == VIVID_SATURATION
    assert f"Vivid: <b>{VIVID_SATURATION[0]:.2f}</b> with <b>{VIVID_SATURATION[1]:.2f}</b>" in b
    assert vivid["local_contrast"] == VIVID_LOCAL_CONTRAST
    assert f"Vivid: <b>{VIVID_LOCAL_CONTRAST:.2f}</b>" in b
    assert vivid["star_reduction"] == VIVID_STAR_REDUCTION
    assert f"Vivid: <b>{VIVID_STAR_REDUCTION:.2f}</b>. Gold and blue: " \
           f"<b>{GOLD_BLUE_STAR_REDUCTION:.2f}</b>" in b

    # Gold and blue
    gb = dict(build_auto_plan(lp, Settings(), include_crop=False, preset="gold_blue"))
    assert list(gb) == ["color", "stretch", "levels", "green_fringe", "noise_sharpen",
                        "star_reduction", "narrowband"]
    assert gb["stretch"]["amount"] == AUTO_STRETCH_AMOUNT
    assert gb["star_reduction"] == GOLD_BLUE_STAR_REDUCTION
    assert "It skips Saturation and Local Contrast" in b
    assert "<b>Narrowband</b> \u2014 Gold and blue only, last." in b

    # the conditional stages, with the tools present
    full = dict(build_auto_plan(img, Settings(graxpert_path=_RUNNABLE, astap_path=_RUNNABLE,
                                              rcastro_path=_RUNNABLE),
                                include_crop=False))
    assert list(full)[:3] == ["background", "color", "deconvolution"]
    assert full["background"] == AUTO_BACKGROUND_STRENGTH
    assert f"<b>Background</b> at <i>{AUTO_BACKGROUND_STRENGTH}</i>" in b
    assert "<b>only if GraXpert is set up in Settings</b>" in b
    assert full["deconvolution"] == AUTO_DECONVOLUTION["broadband"]
    assert f"<b>Deconvolution</b> at <i>{AUTO_DECONVOLUTION['broadband']}</i> " \
           f"(<i>{AUTO_DECONVOLUTION['dualband']}</i> on dual-band data)" in b
    assert "<b>only if RC-Astro is set up</b>" in b
    assert full["color"].method == "photometric" and plan["color"].method == "sky"
    assert "<b>photometric</b> if ASTAP is set up" in b and "sky-neutralise" in b


def test_auto_enhance_help_names_the_stages_it_refuses_to_run(_no_nr_models):
    """Everything the plan leaves out is a step the user can reach by hand, and
    the topic says which and why. Guard the list against the pipeline's."""
    from nocturne.core.auto_enhance import PRESETS, build_auto_plan
    from nocturne.core.image import AstroImage
    from nocturne.settings import Settings
    from nocturne.ui.pipeline import PROCESSING_ORDER, STEP_NAME
    b = _body("auto-enhance")
    img = AstroImage(np.full((32, 32, 3), 0.3, np.float32), is_linear=True)
    every = Settings(graxpert_path=_RUNNABLE, astap_path=_RUNNABLE,
                     rcastro_path=_RUNNABLE)
    planned = set()
    for preset in PRESETS:
        meta = {"filter": "LP"} if preset == "gold_blue" else {}
        planned |= {s for s, _ in build_auto_plan(
            AstroImage(img.data, is_linear=True, metadata=meta), every, preset=preset)}
    omitted = [s for s in PROCESSING_ORDER if s not in planned]
    assert omitted == ["tint", "remove_green", "recover_core", "curves"], \
        "the set of stages Auto Enhance skips changed"
    for stage in ("recover_core", "curves"):
        assert f"<b>{STEP_NAME[stage]}</b> and" in b or f"and <b>{STEP_NAME[stage]}</b>" in b, \
            f"the topic does not say {STEP_NAME[stage]!r} is left out"
    assert "<b>Recover Core</b> and <b>Curves</b>, always" in b
    # and the two left out for want of a tool
    bare = {s for s, _ in build_auto_plan(img, Settings())}
    assert {"background", "deconvolution"} - bare == {"background", "deconvolution"}
    assert "<b>Background</b> without GraXpert" in b
    assert "<b>Deconvolution</b> without RC-Astro" in b


def test_auto_enhance_help_names_its_presets_and_drops_the_no_palette_promise():
    from nocturne.core.auto_enhance import PRESET_NAMES
    b = _body("auto-enhance")
    for shown in PRESET_NAMES.values():
        assert f"<p><b>{shown}</b> \u2014 " in b, f"the topic does not describe {shown!r}"
    assert "a click is always Natural" in b
    assert "No narrowband palette" not in b


def test_auto_enhance_help_says_denoise_never_uses_graxpert(monkeypatch):
    """GraXpert's denoise is never chosen, whatever is installed — the help says so."""
    import itertools
    from nocturne.core import nr_models
    from nocturne.core.auto_enhance import _auto_denoise_engine
    from nocturne.settings import Settings
    b = _body("auto-enhance")
    assert "It <b>never uses GraXpert</b> for denoise" in b
    assert "else GraXpert" not in b
    monkeypatch.setattr(nr_models, "available", lambda: [])
    for gx, rc, pref in itertools.product(("", _RUNNABLE), ("", _RUNNABLE),
                                          ("graxpert", "rcastro")):
        s = Settings(graxpert_path=gx, rcastro_path=rc, denoise_engine=pref)
        assert _auto_denoise_engine(s) != "graxpert"
    # Users can't have a Nocturne NR model until one ships, so the help names
    # only the engines they can have (2026-10-13: "people can wonder what that
    # is"). Put the model wording back when NR is released.
    assert "NoiseXTerminator if" in b and "built-in denoise" in b
    assert "Nocturne NR" not in b
    test_model = nr_models.NRModel("v21.5", "Ullr (v21.5)", "/x/v21.5.onnx", False)
    monkeypatch.setattr(nr_models, "available", lambda: [test_model])
    assert _auto_denoise_engine(Settings()) == "free"
    assert _auto_denoise_engine(Settings(denoise_engine="nr:v21.5")) == "nr:v21.5"


def test_auto_enhance_help_says_a_failed_stage_is_named(_no_nr_models):
    """run_auto_plan catches per stage and continues; since the presets it
    returns each failure, and the window puts it in the warning line."""
    from nocturne.core.auto_enhance import run_auto_plan
    from nocturne.core.image import AstroImage
    from nocturne.settings import Settings
    b = _body("auto-enhance")
    assert "skipped in silence" not in b
    assert "The warning line names it and why" in b
    assert "<i>Auto Enhance (Vivid): 8 of 9 steps \u2014 Noise Reduction failed: \u2026</i>" in b

    img = AstroImage(np.full((32, 32, 3), 0.3, np.float32), is_linear=True)
    plan = [("stretch", 0.3), ("levels", (0.0, 1.0, 1.0)), ("local_contrast", 0.15)]

    def _boom(*a, **k):
        raise RuntimeError("tool exploded")

    from nocturne.steps import levels as levels_step
    original = levels_step.LevelsStep.apply
    levels_step.LevelsStep.apply = _boom
    try:
        run = run_auto_plan(img, plan, Settings())
    finally:
        levels_step.LevelsStep.apply = original
    assert [name for name, _, _ in run.results] == ["Stretch", "Local Contrast"]
    assert run.failures == [("Levels", "tool exploded")]
    assert "how many steps it" in b


def test_auto_enhance_help_example_is_the_warning_the_window_shows(
        qtbot, tmp_path, monkeypatch, _no_nr_models):
    """The help's example failure line, against the warning a real failing
    Noise Reduction produces under Vivid: same words, only the counts and the
    reason differ (8 of 9 needs a tool installed; this machine has none)."""
    import re
    from nocturne.steps.noise_sharpen import NoiseSharpenStep
    from tests.ui.test_main_window import _crop, _make_fits, _window
    b = _body("auto-enhance")
    m = re.search(r"<i>(Auto Enhance \(Vivid\): \d+ of \d+ steps \u2014 Noise Reduction "
                  r"failed: \u2026)</i>", b)
    assert m, "the topic no longer gives an example failure line"
    example = m.group(1)

    def boom(self, img, option):
        raise RuntimeError("tool exploded")
    monkeypatch.setattr(NoiseSharpenStep, "apply", boom)
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    win._auto_enhance("vivid")
    shown = win._warning.text()
    done = len(win.project.entries()) - 1
    assert shown == (re.sub(r"\d+ of \d+", f"{done} of {done + 1}", example)
                     .replace("\u2026", "tool exploded")), shown


def test_auto_enhance_help_is_right_that_saying_yes_destroys_the_old_edit():
    """The confirmation reads like "we will replace this" — but jump_back
    TRUNCATES, before the first stage runs, so Redo cannot bring the old
    processing back and a cancelled run leaves you on the bare crop."""
    from nocturne.core.image import AstroImage
    from nocturne.history.project import Project
    import tempfile
    b = _body("auto-enhance")
    assert "<b>the old processing is gone at that moment</b>" in b
    mw = _src("nocturne/ui/main_window.py")
    assert "self.project.jump_back(kept)" in mw
    assert "Your crop is kept" in mw and "your crop, rotation and flips" in b

    d = tempfile.mkdtemp()
    p = Project(AstroImage(np.zeros((8, 8, 3), np.float32), is_linear=True), d)
    for name in ("Crop", "Stretch", "Saturation"):
        p.record_precomputed(name, "", AstroImage(np.zeros((8, 8, 3), np.float32),
                                                  is_linear=True))
    assert [n for n, _ in p.entries()] == ["Crop", "Stretch", "Saturation"]
    p.jump_back(1)                       # what _auto_enhance does with kept == 1
    assert [n for n, _ in p.entries()] == ["Crop"]
    assert p.can_redo() is False, \
        "jump_back now keeps the states; the help says Redo cannot bring them back"


def test_the_narrowband_help_names_every_control_the_dialog_shows(qtbot):
    """The systemic guard, not a per-control one. Adding "Tame core" to the
    dialog passed the whole suite while the help said nothing about it — help
    drifts silently on this project, which is exactly why it gets audited every
    release. Walk the real form layout instead of a list someone must remember
    to update."""
    from PySide6.QtWidgets import QFormLayout
    from nocturne.core.image import AstroImage
    from nocturne.settings import Settings
    from nocturne.ui.narrowband_dialog import NarrowbandDialog
    img = AstroImage(np.full((16, 16, 3), 0.4, np.float32), is_linear=False)
    d = NarrowbandDialog(Settings(), img)
    qtbot.addWidget(d)
    b = _body("narrowband")
    from PySide6.QtWidgets import QCheckBox
    labels = []
    for i in range(d._controls.rowCount()):
        item = d._controls.itemAt(i, QFormLayout.ItemRole.LabelRole)
        if item is not None and item.widget() is not None:
            text = item.widget().text().strip()
            if text:
                labels.append(text)
        # Checkboxes carry their own text and are added with an EMPTY label, so
        # walking LabelRole alone silently skipped them — which is the same hole
        # this test exists to close, one level down.
        # Checkboxes carry their own text. They sit in FieldRole or, once they
        # are given the full panel width, in SpanningRole — walk both, or this
        # guard silently stops covering them the day the layout changes.
        for role in (QFormLayout.ItemRole.FieldRole, QFormLayout.ItemRole.SpanningRole):
            item = d._controls.itemAt(i, role)
            if item is not None and isinstance(item.widget(), QCheckBox):
                labels.append(item.widget().text().split("(")[0].strip())
    assert labels, "no labelled controls found — the walk is broken, not the help"
    for name in labels:
        assert name in b, f"the narrowband help never mentions the {name!r} control"

    # Per palette, the rows actually SHOWN — the help must say which palette
    # each palette-only row belongs to, or someone hunts for a slider that
    # is not there.
    from nocturne.core.narrowband import GOLD_BLUE, OFFERED_PALETTES
    shown = {}
    for palette in OFFERED_PALETTES:
        d.palette_box.setCurrentText(palette)
        rows = set()
        for i in range(d._controls.rowCount()):
            item = d._controls.itemAt(i, QFormLayout.ItemRole.LabelRole)
            if d._controls.isRowVisible(i) and item is not None and item.widget() is not None:
                rows.add(item.widget().text().strip())
        shown[palette] = rows
        for name in rows - {""}:
            assert name in b, f"{palette}: the help never mentions {name!r}"
    only_gb = shown[GOLD_BLUE] - shown["HOO"]
    assert only_gb == {"Gold", "Blue"}, only_gb
    assert "Saturation" not in shown[GOLD_BLUE]
    assert all("Saturation" in shown[p] for p in OFFERED_PALETTES if p != GOLD_BLUE)
    assert "<h4>Gold and Blue — SHO-style only" in b
    assert "<h4>Saturation — HOO and Pseudo-SHO" in b


def test_the_haoiii_help_covers_strictness_and_trim():
    """Both were added after the topic was written, and the topic actively said
    neither existed. In-app help has drifted on every release so far; a control
    the help denies is worse than one it omits."""
    from nocturne.ui.help_content import TOPICS
    body = TOPICS["haoiii"].body.lower()
    assert "there is no <b>strictness</b>" not in body, "the help still denies Strictness exists"
    assert "no framing choice" not in body, "the help still denies the trim choice exists"
    assert "strictness" in body, "Strictness is not documented"
    assert "trim the ragged edges" in body, "the trim checkbox is not documented"


def test_the_haoiii_help_describes_one_stacking_pass_not_two():
    """The engine stacks both gases in a single pass now. The topic still walked
    the user through 'stacking Ha' then 'stacking OIII' as separate phases, which
    is not what the progress line says any more."""
    from nocturne.ui.help_content import TOPICS
    body = TOPICS["haoiii"].body.lower()
    assert "stacking ha + oiii" in body, "the progress label in the help is the old one"
    assert "<b>stacking oiii</b>" not in body, "the help still names a separate OIII pass"


def test_the_haoiii_help_describes_every_column_the_table_shows():
    """The topic listed three columns while the table grew to six. Pin the help
    to the header the dialog actually builds, so a new column cannot ship
    undocumented the way Round and Verdict nearly did."""
    from nocturne.settings import Settings
    from nocturne.ui.haoiii_dialog import HaOIIIDialog
    b = _body("haoiii")
    d = HaOIIIDialog(Settings())
    headers = d.browser.headers()
    assert headers == ["Use", "Time", "Stars", "FWHM", "Verdict"]
    for col in ("Time", "Stars", "FWHM", "Verdict"):
        assert f"<b>{col}</b>" in b, f"the {col} column is not explained"
    # Round and Bg left the list for its tooltip (spec 2026-09-28 §2.6); the
    # help still explains both, and the tooltip still carries both.
    fb = _src("nocturne/ui/frame_browser.py")
    for word in ("Round", "Bg"):
        assert f"<b>{word}</b>" in b and f"{word} {{s." in fb, word


def test_the_haoiii_help_mentions_the_frame_preview():
    """Clicking a row shows the frame — the only way to see for yourself why the
    grader rejected something. Undocumented in Stack for its whole life."""
    b = _body("haoiii").lower()
    assert "click any row" in b, "the preview is not mentioned"


def test_the_haoiii_help_does_not_claim_debayering_mixes_the_gases():
    """The Siril/PixInsight argument for this tool is that demosaicing smears the
    gases together. That is true of gradient-corrected demosaics, which infer red
    and blue from the green gradient — and Nocturne deliberately does not use one
    (see the BILINEAR ON PURPOSE block in core/fits_io.py; Malvar was reverted
    2026-08-18). Bilinear never looks across colours, so there is no crosstalk
    here for the tool to prevent, and the topic must not claim there is."""
    import inspect
    from nocturne.core import fits_io
    src = inspect.getsource(fits_io)
    assert "demosaicing_CFA_Bayer_bilinear" in src, (
        "the demosaic changed — recheck whether the help's reasoning now holds")
    b = _body("haoiii").lower()
    assert "mixes the two together" not in b, (
        "the help still claims debayering mixes Ha and OIII")


def test_the_haoiii_help_covers_the_separate_channel_files():
    """A control the help does not mention is a control a beginner will not find
    — and this one changes what lands in their folder."""
    from nocturne.settings import Settings
    from nocturne.ui.haoiii_dialog import HaOIIIDialog
    b = _body("haoiii")
    d = HaOIIIDialog(Settings())
    assert d.channels_check.text() in b, "the checkbox label is not in the help"
    assert "un-equalised" in b.lower(), "the help does not say the files are un-equalised"
    assert "ratio survives" in b.lower(), "the help does not explain the shared scale"


def test_the_combine_help_covers_every_control():
    """A control the help does not mention is a control a beginner will not
    find. Nocturne's help has drifted on most releases; pin it to the widgets."""
    from nocturne.settings import Settings
    from nocturne.ui.combine_dialog import CombineDialog
    b = _body("combine")
    d = CombineDialog(Settings())
    assert d.align_check.text() in b, "the align checkbox is not documented"
    for word in ("<b>Ha</b>", "<b>OIII</b>", "<b>Balance</b>", "Narrowband"):
        assert word in b, f"{word} is not in the Combine topic"
    assert "as measured" in b.lower() and "matched to ha" in b.lower(), \
        "the help must explain what the two ends of Balance mean"


def test_the_combine_help_says_it_needs_stacked_channels_not_subs():
    """The refusal a user is most likely to hit, since a raw sub is 2D too."""
    b = _body("combine").lower()
    assert "raw sub" in b, "the help does not say raw subs are refused"


def test_the_combine_help_matches_the_balance_labels_the_dialog_shows():
    """The topic names both ends of the slider; if the dialog renames them the
    help silently starts describing something the user cannot see."""
    from nocturne.settings import Settings
    from nocturne.ui.combine_dialog import CombineDialog
    b = _body("combine")
    d = CombineDialog(Settings())
    d.balance_slider.setValue(0)
    assert f"<b>{d.balance_label.text()}</b>" in b, "the 0% label is not in the help"
    d.balance_slider.setValue(100)
    assert f"<b>{d.balance_label.text()}</b>" in b, "the 100% label is not in the help"


def test_share_help_explains_why_there_is_a_frame_after_cropping():
    """Andreas, 2026-09-02: "now we have cropping in three places". The help
    has to answer that, and answer it accurately — this one is NOT a crop:
    the box only exists once a ratio is chosen, and apply_aspect locks it to
    that ratio, so there is no free-form rectangle here."""
    b = _body("share")
    assert "not a crop" in b
    assert "never altered" in b
    assert "cannot " in b and "free rectangle" in b, \
        "the help must say the frame is ratio-locked, not a free crop"
    # ...and the claim must match the code that draws it.
    sd = _src("nocturne/ui/share_dialog.py")
    assert "self._image_view.setVisible(reframing)" in sd, \
        "the help says there is no frame on Original; the dialog shows one"
    iv = _src("nocturne/ui/image_view.py")
    assert "def apply_aspect(" in iv and "Lock to a ratio" in iv, \
        "the help says the frame is locked to the ratio; apply_aspect no longer does that"


def test_share_help_does_not_promise_a_free_crop_box():
    """It used to read "pick an aspect (or drag the crop box to frame it by
    eye)", which described a box that does not exist until you pick one."""
    b = _body("share")
    assert "drag the crop box" not in b


# --- Reachability -----------------------------------------------------------
# A topic nobody can open is the same as no topic. Both of the topics this file's
# docstring says were written — Trim and fullscreen — were added to TOPICS and
# never added to SECTIONS, so for months the help contained 406 words that no
# user could reach. Nothing failed, because nothing checked the wiring.

def test_every_help_topic_can_actually_be_opened():
    listed = {tid for sec in h.SECTIONS for tid in sec.topic_ids}
    orphans = sorted(set(h.TOPICS) - listed)
    assert not orphans, (
        "written but unreachable — not in any section of the help browser: "
        + ", ".join(f"{tid} ({h.TOPICS[tid].title})" for tid in orphans))


def test_the_help_browser_lists_no_topic_that_is_missing():
    listed = {tid for sec in h.SECTIONS for tid in sec.topic_ids}
    dangling = sorted(listed - set(h.TOPICS))
    assert not dangling, f"sections reference topics that do not exist: {dangling}"


def test_every_pipeline_step_has_a_topic():
    """The help button is context-sensitive: it opens the topic for the step you
    are standing on. A step with no mapping opens nothing at all."""
    # path_stages(), NOT PROCESSING_ORDER. The latter includes `tint`, which
    # is a step in the history but not a stop in the stepper — it lives inside
    # the Color panel and maps back to Color. A user never stands on it, so it
    # needs no topic of its own; what it needs is for the Color topic to name
    # its controls, which is a separate check. `remove_green` DOES have its
    # own stop now (it moved off the Color panel onto its own stage), so it
    # needs — and has — a topic of its own like any other stepper stage.
    from nocturne.ui.pipeline import path_stages, STEP_NAME

    missing = [f"{s.id} ({STEP_NAME.get(s.id, '?')})"
               for s in path_stages() if h.stage_topic_id(s.id) is None]
    assert not missing, "pipeline steps with no help topic: " + ", ".join(missing)


def test_the_stacking_topic_documents_drizzle():
    """Drizzle shipped in v0.22.0 and the word did not appear anywhere in the
    help until 2026-09-08 — a headline feature with a tick box in the Stack
    dialog and nothing to read about it.

    Tied to drizzle_gate's own constants so the numbers in the prose cannot
    drift away from the numbers in the gate.
    """
    from nocturne.stacking import drizzle_gate as g

    body = _body("stacking")
    assert "drizzle" in body.lower()
    # The control, by the name the dialog gives it.
    assert "Drizzle" in body and "&times;2" in body

    text = re.sub(r"<[^>]+>", " ", body)
    # The three signals the gate actually weighs.
    assert f"{g.FWHM_MAX:.0f}" in text, "the star-size threshold is not stated"
    assert str(g.MIN_FRAMES) in text, "the minimum frame count is not stated"
    assert str(g.GOOD_FRAMES) in text, "the comfortable frame count is not stated"
    # And the cost, which is the whole reason it is a choice.
    assert "four times" in text.lower()
    # The plain-words line and its summary (spec 2026-09-28 §5), by the
    # words the dialog uses.
    assert f"<b>{g.SUITS_SUMMARY}</b>" in body
    assert "green line" not in body


def test_no_step_topic_offers_options_its_step_does_not_have():
    """Local Contrast and Star Reduction both told the user to "pick light,
    medium or strong" long after both controls became sliders. That is worse
    than a thin topic: it is an instruction that cannot be followed.

    Word boundaries matter here — a substring check calls "slightly" a claim
    about a light preset and "strongest" a claim about a strong one.
    """
    from nocturne.settings import Settings
    from nocturne.steps.factory import make_step
    from nocturne.ui.pipeline import path_stages, STEP_NAME

    settings = Settings()
    offenders = []
    for stage in path_stages():
        topic_id = h.stage_topic_id(stage.id)
        if topic_id is None or h.topic(topic_id) is None:
            continue
        try:
            options = {o.lower() for o in make_step(stage.id, settings).options() if o}
        except Exception:
            continue
        if options:
            continue                      # it really does have presets
        text = re.sub(r"<[^>]+>", " ", h.topic(topic_id).body).lower()
        # The INSTRUCTION shape, not the words. "off to strong" is a slider's own
        # label and is fine; "pick light, medium or strong" is a lie about the UI.
        instruction = re.search(
            r"\b(pick|choose|select)\b[^.]{0,60}?"
            r"\b(light|medium|strong)\b[^.]{0,30}?\b(light|medium|strong)\b", text)
        if instruction:
            offenders.append(
                f"{stage.id} ({STEP_NAME.get(stage.id, '?')}) instructs "
                f"{instruction.group(0).strip()!r} but the control is a slider")
    assert not offenders, "help offers presets that do not exist:\n  " + "\n  ".join(offenders)


def test_keyboard_shortcuts_is_in_getting_started():
    """The panels lost "Press Space to toggle before and after" (spec §2.6);
    this topic is its new home, plus F and Escape, which had no topic at all."""
    t = h.topic("keyboard-shortcuts")
    assert t is not None
    body = (t.summary + t.body).lower()
    for key in ("space", "before", "f ", "full", "escape"):
        assert key in body, key
    gs = next(s for s in h.SECTIONS if s.title == "Getting Started")
    assert "keyboard-shortcuts" in gs.topic_ids


# Every sentence moved out of a description (spec §6, "→ How this works") must
# exist in its step's topic, so trimming the panel lost nothing. A tuple of
# phrases per topic id, because De-green Stars alone dropped three separate
# sentences from its old description.
MOVED = {
    "curves": ("pin the sky",),
    "green_fringe": ("Hue/Saturation",
                      "lose their colour and keep their lightness",
                      "always an artefact"),
    "remove_green": ("right = stronger",),
    "saturation": ("left to mute colour, right to boost", "&amp; sky untouched"),
    "recover_core": ("instead of a white blob",),
    "star_reduction": ("drag right for more reduction",),
}


def test_moved_sentences_have_a_home():
    for tid, phrases in MOVED.items():
        t = h.topic(tid)
        assert t is not None, f"no help topic {tid!r}"
        body = (t.summary + t.body).lower()
        for phrase in phrases:
            assert phrase.lower() in body, f"{tid} lost {phrase!r}"


def test_the_stacking_help_describes_the_frame_list_and_output_it_has():
    """Four new controls and a split output, each pinned to the widget that
    draws it: help goes stale every release unless something holds it."""
    from nocturne.ui.frame_browser import FrameBrowser
    b = _body("stacking")
    fb = _src("nocturne/ui/frame_browser.py")
    sd = _src("nocturne/ui/stack_dialog.py")
    assert "<b>Time</b>" in b and "Time" in FrameBrowser.headers()
    for words in ("Reset to suggested", "⇤ bigger preview"):
        assert f"<b>{words}</b>" in b, f"{words!r} is not in the help"
        assert f'"{words}"' in fb, f"{words!r} is no longer a control"
    assert "Back to the verdicts" not in b
    for mode in ("Kept", "Rejected"):
        assert f"<b>{mode}</b>" in b and f'"{mode}"' in fb
    assert "arrow keys" in b and "space bar" in b
    assert "<b>Save to</b>" in b and 'form.addRow("Save to"' in sd
    assert "<b>Name</b>" in b and 'form.addRow("Name"' in sd
    assert "<b>↺ automatic</b>" in b and '"↺ automatic"' in sd
    for group in ("Frames", "Combine", "Result"):
        assert f"<b>{group}</b>" in b and f'add_group("{group}"' in sd
    assert "<b>Change…</b>" in b and '"Change…"' in _src("nocturne/ui/option_band.py")


def test_the_fold_and_strictness_are_named_as_the_dialogs_draw_them():
    """Final review m3: the help said "with ▴" after the button became
    "▴ Fold", named a Strictness control no label showed, and the Ha/OIII
    topic never said its options fold too."""
    ob = _src("nocturne/ui/option_band.py")
    assert '"▴ Fold"' in ob
    for topic, src in (("stacking", "nocturne/ui/stack_dialog.py"),
                       ("haoiii", "nocturne/ui/haoiii_dialog.py")):
        b = _body(topic)
        assert "<b>▴ Fold</b>" in b, f"{topic}: the fold button is not named"
        assert "<b>Strictness</b>" in b, f"{topic}: Strictness is not named"
        assert 'QLabel("strictness:")' in _src(src), f"{src}: no Strictness label"
    assert "with ▴ when" not in _body("stacking")


def test_stacking_help_describes_the_verdict_the_chart_and_the_rejected_folder():
    """Delivery B's three additions, each claim pinned to the code that makes
    it true, so the words and the behaviour cannot drift apart."""
    from nocturne.stacking import reject_move
    from nocturne.ui import frame_browser, quality_chart, theme, verdict_strip
    b = _body("stacking")
    v = _src("nocturne/stacking/verdict.py")
    for word in ("Good night", "Mixed night", "Poor night"):
        assert f"<b>{word}</b>" in b and f'"{word}"' in v, word
    assert "not a measure of the seeing" in b
    assert f"<b>{verdict_strip.MORE_TEXT}</b>" in b
    from nocturne.stacking import verdict as vd
    for label in (vd.LABEL_KEPT, vd.LABEL_REJECTED, vd.LABEL_STARS):
        assert f"<b>{label}</b>" in b, label
    # the chart
    assert "amber" in b and quality_chart.REJECTED_COLOUR == theme.WARNING
    assert "file-name order" in b and "file-name order" in quality_chart.NOTE_NO_TIME
    # Ruling R11 (his own request, final fix wave, 2026-09-28): a smoothed
    # trend line, and a narrow FIXED-pixel gap between nights (GAP_CAP still
    # governs the gap WITHIN a night, unchanged). Ruling R12 (round 2): the
    # line is two-stage (median then mean, not a single median), and the
    # FWHM scale settles around the kept frames, not every raw value.
    assert "smoothed trend line" in b and "running median" in b and "running average" in b
    assert "narrow fixed width" in b
    assert "settles around the kept frames" in b and "pinned at the top or bottom" in b
    qc_src = _src("nocturne/ui/quality_chart.py")
    assert "GAP_CAP" in qc_src and "NIGHT_GAP_PX" in qc_src
    assert "TREND_MEDIAN_WINDOW" in qc_src and "TREND_MEAN_WINDOW" in qc_src
    assert "MIN_FWHM_SPAN" in qc_src
    for words in (quality_chart.HIDE_TEXT, quality_chart.SHOW_TEXT):
        assert f"<b>{words}</b>" in b, words
    assert "Under the list" not in b and "above the list" in b
    # the rejected folder
    assert f"<b>{verdict_strip.move_label(7).replace('7', 'N')}</b>" in b
    assert f"<b>{verdict_strip.BACK_TEXT}</b>" in b
    assert f"<b>{reject_move.MANIFEST_NAME}</b>" in b
    assert f"<b>{frame_browser.MOVED_TEXT}</b>" in b
    assert "Nothing is deleted" in b and "nothing is copied" in b
    rm = _src("nocturne/stacking/reject_move.py")
    assert "shutil" not in rm and "os.rename(" in rm
    # "a folder you open again lists only the frames still there": not recursive
    assert "directly inside the folder" in b
    assert "glob.glob(os.path.join(folder, pattern))" in _src("nocturne/stacking/frames.py")


def test_haoiii_help_mentions_the_chart_it_now_has():
    b = _body("haoiii")
    assert "chart above the list" in b and "<b>FWHM</b>" in b
    assert "self.chart = QualityChart(" in _src("nocturne/ui/frame_browser.py")
    assert "FrameBrowser(" in _src("nocturne/ui/haoiii_dialog.py")


def test_both_topics_say_what_a_stacked_master_shows():
    from nocturne.stacking.grade import REASON_NOT_RAW
    for topic in ("stacking", "haoiii"):
        b = _body(topic)
        assert f"<b>{REASON_NOT_RAW}</b>" in b, topic
        assert "none of the counts" in b, topic


def test_both_topics_say_what_an_unmeasured_frame_shows():
    """M4 (final fix wave, 2026-09-28): Ruling R1 gave a frame that could not
    be measured the same treatment as a stacked master — sorts last, shows
    its real reason, counted nowhere — but the help never said so, leaving a
    user who sees "Unmeasured N frames" with no explanation."""
    from nocturne.stacking.grade import REASON_MEASURE
    for topic in ("stacking", "haoiii"):
        b = _body(topic)
        assert f"<b>{REASON_MEASURE}</b>" in b, topic
        assert "none of the counts" in b, topic


# --- several nights (spec 2026-09-28 §9) ---------------------------------------

def test_stacking_help_describes_nights_as_they_are_built():
    b = _body("stacking")
    nights = _src("nocturne/stacking/nights.py")
    strip = _src("nocturne/ui/verdict_strip.py")
    assert "noon to noon" in b and "NIGHT_TURNS_AT = 12" in nights
    assert "<b>Nights</b>" in b and 'NIGHTS_TEXT = "Nights"' in strip
    assert "<b>No date</b>" in b and 'NO_DATE_LABEL = "No date"' in nights
    assert "<b>Soft</b>" in b and '"Soft"' in _src("nocturne/stacking/verdict.py")
    assert "fewer than five frames" in b and "JUDGE_MIN = 5" in _src("nocturne/stacking/grade.py")


def test_stacking_help_names_add_folder():
    b = _body("stacking")
    assert "<b>Add folder…</b>" in b
    assert 'ADD_FOLDER_TEXT = "Add folder…"' in _src("nocturne/ui/stack_dialog.py")


def test_stacking_help_no_longer_says_a_folder_of_nights_is_judged_as_one():
    """True until 2026-09-28; each night is graded on its own since."""
    b = _body("stacking")
    assert "combined as though it were one — and a night" not in b
    assert "a whole bad session is not an outlier" not in b


def test_haoiii_help_mentions_the_night_lines():
    b = _body("haoiii")
    assert "dashed line" in b and "no night chips" in b


def test_upscale_help_says_the_navigator_maps_the_whole_frame(qtbot):
    """[final 9] It draws the whole frame with the crop outlined, not the crop."""
    from nocturne.core.image import AstroImage
    from nocturne.settings import Settings
    from nocturne.ui.upscale_dialog import UpscaleDialog
    b = _body("upscale")
    assert "map of the whole crop" not in b
    assert "a small map of the whole image, with your crop outlined" in b
    data = np.full((60, 100, 3), 0.1, np.float32)
    d = UpscaleDialog(AstroImage(data, is_linear=False, metadata={}), {}, Settings())
    qtbot.addWidget(d)
    d.picker.set_crop_overlay(True, content_bounds=(10, 40, 20, 60)); d.picker.show_crop_box()
    d._run_upscale()
    assert (d.navigator._fw, d.navigator._fh) == (100, 60), "the navigator no longer maps the frame"


def test_share_help_gives_the_opacity_range_the_slider_has(qtbot):
    from nocturne.settings import Settings
    from nocturne.ui.share_dialog import ShareDialog
    b = _body("share")
    dlg = ShareDialog(np.zeros((40, 30, 3), np.uint8), {"target": "X"}, Settings())
    qtbot.addWidget(dlg)
    s = dlg._opacity_slider
    assert f"from {s.minimum()}% to {s.maximum()}%" in b
    assert f"stops at {s.minimum()}%" in b
    assert "a shadow fades with the text" in b
    # 2026-10-10: opacity starts at full on every open and is not remembered.
    from dataclasses import replace
    from nocturne.core.presets import preset_by_name, style_to_dict
    worn = style_to_dict(replace(preset_by_name("Plate"), text_opacity=0.6))
    again = ShareDialog(np.zeros((40, 30, 3), np.uint8), {"target": "X"},
                        Settings(plate_preset="Plate", plate_style=worn))
    qtbot.addWidget(again)
    assert f"starts at {again._opacity_slider.value()}% every time you open Share" in b
    assert "not part of the remembered look" in b
    assert "The look is remembered between shares;" not in b, \
        "the old sentence claims everything is remembered"


def test_help_names_the_levels_auto_button_as_the_button_shows_it():
    """The Levels button became "Auto black point" (2026-10-08). Every help
    passage that tells the user to press it must use the label they will see;
    a bare <b>Auto</b> sends them looking for a button that is not there."""
    from nocturne.ui.pipeline import path_stages
    from nocturne.ui.step_panels import build_panel
    stage = next(s for s in path_stages() if s.id == "levels")
    w = build_panel(stage, on_levels_auto=lambda: None)
    try:
        label = w.auto_btn.text()
    finally:
        w.deleteLater()
    assert label == "Auto black point"
    for tid in ("levels", "starless_levels", "recipes"):
        b = _body(tid)
        assert "<b>Auto</b>" not in b, f"{tid!r} still names the old 'Auto' button"
        assert f"<b>{label}</b>" in b, f"{tid!r} does not name the {label!r} button"


def test_color_help_matches_what_photometric_colour_does():
    """Written with the 2026-10-10 fix: photometric colour now measures star
    colour with the sky taken off, and steps aside on dual-band data. The topic
    must say what it corrects, when it steps aside and why, and what an
    unlinked stretch does to it."""
    from nocturne.core.color import ColorSettings
    from nocturne.core.image import AstroImage
    from nocturne.steps.color import DUALBAND_MESSAGE, ColorStep
    b = _body("color")
    assert "<b>Gaia</b>" in b and "colour of the <i>stars</i>" in b
    assert "bkgann" in _src("nocturne/core/spcc.py"), "the sky is no longer taken off"
    assert "taken off before each star is measured" in b
    # steps aside on LP, through the sky balance, and the log says so
    assert "<b>LP</b>" in b and "steps aside" in b and "two narrow slices" in b
    step = ColorStep(astap=None, gaia_query=None)
    img = AstroImage(np.full((16, 16, 3), 0.3, np.float32), is_linear=True,
                     metadata={"filter": "LP"})
    step.apply(img, ColorSettings(method="photometric"))
    assert step.last_message == DUALBAND_MESSAGE and step.fell_back is True
    # It reaches the result line (Output), not the step log, so the help names
    # neither: "tells you so" is true of the manual step and of Auto Enhance.
    assert "and tells you so" in b and "the log says so" not in b
    # a recipe keeps the choice
    assert step.recorded_option(ColorSettings(method="photometric")).method == "photometric"
    assert "recipe keeps your choice" in b
    # unlinked stretch: the same claim the Stretch topic makes
    assert "<i>unlinked</i> stretch normalises each channel" in b
    assert "undoes a" in _body("stretch") and "photometric colour calibration completely" in _body("stretch")
    # Auto Enhance's topic mentions the step-aside
    assert "On dual-band (<b>LP</b>) data" in _body("auto-enhance")


def test_stretch_help_describes_the_stretch_version_in_use():
    """The Stretch topic says how the linked stretch picks its sky and its black
    point, which is stretch VERSION 2's behaviour (2026-10-11). Flip the revert
    switch (autostretch.STRETCH_VERSION) and this fails, so the help is changed
    with it rather than left describing a stretch that no longer runs."""
    from nocturne.core import autostretch as A
    b = _body("stretch")
    assert "darkest part of the frame" in b and "noisiest channel" in b
    assert A.STRETCH_VERSION == A.STRETCH_V2
    src = _src("nocturne/core/autostretch.py")
    assert "_SKY_PCT = 30.0" in src            # "the darkest part"
    assert "noisiest" in src.split("def _neutral_stretch_v1")[0]


def test_linked_is_never_said_to_keep_the_skys_own_colour():
    """The linked stretch makes the sky neutral (measured on the sky since
    stretch version 2), so "keeps the sky's own colour" said the opposite of
    what it does, in six places (review 2026-10-11, I-2). The owner's wording,
    2026-10-11: "One curve for all colours: keeps the colours of stars and
    nebula" / "Each colour stretched on its own: evens the channels out"."""
    for rel in ("nocturne/ui/step_panels.py", "nocturne/ui/main_window.py",
                "nocturne/ui/stretch_picker.py", "nocturne/ui/help_content.py"):
        assert "sky's own colour" not in _src(rel), rel
    from nocturne.ui.stretch_picker import COLOUR_PICKS
    subs = {name: sub for name, _linked, sub in COLOUR_PICKS}
    assert subs["Linked"] == "One curve for all colours: keeps the colours of stars and nebula"
    assert subs["Unlinked"] == "Each colour stretched on its own: evens the channels out"
    b = _body("stretch")
    assert "one curve for all colours" in b and "keeps the colours of stars and nebula" in b
    assert "makes the sky neutral" in b


# ---- Presets (2026-10-13) ----

def _plain(html):
    """Body text without tags, so a claim split by <b> still reads whole."""
    return re.sub(r"<[^>]+>", "", html)


def test_presets_topic_exists_and_is_listed_beside_recipes():
    ids = {t.id for t in h._TOPIC_LIST}
    assert "presets" in ids
    section = next(s for s in h.SECTIONS if "recipes" in s.topic_ids)
    assert "presets" in section.topic_ids


def test_presets_help_names_the_real_controls():
    b = _plain(_body("presets"))
    mw = _src("nocturne/ui/main_window.py")
    sp = _src("nocturne/ui/step_panels.py")
    pb = _src("nocturne/ui/preset_browser.py")
    # Save as Preset… is a Project menu item and the Export button (moved off
    # Enhancements 2026-10-14).
    assert "Save as Preset…" in b
    assert 'project_menu.addAction("Save as Preset…"' in mw
    export = sp.split('elif stage.kind == "export":')[1].split("else:  # placeholder")[0]
    assert 'QPushButton(load_icon("save-preset"), "Save as Preset…")' in export
    assert "Save as Preset" not in sp.split('elif stage.kind == "enhance":')[1].split(
        "elif stage.kind ==")[0].replace("No Save as Preset", "")
    assert "Project menu" in b and "Export step" in b
    assert "Enhancements step" not in b, "the button is no longer there"
    # Presets… on Crop, under Guides, the chosen preset directly under it, and
    # the Apply label it produces.
    assert "Presets…" in b and 'QPushButton("Presets…")' in sp
    crop = sp.split('controls.addWidget(section_label("Guides"))')[1]
    assert crop.index("controls.addWidget(guides)") < crop.index("_add_preset_controls(w, controls")
    controls = sp.split("def _add_preset_controls")[1].split("\ndef ")[0]
    assert controls.index("controls.addWidget(btn)") < controls.index("controls.addWidget(chip)")
    assert "under Guides" in b and "directly under the Presets… button" in b
    assert "How this works" not in b                # the old title-row link is gone
    assert "Apply button names it" in b
    assert "Apply Crop + " in b and '"Apply Crop + " if box' in mw
    assert "Apply M 8" in b and 'else "Apply "' in mw
    for label in ("Rename…", "Delete…", "Use no preset", "Choose"):
        assert label in b and f'QPushButton("{label}")' in pb, label
    for label in ("Grid", "List"):
        assert label in b and f'(self.{label.lower()}_btn, "{label}"' in pb, label
    assert "✕" in b and 'clear.setText("\\u2715")' in sp


def test_presets_help_names_the_sort_and_filter_the_browser_offers():
    from nocturne.ui.preset_browser import _SORT_LABELS
    b = _plain(_body("presets"))
    for label in _SORT_LABELS.values():
        assert label in b, label
    pb = _src("nocturne/ui/preset_browser.py")
    assert "Only presets for this kind of data" in b
    assert 'QCheckBox("Only presets for this kind of data")' in pb


def test_presets_help_gets_the_save_gate_right():
    b = _plain(_body("presets"))
    mw = _src("nocturne/ui/main_window.py")
    gate = mw.split("def _sync_preset_action")[1].split("def _save_preset")[0]
    assert '("enhancements", "export")' in gate and "is_linear_at" in gate
    assert "recipe_from_entries" in gate                 # at least one step to carry
    assert "Enhancements" in b and "stretched" in b and "nothing to save" in b.lower()


def test_presets_help_names_exactly_what_is_left_out():
    from nocturne.recipe import PRESET_EXCLUDED_NAMES
    b = _plain(_body("presets")).lower()
    for name in ("crop", "rotate", "flip", "trim", "share", "upscale crop"):
        assert name in b, name
    assert {"Crop", "Rotate", "Flip H", "Flip V", "Trim"} == set(PRESET_EXCLUDED_NAMES)


def test_presets_help_says_which_tools_recipes_cannot_carry():
    """Both topics: a preset carries them, a recipe names them as left out."""
    from nocturne.recipe import PRESET_ONLY_STAGES, uncaptured_step_names
    for name in PRESET_ONLY_STAGES:
        assert name in _body("presets"), name
        assert name in _body("recipes"), name
    left = uncaptured_step_names([("Star Spikes", {}), ("Starless Levels", [0.1, 0.9]),
                                  ("Trim", {})])
    assert set(left) == set(PRESET_ONLY_STAGES) | {"Trim"}


def test_presets_help_states_the_data_type_rules_the_code_enforces():
    import nocturne.user_presets as up
    b = _plain(_body("presets"))
    assert "dual-band" in b and "broadband" in b
    dual = up.Preset(id="x", name="x", steps=(), data_type="dualband")
    broad = up.Preset(id="y", name="y", steps=(), data_type="broadband")
    for picture in ("broadband", "unknown"):     # anything not dual-band
        assert up.can_apply(dual, picture)[0] is False, picture
    assert up.can_apply(dual, "dualband")[0] is True
    assert "any picture that is not dual-band" in b and "cannot tell" in b
    ok, note = up.can_apply(broad, "dualband")
    assert ok is True and note in b                     # allowed, and marked


def test_presets_help_quotes_the_already_stretched_rule():
    import nocturne.user_presets as up
    b = _plain(_body("presets"))
    assert up.STRETCHED_NOTE in b
    p = up.Preset(id="x", name="x", steps=({"stage": "levels", "option": None},),
                  data_type="broadband")
    assert up.can_apply(p, "broadband", base_linear=True) == (False, up.STRETCHED_NOTE)
    assert up.can_apply(p, "broadband", base_linear=False)[0] is True


def test_presets_help_describes_how_a_run_ends():
    b = _plain(_body("presets"))
    mw = _src("nocturne/ui/main_window.py")
    run = mw.split("def _run_preset")[1].split("\n    def ")[0]
    assert "Enhancements" in b and 'self._go_to_id("enhancements"' in run
    # Each step its own history entry: the run is folded in one result at a time.
    assert "self._record_auto_run(run, " in run
    rec = mw.split("def _record_auto_run")[1].split("\n    def ")[0]
    loop = rec.split("for (name, option, img), engine, res, stage in zip(")[1].split("):", 1)[1]
    assert loop.lstrip().startswith("self.project.record_precomputed(name, option, img)")
    assert "its own step, so you can change or undo any of them" in b
    # Apply and continue on Crop presses the crop-only path, which never runs a preset.
    press = mw.split("def _press_apply_plan")[1].split("\n    def ")[0]
    assert ('btn is getattr(self._panel, "apply_btn", None)):\n'
            '                self._apply_plain_crop()') in press
    plain = mw.split("def _apply_plain_crop")[1].split("\n    def ")[0]
    assert "preset" not in plain.split('"""')[2]
    assert "Apply and continue" in b and "crop only" in b


def test_presets_help_auto_levels_re_measures_and_the_rest_is_as_saved():
    """A preset's Levels saved as Auto reaches the run as the AUTO decision,
    which LevelsStep derives from the picture in front of it; a chosen Levels
    reaches it as its numbers."""
    import nocturne.user_presets as up
    from nocturne.core.image import AstroImage
    from nocturne.recipe import LEVELS_AUTO
    from nocturne.settings import Settings
    from nocturne.steps.levels import LevelsStep
    b = _plain(_body("presets"))
    assert "Auto black point" in b and "re-measures" in b and "values you saved" in b
    auto = up.Preset(id="a", name="a", steps=({"stage": "levels", "option": LEVELS_AUTO},))
    fixed = up.Preset(id="f", name="f", steps=({"stage": "levels", "option": [0.1, 1.0, 1.0]},))
    # "auto" reaches the run as the CURRENT Auto (2026-10-14), still re-derived.
    from nocturne.core.levels import new_levels_option
    assert up.preset_plan(auto, Settings()).plan == [("levels", new_levels_option(auto=True))]
    assert up.preset_plan(fixed, Settings()).plan == [("levels", (0.1, 1.0, 1.0))]
    rng = np.random.default_rng(7)
    dim = (0.10 + 0.01 * rng.standard_normal((32, 32, 3))).astype(np.float32)
    bright = dim + np.float32(0.2)
    # The run applies the PLAN's option (the current Auto), not the bare string.
    (_stage, run_option), = up.preset_plan(auto, Settings()).plan
    from nocturne.core.levels import apply_levels, auto_black
    for data in (dim, bright):
        img = AstroImage(data, is_linear=False)
        out = LevelsStep().apply(img, run_option).data
        black = auto_black(img).black
        np.testing.assert_array_equal(out, apply_levels(img, black, 1.0, 1.0).data)
        assert black > 0
    assert auto_black(AstroImage(dim, is_linear=False)).black != auto_black(
        AstroImage(bright, is_linear=False)).black       # re-measured, not carried


def test_crop_and_enhancements_help_point_at_presets():
    assert "Presets…" in _body("crop")
    assert "Save as Preset…" in _body("enhancements")


# ---- Export redesign (2026-10-14) ----

def test_export_help_names_the_buttons_the_panel_has():
    from nocturne.ui.step_panels import _FORMAT_TILES, _GALLERY_HINT
    b = _plain(_body("export"))
    for label, sub, _icon in _FORMAT_TILES:
        assert label in b, f"the {label} button is not in the help"
    assert "Format" in b and "Export…" in b
    assert "P3" in b and "Display P3" in b      # the button's short name and the space's
    # The gallery is behind a button, in a window of its own.
    assert "Share to the gallery…" in b and "window" in b
    sp = _src("nocturne/ui/step_panels.py")
    assert 'QPushButton(load_icon("upload"), "Share to the gallery…")' in sp
    # C2's line under the button is "Your exported picture in the public
    # gallery."; the dialog it opens names the site.
    assert _GALLERY_HINT == "Your exported picture in the public gallery."
    from PySide6.QtWidgets import QApplication, QLabel
    from nocturne.ui.pipeline import path_stages
    from nocturne.ui.step_panels import build_panel
    QApplication.instance() or QApplication([])
    panel = build_panel(next(s for s in path_stages() if s.id == "export"),
                        wall_fields={"target": "M 31"}, wall_handle="@a")
    dialog_words = " ".join(l.text() for l in panel.gallery_dialog.findChildren(QLabel))
    assert "public gallery at nocturneastro.com" in dialog_words
    panel.deleteLater()
    # Burn annotations appears only once solved, and the help says when.
    assert "plate-solved" in b and "Burn annotations" in b
    mw = _src("nocturne/ui/main_window.py")
    assert "burn_annotations.setVisible(solved)" in mw
    # Save as Preset… is on this step now.
    assert "Save as Preset…" in b


def test_enhancements_help_no_longer_puts_the_preset_button_on_its_own_step():
    b = _plain(_body("enhancements"))
    assert "button at the top of this step" not in b
    assert "Export step" in b



def test_export_help_gives_the_c2_order_and_what_the_extras_do_not_do():
    from nocturne.ui import step_panels as sp
    b = _plain(_body("export"))
    # Export first, then optionally share — and Share waits for it.
    assert b.index("export first") < b.index("then, if you like, share it")
    assert sp._GALLERY_HINT_WAIT in b
    assert "until this version of the picture has been exported" in b
    assert "See the gallery ↗" in b and "See the gallery ↗" in _src("nocturne/ui/step_panels.py")
    # The heading, in the help's own case, and what the preset does not save.
    assert "Optional — doesn't save your picture".upper() == sp._OPTIONAL_HEADING
    assert "Optional — doesn't save your picture" in b
    assert "not the picture itself" in b
    mw = _src("nocturne/ui/main_window.py")
    assert "self._exported_key = self._gallery_key()" in mw.split("def _export_done")[1][:600]


# ---- Levels, clip-aware (2026-10-14) ----------------------------------------

def test_levels_help_auto_stops_at_the_warning_and_never_turns_a_colour_amber():
    """'stops at the clipping warning … without pushing any colour past the limit
    where the ▼ read-out turns amber': on a picture where the unlimited black
    crushes blue past the limit, Auto stops, and every channel stays under it —
    measured the read-out's way (CrushProbe is held equal to it in core tests)."""
    from nocturne.core.inspect import CRUSHED_LIMIT
    from nocturne.core.levels import CrushProbe, auto_black
    from tests.core.test_levels_clip_aware import _stop_image
    b = _plain(_body("levels"))
    assert "It stops at the clipping warning." in b
    assert "never turns a colour amber by itself" in b
    img = _stop_image()
    probe = CrushProbe(img)
    a = auto_black(img)
    assert max(probe.crushed(a.candidate)) >= CRUSHED_LIMIT, "fixture: unlimited Auto must cross"
    assert a.stopped and a.black < a.candidate
    assert all(c < CRUSHED_LIMIT for c in probe.crushed(a.black))


def test_levels_help_quotes_the_auto_note_and_the_log_line_gives_both_numbers():
    from nocturne.core.levels import AutoBlack, new_levels_option
    from nocturne.ui.main_window import MainWindow
    b = _plain(_body("levels"))
    quoted = "Auto stopped at 0.031 so no colour is crushed past the warning limit"
    assert quoted in b
    mw = _src("nocturne/ui/main_window.py")
    assert ('f"Auto stopped at {_floor_black(cached.black) / BLACK_STEPS:.3f} so no "\n'
            '                    "colour is crushed past the warning limit. Drag Black point "\n'
            '                    "right to go darker on purpose.")') in mw
    assert "where it stopped, and where it would have gone without the limit" in b
    resolved = type("R", (), {"auto": AutoBlack(0.031, 0.062, True)})()
    line = MainWindow._levels_log_detail(new_levels_option(auto=True), resolved)
    assert "0.031" in line and "unlimited Auto: 0.062" in line


def test_levels_help_go_darker_by_dragging_black_point(qtbot, tmp_path):
    """'To go darker on purpose, drag Black point to the right past where Auto
    stopped … the read-out turns amber': the drag is not refused or capped, and
    past Auto's black a channel does cross the limit."""
    from nocturne.core.inspect import CRUSHED_LIMIT
    from nocturne.core.levels import BLACK_STEPS, CrushProbe
    from tests.ui.test_levels_clip_aware_ui import _at_levels
    b = _plain(_body("levels"))
    assert "To go darker on purpose, drag Black point to the right" in b
    win = _at_levels(qtbot, tmp_path)
    win._on_levels_auto()
    p = win._panel
    stopped_at = p.black_slider.value()
    p.black_slider.setValue(stopped_at + 150)
    assert p.black_slider.value() == stopped_at + 150
    assert not p.auto_btn.isChecked()
    probe = CrushProbe(win._preview_base("levels"))
    assert max(probe.crushed(p.black_slider.value() / BLACK_STEPS)) >= CRUSHED_LIMIT


def test_levels_help_which_sliders_pop_auto_out_and_which_keep_it(qtbot, tmp_path):
    from tests.ui.test_levels_clip_aware_ui import _at_levels
    b = _plain(_body("levels"))
    assert "Nudge Black point, Midtones or White point and the button pops out" in b
    assert "Moving a colour keeps Auto black point selected" in b
    win = _at_levels(qtbot, tmp_path)
    p = win._panel
    for colour in (p.red_slider, p.green_slider, p.blue_slider):
        win._on_levels_auto()
        colour.setValue(colour.value() - 10)
        assert p.auto_btn.isChecked(), "a colour slider popped Auto out"
        colour.setValue(0)
    for s in (p.black_slider, p.gamma_slider, p.white_slider):
        win._on_levels_auto()
        assert p.auto_btn.isChecked()
        s.setValue(s.value() - 5)
        assert not p.auto_btn.isChecked(), f"{s.objectName() or s} left Auto selected"


def test_levels_help_lift_is_left_and_raises_the_floor_without_detail():
    """'Drag a colour left to lift it: less of that colour is cut to black, and
    lifted far enough its floor sits above zero. Lifting does not bring back
    detail that was already lost — it only raises the floor.' Left is negative;
    a channel already at zero in Levels' input comes out a raised constant, the
    other channels untouched."""
    from nocturne.core.image import AstroImage
    from nocturne.core.levels import apply_levels
    from nocturne.ui.pipeline import path_stages
    from nocturne.ui.step_panels import build_panel
    b = _plain(_body("levels"))
    assert "Drag a colour left to lift it: less of that colour is cut to black" in b
    assert "lifted far enough its floor sits above zero" in b and "right to darken" in b
    assert "does not bring back detail that was already lost" in b
    assert "it only raises the floor" in b
    w = build_panel(next(s for s in path_stages() if s.id == "levels"))
    try:
        ends = [lbl.text() for lbl in w.findChildren(type(w.black_val))
                if lbl.objectName() == "sliderEnd"]
        assert ends == ["← lift", "darken →"], ends
        assert w.blue_slider.minimum() < 0 < w.blue_slider.maximum()
    finally:
        w.deleteLater()
    rng = np.random.default_rng(3)
    d = (0.2 + 0.05 * rng.standard_normal((40, 40, 3))).astype(np.float32)
    d[:20, :, 2] = 0.0                                  # blue lost before Levels
    img = AstroImage(np.clip(d, 0, 1), is_linear=False)
    plain = apply_levels(img, 0.02, 1.0, 1.0).data
    lifted = apply_levels(img, 0.02, 1.0, 1.0, (0.0, 0.0, -0.05)).data
    lost = lifted[:20, :, 2]
    assert lost.min() > 0 and plain[:20, :, 2].max() == 0     # the floor rose
    assert np.ptp(lost) == 0                                   # …and no detail came back
    np.testing.assert_array_equal(lifted[..., :2], plain[..., :2])
    # "less of that colour is cut to black" on a lift that stays above zero
    nearly = apply_levels(img, 0.2, 1.0, 1.0, (0.0, 0.0, -0.05)).data
    cut = apply_levels(img, 0.2, 1.0, 1.0).data
    assert (nearly[20:, :, 2] == 0).sum() < (cut[20:, :, 2] == 0).sum()
    darker = apply_levels(img, 0.02, 1.0, 1.0, (0.0, 0.0, 0.03)).data
    assert darker[20:, :, 2].mean() < plain[20:, :, 2].mean()


def test_levels_help_colour_sliders_hidden_on_mono(qtbot, tmp_path):
    from nocturne.core.image import AstroImage
    from tests.ui.test_levels_clip_aware_ui import _at_levels
    assert "On a mono picture there is only one colour, so they are hidden." in _plain(
        _body("levels"))
    rng = np.random.default_rng(0)
    mono = AstroImage((0.25 + 0.02 * rng.standard_normal((300, 400))).astype(np.float32),
                      is_linear=False)
    win = _at_levels(qtbot, tmp_path, mono)
    assert win._panel.levels_colour_box.isHidden()


def test_levels_help_a_recipe_auto_stops_at_the_same_limit():
    from nocturne.core.levels import AUTO, AUTO_V2, parse_levels_option
    from nocturne.recipe import deserialize_option
    assert "stopping at the same warning limit" in _plain(_body("levels"))
    p = parse_levels_option(deserialize_option("levels", AUTO))
    assert p.auto and p.version == AUTO_V2


def test_clipping_help_points_to_levels_and_a_colour_slider_lifts_amber():
    """'Levels is where you decide clipping … One colour amber? That colour's
    own slider in Levels lifts it.' On the fixture, a black dragged past Auto's
    stop crushes blue past the limit; lifting blue alone, within the slider's
    range, brings it back under, red and green unchanged."""
    from nocturne.core.inspect import CRUSHED_LIMIT
    from nocturne.core.levels import CrushProbe, auto_black
    from tests.core.test_levels_clip_aware import _stop_image
    b = _plain(_body("readout"))
    assert "Levels is where you decide clipping." in b
    assert "Auto black point stops at this warning, so it never turns a number amber" in b
    assert "That colour's own slider in Levels lifts it." in b
    img = _stop_image()
    probe = CrushProbe(img)
    darker = auto_black(img).black + 0.05                # gone darker on purpose
    before = probe.crushed(darker)
    assert before[2] >= CRUSHED_LIMIT
    after = probe.crushed(darker, offsets=(0.0, 0.0, -0.1))   # the slider's far left
    assert after[2] < CRUSHED_LIMIT and after[:2] == before[:2]


def test_auto_enhance_and_recipes_help_say_auto_levels_stops_at_the_warning():
    """Auto Enhance's Levels and a recipe's Auto are the button's Auto: on the
    fixture where it stops, the run's picture is the stopped black, not the
    unlimited one."""
    from nocturne.core.auto_enhance import AUTO_LEVELS, run_auto_plan
    from nocturne.core.levels import apply_levels, auto_black
    from nocturne.settings import Settings
    from tests.core.test_levels_clip_aware import _stop_image
    ae = _plain(_body("auto-enhance"))
    assert ("stopped short of it where it would crush a colour past the clipping warning "
            "— the same Auto black point as the Levels step") in ae
    rec = _plain(_body("recipes"))
    assert "it stops at the same clipping warning the button does" in rec
    assert "Nudge Black point, Midtones or White point afterwards" in rec
    img = _stop_image()
    a = auto_black(img)
    assert a.stopped
    (_n, _o, out), = run_auto_plan(img, [("levels", AUTO_LEVELS)], Settings()).results
    np.testing.assert_array_equal(out.data, apply_levels(img, a.black, 1.0, 1.0).data)


def test_levels_help_already_amber_means_no_more_regions_not_a_steady_number():
    """The read-out SHOWS the raw crushed fraction; Auto limits the STRUCTURAL
    figure, which only decides amber or grey. The old sentence ("no worse, give
    or take the last digit") was false: here blue arrives amber, Auto keeps
    its full black because the crushed regions barely move — and the shown
    blue number climbs from 0.07% to over 13%."""
    from nocturne.core.histogram import histogram
    from nocturne.core.inspect import CRUSH_INVISIBLE, CRUSHED_LIMIT
    from nocturne.core.inspect import channel_clipping_from_histogram as shown_fig
    from nocturne.core.levels import CrushProbe, apply_levels, auto_black
    from tests.core.test_levels_clip_aware import _amber_blue
    b = _plain(_body("levels"))
    assert "give or take the last digit" not in b and "comes out no worse" not in b
    assert "A colour that was already amber gets no more crushed regions to speak of" in b
    assert ("scattered single pixels can still be pushed to black, so the number shown, "
            "which counts every pixel, can still climb") in b
    img = _amber_blue(1)
    probe = CrushProbe(img)
    a = auto_black(img)
    was, now = probe.crushed(0.0)[2], probe.crushed(a.black)[2]
    assert was >= CRUSHED_LIMIT and now - was < CRUSH_INVISIBLE     # regions: held
    before = shown_fig(histogram(img)).lo[2]
    after = shown_fig(histogram(apply_levels(img, a.black, 1.0, 1.0))).lo[2]
    assert after > 100 * before, (before, after)                    # shown: climbs


def test_levels_help_an_already_stretched_picture_can_stop_earlier_than_the_warning():
    """A picture that opens already stretched has its arrival subtracted by the
    read-out; Auto judges the picture as it is (it must replay from its option
    and input alone), so it can stop where the warning would have stayed grey."""
    import nocturne.ui.main_window as mw
    from nocturne.core.export import display_rgb8
    from nocturne.core.histogram import histogram
    from nocturne.core.inspect import channel_clipping_from_histogram, structural_channel_clipping
    from nocturne.core.levels import apply_levels, auto_black
    from tests.core.test_levels_clip_aware import _amber_blue
    b = _plain(_body("levels"))
    assert "On a picture that opened already stretched" in b
    assert "so it can stop earlier than the warning would" in b
    img = _amber_blue(10)                      # opened as it is: the import IS this
    a = auto_black(img)
    assert a.stopped and a.black < a.candidate
    at_cand = apply_levels(img, a.candidate, 1.0, 1.0)
    lo, _hi = mw._clip_values(channel_clipping_from_histogram(histogram(at_cand)), None,
                              structural_channel_clipping(display_rgb8(at_cand)),
                              structural_channel_clipping(display_rgb8(img)))
    assert not any(v.over for v in lo), "the warning would have gone amber at the candidate"


def test_plate_solve_help_points_at_the_overlay_tips_and_they_say_the_same():
    # The help promises a tip on the labels and explains 15′; both must match the
    # code's own words, or the help drifts from what the pointer shows.
    from nocturne.core.annotate import scale_bar_tip
    from nocturne.core.annotation_layout import _dec_tip, _ra_tip
    body = _body("plate-solve")
    assert "Rest the pointer on it" in body
    assert "half the width of the full Moon" in body and "half the width of the full Moon" in scale_bar_tip(900)
    assert "15 arcminutes" in scale_bar_tip(900)
    assert "right ascension" in body and "right ascension" in _ra_tip("18h20m")
    assert "declination" in body and "declination" in _dec_tip("-14°")
