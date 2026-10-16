"""The glossary is ONE list with two outputs — the in-app help topic and a
website page — so the two can never disagree. These tests check the list
itself and the website output; the help topic and the Nocturne-specific
claims are checked in tests/ui/test_help_accuracy.py."""
import re
from html.parser import HTMLParser

from nocturne import glossary as g

# The terms the glossary was commissioned to explain (TODO "GLOSSARY",
# 2026-10-14), looked up by any of their names.
REQUIRED = (
    "arcminute", "arcsecond", "degree", "right ascension", "declination",
    "field of view", "plate solving", "pixel scale", "linear", "stretched",
    "stretch", "histogram", "black point", "white point", "midtones",
    "clipping", "crushed", "blown", "noise", "signal-to-noise ratio", "sub",
    "stacking", "integration time", "drizzle", "calibration frames", "darks",
    "flats", "bias", "master", "OSC", "mono", "Bayer pattern", "debayering",
    "broadband", "narrowband", "dual-band", "Hα", "OIII", "SII", "HOO", "SHO",
    "star separation", "starless", "deconvolution", "SPCC",
    "background extraction", "gradient", "Bortle scale", "FITS", "TIFF",
    "colour space", "sRGB", "P3", "recipe", "preset", "FWHM",
)


def test_every_commissioned_term_is_there():
    missing = [name for name in REQUIRED if g.lookup(name) is None]
    assert not missing, f"no glossary entry for: {missing}"


def test_every_entry_has_a_term_and_a_definition():
    for t in g.TERMS:
        assert t.term.strip() == t.term and t.term, repr(t)
        assert t.definition.strip() == t.definition and t.definition, t.term
        assert all(a.strip() for a in t.aliases), t.term


def test_names_are_unique_across_terms_and_aliases():
    """A name that belongs to two entries makes a link ambiguous."""
    seen = {}
    for t in g.TERMS:
        for name in (t.term, *t.aliases):
            key = name.casefold()
            assert key not in seen, f"{name!r} names both {seen[key]!r} and {t.term!r}"
            seen[key] = t.term


def test_anchors_are_unique_and_safe():
    anchors = [t.anchor for t in g.TERMS]
    assert len(set(anchors)) == len(anchors)
    for a in anchors:
        assert re.fullmatch(r"term-[a-z0-9]+(-[a-z0-9]+)*", a), a


def test_definitions_stay_short():
    """One to three sentences each: a glossary line, not a help topic."""
    for t in g.TERMS:
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", t.definition) if s]
        assert 1 <= len(sentences) <= 3, f"{t.term}: {len(sentences)} sentences"


def test_no_ai_wording_and_british_spelling():
    """See memory no-ai-in-ui-names; and the help is British throughout."""
    for t in g.TERMS:
        text = " ".join((t.term, t.definition, *t.aliases))
        assert not re.search(r"\bAI\b", text), t.term
        for us in (r"\bcolor", r"\bcenter", r"\bgray\b", r"\bneutraliz"):
            assert not re.search(us, text), f"{t.term}: American spelling {us}"


def test_sorted_terms_are_alphabetical_with_greek_read_as_latin():
    names = [t.term for t in g.sorted_terms()]
    assert len(names) == len(g.TERMS)
    keys = [g.sort_key(n) for n in names]
    assert keys == sorted(keys)
    # Hα files under H, before Histogram — not after Z, where code point order puts α.
    assert names.index(g.lookup("Hα").term) < names.index(g.lookup("histogram").term)


def test_lookup_ignores_case_and_returns_none_for_unknown():
    assert g.lookup("FITS") is g.lookup("fits")
    assert g.lookup("no such term") is None


class _Checker(HTMLParser):
    """Balanced tags, and every id collected."""
    VOID = {"br", "img", "meta", "link", "hr", "input", "source", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.ids, self.errors, self.text = [], [], [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)
        for k, v in attrs:
            if k == "id":
                self.ids.append(v)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"</{tag}> closes {self.stack[-1:]}")
        else:
            self.stack.pop()

    def handle_data(self, data):
        self.text.append(data)


def _website():
    page = g.website_page()
    assert page.startswith("---\n"), "the site's pages begin with front matter"
    head, sep, body = page[4:].partition("\n---\n")
    assert sep, "front matter is not closed"
    return head, body


def test_website_page_is_well_formed_and_carries_every_term():
    head, body = _website()
    for key in ("title:", "description:"):
        assert key in head
    c = _Checker()
    c.feed(body)
    c.close()
    assert not c.errors, c.errors[:5]
    assert not c.stack, f"unclosed: {c.stack}"
    assert len(c.ids) == len(set(c.ids)), "duplicate ids"
    text = " ".join(c.text)
    for t in g.TERMS:
        assert t.anchor in c.ids, t.term
        assert t.term in text, t.term


def test_website_page_follows_the_site_csp():
    """The site enforces a CSP: no inline style or script on public pages."""
    _, body = _website()
    assert "style=" not in body and "<script" not in body
    assert "<main" in body and 'class="wrap prose"' in body


def test_website_page_escapes_definitions(monkeypatch):
    odd = g.Term("Odd & <term>", "Uses <b> & such.")
    monkeypatch.setattr(g, "TERMS", g.TERMS + (odd,))
    page = g.website_page()
    assert "Odd &amp; &lt;term&gt;" in page and "Uses &lt;b&gt; &amp; such." in page
    assert "<term>" not in page
