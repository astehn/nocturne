# tests/test_planner_page.py
"""Asserts against the BUILT page, the way tests/test_contribute_page.py does."""
import json
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


def test_the_page_offers_three_nights():
    """Spec 1: tonight plus the next two. Capped there deliberately -- day six of
    a forecast is a guess dressed as a forecast, and the page should not imply
    certainty it does not have."""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "MAX_NIGHT = 2" in js
    assert "Tomorrow night" in js and "The night after" in js


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


def test_the_page_reports_a_fog_margin():
    """Andreas asked for this by name and it is the second weather fact after
    cloud that decides a night: when temperature closes on the dew point the
    corrector plate fogs and the session is over. His own sky.stehn.com calls
    it "fog margin", so this one does too -- two sites, one vocabulary."""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "dew_point_2m" in js and "temperature_2m" in js
    assert "fogMargin" in js
    assert "Math.min" in js, "the WORST hour fogs the optics, not the average"


def test_the_clock_and_unit_defaults_are_chosen_not_inherited():
    """Deriving these from the browser locale was tried and failed in the
    wild: Andreas is in Sweden, his browser reports an English locale, and
    the page served him "09:30 PM". Astro is a 24-hour-clock hobby and the
    data is metric, so both defaults are picked outright."""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "clock: '24'" in js and "units: 'c'" in js
    assert "'en-GB'" in js, "pass a locale explicitly or it can reassert 12-hour"
    h = (SITE / "planner.html").read_text(encoding="utf-8")
    assert 'id="clock"' in h and 'id="units"' in h


def test_a_fog_MARGIN_is_converted_as_a_difference_not_a_temperature():
    """2°C of margin is 3.6°F, not 35.6°F. The margin and the temperatures
    it is derived from live in the same sentence and convert by different
    rules, which is precisely why this is pinned.

    Runs the SHIPPED engine under node with both a Celsius and a Fahrenheit
    formatter injected into verdict(), and reads the rendered Fog factor back
    -- not a source-level guess at what the code does.
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
      const celsius = c => Math.round(c) + '\\u00b0C';
      const fahrenheit = c => Math.round(c * 9 / 5 + 32) + '\\u00b0F';
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


def test_the_icons_carry_accessible_labels_and_real_data():
    """Copied from Andreas's own sky.stehn.com so the two sites share one
    visual family. His moon is COMPUTED, not a glyph: the terminator's
    x-radius is |2f-1| x r, which is why his markup reads "A 6.693 12" for a
    77.9% Moon. A static moon would be a regression from his prototype."""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "aria-label" in js
    assert "2 * fraction - 1" in js, "the moon must be drawn to its real phase"
    assert "rotate(" in js, "the wind arrow points along the bearing"


def test_the_wind_arrow_is_backed_by_a_real_bearing():
    """A rotated arrow with no bearing behind it would be decoration
    pretending to be data (task-4 brief). The forecast request must actually
    fetch direction, and the engine must report a real speed range rather
    than inventing an unmeasured "this is windy" threshold."""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "wind_direction_10m" in js and "wind_speed_10m" in js
    assert "windBearing" in js
    engine = (SITE / "planner-engine.js").read_text(encoding="utf-8")
    assert "windMin" in engine and "windMax" in engine


def test_the_page_says_which_location_it_used():
    """It fetched five candidates and silently used the first. Ask for
    "Cambridge" and you got one of two countries with no indication. Andreas
    asked for this after typing Helsingborg and not being told what it
    resolved to."""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "Planning for" in js
    assert "hits.length > 1" in js, "more than one candidate must be offered, not guessed"
    assert "function esc" in js, "a third-party place name is interpolated into HTML"
