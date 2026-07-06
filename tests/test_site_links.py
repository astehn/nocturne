import re
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
HTML = (SITE / "index.html").read_text(encoding="utf-8")


def test_local_assets_exist():
    refs = re.findall(r'(?:src|href)="([^"]+)"', HTML)
    local = [r for r in refs if not r.startswith(("http", "#", "mailto:", "//"))]
    assert local, "expected some local asset references"
    for r in local:
        assert (SITE / r).exists(), f"missing local asset: {r}"


def test_required_content_present():
    assert "https://nocturne.stehn.com/download/Nocturne.zip" in HTML
    assert "GPLv3" in HTML or "GNU General Public License" in HTML
    assert "not affiliated" in HTML.lower()
    assert "graxpert" in HTML.lower() and "rc-astro" in HTML.lower()


def test_no_external_resource_calls():
    lower = HTML.lower()
    assert "cdn" not in lower
    assert "fonts.googleapis" not in lower
    assert "<script" in HTML  # local main.js only
