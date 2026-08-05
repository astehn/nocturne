"""Assemble site/*.html from site/_src/ — one layout, one nav, one footer.

Why this exists: the nav and footer were copy-pasted into 14 files, and had
already drifted — ten pages linked "Home" while three linked "Features", purely
because newer pages were copied from a different ancestor. Adding a page meant
reproducing the boilerplate by hand, which is also how the Phase 2 audit found
13 pages with no Open Graph tags at all.

The output stays completely static. This is a build step, not a server: it runs
before rsync and produces the same flat HTML the site has always served. A
database was considered and rejected — the pages have no dynamic content, and a
runtime dependency would trade away the zero-JS, fully-cacheable delivery that
makes the site fast.

Head metadata is GENERATED, not stored. A page declares a title, a description
and optionally a social image; the canonical URL, Open Graph tags, Twitter card
and structured data all follow from those. That is deliberate — it makes the
"page shipped without og: tags" class of bug impossible rather than merely fixed.

    .venv/bin/python packaging/build_site.py [--check]

--check builds to memory and reports which files WOULD change, without writing.
"""
from __future__ import annotations

import json
import pathlib
import sys

BASE = "https://nocturne.stehn.com"
ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SRC = SITE / "_src"

# label -> (href from another page, href from the homepage itself)
NAV = [
    ("Home",      "index.html",          "#top"),
    ("Tools",     "tools.html",          "tools.html"),
    ("Guide",     "guide.html",          "guide.html"),
    ("Sample data", "sample-data.html",  "sample-data.html"),
    ("FAQ",       "faq.html",            "faq.html"),
    ("Changelog", "changelog.html",      "changelog.html"),
    ("Download",  "index.html#download", "#download"),
]
GITHUB = "https://github.com/astehn/nocturne"

# The fuller of the three footers that had drifted apart. Ten pages carried a
# shortened credit and an abbreviated licence name; the three older pages had
# this one. Standardising UP rather than down — the full licence name is the
# clearer statement, and "works alongside" is true and useful.
FOOTER_CREDIT = ("Created &amp; directed by <strong>Andreas Stehn</strong>. Built with "
                 "PySide6/Qt, NumPy, astropy, SciPy, scikit-image, astroalign, SEP, "
                 "tifffile &amp; Pillow. Works alongside GraXpert and RC-Astro.")
FOOTER_LICENCE = ('Released under the <a href="https://www.gnu.org/licenses/gpl-3.0.html" '
                  'rel="noopener">GNU General Public License v3.0 (GPLv3)</a>. '
                  '© <span id="year"></span> · Not affiliated with ZWO, GraXpert, or RC-Astro.')
# Transparency about the download counter. Lives only where it is claimed — the
# homepage, which carries the Download button. It must survive any refactor of
# this file: it is a privacy disclosure, not decoration.
FOOTER_PRIVACY = ('No analytics, no trackers, no cookies. Downloads are counted — a click '
                  'on Download records the IP address and browser string so I can see how '
                  'many real people are using Nocturne, and those rows are deleted after '
                  '4 weeks. Nothing is shared with anyone. Questions or a removal request: '
                  '<a href="mailto:andreas@stehn.com">andreas@stehn.com</a>.')

SOFTWARE_APP = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "name": "Nocturne",
    "applicationCategory": "MultimediaApplication",
    "applicationSubCategory": "Astrophotography image processing",
    "operatingSystem": "macOS",
    "url": f"{BASE}/",
    "downloadUrl": f"{BASE}/get.php",
    "description": ("A free, native macOS app that turns a stacked ZWO Seestar image "
                    "into a finished picture through a guided, non-destructive pipeline."),
    "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
    "license": "https://www.gnu.org/licenses/gpl-3.0.html",
    "isAccessibleForFree": True,
    "author": {"@type": "Person", "name": "Andreas Stehn"},
    "codeRepository": GITHUB,
    # No softwareVersion: it would need updating on every release, and a stale
    # version asserted in machine-readable metadata is worse than none.
}


def parse_front_matter(text: str) -> tuple[dict, str]:
    """`--- key: value ... ---` then the body. Values are plain strings; `scripts`
    is comma-separated."""
    if not text.startswith("---"):
        raise ValueError("missing front matter")
    _, fm, body = text.split("---", 2)
    meta: dict = {}
    for line in fm.strip().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    meta["scripts"] = [s.strip() for s in meta.get("scripts", "main.js").split(",") if s.strip()]
    return meta, body.strip()


def nav_html(is_home: bool) -> str:
    brand = "#top" if is_home else "index.html"
    links = "\n".join(
        f'      <a href="{home if is_home else other}">{label}</a>'
        for label, other, home in NAV)
    return f'''  <header class="nav">
    <a class="brand" href="{brand}">
      <img src="img/icon.png" alt="" width="28" height="28">
      <span>Nocturne</span>
    </a>
    <nav class="nav-links">
{links}
      <a href="{GITHUB}" rel="noopener">GitHub</a>
    </nav>
  </header>'''


def head_html(name: str, meta: dict) -> str:
    title = meta["title"]
    desc = meta["description"]
    url = f"{BASE}/" if name == "index.html" else f"{BASE}/{name}"
    image = f"{BASE}/{meta.get('image', 'img/hero.png')}"
    out = [
        '  <meta charset="UTF-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        f"  <title>{title}</title>",
        f'  <meta name="description" content="{desc}">',
        '  <meta property="og:type" content="website">',
        f'  <meta property="og:title" content="{title}">',
        f'  <meta property="og:description" content="{desc}">',
        f'  <meta property="og:url" content="{url}">',
        f'  <meta property="og:image" content="{image}">',
        '  <meta name="twitter:card" content="summary_large_image">',
        f'  <meta name="twitter:title" content="{title}">',
        f'  <meta name="twitter:description" content="{desc}">',
        f'  <meta name="twitter:image" content="{image}">',
        f'  <link rel="canonical" href="{url}">',
        '  <link rel="icon" type="image/png" href="img/favicon.png">',
        '  <link rel="stylesheet" href="styles.css">',
    ]
    ld = None
    if name == "index.html":
        ld = SOFTWARE_APP
    elif meta.get("article"):
        # No datePublished/dateModified: they can only come from file mtimes here,
        # which change on every checkout. A wrong date is worse than none.
        ld = {
            "@context": "https://schema.org", "@type": "Article",
            "headline": meta["article"],
            "description": desc,
            "image": image,
            "author": {"@type": "Person", "name": "Andreas Stehn"},
            "publisher": {"@type": "Person", "name": "Andreas Stehn"},
            "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        }
    elif meta.get("crumb"):
        ld = {
            "@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{BASE}/"},
                {"@type": "ListItem", "position": 2, "name": "Tools",
                 "item": f"{BASE}/tools.html"},
                {"@type": "ListItem", "position": 3, "name": meta["crumb"],
                 "item": url},
            ],
        }
    if ld:
        out.append('  <script type="application/ld+json">')
        out.append(json.dumps(ld, indent=2, ensure_ascii=False))
        out.append("  </script>")
    return "\n".join(out)


def render(name: str, meta: dict, body: str) -> str:
    is_home = name == "index.html"
    scripts = "\n".join(f'  <script src="{s}"></script>' for s in meta["scripts"])
    privacy = f'\n      <p class="fine">{FOOTER_PRIVACY}</p>' if is_home else ""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
{head_html(name, meta)}
</head>
<body>
  <div class="stars" aria-hidden="true"></div>

{nav_html(is_home)}

{body}

  <footer class="footer">
    <div class="wrap">
      <p>{FOOTER_CREDIT}</p>
      <p class="fine">{FOOTER_LICENCE}</p>{privacy}
    </div>
  </footer>

{scripts}
</body>
</html>
'''


def build(check: bool = False) -> list[str]:
    changed = []
    for src in sorted(SRC.glob("*.html")):
        meta, body = parse_front_matter(src.read_text())
        out = render(src.name, meta, body)
        dst = SITE / src.name
        if dst.exists() and dst.read_text() == out:
            continue
        changed.append(src.name)
        if not check:
            dst.write_text(out)
    return changed


if __name__ == "__main__":
    _check = "--check" in sys.argv
    _changed = build(check=_check)
    _verb = "would change" if _check else "wrote"
    print(f"{_verb} {len(_changed)} page(s)"
          + (": " + ", ".join(_changed) if _changed else ""))
