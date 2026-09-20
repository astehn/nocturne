"""astropy computes ground truth; the shipped engine computes the same thing.

Nothing in nocturne/ does alt/az or ephemeris -- checked 2026-09-20, astropy is
imported only for FITS I/O and Angle formatting -- so the planner's astronomy is
entirely new code with no reference implementation in the repo. This test is
where "the numbers are right" stops being an assumption.

Both libraries are already present, neither knows about the other, and no
expected values are written down here.

REFRACTION MUST BE OFF ON BOTH SIDES. astropy's AltAz applies none without a
pressure; astronomy-engine's 'normal' applies it, and the two disagreed by 0.44
degrees on the Sun until that was found.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "site" / "planner-engine.js"

pytestmark = [
    pytest.mark.skipif(not ENGINE.exists(),
                       reason="site/ is decoupled and gitignored -- only checked locally"),
    pytest.mark.skipif(shutil.which("node") is None,
                       reason="node is not installed; the JS engine cannot be exercised"),
]

TOLERANCE_DEG = 0.05

# Deliberately spread: a Nordic autumn night, a tropical one, and a southern one.
# A sign error in latitude passes the first and fails the third.
CASES = [
    ("Vallentuna", 59.53, 18.08, "2026-09-20T22:00:00Z"),
    ("Nairobi", -1.29, 36.82, "2026-03-15T20:30:00Z"),
    ("Wellington", -41.29, 174.78, "2026-12-01T11:00:00Z"),
]

# M 31, M 42, omega Centauri -- north, equatorial, far south.
TARGETS = [("M 31", 10.6847, 41.2690), ("M 42", 83.8221, -5.3911),
           ("omega Cen", 201.6970, -47.4795)]


def _engine(lat, lon, iso):
    """Run the SHIPPED engine file under node and return its numbers."""
    script = f"""
      const E = require({json.dumps(str(ENGINE))});
      const d = new Date({json.dumps(iso)});
      const out = {{ sun: E.sunAltitude(d, {lat}, {lon}), targets: {{}} }};
      for (const [n, ra, dec] of {json.dumps(TARGETS)}) {{
        const p = E.targetAltAz(ra, dec, d, {lat}, {lon});
        const m = E.moonAltAzAndSeparation(ra, dec, d, {lat}, {lon});
        out.targets[n] = {{ alt: p.altitude, az: p.azimuth,
                            moonAlt: m.moonAltitude, sep: m.separation }};
      }}
      console.log(JSON.stringify(out));
    """
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                       cwd=ROOT, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _astropy(lat, lon, iso):
    from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
    from astropy.time import Time
    import astropy.units as u
    loc = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=0 * u.m)
    t = Time(iso.replace("Z", ""))
    frame = AltAz(obstime=t, location=loc)          # no pressure -> no refraction
    moon = get_body("moon", t, loc).transform_to(frame)
    out = {"sun": get_body("sun", t, loc).transform_to(frame).alt.deg, "targets": {}}
    for name, ra, dec in TARGETS:
        c = SkyCoord(ra=ra * u.deg, dec=dec * u.deg).transform_to(frame)
        out["targets"][name] = {"alt": c.alt.deg, "az": c.az.deg,
                                "moonAlt": moon.alt.deg,
                                "sep": moon.separation(c).deg}
    return out


@pytest.mark.parametrize("place,lat,lon,iso", CASES)
def test_the_engine_agrees_with_astropy(place, lat, lon, iso):
    js, py = _engine(lat, lon, iso), _astropy(lat, lon, iso)
    assert abs(js["sun"] - py["sun"]) < TOLERANCE_DEG, (
        f"{place}: sun altitude {js['sun']:.3f} vs astropy {py['sun']:.3f}")
    for name, _ra, _dec in TARGETS:
        j, p = js["targets"][name], py["targets"][name]
        assert abs(j["alt"] - p["alt"]) < TOLERANCE_DEG, f"{place} {name} altitude"
        assert abs(j["moonAlt"] - p["moonAlt"]) < TOLERANCE_DEG, f"{place} moon altitude"
        assert abs(j["sep"] - p["sep"]) < TOLERANCE_DEG, f"{place} {name} moon separation"
        # Azimuth is the one that catches a dropped precession: near culmination
        # altitude barely moves while azimuth swings, so altitude alone would
        # pass a J2000-fed-raw implementation.
        d = abs(j["az"] - p["az"]) % 360
        assert min(d, 360 - d) < TOLERANCE_DEG, (
            f"{place} {name} azimuth {j['az']:.2f} vs astropy {p['az']:.2f} -- "
            f"a ~0.8 deg gap here means J2000 coordinates reached Horizon() "
            f"without being precessed to equator-of-date")


# --- The decision layer -------------------------------------------------------
#
# Everything above pins the astronomy against astropy. Nothing pinned what the
# page DECIDES from it: darkness classification, the usable-target gate, the
# verdict and the framing rule were all untested, including a timezone defect
# that was found, fixed by hand across four zones, and then shipped with nothing
# holding it down.

TARGETS_JSON = ROOT / "site" / "planner-targets.json"


def _node(script: str, tz: str | None = None):
    """Run a snippet against the shipped engine, optionally under a given TZ."""
    import os
    env = dict(os.environ)
    if tz is not None:
        env["TZ"] = tz
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                       cwd=ROOT, timeout=60, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _require(path: Path) -> str:
    return f"require({json.dumps(str(path))})"


def _dark_window(lat, lon, iso, tz=None):
    return _node(f"""
      const E = {_require(ENGINE)};
      const w = E.darkWindow(new Date({json.dumps(iso)}), {lat}, {lon});
      console.log(JSON.stringify({{
        kind: w.kind, minSunAlt: w.minSunAlt,
        start: w.start && w.start.toISOString(),
        end: w.end && w.end.toISOString(),
      }}));
    """, tz=tz)


# Two locations, deliberately: a machine-local anchor in Los Angeles happens to
# select the same Vallentuna window as one in UTC on 2026-09-20, so Vallentuna
# alone would let that third zone pass a broken engine. Wellington, on the far
# side of the world from Los Angeles, does not.
TZ_CASES = ["UTC", "Pacific/Auckland", "America/Los_Angeles"]
TZ_PLACES = [
    ("Vallentuna", 59.53, 18.08, "2026-09-20T12:00:00Z"),
    ("Wellington", -41.29, 174.78, "2026-06-15T12:00:00Z"),
]


@pytest.mark.parametrize("place,lat,lon,iso", TZ_PLACES)
def test_the_dark_window_does_not_depend_on_the_machine_clock(place, lat, lon, iso):
    """The night belongs to the LOCATION, never to the browser.

    The sample window is anchored on solar noon at the observer's longitude. An
    earlier version anchored it on local noon in whatever timezone the machine
    happened to be in, so a visitor planning Vallentuna from a laptop set to
    Auckland got a window offset by ten hours -- truncating the night or
    catching the tail of the previous one, with nothing about the output looking
    wrong. That defect is invisible to every other test in this file, because
    they all pass an explicit instant.

    If this fails, the engine is reading the machine's clock somewhere and the
    answer a visitor gets depends on where their laptop thinks it is.
    """
    got = {tz: _dark_window(lat, lon, iso, tz=tz) for tz in TZ_CASES}
    distinct = {(w["kind"], w["start"], w["end"]) for w in got.values()}
    assert len(distinct) == 1, (
        f"{place} resolves to a different night depending on the machine clock:\n"
        + "\n".join(f"  TZ={tz}: {w['kind']} {w['start']} -> {w['end']}"
                     for tz, w in got.items()))


def test_a_september_night_at_vallentuna_is_properly_dark():
    """The ordinary case, and the one the page is mostly used for.

    If this reports nautical or none, the -18 degree threshold or the 24-hour
    sample window is wrong, and the page understates every autumn night at the
    author's own latitude.
    """
    w = _dark_window(59.53, 18.08, "2026-09-20T12:00:00Z")
    assert w["kind"] == "astronomical"
    assert w["start"] < w["end"]


def test_midsummer_at_vallentuna_has_no_real_darkness():
    """'none' is a first-class answer, not an error (spec 7.1).

    At 59.5N there is no astronomical darkness from mid-May to late July. If
    this returns a window, the page promises a dark night that does not exist;
    if it raises, a quarter of the year renders blank at the author's latitude.
    """
    w = _dark_window(59.53, 18.08, "2026-06-21T12:00:00Z")
    assert w["kind"] == "none"
    assert w["start"] is None and w["end"] is None


def test_midsummer_at_tromso_has_no_real_darkness():
    """Above the Arctic circle the Sun does not set at all, so minSunAlt is
    POSITIVE -- the case that has no 'degrees below the horizon' to report.

    If minSunAlt comes back negative here the midnight sun is being modelled as
    a shallow twilight, and planner.js will print a depth below the horizon that
    the Sun never reaches.
    """
    w = _dark_window(69.65, 18.96, "2026-06-21T12:00:00Z")
    assert w["kind"] == "none"
    assert w["minSunAlt"] > 0, f"the Sun should never set here; got {w['minSunAlt']}"


@pytest.mark.skipif(not TARGETS_JSON.exists(),
                    reason="planner-targets.json is generated into gitignored site/")
def test_the_verdict_and_the_target_list_cannot_contradict_each_other():
    """The page must not say 'nothing gets high enough' above three target cards.

    59.53N on 2026-07-30 gives a 40-minute nautical window -- every target in
    the catalogue falls under the 45-minute bar, so verdict() reports no usable
    targets. rank() once filtered on Boolean alone and handed render() 33 cards
    to print underneath that sentence.

    If this fails, verdict() and rank() are using different thresholds again,
    and spec 8.1's 'Nothing worth pointing at tonight from here.' branch is
    unreachable.
    """
    out = _node(f"""
      const E = {_require(ENGINE)};
      const T = {_require(TARGETS_JSON)}.targets;
      const w = E.darkWindow(new Date("2026-07-30T12:00:00Z"), 59.53, 18.08);
      const ev = T.map(t => E.evaluateTarget(t, w, 59.53, 18.08, E.INSTRUMENTS.s30pro));
      const v = E.verdict(w, {{ meanCloud: 0, maxCloud: 0,
                               moonIllumination: 0, moonUpMinutes: 0 }}, ev);
      console.log(JSON.stringify({{
        kind: w.kind,
        windowMinutes: Math.round((new Date(w.end) - new Date(w.start)) / 60000),
        evaluated: ev.filter(Boolean).length,
        longest: ev.filter(Boolean).reduce((a, e) => Math.max(a, e.usableMinutes), 0),
        headline: v.headline, limiting: v.limiting, ranked: E.rank(ev).length,
      }}));
    """)
    assert out["kind"] == "nautical" and out["windowMinutes"] < 45, out
    assert out["evaluated"] > 0, "this date is only interesting if targets DO clear 30 deg"
    assert out["longest"] <= out["windowMinutes"], \
        "a target cannot be usable for longer than the darkness it was sampled in"
    assert out["headline"] == "skip"
    assert out["limiting"] == "nothing gets high enough tonight"
    assert out["ranked"] == 0, (
        f"verdict says nothing is worth pointing at, but rank() would render "
        f"{out['ranked']} cards saying otherwise")


def test_framing_is_judged_against_the_short_axis_of_the_actual_instrument():
    """M 31 is 178' -- wider than the S30 Pro's 135' short axis, and still one
    frame along its 239' long one. That distinction is why the catalogue has no
    upper size bound (tests/test_planner_targets.py::test_m31_is_present).

    If the S30 Pro case says 'needs a mosaic', framing is being judged against
    the short axis alone and the page tells people to skip the most photographed
    target in the northern sky. If the S50 case does not, the rule is ignoring
    the instrument, which is the one thing it exists to account for.
    """
    out = _node(f"""
      const E = {_require(ENGINE)};
      console.log(JSON.stringify({{
        s30pro: E._framing(178.0, E.INSTRUMENTS.s30pro),
        s50: E._framing(178.0, E.INSTRUMENTS.s50),
        fov30: E.fieldOfViewArcmin(E.INSTRUMENTS.s30pro),
        fov50: E.fieldOfViewArcmin(E.INSTRUMENTS.s50),
      }}));
    """)
    assert out["fov30"]["short"] < 178.0 < out["fov30"]["long"]
    assert out["s30pro"] == "wider than the frame"
    assert out["fov50"]["long"] < 178.0
    assert out["s50"] == "needs a mosaic"


def test_the_usable_gate_is_one_constant_shared_by_both_callers():
    """F2 was a drift between two copies of the same 45-minute rule.

    A future edit that re-inlines the number in either verdict() or rank()
    reintroduces exactly that drift, so the constant is asserted to exist and to
    be the only place the threshold is written.
    """
    src = ENGINE.read_text(encoding="utf-8")
    assert "MIN_USABLE_MINUTES = 45" in src
    assert "usableMinutes >= 45" not in src, \
        "the threshold is inlined again; verdict() and rank() can drift apart"
    out = _node(f"console.log(JSON.stringify({_require(ENGINE)}.MIN_USABLE_MINUTES));")
    assert out == 45


def test_a_missing_forecast_and_a_forecast_that_does_not_reach_read_differently():
    """'We could not fetch it' sends a visitor to check their connection; 'it
    does not run that far ahead' tells them to come back tomorrow. Both were the
    same sentence, and one of them was a lie on the third night.

    If this fails, the page is blaming the network for a night the forecast
    simply does not cover yet.
    """
    out = _node(f"""
      const E = {_require(ENGINE)};
      const w = E.darkWindow(new Date("2026-09-20T12:00:00Z"), 59.53, 18.08);
      const ev = [];
      console.log(JSON.stringify({{
        gone: E.verdict(w, null, ev),
        beyond: E.verdict(w, {{ cloudReason: 'beyond-forecast',
                                moonIllumination: 0, moonUpMinutes: 0 }}, ev),
      }}));
    """)
    assert out["gone"]["headline"] == "can't say"
    assert out["beyond"]["headline"] == "can't say"
    assert out["gone"]["limiting"] != out["beyond"]["limiting"]
    assert "fetch" in out["gone"]["limiting"]
    assert "reach this night" in out["beyond"]["limiting"]


def test_the_verdict_reports_worst_cloud_as_well_as_mean():
    """Spec 7.3 asks for mean AND worst across the dark hours. A night that
    averages 30% because it is clear until 01:00 and then solid is not the night
    a flat 30% is, and the mean alone cannot tell them apart.

    If this fails the factor list is back to a single number, and the page is
    quietly recommending a night that closes over halfway through.
    """
    out = _node(f"""
      const E = {_require(ENGINE)};
      const w = E.darkWindow(new Date("2026-09-20T12:00:00Z"), 59.53, 18.08);
      const v = E.verdict(w, {{ meanCloud: 30, maxCloud: 100,
                                moonIllumination: 0, moonUpMinutes: 0 }}, []);
      console.log(JSON.stringify(v.factors.filter(f => f.label === 'Cloud')));
    """)
    assert len(out) == 1
    assert "30% average" in out[0]["value"]
    assert "100% at worst" in out[0]["value"], out[0]["value"]
    assert out[0]["concern"] is True, "a night that reaches 100% cloud is a concern"


def test_no_verdict_string_carries_a_decimal_score():
    """Spec 7.3: no two-decimal scores anywhere. A precise number on a forecast
    is the brief's named failure mode for looking untrustworthy.

    If this fails, something is rendering a raw float into user-visible copy.
    """
    import re
    out = _node(f"""
      const E = {_require(ENGINE)};
      const w = E.darkWindow(new Date("2026-09-20T12:00:00Z"), 59.53, 18.08);
      const v = E.verdict(w, {{ meanCloud: 41.3746, maxCloud: 88.2211,
                                moonIllumination: 63.8817, moonUpMinutes: 70 }}, []);
      console.log(JSON.stringify([v.headline, v.limiting || '']
        .concat(v.factors.map(f => f.label + ' ' + f.value))));
    """)
    for line in out:
        assert not re.search(r"\d+\.\d", line), f"a decimal reached the copy: {line}"
