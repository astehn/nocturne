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
    """At the point of the decision, not buried on another page."""
    h = _html()
    assert "Nothing is sent anywhere until you press this" in h
    assert 'href="privacy.html"' in h


def test_both_telescopes_are_offered():
    """Spec 6 ships two presets and no more. The engine takes four numbers and
    never branches on which instrument it is, so a third is one row of data --
    but only these two have specs read off real sub headers."""
    h = _html()
    assert 'id="scope"' in h
    assert 'value="s30pro"' in h and "Seestar S30 Pro" in h
    assert 'value="s50"' in h and "Seestar S50" in h
    assert "Dwarf" not in h and "Other" not in h, \
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
