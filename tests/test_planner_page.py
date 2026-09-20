# tests/test_planner_page.py
"""Asserts against the BUILT page, the way tests/test_contribute_page.py does."""
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
