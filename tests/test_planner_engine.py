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
