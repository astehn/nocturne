"""Regenerate site/sitemap.xml from the deployable HTML pages.

Generated, not hand-maintained: a sitemap that silently goes stale is worse than
none, and we have already shipped two new pages in one day. Run before a deploy.

Deliberately omits <lastmod>. It can only be sourced from file mtimes here, which
change on every checkout and would tell crawlers everything was edited at once —
a wrong date is worse than a missing one.
"""
from __future__ import annotations

import pathlib

BASE = "https://nocturne.stehn.com"
SITE = pathlib.Path(__file__).resolve().parent.parent / "site"

# Pages that exist but should not be advertised: no public entry point, or a
# duplicate of a canonical URL.
SKIP = {"admin.html"}

def main() -> None:
    pages = sorted(p.name for p in SITE.glob("*.html") if p.name not in SKIP)
    locs = [f"{BASE}/" if n == "index.html" else f"{BASE}/{n}" for n in pages]
    urls = [f"  <url><loc>{loc}</loc></url>" for loc in locs]
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "\n".join(urls) + "\n</urlset>\n")
    out = SITE / "sitemap.xml"
    out.write_text(xml)
    print(f"wrote {out} — {len(urls)} URLs")
    for loc in locs:
        print("  " + loc)

if __name__ == "__main__":
    main()
