# tests/test_planner_page.py
"""Asserts against the BUILT page, and RUNS the shipped JavaScript under node.

The page half works the way tests/test_contribute_page.py does. The JS half
does not grep: `assert "<literal>" in js` passes for a file that never runs,
and one such test guarded the Moon icon through two reviews while the icon
drew every waning Moon mirrored -- it was pinned on `2 * fraction - 1`, the
one part of the expression that was never at risk. planner.js hands node its
pure half (`esc`, `icons`, `makeTempFormatters`) via module.exports,
planner-engine.js exports everything, and both are exercised here as code --
including the page's own temperature formatters, so nothing below reimplements
the rounding it is checking.
"""
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parent.parent / "site"
pytestmark = pytest.mark.skipif(
    not (SITE / "planner.html").exists(),
    reason="site/ is decoupled and gitignored -- only validated when present locally",
)


def _html():
    return (SITE / "planner.html").read_text(encoding="utf-8")


def test_the_noscript_explains_itself():
    """This is the first page on the site that requires JavaScript (design doc
    2.1). An empty panel would read as a broken page, so the fallback has to say
    what is needed and why."""
    h = _html()
    assert "<noscript>" in h
    assert "needs JavaScript" in h
    assert "location" in h.split("<noscript>")[1].split("</noscript>")[0]


def test_the_privacy_claim_is_on_the_page_itself():
    """At the point of the decision, not buried on another page.

    The claim must also be TRUE. It used to read "Nothing is sent anywhere until
    you press this" flat out, while a returning visitor's remembered location
    made planner.js fire both the target fetch and the Open-Meteo forecast on
    load. The behaviour is defensible -- they opted in once -- but the sentence
    was not, and an unqualified version of it must not come back.
    """
    h = _html()
    # The sentence names the BUTTON, so it has to track the button's label.
    # It said "press this" when the action sat directly beneath it; the action
    # moved up beside the location box (there was no visible affordance and
    # people were left pressing Enter on faith), and "this" then pointed at
    # nothing. A claim about what a control does must name the control.
    assert "until you press Plan tonight" in h
    import re
    labels = re.findall(r'<button type="submit"[^>]*>([^<]+)</button>', h)
    assert labels == ["Plan tonight"], f"one submit, and the copy names it: {labels}"
    assert "exactly as you typed it" in h, \
        "the geocoder gets the place name verbatim; say so at the point of entry"
    assert "next time you open this page" in h, \
        "a remembered location makes a request on load; the fine print must admit it"
    assert 'href="privacy.html"' in h


def test_both_telescopes_are_offered():
    """Spec 6 ships two presets and no more. The engine takes four numbers and
    never branches on which instrument it is, so a third is one row of data --
    but only these two have specs read off real sub headers."""
    h = _html()
    assert 'id="scope"' in h
    assert 'value="s30pro"' in h and "Seestar S30 Pro" in h
    assert 'value="s50"' in h and "Seestar S50" in h
    # Scoped to the <select>, not the whole document: "Other" appears in ordinary
    # prose and navigation all over this site, and asserting its absence from the
    # built page would fail the day a footer gains an "Other projects" link --
    # a red test for a change that has nothing to do with optics.
    select = h.split('id="scope"', 1)[1].split("</select>", 1)[0]
    assert "Dwarf" not in select and "Other" not in select, \
        "custom optics are deferred (design doc 13.3); do not ship an unverified spec"


def test_every_engine_asset_is_referenced():
    h = _html()
    for asset in ("vendor/astronomy.min.js", "planner-engine.js", "planner.js"):
        assert asset in h, asset


def test_privacy_page_documents_the_planner():
    p = (SITE / "privacy.html").read_text(encoding="utf-8")
    assert "session planner" in p.lower()
    assert "open-meteo" in p.lower()
    assert "rounded" in p.lower()


def test_the_privacy_page_admits_what_a_return_visit_does():
    """It said "no request of any kind is made before that" -- and then made two
    on load for anyone whose location was remembered.

    This page's whole argument is that a connection you discover for yourself is
    worth less than one you were told about, so a false sentence here costs more
    than the behaviour it was hiding. Both the remembered-location load and the
    verbatim place name sent to the geocoder must be stated.

    If this fails, the disclosure has drifted back behind the code.
    """
    p = (SITE / "privacy.html").read_text(encoding="utf-8")
    assert "On a first visit nothing" in p
    assert "as soon as it loads" in p, \
        "the return visit fetches before the visitor presses anything; say so"
    assert "exactly as you typed it" in p, \
        "the geocoder receives the place name verbatim, not just coordinates"


def test_the_clock_and_unit_defaults_are_chosen_not_inherited():
    """Deriving these from the browser locale was tried and failed in the
    wild: Andreas is in Sweden, his browser reports an English locale, and
    the page served him "09:30 PM". Astro is a 24-hour-clock hobby and the
    data is metric, so both defaults are picked outright.

    Asserted on the built page rather than on planner.js's source, because the
    FIRST option is what a browser selects before any script runs -- reorder
    these two <select>s and the default changes whatever the source says.
    """
    h = _html()
    for select_id, want in (("clock", "24"), ("units", "c")):
        block = h.split('id="%s"' % select_id, 1)[1].split("</select>", 1)[0]
        options = re.findall(r'value="([^"]+)"', block)
        assert options and options[0] == want, (
            f"#{select_id} offers {options} -- the first option is what the "
            f"browser selects before any script runs, so the default is now "
            f"{options[0] if options else None!r}, not {want!r}")


def test_a_fog_MARGIN_is_converted_as_a_difference_not_a_temperature():
    """2°C of margin is 3.6°F, not 35.6°F. The margin and the temperatures
    it is derived from live in the same sentence and convert by different
    rules, which is precisely why this is pinned.

    Runs the SHIPPED engine under node with a Celsius and then a Fahrenheit
    formatter PAIR injected into verdict(), and reads the rendered Fog factor
    back -- not a source-level guess at what the code does. The pair is the
    point: the engine used to be handed one function and sniff its output for
    an "F" to decide whether to apply 9/5 itself, which put a second copy of
    that arithmetic in the engine to drift against the page's.
    """
    if shutil.which("node") is None:
        pytest.skip("node is not installed; the JS engine cannot be exercised")
    engine = SITE / "planner-engine.js"
    script = """
      const E = require(%s);
      const win = { kind: 'astronomical', start: new Date('2026-09-20T20:00:00Z'),
                    end: new Date('2026-09-21T02:00:00Z') };
      const weather = { meanCloud: 10, maxCloud: 20, moonIllumination: 5,
                         moonUpMinutes: 0, fogMargin: 2, tempC: 11, dewC: 9 };
      const celsius = { temp: c => Math.round(c) + '\\u00b0C',
                        delta: d => (Math.round(d * 10) / 10 || 0) + '\\u00b0C' };
      const fahrenheit = { temp: c => Math.round(c * 9 / 5 + 32) + '\\u00b0F',
                           delta: d => (Math.round(d * 9 / 5 * 10) / 10 || 0) + '\\u00b0F' };
      const fogValue = fmt => E.verdict(win, weather, [], fmt)
        .factors.find(f => f.label === 'Fog').value;
      console.log(JSON.stringify({ c: fogValue(celsius), f: fogValue(fahrenheit) }));
    """ % json.dumps(str(engine))
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                       cwd=SITE.parent, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["c"].startswith("2°C margin"), out["c"]
    assert out["f"].startswith("3.6°F margin"), out["f"]
    assert "35.6" not in out["f"], \
        "the margin must convert by the 9/5 ratio alone, never the +32 offset"


# --- Running the shipped JavaScript -------------------------------------------

ENGINE = SITE / "planner-engine.js"
PLANNER = SITE / "planner.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not installed; the shipped JavaScript cannot be exercised")


def _node(script, tz=None):
    """Run a snippet against the shipped files, optionally under a given TZ."""
    env = dict(os.environ)
    if tz is not None:
        env["TZ"] = tz
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                       cwd=SITE.parent, timeout=60, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _req(path):
    return "require(%s)" % json.dumps(str(path))


# The two arcs of the Moon path both span the vertical diameter of the 26x26
# viewBox, so each is a half-ellipse centred on (13, 13) with ry = 12 and the
# sweep flag choosing which half. That is plain SVG semantics, not a second
# copy of the icon's logic: nothing here knows about phases, only about arcs.
_MOON_D = re.compile(
    r"M 13 1 A ([\d.]+) 12 0 0 ([01]) 13 25 A ([\d.]+) 12 0 0 ([01]) 13 1 Z")


def _lit_region(svg):
    """Return (centroid x, area) of the lit region actually drawn."""
    d = re.search(r'<path d="([^"]+)" fill="#ece6d2"', svg)
    assert d, "no lit-limb path in the rendered Moon:\n" + svg
    m = _MOON_D.fullmatch(d.group(1))
    assert m, "unexpected Moon path shape: " + d.group(1)
    rx1, s1, rx2, s2 = float(m[1]), int(m[2]), float(m[3]), int(m[4])
    pts, N = [], 400
    # Arc 1 runs top -> bottom, where sweep=1 is the RIGHT half; arc 2 runs
    # bottom -> top, where the same half is sweep=0.
    for rev, rx, side in ((False, rx1, 1 if s1 == 1 else -1),
                          (True, rx2, 1 if s2 == 0 else -1)):
        for k in range(N + 1):
            th = math.pi * ((1 - k / N) if rev else (k / N))
            pts.append((13 + side * rx * math.sin(th), 13 - 12 * math.cos(th)))
    area = cx = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
    area /= 2
    return cx / (6 * area), abs(area)


@needs_node
@pytest.mark.parametrize("fraction", [0.25, 0.75])
def test_the_moon_is_drawn_waxing_OR_waning_not_always_waxing(fraction):
    """THE defect this file exists to catch.

    |2f-1| and the sweep flip give the Moon its SHAPE. Nothing carried its
    DIRECTION: moonConditions() returned only {illumination, upMinutes}, arc 1
    was hard-coded to the right semicircle, and so the lit limb sat on the right
    every night of the month. Northern-hemisphere convention is that a waxing
    Moon is lit on the right -- so for roughly half of every month the icon was
    mirrored, beside a percentage that was still correct. That is why it looked
    fine, and why the old grep on "2 * fraction - 1" could never see it.

    Both a crescent and a gibbous are checked: they take different branches for
    the inner arc, and a fix that flipped only one would pass on the other.

    This reads the geometry of the path the icon actually emits -- which side of
    the disc the lit area sits on, and how much of the disc it covers -- rather
    than asserting on the source text that produces it.
    """
    P = _node("const P = %s; console.log(JSON.stringify({"
              "  waxing: P.icons.moon(%r, true, true),"
              "  waning: P.icons.moon(%r, true, false) }));"
              % (_req(PLANNER), fraction, fraction))
    # Compared on the PATH, not the whole <svg>: the accessible label also says
    # which way the Moon is going, so an icon that draws one shape and labels it
    # two ways still produces two different strings. The drawing is the claim.
    paths = [re.search(r'<path d="([^"]+)" fill="#ece6d2"', P[k]).group(1)
             for k in ("waxing", "waning")]
    assert paths[0] != paths[1], (
        "the same shape is drawn for waxing and waning -- direction is not "
        "reaching the geometry, so half of every month renders mirrored under a "
        "label that still reads correctly: " + paths[0])

    wax_x, wax_area = _lit_region(P["waxing"])
    wan_x, wan_area = _lit_region(P["waning"])

    assert wax_x > 13, f"a waxing Moon must be lit on the RIGHT; centroid x={wax_x:.2f}"
    assert wan_x < 13, f"a waning Moon must be lit on the LEFT; centroid x={wan_x:.2f}"
    # An exact mirror about the disc's vertical axis, not merely "different".
    assert abs((wax_x - 13) + (wan_x - 13)) < 1e-6, (wax_x, wan_x)
    # ...and mirroring must not have changed how much of the Moon is lit.
    full = math.pi * 12 * 12
    assert abs(wax_area / full - fraction) < 1e-3, wax_area / full
    assert abs(wan_area / full - fraction) < 1e-3, wan_area / full


@needs_node
def test_the_engine_actually_reports_which_way_the_moon_is_going():
    """The icon can only draw a direction it is given.

    MoonPhase() is the Sun-Moon elongation: 0 new, 90 first quarter, 180 full,
    270 last quarter -- so waxing is < 180. Two real windows a fortnight apart
    in 2026 straddle full Moon, and moonConditions() must disagree about them.

    If this fails, `waxing` is a constant and the icon test above is being fed a
    hard-coded direction.
    """
    out = _node("""
      const E = %s;
      const w = iso => ({ kind: 'astronomical',
                          start: new Date(iso + 'T20:00:00Z'),
                          end: new Date(iso + 'T23:00:00Z') });
      const at = iso => {
        const m = E.moonConditions(w(iso), 59.53, 18.08);
        return { waxing: m.waxing, illumination: Math.round(m.illumination) };
      };
      console.log(JSON.stringify({ before: at('2026-09-20'), after: at('2026-10-04') }));
    """ % _req(ENGINE))
    assert out["before"]["waxing"] is True, out["before"]
    assert out["after"]["waxing"] is False, out["after"]
    # Both are partly lit, so illumination alone cannot tell them apart -- which
    # is precisely the information the icon was missing.
    for side in ("before", "after"):
        assert 5 < out[side]["illumination"] < 95, out[side]


@needs_node
def test_the_wind_arrow_rotation_is_the_bearing_it_was_given():
    """A rotated arrow with no real bearing behind it would be decoration
    pretending to be data (task-4 brief). The rotation and the label must both
    come from the number passed in, and the label must carry the FROM -- a
    rotation alone reads either way round."""
    out = _node("const P = %s; console.log(JSON.stringify("
                "[0, 90, 217.4].map(b => P.icons.wind(b))));" % _req(PLANNER))
    for bearing, svg in zip((0, 90, 217), out):
        assert "rotate(%d" % bearing in svg, svg
        assert 'aria-label="wind from %d' % bearing in svg, svg


@needs_node
def test_esc_neutralises_markup_and_leaves_ordinary_place_names_readable():
    """Place names arrive from Open-Meteo's geocoder and target names from
    planner-targets.json, and both are interpolated into innerHTML. The second
    is first-party so it is not a vector -- but the common-name overlay in it is
    hand-written, and an ampersand in a name is the likely way this bites.

    An escaper that mangles O'Brien or Ma & Pa into double-escaped noise is its
    own defect, so both directions are asserted.
    """
    cases = ["<img src=x onerror=alert(1)>", "O'Brien, Cork, IE", "Ma & Pa, TX"]
    out = _node("const P = %s; console.log(JSON.stringify(%s.map(P.esc)));"
                % (_req(PLANNER), json.dumps(cases)))
    assert "<" not in out[0] and ">" not in out[0], out[0]
    assert out[0] == "&lt;img src=x onerror=alert(1)&gt;", out[0]
    assert out[1] == "O&#39;Brien, Cork, IE", out[1]
    assert out[2] == "Ma &amp; Pa, TX", out[2]
    assert "&amp;amp;" not in out[2], "double-escaped; the name renders as noise"


# --- The fog margin -----------------------------------------------------------

_CLEAR_NIGHT = """
  const win = { kind: 'astronomical', start: new Date('2026-09-20T20:00:00Z'),
                end: new Date('2026-09-21T02:00:00Z') };
  const clear = extra => Object.assign(
    { meanCloud: 10, maxCloud: 20, moonIllumination: 5, moonUpMinutes: 0 }, extra);
  const usable = [{ usableMinutes: 180 }];
"""


def _verdicts(cases, units=None):
    """Run verdict() over a {name: weatherExtras} map on an otherwise fine night.

    `units` picks planner.js's OWN formatters -- the ones the page hands the
    engine -- rather than a copy of them written here. A test that reimplements
    the rounding it is checking proves only that the test agrees with itself.
    """
    fmt = ("undefined" if units is None
           else "%s.makeTempFormatters(%s)" % (_req(PLANNER), json.dumps(units)))
    return _node("""
      const E = %s;
      %s
      const cases = %s;
      const out = {};
      for (const k of Object.keys(cases)) {
        const v = E.verdict(win, clear(cases[k]), usable, %s);
        const fog = v.factors.find(f => f.label === 'Fog');
        out[k] = { headline: v.headline, limiting: v.limiting,
                   fog: fog && fog.value, concern: fog && fog.concern };
      }
      console.log(JSON.stringify(out));
    """ % (_req(ENGINE), _CLEAR_NIGHT, json.dumps(cases), fmt))


@needs_node
def test_a_NEGATIVE_fog_margin_gates_the_headline():
    """Fog was declared session-ending and then gated nothing.

    A clear sky, usable targets and a -3C margin returned the headline "worth
    going out" directly above the line "-3C margin -- expect the optics to fog".
    Cloud gated to skip, Moon gated to marginal, fog gated nothing at all.

    The bar is the SIGN, not the warning threshold: a close margin is something
    to watch, a negative one means the air is past its dew point and the
    corrector plate is already wet.
    """
    out = _verdicts({"wet": {"fogMargin": -3, "tempC": 4, "dewC": 7},
                     "just_under": {"fogMargin": -0.4, "tempC": 4, "dewC": 4.4}})
    for key in ("wet", "just_under"):
        assert out[key]["headline"] == "marginal", (
            f"{key}: a negative fog margin left the headline at "
            f"{out[key]['headline']!r} above {out[key]['fog']!r}")
        assert "dew point" in out[key]["limiting"], out[key]["limiting"]
        assert out[key]["concern"] is True


@needs_node
def test_a_close_but_POSITIVE_fog_margin_warns_without_gating():
    """The other half of the ruling, and the one that keeps the gate honest.

    Under 2C is a warning -- the threshold is provisional and unmeasured, see
    FOG_MARGIN_WARN -- but the optics are not wet yet, so it must not take the
    verdict down with it. If this starts failing, an unmeasured constant has
    quietly become a decision.
    """
    out = _verdicts({"close": {"fogMargin": 1.5, "tempC": 6, "dewC": 4.5},
                     "comfortable": {"fogMargin": 6, "tempC": 10, "dewC": 4}})
    assert out["close"]["headline"] == "worth going out", out["close"]
    assert out["close"]["concern"] is True, "under 2C must still be flagged"
    assert "expect the optics to fog" in out["close"]["fog"]
    assert out["comfortable"]["headline"] == "worth going out"
    assert out["comfortable"]["concern"] is False
    assert "dew point 4" in out["comfortable"]["fog"], out["comfortable"]["fog"]


@needs_node
def test_a_missing_forecast_says_so_rather_than_guessing():
    """Weather is optional; astronomy is not. With no forecast at all the page
    must decline to answer rather than fall through to "worth going out" on the
    strength of the darkness alone -- and it must not claim a fog margin it does
    not have."""
    out = _node("""
      const E = %s;
      %s
      const v = E.verdict(win, null, usable);
      console.log(JSON.stringify({
        headline: v.headline, limiting: v.limiting,
        labels: v.factors.map(f => f.label),
      }));
    """ % (_req(ENGINE), _CLEAR_NIGHT))
    assert out["headline"] == "can't say", out
    assert "fetch" in out["limiting"], out["limiting"]
    assert "Fog" not in out["labels"], "a margin was invented out of no forecast"
    assert "Moon" not in out["labels"], \
        "the forecast branch returns early; it must not half-render the rest"


@needs_node
def test_a_tiny_NEGATIVE_margin_reads_the_same_in_both_units():
    """Math.round(-0.05) is -0 in JavaScript, which stringifies as "0".

    So a -0.05C margin rendered "0C margin" while the same instant in F rendered
    "-0.1F": two units disagreeing on screen about the same number, one of them
    hiding the sign that now decides the headline. Rounding once in Celsius and
    converting the rounded figure is what keeps them in step.
    """
    cases = {"tiny": {"fogMargin": -0.05, "tempC": 4, "dewC": 4.05},
             "real": {"fogMargin": -0.4, "tempC": 4, "dewC": 4.4}}
    out = _verdicts(cases, units="f")
    celsius = _verdicts(cases, units="c")
    for key in ("tiny", "real"):
        neg_c = celsius[key]["fog"].lstrip().startswith("-")
        neg_f = out[key]["fog"].lstrip().startswith("-")
        assert neg_c == neg_f, (
            f"{key}: Celsius reads {celsius[key]['fog']!r} but Fahrenheit reads "
            f"{out[key]['fog']!r} -- the two units disagree about the sign")
    assert celsius["tiny"]["fog"].startswith("0\u00b0C margin"), celsius["tiny"]["fog"]
    assert out["tiny"]["fog"].startswith("0\u00b0F margin"), out["tiny"]["fog"]
    # A margin big enough to survive rounding keeps its sign in both scales.
    assert celsius["real"]["fog"].startswith("-0.4\u00b0C"), celsius["real"]["fog"]
    assert out["real"]["fog"].startswith("-0.7\u00b0F"), out["real"]["fog"]
    # The headline is decided by the RAW margin, never by this rounded string.
    assert celsius["tiny"]["headline"] == "marginal", celsius["tiny"]


# --- The factor row: icons and the slot they sit in ---------------------------


@needs_node
def test_every_factor_row_has_an_icon_and_they_all_fit_one_slot():
    """Three of the six rows had no icon at all.

    Cloud, Wind and Moon rendered with one and had their label pushed right;
    Darkness, Fog and Targets started flush left -- and the three that DID have
    one pushed it by three different amounts, because the cloud is 34 wide, the
    arrow was 22 and the Moon is 26. Six stacked cards, four different left
    edges, which reads as a rendering fault rather than a choice.

    Two halves, and this pins both:

    * every label the engine can put in the factors array has a builder here,
      and each one produces a real labelled SVG -- role, aria-label and a
      <title>, the way the originals do;
    * the widest of them still fits the fixed slot in styles.css.

    The second is a genuine cross-check and not a grep: the icon widths are read
    off the rendered markup, the slot width off the stylesheet, and an icon that
    outgrew the box would fail here rather than in a browser. What it cannot see
    is the rendered layout -- that the slot is emitted on rows with no icon is a
    DOM fact, and nothing in this suite can reach it.
    """
    out = _node("""
      const P = %s;
      console.log(JSON.stringify({
        darknessDark: P.icons.darkness(true),
        darknessNone: P.icons.darkness(false),
        moon: P.icons.moon(0.69, true, true),
        cloud: P.icons.cloud(34),
        fog: P.icons.fog('close to the dew point'),
        wind: P.icons.wind(217),
        targets: P.icons.targets(),
      }));
    """ % _req(PLANNER))

    widest = 0
    for name, svg in out.items():
        assert 'role="img"' in svg, name
        label = re.search(r'aria-label="([^"]+)"', svg)
        assert label and label.group(1).strip(), f"{name} has no accessible label"
        assert "<title>" in svg, f"{name} has no <title>"
        assert re.search(r'viewBox="0 0 (22|26) (22|26)"', svg), f"{name}: odd viewBox"
        widest = max(widest, int(re.search(r'width="(\d+)"', svg).group(1)))

    # The Sun must actually MOVE between the two darkness states. Compared on
    # the drawn circle and not the whole <svg>, for the same reason the Moon
    # test compares paths: the accessible label also says which night it is, so
    # an icon pinned to one geometry and labelled two ways still yields two
    # different strings. Mutation found this assertion passing on exactly that.
    discs = [re.search(r"<circle[^>]*cy=\"([\d.]+)\"[^>]*>", out[k]).group(1)
             for k in ("darknessDark", "darknessNone")]
    assert discs[0] != discs[1], (
        f"the Sun is drawn at cy={discs[0]} for both a dark night and a night "
        f"with no real darkness; the icon says the same thing about either")
    # ...and it must move the right way: below the horizon when it is dark.
    horizon = re.search(r"M[\d.]+ ([\d.]+) H", out["darknessDark"]).group(1)
    assert float(discs[0]) > float(horizon) > float(discs[1]), (
        f"disc centres {discs} straddle the horizon at {horizon} the wrong way "
        f"round -- the dark night must be the one with the Sun below the line")

    css = (SITE / "styles.css").read_text(encoding="utf-8")
    rule = re.search(r"\.factors li \.ficon\s*\{([^}]*)\}", css)
    assert rule, "the fixed icon slot is gone from styles.css; the labels will "\
                 "go back to four different left edges"
    basis = re.search(r"flex:\s*0\s+0\s+(\d+)px", rule.group(1))
    assert basis, rule.group(1)
    assert int(basis.group(1)) >= widest, (
        f"the widest icon is {widest}px but the slot reserves "
        f"{basis.group(1)}px -- it will push its own label out of line")


def test_the_primary_action_uses_the_sites_own_button():
    """"Plan tonight" shipped as a bare <button>: default UA chrome, default
    font, grey, on a page that is otherwise fully themed. It is the page's
    primary action and it looked like a mistake.

    It now carries the site's own .btn/.btn-primary, rather than a treatment
    invented for this one page. .btn had only ever landed on an <a>, so it also
    needed `font-family: inherit` and `cursor: pointer` -- both inert on an
    anchor -- for a real <button> to pick it up.
    """
    h = _html()
    form = h.split('id="where"', 1)[1].split("</form>", 1)[0]
    submit = re.search(r"<button[^>]*type=\"submit\"[^>]*>", form)
    assert submit, form
    assert "btn" in submit.group(0) and "btn-primary" in submit.group(0), submit.group(0)

    css = (SITE / "styles.css").read_text(encoding="utf-8")
    btn = re.search(r"\n\.btn\s*\{([^}]*)\}", css)
    assert btn, ".btn is gone from styles.css"
    assert "font-family: inherit" in btn.group(1), \
        "without it a <button> keeps the UA font and the label looks wrong"
    assert "cursor: pointer" in btn.group(1)


# --- What the page PRINTS belongs to the location, not to the machine ---------
#
# tests/test_planner_engine.py already pins this for darkWindow: the night the
# engine computes must not depend on where the laptop thinks it is. It did not
# reach the display layer, and the display layer had the same bug -- the third
# in this family, after the solar-noon anchor and Open-Meteo's timestamps.

CLOCK_TZ_CASES = ["Europe/Stockholm", "Pacific/Auckland", "America/Los_Angeles", "UTC"]

# Malé. Far from every runtime zone below, and on a half-hour-free offset
# (UTC+5) that none of them share.
MALE_LON = 73.51
MALE_ZONE = "Indian/Maldives"
DARK_START = "2026-09-20T14:16:00Z"
DARK_END = "2026-09-20T23:46:00Z"


def _clock(zone, tz):
    """Format the two instants through the SHIPPED clock, under a given TZ."""
    return _node("""
      const P = %s;
      const z = %s;
      const clock = P.makeClock(z, %s, false);
      const machine = d => d.toLocaleTimeString('en-GB',
        { hour: '2-digit', minute: '2-digit', hour12: false });
      const a = new Date(%s), b = new Date(%s);
      console.log(JSON.stringify({
        rendered: clock(a) + '-' + clock(b),
        machine: machine(a) + '-' + machine(b),
      }));
    """ % (_req(PLANNER), json.dumps(zone), MALE_LON,
           json.dumps(DARK_START), json.dumps(DARK_END)), tz=tz)


@needs_node
def test_times_render_in_the_LOCATIONS_zone_not_the_machines():
    """Planning Malé from Sweden printed a dark window of 16:16-01:46 for a
    night that runs 19:16-04:46. Three hours out, across the "Dark from" line
    and every target card, because fmt() called toLocaleTimeString with no
    timeZone and got the laptop's.

    It is invisible whenever you plan where you are, which is how it survived
    two reviews and a rendering pass: you have to type somewhere far away
    before the page is wrong in a way you can see.

    Four runtime zones, one instant, one location. The rendered time must be
    the same in all four and must be Malé's.
    """
    got = {tz: _clock(MALE_ZONE, tz) for tz in CLOCK_TZ_CASES}

    rendered = {tz: g["rendered"] for tz, g in got.items()}
    assert len(set(rendered.values())) == 1, (
        "the page prints a different time depending on the machine's clock:\n"
        + "\n".join(f"  TZ={tz}: {v}" for tz, v in rendered.items()))
    assert set(rendered.values()) == {"19:16-04:46"}, rendered

    # And the harness is genuinely sensitive: the machine-zone reading, which
    # is what the page used to print, really does vary across these four. If
    # this ever stops being true the test above has quietly stopped proving
    # anything, because every zone would agree by accident.
    machine = {g["machine"] for g in got.values()}
    assert len(machine) == len(CLOCK_TZ_CASES), (
        f"the runtime zones no longer disagree ({machine}); pick zones that do, "
        f"or this test cannot tell a fixed clock from a broken one")
    assert "16:16-01:46" in machine, \
        "Europe/Stockholm should still reproduce the original wrong reading"


@needs_node
def test_with_no_forecast_the_clock_falls_back_to_SOLAR_time_not_the_browser():
    """The astronomy works with the network down and times are still shown in
    that state, so a fallback to the machine's zone would put the bug back
    exactly where the visitor cannot notice it.

    Mean solar time at the longitude -- one degree to four minutes, the same
    arithmetic the engine anchors its sample window with -- can sit about 1.5h
    from civil time. A browser zone can sit 12h out. For Malé the gap is six
    minutes.
    """
    got = {tz: _clock(None, tz) for tz in CLOCK_TZ_CASES}
    rendered = {g["rendered"] for g in got.values()}
    assert len(rendered) == 1, (
        "the no-forecast clock still reads the machine:\n"
        + "\n".join(f"  TZ={tz}: {g['rendered']}" for tz, g in got.items()))
    solar = rendered.pop()
    assert solar == "19:10-04:40", solar
    # Within the stated bound of civil time, and nowhere near a browser zone.
    assert abs(int(solar[:2]) * 60 + int(solar[3:5]) - (19 * 60 + 16)) <= 90, solar
    for tz, g in got.items():
        if g["machine"] != solar:
            break
    else:                                   # pragma: no cover - guards the guard
        raise AssertionError("no runtime zone disagrees; the test proves nothing")


@needs_node
def test_a_zone_the_provider_got_wrong_costs_the_zone_not_the_page():
    """An unknown IANA name is a RangeError out of toLocaleTimeString, and it
    would be thrown once per timestamp from inside render(). makeClock probes
    the zone once and drops to solar time if it is bad, so a provider typo
    degrades the clock rather than blanking the results."""
    out = _node("""
      const P = %s;
      const d = new Date(%s);
      console.log(JSON.stringify({
        bad: P.makeClock('Nowhere/Fake', %s, false)(d),
        good: P.makeClock('Indian/Maldives', %s, false)(d),
        twelve: P.makeClock('Indian/Maldives', %s, true)(d),
      }));
    """ % (_req(PLANNER), json.dumps(DARK_START), MALE_LON, MALE_LON, MALE_LON),
        tz="Europe/Stockholm")
    assert out["bad"] == "19:10", out            # solar, not a crash and not 16:16
    assert out["good"] == "19:16", out
    assert out["twelve"].lower().replace("\u202f", " ") == "07:16 pm", out["twelve"]


def test_the_cloud_icon_does_not_claim_rain_the_page_cannot_see():
    """Andreas, on the live page: *"The cloud icon shows rain under it but the
    planner does not seem to consider rain or any percipitation at all or?"*

    He was right. The shape came from sky.stehn.com with three blue strokes
    beneath it, and nothing precipitation-shaped was ever requested — the
    drawing asserted a fact the page did not have. That is the same test the
    wind arrow had to pass (it gained a real bearing rather than rotating
    decoratively) and this one had quietly failed.

    The strokes did not go; they MOVED, to the row that is about rain.
    """
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "precipitation_probability" in js, "the forecast must actually ask for rain"

    import re
    cloud = re.search(r"cloud: function[\s\S]*?\n    \},", js).group(0)
    rain = re.search(r"rain: function[\s\S]*?\n    \},", js).group(0)
    assert "#5b8dd9" not in cloud, "the cloud must not draw rain it knows nothing about"
    assert "#5b8dd9" in rain, "the rain row is where the rain strokes belong"


def test_rain_gates_the_verdict_but_wind_does_not():
    """Rain needs no tuned constant to gate on — there is no judgement call in
    "it is forecast to rain on the telescope" — while no measured "this is
    windy" threshold exists, and CLAUDE.md forbids inventing one. So the two
    factors deliberately behave differently, and that asymmetry is the point.
    """
    eng = (SITE / "planner-engine.js").read_text(encoding="utf-8")
    assert "raining" in eng and "rain is forecast during the dark hours" in eng
    wind = eng[eng.index("label: 'Wind'"):]
    assert "concern: false" in wind[:400], "wind must not flag a guessed threshold"


def test_the_verdict_is_not_the_same_colour_whatever_it_says():
    """It read in --ink for every outcome, so "skip" and "worth going out" were
    typographically identical and the answer had to be read to be seen — on a
    page whose entire job is one word. Colour is never alone: the word says it,
    and the limiting factor beneath says why.
    """
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    assert "verdict v-" in js
    for cls in ("v-worth-going-out", "v-marginal", "v-skip", "v-can-t-say"):
        assert f".verdict.{cls}" in css, cls


def test_a_target_row_opens_to_show_more():
    """His ask: collapsed rows show what they show now plus a thumbnail;
    expanded they describe the target. <details> so the browser owns the
    state, the keyboard and the screen reader rather than our own JavaScript.
    """
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "<details class=\"target\"" in js
    assert "t-thumb" in js, "the thumbnail slot must exist even before images do"
    for fact in ("Type", "Size", "Framing", "Highest", "Worth giving it"):
        assert f"'{fact}'" in js or f'"{fact}"' in js, fact


def test_place_choices_render_inside_the_form_above_the_telescope():
    """His report 2026-10-03: on a phone 'Which one?' landed below the telescope
    and preferences, out of sight. The slot sits right after Use my location."""
    html = _html()
    hits, scope = html.find('id="hits"'), html.find('id="scope"')
    locate = html.find('id="locate-row"')
    assert -1 < locate < hits < scope, (locate, hits, scope)
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "getElementById('hits')" in js


def test_the_sky_choice_is_offered_with_plain_descriptions():
    html = _html()
    assert 'id="sky"' in html
    for value in ("city", "suburban", "rural", "dark"):
        assert f'value="{value}"' in html, value
    assert "Milky Way" in html, "skies are described by what you can see"


def test_a_preference_saved_before_sky_existed_falls_back_to_suburban():
    """Review Focus 3: a returning visitor's prefs have no `sky`."""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "prefs.sky = SKIES.indexOf(savedPrefs.sky) >= 0 ? savedPrefs.sky : 'suburban'" in js


def test_the_factor_rows_fold_behind_details():
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert '<details class="conditions"' in js
    assert "E.lean(" in js


@needs_node
def test_photos_promoted_to_a_merged_id_still_show_on_the_parent():
    """Review Focus 2: live rows exist for NGC6995 and IC4703."""
    out = _node(f"""
      const P = {_req(PLANNER)};
      global.window = {{ PLANNER_IMAGES: {{ NGC6992: [{{thumb:'a'}}], NGC6995: [{{thumb:'b'}}] }} }};
      console.log(JSON.stringify(P.imagesFor({{id:'NGC6992', also:['NGC6995']}}).map(i => i.thumb)));
    """)
    assert out == ["a", "b"]


@needs_node
def test_filter_advice_follows_the_kind_of_light():
    out = _node(f"""
      const P = {_req(PLANNER)};
      console.log(JSON.stringify(['HII','SNR','G','RfN','OCl'].map(P.filterAdvice)));
    """)
    assert out[0] == out[1] and "LP filter" in out[0]
    assert "No filter" in out[2] and out[2] == out[3]
    assert "No filter" in out[4]


def test_every_sample_link_points_at_an_anchor_that_exists():
    import re
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    page = (SITE / "sample-data.html").read_text(encoding="utf-8")
    anchors = re.findall(r"'sample-data\.html#([a-z0-9-]+)'", js)
    assert len(anchors) == 6, anchors
    for a in anchors:
        assert f'id="{a}"' in page, a


def test_the_card_shows_constellation_grade_moons_and_a_bar():
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    for needle in ("t-const", "t-grade", "E.moonsText(", "t-bar", "Worth it tonight",
                   "more under darker skies", "too small for your"):
        assert needle in js, needle
    # ONE inline style exists already (the wind arrow's rotation, planner.js:108,
    # pinned by its own test). No new ones: geometry goes through el.style (CSP).
    assert js.count('style="') == 1, "geometry is set through el.style, not inline"


@needs_node
def test_the_pick_label_follows_the_verdict():
    """Ruling (Task 5 review): no "Worth it tonight" under a skip verdict."""
    out = _node(f"""
      const P = {_req(PLANNER)};
      console.log(JSON.stringify(['worth going out', 'marginal', 'skip', "can't say"].map(P.pickLabel)));
    """)
    assert out == ["Worth it tonight", "Best tonight", "", ""]
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "var pick = pickLabel(v.headline);" in js
    assert "!t.revealed && pick" in js, "a revealed card never carries the label"


@needs_node
def test_nothing_worth_pointing_at_only_when_nothing_is_held_back_either():
    out = _node(f"""
      const P = {_req(PLANNER)};
      console.log(JSON.stringify([
        P.showNothingLine(0, 0, 'astronomical'),
        P.showNothingLine(0, 3, 'astronomical'),
        P.showNothingLine(2, 0, 'astronomical'),
        P.showNothingLine(0, 0, 'none')]));
    """)
    assert out == [True, False, False, False]
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "if (showNothingLine(ranked.length, hidden, win.kind))" in js


@needs_node
def test_a_pressed_reveal_button_offers_to_hide():
    out = _node(f"""
      const P = {_req(PLANNER)};
      console.log(JSON.stringify([
        P.revealText('darker', 4, '', false), P.revealText('darker', 4, '', true),
        P.revealText('small', 2, 'Seestar S50', false), P.revealText('small', 2, 'Seestar S50', true)]));
    """)
    assert out == ["4 more under darker skies &rarr;", "Hide the 4 under darker skies",
                   "2 more are too small for your Seestar S50 &rarr;",
                   "Hide the 2 too small for your Seestar S50"]


def test_show_all_sits_before_the_revealed_cards():
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    more, revealed = js.find("id=\"more\""), js.find("html += revealed.map(card)")
    assert -1 < js.find("html += shown.map(card)") < more < revealed


@needs_node
def test_the_same_photo_under_parent_and_merged_id_shows_once():
    """Final review B4: one photo was promoted under NGC6992 AND NGC6995."""
    out = _node(f"""
      const P = {_req(PLANNER)};
      global.window = {{ PLANNER_IMAGES: {{
        NGC6992: [{{full:'x.jpg', thumb:'a'}}, {{full:'y.jpg', thumb:'b'}}],
        NGC6995: [{{full:'x.jpg', thumb:'a2'}}, {{full:'z.jpg', thumb:'c'}}] }} }};
      console.log(JSON.stringify(P.imagesFor({{id:'NGC6992', also:['NGC6995']}}).map(i => i.thumb)));
    """)
    assert out == ["a", "b", "c"]


@needs_node
def test_the_weather_and_moon_lines_under_the_verdict():
    """Spec D7: one weather line and one Moon line, from numbers already computed."""
    out = _node(f"""
      const P = {_req(PLANNER)};
      const win = {{ start: new Date(0), end: new Date(600 * 60000) }};
      console.log(JSON.stringify({{
        full: P.weatherLine({{ meanCloud: 40.4, rainChance: 5, windMin: 1.2, windMax: 3.4 }}),
        wet: P.weatherLine({{ meanCloud: 80, rainChance: 70 }}),
        some: P.weatherLine({{ meanCloud: 10, rainChance: 30, windMin: 2, windMax: 2.2 }}),
        partial: P.weatherLine({{ meanCloud: 12 }}),
        missing: P.weatherLine({{ moonIllumination: 40, moonUpMinutes: 0, cloudReason: 'unreachable' }}),
        none: P.weatherLine(null),
        most: P.moonLine({{ moonIllumination: 46.2, moonUpMinutes: 400 }}, win),
        all: P.moonLine({{ moonIllumination: 90, moonUpMinutes: 590 }}, win),
        part: P.moonLine({{ moonIllumination: 20, moonUpMinutes: 60 }}, win),
        down: P.moonLine({{ moonIllumination: 46, moonUpMinutes: 0 }}, win),
        nomoon: P.moonLine(null, win) }}));
    """)
    assert out["full"] == "40% cloud · no rain · 1–3 m/s wind"
    assert out["wet"] == "80% cloud · rain likely"
    assert out["some"] == "10% cloud · 30% chance of rain · 2 m/s wind"
    assert out["partial"] == "12% cloud", "unavailable parts are left out"
    assert out["missing"] == "" and out["none"] == "", "no forecast, no weather line"
    assert out["most"] == "Moon 46% lit, up most of the night"
    assert out["all"] == "Moon 90% lit, up all night"
    assert out["part"] == "Moon 20% lit, up for part of the night"
    assert out["down"] == "Moon below the horizon"
    assert out["nomoon"] == ""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    wx, moon = js.find("esc(wxText)"), js.find("esc(moonText)")
    lean, dark = js.find("esc(leanText)"), js.find("'<p>Dark from '")
    assert -1 < js.find("esc(v.headline)") < wx < moon < lean < dark, (wx, moon, lean, dark)


def test_place_lookup_answers_land_under_the_search_box():
    """Final review B1, m2, m3: 'Which one?' and both lookup failures render into
    #hits and scroll into view; choosing clears the place in play so a settings
    change cannot redraw the previous place under the choices."""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    start = js.find("document.getElementById('where').addEventListener('submit'")
    handler = js[start:js.find("document.getElementById('scope')", start)]
    assert "if (slot.scrollIntoView) slot.scrollIntoView({ block: 'nearest' });" in handler
    for msg in ("Could not find that", "Could not reach the place lookup", "Which one?"):
        i = handler.find(msg)
        assert i > -1, msg
        assert handler.rfind("showInSlot(", 0, i) > handler.rfind("out.innerHTML", 0, i), msg
    assert "out.innerHTML" not in handler, "lookup answers never go to #result"
    choose = handler.find("if (hits.length > 1)")
    assert -1 < choose < handler.find("activeLocation = null;") < handler.find("Which one?")


def test_sky_options_are_short_and_describe_themselves_below():
    """Final review B2: long option text truncated on a phone."""
    html = _html()
    sel = html[html.find('<select id="sky"'):]
    sel = sel[:sel.find("</select>")]
    labels = re.findall(r'<option value="(\w+)" data-desc="([^"]+)">([^<]+)</option>', sel)
    assert [(v, l) for v, _, l in labels] == [("city", "City"), ("suburban", "Suburban"),
                                              ("rural", "Rural"), ("dark", "Dark")]
    assert all(d for _, d, _ in labels)
    assert '<p class="fine" id="sky-desc"></p>' in html
    assert html.find('id="sky"') < html.find('id="sky-desc"') < html.find('class="prefs"')
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "getAttribute('data-desc')" in js
    assert "showSkyDesc();\n  skySel.addEventListener('change', showSkyDesc);" in js


def test_each_reveal_button_sits_on_its_own_line():
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "revealParts.join(' &middot; ')" not in js
    assert "revealParts.map(function (b) { return '<p class=\"t-reveal\">' + b + '</p>'; })" in js


def test_no_planner_markup_borrows_the_scroll_reveal_class():
    """`.reveal` is main.js's scroll-in animation: opacity 0 until it adds
    .is-in, and it only ever adds that to blocks it tagged itself. The reveal
    links were briefly named `reveal`, a hidden-by-default class on markup
    main.js never watches."""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert 'class="reveal"' not in js
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    assert ".planner .reveal" not in css
    assert ".planner .t-reveal button { text-align: left; }" in css


def test_card_label_bar_and_link_styles():
    """Final review m1 and B6."""
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    pick = re.search(r"\.t-pick \{[^}]*\}", css).group(0)
    assert "var(--verdict-go)" in pick and "verdict-warn" not in pick
    bar = re.search(r"\.t-bar > span \{[^}]*\}", css).group(0)
    assert "var(--ink)" in bar and "opacity: .55" in bar and "verdict-warn" not in bar
    assert re.search(r"\.t-more a \{[^}]*text-decoration: underline", css)


def test_render_hands_rank_the_dark_window_length():
    """Final review B5: the short-window bar needs the night's length."""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert js.count("windowMinutes: lastWindowMinutes") == 2, "both rank() calls"
    assert "lastWindowMinutes = win.start && win.end ? (win.end - win.start) / 60000 : 0;" in js


def test_the_data_files_are_revalidated_not_reused_stale():
    """No cache headers on the JSON, so browsers reused the old catalogue by
    heuristic: on 2026-10-03 the new page code ran on the previous day's
    ungraded list. Both fetches must ask the server first."""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "var REVALIDATE = { cache: 'no-cache' };" in js
    assert "fetch('planner-targets.json', REVALIDATE)" in js
    assert "fetch('planner-images.json', REVALIDATE)" in js
    assert "fetch('planner-targets.json')" not in js


# ---- The altitude curve in an opened card (C1) -----------------------------

def _curve(samples, moon, ws, we, us, ue, ticks="[]", peak="'21:20'"):
    """curveSvg under node. Times are minutes after a fixed dusk."""
    return _node("""
      const P = %s;
      const T0 = Date.UTC(2026, 9, 3, 18, 0);
      const at = m => m == null ? null : new Date(T0 + m * 60000);
      const pts = a => a.map(p => ({t: at(p[0]), alt: p[1], az: 180}));
      console.log(JSON.stringify(P.curveSvg(pts(%s), pts(%s), at(%s), at(%s),
                                            at(%s), at(%s), 30,
                                            %s.map(k => ({x: at(k[0]), label: k[1]})),
                                            %s)));
    """ % (_req(PLANNER), json.dumps(samples), json.dumps(moon),
           json.dumps(ws), json.dumps(we), json.dumps(us), json.dumps(ue),
           ticks, peak))


_NIGHT = [[0, 20], [300, 66], [600, 25]]
_MOON = [[0, -5], [300, 10], [600, 40]]
_PARTS = ("t-curve-low", "t-curve-floor", "t-curve-usable", "t-curve-moon",
          "t-curve-target", "t-curve-peak")


@needs_node
def test_the_curve_draws_every_part_of_the_night():
    svg = _curve(_NIGHT, _MOON, 0, 600, 120, 480,
                 ticks='[[120, "20:00"], [240, "22:00"]]')
    for cls in _PARTS:
        assert f'class="{cls}"' in svg, cls
    assert 'viewBox="0 0 300 120"' in svg and 'class="t-curve"' in svg
    assert 'role="img"' in svg
    assert 'aria-label="Altitude through the night: highest 66&deg; at 21:20"' in svg \
        or 'aria-label="Altitude through the night: highest 66° at 21:20"' in svg, svg
    assert svg.count('class="t-curve-tick"') == 4 and ">22:00<" in svg, "two times + 30° and 90"
    assert "NaN" not in svg and "style=" not in svg
    # Every coordinate rounded to one decimal.
    assert not re.search(r"\d\.\d\d", svg), svg


@needs_node
def test_the_moon_is_drawn_only_while_it_is_up():
    svg = _curve(_NIGHT, [[0, -5], [300, -1], [600, -20]], 0, 600, 120, 480)
    assert "t-curve-moon" not in svg
    assert "t-curve-target" in svg


@needs_node
def test_no_curve_without_samples_or_without_a_night():
    """Review Focus 3: midsummer far north has no dark window at all -- the
    engine returns no samples and the window has no length. Nothing is drawn
    rather than an SVG full of NaN."""
    assert _curve([], [], 0, 600, None, None) == ""
    zero = _curve(_NIGHT, _MOON, 300, 300, None, None)
    assert "NaN" not in zero and zero == ""
    assert _curve([], [], None, None, None, None) == ""


@needs_node
def test_the_highlight_follows_the_view_but_the_line_shows_the_whole_night():
    """Review Focus 5: blocking a direction moves (or removes) the highlighted
    stretch -- the same usableStart/End the bar uses -- while the plotted line
    is the whole night either way."""
    a = _curve(_NIGHT, _MOON, 0, 600, 120, 480)
    b = _curve(_NIGHT, _MOON, 0, 600, 300, 420)
    none = _curve(_NIGHT, _MOON, 0, 600, None, None)
    target = lambda s: re.search(r'<polyline class="t-curve-target"[^>]*>', s).group(0)
    usable = lambda s: re.search(r'<rect class="t-curve-usable"[^>]*>', s).group(0)
    assert target(a) == target(b) == target(none)
    assert usable(a) != usable(b)
    assert "t-curve-usable" not in none
    assert "t-curve-peak" in none, "the peak is a fact of the night, not the view"


def test_the_card_draws_the_curve_from_the_view_aware_window():
    js = PLANNER.read_text(encoding="utf-8")
    det = js[js.index("function detail("):js.index("function suggestedIntegration(")]
    assert "curveSvg(" in det
    assert "t.usableStart, t.usableEnd" in det
    assert "E.moonTrack(win, loc.lat, loc.lon)" in js
    assert "imageBlock(t) + curve + season + '<dl class=\"t-facts\">'" in det, "after the image, before the facts"
    assert js.count('style="') == 1, "the wind arrow stays the only inline style"


def test_the_curve_is_styled_by_class():
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    assert re.search(r"\.t-curve \{[^}]*width: 100%", css)
    for cls in _PARTS + ("t-curve-tick",):
        assert re.search(r"\." + cls + r"\b[^{]*\{", css), cls


@needs_node
def test_a_target_below_the_horizon_sits_on_the_ground_line():
    """Altitude is clamped to 0-90: a setting target must not draw below the
    plot into the tick labels."""
    svg = _curve([[0, -10], [300, 66], [600, -5]], [], 0, 600, None, None)
    pts = re.search(r'class="t-curve-target" points="([^"]*)"', svg).group(1).split()
    ys = [float(p.split(",")[1]) for p in pts]
    assert ys[0] == ys[2] == max(ys), ys


# ---- Direction toggles (spec C2) -------------------------------------------

_SECTORS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
# The visible letters lead the accessible name (WCAG 2.5.3, label in name).
_SECTOR_NAMES = ["N, north", "NE, north-east", "E, east", "SE, south-east",
                 "S, south", "SW, south-west", "W, west", "NW, north-west"]


def test_eight_direction_toggles_sit_in_the_form_before_the_preferences():
    html = _html()
    form = html[html.index('<form id="where"'):html.index("</form>")]
    view = form[form.index('<fieldset class="view">'):form.index('class="prefs"')]
    assert "<legend>Where is your view clear?</legend>" in view
    buttons = re.findall(r'<button type="button" class="dir" data-dir="(\d)" '
                         r'aria-label="([A-Za-z, -]+)" aria-pressed="true">([A-Z]+)</button>', view)
    assert buttons == [(str(i), n, s) for i, (n, s) in enumerate(zip(_SECTOR_NAMES, _SECTORS))]
    assert view.count("<button") == 8
    assert form.index('id="sky-desc"') < form.index('<fieldset class="view">')


def test_the_direction_row_is_one_row_of_eight():
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    assert re.search(r"\.view \{[^}]*grid-template-columns: repeat\(8, 1fr\)", css)
    assert re.search(r"\.dir\.off\b[^{]*\{", css)
    # `.planner-where button { justify-self: start }` (0,1,1) shrank each
    # button to its letter -- E and S measured 11 px wide at 320 px. The
    # stretch must out-rank it, and the height must be a real tap target.
    rule = re.search(r"\.view \.dir \{([^}]*)\}", css)
    assert rule, "a (0,2,0) rule beats .planner-where button"
    assert "justify-self: stretch" in rule.group(1)
    h = re.search(r"min-height: (\d+)px", rule.group(1))
    assert h and int(h.group(1)) >= 32


@needs_node
def test_a_saved_view_is_taken_only_when_it_is_eight_booleans():
    """Review Focus 2: a preference saved before this release has no `view`,
    and must come back all OPEN, not all blocked."""
    out = _node(f"""
      const P = {_req(PLANNER)};
      const mixed = [true, false, true, true, false, true, true, true];
      console.log(JSON.stringify([
        P.validView(undefined), P.validView(null), P.validView([true, true]),
        P.validView([1, 1, 1, 1, 1, 1, 1, 1]), P.validView('NNNNNNNN'),
        P.validView(mixed), P.validView(Array(8).fill(false))]));
    """)
    open8 = [True] * 8
    assert out[:5] == [open8] * 5
    assert out[5] == [True, False, True, True, False, True, True, True]
    assert out[6] == [False] * 8, "all blocked is a real choice, kept as saved"
    js = PLANNER.read_text(encoding="utf-8")
    assert "prefs.view = validView(savedPrefs.view);" in js
    assert "var prefs = { clock: '24', units: 'c', sky: 'suburban', view: validView(null) };" in js


@needs_node
def test_a_saved_view_is_a_copy_not_the_saved_array():
    out = _node(f"""
      const P = {_req(PLANNER)};
      const saved = [true, false, true, true, true, true, true, true];
      const v = P.validView(saved); v[0] = false;
      console.log(JSON.stringify(saved));
    """)
    assert out[0] is True


def test_every_target_is_evaluated_against_the_view():
    js = PLANNER.read_text(encoding="utf-8")
    assert "E.evaluateTarget(t, win, loc.lat, loc.lon, inst, prefs.view)" in js
    assert js.count("E.evaluateTarget(") == 1
    assert ("var hidden = parts.darker.length + parts.tooSmall.length + "
            "parts.blocked.length;") in js


@needs_node
def test_the_blocked_reveal_says_what_pressing_it_will_do():
    out = _node(f"""
      const P = {_req(PLANNER)};
      console.log(JSON.stringify([P.revealText('blocked', 3, '', false),
                                  P.revealText('blocked', 3, '', true)]));
    """)
    assert out == ["3 more are behind your blocked directions &rarr;",
                   "Hide the 3 behind your blocked directions"]
    js = PLANNER.read_text(encoding="utf-8")
    assert "id=\"rv-blocked\"" in js
    assert "markRevealed(parts.blocked, 'blocked')" in js
    assert "['darker', 'small', 'blocked'].forEach" in js
    assert "reveal = { darker: false, small: false, blocked: false };" in js
    assert js.count("reveal = { darker: false, small: false, blocked: false };") == 2, \
        "declared, and reset on a new location"
    assert "' &middot; behind your blocked directions'" in js


@needs_node
def test_a_revealed_blocked_card_reads_its_window_from_the_open_run():
    """A blocked card has no usable window; it must never reach clock(null)."""
    out = _node(f"""
      const P = {_req(PLANNER)};
      const blocked = {{revealed: 'blocked', usableStart: null, usableEnd: null,
                       openStart: 100, openEnd: 200, usableMinutes: 0}};
      const short = {{revealed: 'blocked', usableStart: 120, usableEnd: 130,
                     openStart: 100, openEnd: 200, usableMinutes: 10}};
      const plain = {{usableStart: 120, usableEnd: 180, openStart: 100, openEnd: 200}};
      console.log(JSON.stringify([P.cardWindow(blocked), P.cardWindow(short), P.cardWindow(plain)]));
    """)
    assert out == [[100, 200], [100, 200], [120, 180]]
    js = PLANNER.read_text(encoding="utf-8")
    card = js[js.index("function card(t, i)"):js.index("html += shown.map(card)")]
    assert "t.usableStart" not in card and "t.usableEnd" not in card, \
        "the card reads its times and bar through cardWindow()"
    assert "cardWindow(t)" in card
    assert "(t.revealed === 'blocked' ? ' held' : '')" in card, \
        "a would-be window must not look like a usable one"
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    assert re.search(r"\.t-bar\.held > span \{[^}]*opacity: \.2", css)
    sugg = js[js.index("function suggestedIntegration("):js.index("function fmtMins(")]
    assert "t.revealed === 'blocked'" in sugg, "no integration advice for a target you cannot see"


@needs_node
def test_a_blocked_reveal_is_ranked_not_filtered_out():
    """rank() drops anything under the usable minimum, which every blocked
    target is by definition: a reveal that ranks through it shows nothing.
    Held back by the view, they rank on what they would give with it clear."""
    out = _node(f"""
      const E = {_req(ENGINE)};
      const P = {_req(PLANNER)};
      const mk = (id, open) => ({{id, grade: 'Rewarding', type: 'HII', peakAltitude: 60, usablePeak: 0,
        moonUp: false, usableMinutes: 0, usableMinutesOpen: open,
        usableStart: null, usableEnd: null, openStart: 1, openEnd: 2}});
      // Both over the short-window bar, so only the score (minutes x the
      // peak markHeld swaps in) can put 'long' first.
      const list = [mk('short', 150), mk('long', 300)];
      const held = P.markHeld(list, 'blocked', E.rank, {{moonLit: 0, windowMinutes: 600}});
      const small = P.markHeld([Object.assign(mk('tiny', 300), {{usableMinutes: 300}})],
                               'small', E.rank, {{moonLit: 0, windowMinutes: 600}});
      console.log(JSON.stringify({{
        ids: held.map(e => e.id), mins: held.map(e => e.usableMinutes),
        why: held.map(e => e.revealed), start: held.map(e => e.usableStart),
        peak: held.map(e => e.usablePeak),
        untouched: list.map(e => [e.usableMinutes, e.revealed === undefined]),
        small: small.map(e => e.revealed)}}));
    """)
    assert out["ids"] == ["long", "short"]
    assert out["mins"] == [0, 0], "the card still says it is blocked, after ranking"
    assert out["why"] == ["blocked", "blocked"]
    assert out["start"] == [None, None]
    assert out["peak"] == [0, 0], "and its usable peak is still nothing, after ranking"
    assert out["untouched"] == [[0, True], [0, True]], "copies, not the evaluated objects"
    assert out["small"] == ["small"]
    js = PLANNER.read_text(encoding="utf-8")
    mr = js[js.index("function markRevealed("):js.index("function render(")]
    assert "markHeld(list, why, E.rank" in mr


TARGETS_JSON = SITE / "planner-targets.json"


@needs_node
def test_every_direction_blocked_says_nothing_suits_not_nothing_high_enough():
    """Review Focus 1: all eight blocked empties `shown` into `blocked`, and the
    verdict takes the `hidden` path -- the same sum render() passes."""
    out = _node(f"""
      const E = {_req(ENGINE)};
      const T = {_req(TARGETS_JSON)}.targets;
      const w = E.darkWindow(new Date("2026-10-03T12:00:00Z"), 56.05, 12.69);
      const ev = T.map(t => E.evaluateTarget(t, w, 56.05, 12.69, E.INSTRUMENTS.s30pro,
                                             Array(8).fill(false)));
      const parts = E.partition(ev, 'suburban');
      const hidden = parts.darker.length + parts.tooSmall.length + parts.blocked.length;
      const wx = {{ meanCloud: 0, maxCloud: 0, moonIllumination: 0, moonUpMinutes: 0 }};
      const v = E.verdict(w, wx, parts.shown, null, {{hidden}});
      console.log(JSON.stringify({{shown: parts.shown.length, blocked: parts.blocked.length,
                                  darker: parts.darker.length, small: parts.tooSmall.length,
                                  headline: v.headline, limiting: v.limiting}}));
    """)
    assert out["shown"] == 0
    assert out["blocked"] > 10
    assert out["darker"] == out["small"] == 0, "blocked wins over darker and too small"
    assert out["headline"] == "skip"
    assert out["limiting"] == "nothing suits your sky and telescope tonight"


# ---- Month strip (spec C3) -------------------------------------------------

def _strip(minutes, month, text="Best Oct–Jan from here.", no_dark=None):
    return _node("const P = %s; console.log(JSON.stringify(P.seasonStripHtml(%s, %s, %s, %s)));"
                 % (_req(PLANNER), json.dumps(minutes), json.dumps(month),
                    json.dumps(text), json.dumps(no_dark)))


_LEVELS = [0, 59, 60, 179, 180, 0, 0, 0, 0, 0, 0, 0]


@needs_node
def test_the_strip_shades_each_month_by_the_spec_thresholds():
    html = _strip(_LEVELS, 9)
    cells = re.findall(r'<span class="t-month (m\d)( now)?" title="([^"]*)">([^<]*)</span>', html)
    assert len(cells) == 12, html
    assert [c[0] for c in cells[:5]] == ["m0", "m1", "m2", "m2", "m3"]
    assert [c[3] for c in cells] == list("JFMAMJJASOND")
    assert sum(1 for c in cells if c[1]) == 1 and cells[9][1] == " now"
    assert cells[4][2] == "May: 3.0 h" and cells[0][2] == "January: none"
    assert cells[1][2] == "February: 59 min", "not 1.0 h (final review D2)"
    assert cells[2][2] == "March: 1.0 h"
    assert re.match(r'<div class="t-season" role="img" aria-label="[^"]*October[^"]*">', html), html
    assert "May 3.0 h" in html or "May: 3.0 h" in re.search(r'aria-label="([^"]*)"', html).group(1)
    assert "NaN" not in html and "style=" not in html


@needs_node
def test_the_strip_sentence_is_escaped():
    html = _strip(_LEVELS, 0, text="<b>&")
    assert '<p class="t-season-text">&lt;b&gt;&amp;</p>' in html
    assert "<b>" not in html


@needs_node
def test_midsummer_far_north_has_no_darkness_and_the_strip_still_renders():
    """Review Focus 3: at 69 N June has no dark window at all. The engine says
    0 without throwing, the strip renders, and the month says why it is empty."""
    out = _node(f"""
      const E = {_req(ENGINE)};
      const P = {_req(PLANNER)};
      const m = E.seasonMinutes({{ra: 10.68, dec: 41.27}}, 69.65, 18.96, 2026,
                                [true, true, true, true, true, true, true, true]);
      const nd = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map(i =>
        E.darkWindow(new Date(Date.UTC(2026, i, 15, 12)), 69.65, 18.96).kind === 'none');
      console.log(JSON.stringify({{m, nd,
        html: P.seasonStripHtml(m, 5, E.bestMonthsText(m), nd)}}));
    """)
    assert out["m"][5] == 0 and len(out["m"]) == 12
    assert out["nd"][5] is True
    html = out["html"]
    assert 'title="June: no darkness"' in html
    assert re.search(r'<div class="t-season"[^>]* title="[^"]*June[^"]*"', html), html
    assert html.count('class="t-month') == 12 and "NaN" not in html


def test_the_card_only_leaves_a_slot_for_the_strip():
    """Lazy: twelve nights of sampling per target is too much for every card,
    so detail() emits a slot and the strip is filled when a card opens."""
    js = PLANNER.read_text(encoding="utf-8")
    det = js[js.index("function detail("):js.index("function suggestedIntegration(")]
    assert 't-season-slot' in det and 'data-id="' in det
    assert "seasonMinutes" not in det and "seasonStripHtml" not in det
    assert "Through the year" in det
    assert det.index("curve") < det.index("t-season-slot") < det.index("t-facts")
    rnd = js[js.index("function render("):]
    assert "E.seasonMinutes(" in rnd
    # Keyed by everything the answer depends on, so a view change is fresh
    # and a sky or telescope re-render is not recomputed.
    assert "prefs.view.join(',')" in rnd
    # Filled both for a card rendered already open and for one opened later.
    tog = rnd[rnd.index("querySelectorAll('details.target')"):]
    tog = tog[:tog.index("});\n    });") + 12]
    assert tog.count("if (d.open) fillSeason(d);") == 2, tog
    assert js.count('style="') == 1


def test_the_strip_is_styled_by_class():
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    assert re.search(r"\.t-season \{[^}]*grid-template-columns: repeat\(12,", css)
    for cls in ("m0", "m1", "m2", "m3", "now"):
        assert re.search(r"\.t-month\." + cls + r"\b[^{]*\{", css), cls
    assert re.search(r"\.t-month\.now[^{]*\{[^}]*--verdict-go", css)


# ---- Final review fix wave --------------------------------------------------

def _rect(svg, cls):
    m = re.search(r'<rect class="%s" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"/>' % cls, svg)
    assert m, svg
    return [float(v) for v in m.groups()]


@needs_node
def test_the_usable_stretch_is_shaded_only_above_the_floor_with_a_scale():
    """Final review C1: the green ran down through the grey "too low" band, so
    the floor was unreadable; and nothing said what height the lines were."""
    svg = _curve(_NIGHT, _MOON, 0, 600, 120, 480)
    x, y, w, h = _rect(svg, "t-curve-usable")
    fy = float(re.search(r'<line class="t-curve-floor" x1="[\d.]+" y1="([\d.]+)"', svg).group(1))
    assert y + h <= fy + 1e-9, (y, h, fy)
    assert h > 0
    lx, ly, lw, lh = _rect(svg, "t-curve-low")
    assert ly == fy, "the grey band starts where the green stops"
    scale = re.findall(r'<text class="t-curve-tick" x="([\d.]+)" y="([\d.]+)" '
                       r'text-anchor="start">([^<]*)</text>', svg)
    assert [t[2] for t in scale] == ["30°", "90°"], svg
    assert float(scale[0][0]) == float(scale[1][0]) == lx, "on the left edge"
    assert float(scale[1][1]) < float(scale[0][1]) <= fy, "90 above 30, 30 at the line"


def test_the_curve_floor_is_dashed_and_the_curve_is_capped():
    """Final review C1/C2: 300 user units stretched to a 900 px card made the
    ticks 30 px; 520 px holds them near 19 px at 11 units."""
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    curve = re.search(r"\.t-curve \{([^}]*)\}", css).group(1)
    assert "max-width: 520px" in curve and "width: 100%" in curve
    floor = re.search(r"\.t-curve-floor \{([^}]*)\}", css).group(1)
    assert "stroke: var(--muted)" in floor and "stroke-dasharray: 3 3" in floor
    tick = re.search(r"\.t-curve-tick \{([^}]*)\}", css).group(1)
    assert "font-size: 11px" in tick


@needs_node
def test_the_open_season_is_worked_out_only_when_the_view_hides_it_all():
    """Final review I1: the all-clear season costs twelve more nights, so it is
    asked for only when the view's own season never reaches the usable
    minimum -- and then the sentence says the view is why."""
    out = _node(f"""
      const E = {_req(ENGINE)};
      const P = {_req(PLANNER)};
      let calls = 0;
      const open = [0, 0, 0, 0, 0, 0, 0, 0, 120, 200, 200, 120];
      const get = () => {{ calls++; return open; }};
      const fine = P.seasonText(E, [0, 0, 0, 0, 0, 0, 0, 0, 120, 200, 200, 120], get);
      const c1 = calls;
      const held = P.seasonText(E, Array(12).fill(0), get);
      const c2 = calls;
      const never = P.seasonText(E, Array(12).fill(0), () => {{ calls++; return Array(12).fill(0); }});
      console.log(JSON.stringify({{fine, c1, held, c2, never, c3: calls}}));
    """)
    assert out["c1"] == 0, "a season the view allows never asks for the open one"
    assert out["fine"] == "Best Oct–Nov from here."
    assert out["held"] == "Only in your blocked directions from here." and out["c2"] == 1
    assert out["never"] == "Never gets high enough from here." and out["c3"] == 2
    js = PLANNER.read_text(encoding="utf-8")
    rnd = js[js.index("function fillSeason("):]
    rnd = rnd[:rnd.index("// Remember which rows are open")]
    assert "seasonText(E, mins, function" in rnd
    # The open season shares the cache, under the all-clear view's own key.
    assert "OPEN_VIEW.join(',')" in rnd


def test_a_season_that_throws_cannot_stop_the_rest_of_the_wiring():
    """Final review D1: fillSeason runs inside render()'s wiring; an exception
    there would leave every later listener unattached."""
    js = PLANNER.read_text(encoding="utf-8")
    body = js[js.index("function fillSeason("):]
    body = body[:body.index("// Remember which rows are open")]
    assert re.search(r"function fillSeason\(d\) \{\s*try \{", body), body
    assert re.search(r"\} catch \(e\) \{[^}]*\}\s*\}\s*$", body.strip() + "\n"), body


@needs_node
def test_a_blocked_card_that_also_needs_a_darker_sky_says_both():
    """Final review M2: partition() files a target behind the view as blocked
    whatever its sky, so the card is the only place the second reason shows."""
    out = _node(f"""
      const E = {_req(ENGINE)};
      const P = {_req(PLANNER)};
      const dark = {{revealed: 'blocked', sky: 'dark'}}, city = {{revealed: 'blocked', sky: 'city'}};
      console.log(JSON.stringify([
        P.heldWhy(dark, 'S30 Pro', E.skyOk(dark, 'suburban')),
        P.heldWhy(city, 'S30 Pro', E.skyOk(city, 'suburban')),
        P.heldWhy({{revealed: 'darker', sky: 'rural'}}, 'S30 Pro', false),
        P.heldWhy({{revealed: 'small', sky: 'city'}}, 'S30 <Pro>', true),
        P.heldWhy({{sky: 'dark'}}, 'S30 Pro', false)]));
    """)
    assert out == [" &middot; behind your blocked directions &middot; needs a dark sky",
                   " &middot; behind your blocked directions",
                   " &middot; needs a rural sky",
                   " &middot; too small for your S30 &lt;Pro&gt;",
                   ""]
    js = PLANNER.read_text(encoding="utf-8")
    card = js[js.index("function card(t, i)"):js.index("html += shown.map(card)")]
    assert "heldWhy(t, inst.label, E.skyOk(t, prefs.sky))" in card


@needs_node
@pytest.mark.parametrize("zone,hour12,first,labels", [
    # 18:10-06:10 UTC. Stockholm (+02:00 in October): 20:10 -> first whole
    # hour 21:00, odd, so the ticks are 22, 00, 02, 04, 06, 08.
    ("Europe/Stockholm", False, None, ["22:00", "00:00", "02:00", "04:00", "06:00", "08:00"]),
    ("Europe/Stockholm", True, None, ["10:00 pm", "12:00 am", "02:00 am", "04:00 am",
                                      "06:00 am", "08:00 am"]),
    # +05:30: 23:40 local -> 00:00 is 18:30 UTC, not on a UTC whole hour.
    ("Asia/Kolkata", False, "2026-10-03T18:30:00.000Z", ["00:00", "02:00", "04:00", "06:00", "08:00", "10:00"]),
])
def test_curve_ticks_land_on_the_pages_own_whole_even_hours(zone, hour12, first, labels):
    """Final review D3: curveTicks is pure, so it is exercised, not grepped."""
    out = _node(f"""
      const P = {_req(PLANNER)};
      const clock = P.makeClock({json.dumps(zone)}, 0, {json.dumps(hour12)});
      const win = {{kind: 'astronomical', start: new Date(Date.UTC(2026, 9, 3, 18, 10)),
                   end: new Date(Date.UTC(2026, 9, 4, 6, 10))}};
      const t = P.curveTicks(win, clock);
      console.log(JSON.stringify({{labels: t.map(k => k.label), first: t[0].x.toISOString(),
        none: P.curveTicks({{kind: 'none', start: null, end: null}}, clock)}}));
    """)
    assert [l.lower() for l in out["labels"]] == labels
    if first:
        assert out["first"] == first
    assert out["none"] == []


def test_detail_joins_the_facts_with_a_single_space():
    js = PLANNER.read_text(encoding="utf-8")
    assert "'<dl class=\"t-facts\">'  +" not in js
    assert "'<dl class=\"t-facts\">' + rows.map(" in js
