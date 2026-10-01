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
