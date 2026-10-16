"""The report dialog's browser fallback hands the typed problem to
support.html in the URL fragment (the page's support.js fills the field from
it, 2026-10-16). Bounded, so a long report still opens."""
from urllib.parse import parse_qs, urlsplit

from nocturne.core.update_check import SUPPORT_URL
from nocturne.ui.report_dialog import MAX_SUPPORT_URL, SHORTENED, support_url


def _problem(url: str) -> str:
    """What URLSearchParams on the page reads back (+ is a space there too)."""
    return parse_qs(urlsplit(url).fragment)["problem"][0]


def test_the_problem_arrives_exactly():
    text = 'Stretch froze on M 8 & "Apply" stayed green\nsecond line: 100% #1 ✓'
    url = support_url(text)
    assert url.startswith(SUPPORT_URL + "#problem=")
    assert "?" not in url, "a query string reaches the server's access log"
    assert _problem(url) == text


def test_nothing_typed_opens_the_bare_page():
    assert support_url("") == SUPPORT_URL


def test_a_long_problem_is_shortened_and_says_so():
    text = "Ærlig talt — stjärnorna blev gröna. " * 200      # multi-byte, ~7 kB
    url = support_url(text)
    assert len(url) <= MAX_SUPPORT_URL
    got = _problem(url)
    assert got.endswith(SHORTENED)
    kept = got[: -len(SHORTENED)]
    assert text.startswith(kept) and len(kept) > 300      # as much as fits, not a stub


def test_one_that_just_fits_is_not_shortened():
    text = "x" * (MAX_SUPPORT_URL - len(SUPPORT_URL) - len("#problem="))
    assert len(support_url(text)) == MAX_SUPPORT_URL
    assert _problem(support_url(text)) == text
