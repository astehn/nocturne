"""Audit 2026-10-01, group A: skip link, one menu control, a branded 404."""
import re
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parent.parent / "site"
pytestmark = pytest.mark.skipif(
    not (SITE / "index.html").exists(),
    reason="site/ is decoupled and gitignored — only validated when present locally",
)
PAGES = sorted(p for p in SITE.glob("*.html") if p.name not in {"admin.html", "404.html"})


def _html(p):
    return p.read_text(encoding="utf-8")


def test_every_page_starts_with_a_skip_link_to_its_main():
    for p in PAGES:
        h = _html(p)
        body = h.split("<body>", 1)[1]
        first_link = re.search(r"<a\b[^>]*>", body)
        assert first_link and 'class="skip-link"' in first_link.group(0), p.name
        target = re.search(r'href="#([\w-]+)"', first_link.group(0)).group(1)
        assert re.search(rf'<main\b[^>]*\bid="{target}"', h), (p.name, target)


def test_the_menu_is_one_control_for_assistive_tech():
    """The mobile menu exposed a checkbox AND a button both named Menu."""
    for p in PAGES:
        h = _html(p)
        box = re.search(r'<input[^>]*id="nav-open"[^>]*>', h).group(0)
        assert 'aria-label="Menu"' in box, p.name
        label = re.search(r'<label class="nav-toggle"[^>]*>', h).group(0)
        assert 'aria-hidden="true"' in label and "role=" not in label \
            and "aria-label" not in label, p.name


def test_escape_hands_focus_to_the_real_control():
    js = (SITE / "main.js").read_text(encoding="utf-8")
    assert "box.focus()" in js and "toggle.focus()" not in js


def test_a_branded_404_exists_and_finds_its_way_home():
    h = _html(SITE / "404.html")
    assert '<base href="/">' in h, "deep broken links must still load the styles"
    assert '<meta name="robots" content="noindex">' in h
    for target in ('href="/"', 'href="download.html"', 'href="guide.html"',
                   'href="planner.html"', 'href="support.html"'):
        assert target in h, target


def test_the_404_page_is_not_in_the_sitemap():
    assert "404.html" not in (SITE / "sitemap.xml").read_text(encoding="utf-8")


def test_in_page_links_move_focus_not_only_the_scroll():
    """The smooth-scroll handler moved the view but left focus at the top, so
    the skip link did nothing for the keyboard users it exists for."""
    js = (SITE / "main.js").read_text(encoding="utf-8")
    handler = js.split("Smooth-scroll for in-page anchor links", 1)[1].split("});\n});", 1)[0]
    assert "target.focus(" in handler


def test_every_form_field_on_the_home_page_has_a_name():
    """Placeholders vanish on typing and are not labels (audit 2026-10-01)."""
    h = (SITE / "index.html").read_text(encoding="utf-8")
    form = h.split('id="contribute-form"', 1)[1].split("</form>", 1)[0]
    for field in re.findall(r"<(?:input|textarea)\b[^>]*>", form):
        if 'type="hidden"' in field or 'class="hp"' in field or 'type="checkbox"' in field:
            continue
        fid = re.search(r'\bid="([\w-]+)"', field)
        labelled = (fid and f'for="{fid.group(1)}"' in form) or "aria-label=" in field
        assert labelled, field


def test_every_tool_page_ends_with_a_next_step():
    """Audit 2026-10-01: a reader who finishes a tool page gets one clear next
    action — the Download page (not the old homepage anchor) and sample data."""
    tools = (SITE / "tools.html").read_text(encoding="utf-8")
    pages = sorted(set(re.findall(r'href="([\w-]+\.html)"', tools.split("<main", 1)[1]))
                   - {"tools.html", "download.html", "sample-data.html", "guide.html",
                      "index.html", "gallery.html", "planner.html", "faq.html",
                      "setup.html", "changelog.html", "privacy.html", "support.html"})
    assert len(pages) >= 10, pages
    for name in pages:
        h = (SITE / name).read_text(encoding="utf-8")
        cta = h.split('class="tool-cta"', 1)
        assert len(cta) == 2, name
        assert 'href="download.html"' in cta[1][:600] and 'href="sample-data.html"' in cta[1][:600], name
        assert 'href="/#download"' not in h, name


def test_the_faq_carries_faqpage_markup_from_its_visible_entries():
    """Audit 2026-10-01: machine-readable Q&A — built FROM the page, so it can
    never say anything the visitor cannot see."""
    import html as _h
    import json
    h = (SITE / "faq.html").read_text(encoding="utf-8")
    blocks = re.findall(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', h, re.S)
    faq = next(json.loads(b) for b in blocks if '"FAQPage"' in b)
    visible = [_h.unescape(re.sub(r"<[^>]+>", "", q)).strip()
               for q in re.findall(r"<summary>(.*?)</summary>", h, re.S)]
    asked = [q["name"] for q in faq["mainEntity"]]
    assert asked == visible and len(asked) >= 8
    assert all(q["acceptedAnswer"]["text"].strip() for q in faq["mainEntity"])
