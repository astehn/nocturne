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
    assert "On a first visit nothing is sent anywhere until you press this" in h
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


def _node(script):
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                       cwd=SITE.parent, timeout=60)
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
