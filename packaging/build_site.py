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

import hashlib
import json
import pathlib
import re
import sys

BASE = "https://nocturne.stehn.com"
ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SRC = SITE / "_src"

# label -> (href from another page, href from the homepage itself)
NAV = [
    ("Home",      "index.html",          "#top"),
    ("Gallery",   "gallery.html",        "gallery.html"),
    ("Tools",     "tools.html",          "tools.html"),
    # The session planner. Its own entry at Andreas's request 2026-09-20 — it is
    # not a page ABOUT Nocturne, it is a thing you use, and burying a nightly
    # utility inside Tools (which describes the app's steps) would hide it.
    ("Planner",   "planner.html",        "planner.html"),
    ("Guide",     "guide.html",          "guide.html"),
    ("Sample data", "sample-data.html",  "sample-data.html"),
    ("FAQ",       "faq.html",            "faq.html"),
    ("Changelog", "changelog.html",      "changelog.html"),
    # The dedicated page, not the homepage anchor: with two platforms and 38
    # releases, one button cannot serve a Linux visitor or anyone who wants the
    # version they were running last week (2026-09-18).
    ("Download",  "download.html",       "download.html"),
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
                  '© <span id="year"></span> · <a href="privacy.html">Privacy</a> · '
                  'Not affiliated with ZWO, GraXpert, or RC-Astro.')
# Transparency about the download counter, next to the button it describes.
# ONE SENTENCE since 2026-09-17, when privacy.html was written: this used to
# carry the whole disclosure — what is recorded, for how long, who to email —
# because there was nowhere else to put it. Measured then at 292 characters and
# 108px, three lines of fine print, twice the height of the licence line above
# it, plus a SECOND link to the same privacy page the licence line already
# links. The page holds the detail now; this holds the claim.
FOOTER_PRIVACY = ('No analytics, no trackers, no cookies. Downloads are counted — '
                  'a number, not you.')

SOFTWARE_APP = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "name": "Nocturne",
    "applicationCategory": "MultimediaApplication",
    "applicationSubCategory": "Astrophotography image processing",
    # Both, since v0.35.0. This is what a search engine reads to describe the
    # app, so leaving it at "macOS" told Google the Linux build does not exist.
    "operatingSystem": "macOS, Linux",
    "url": f"{BASE}/",
    "downloadUrl": f"{BASE}/get.php",
    "description": ("A free, native app for macOS and Linux that turns a stacked ZWO "
                    "Seestar image into a finished picture through a guided, "
                    "non-destructive pipeline."),
    "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
    "license": "https://www.gnu.org/licenses/gpl-3.0.html",
    "isAccessibleForFree": True,
    "author": {"@type": "Person", "name": "Andreas Stehn"},
    "codeRepository": GITHUB,
    # No softwareVersion: it would need updating on every release, and a stale
    # version asserted in machine-readable metadata is worse than none.
}


def asset_url(name: str) -> str:
    """`name?v=<content hash>` — a cache buster, not decoration.

    The server sends `Cache-Control: public, max-age=2592000`, so a returning
    visitor keeps a stylesheet for THIRTY DAYS. That is the right setting for
    a file that never changes and exactly wrong for one that does: the sample
    data page shipped with new .sample rules and every existing visitor got the
    new HTML against their cached old CSS, which rendered the cards unstyled.
    Seen live 2026-08-05.

    Keying the query string to the file's contents means an unchanged asset
    keeps its long cache and a changed one is fetched immediately, with no
    manual version to remember to bump.
    """
    path = SITE / name
    if not path.exists():
        return name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    return f"{name}?v={digest}"


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
    # The toggle is a CHECKBOX, not a button, so the menu opens with no
    # JavaScript at all — nine links behind a control that needs a script is
    # nine links a failed script can hide. The input stays focusable (it is
    # clipped, not `hidden`) so it works from the keyboard on its own too;
    # main.js only adds aria-expanded and close-on-choose.
    return f'''  <header class="nav">
    <a class="brand" href="{brand}">
      <img src="img/icon.png" alt="" width="28" height="28">
      <span>Nocturne</span>
    </a>
    <input type="checkbox" id="nav-open" class="nav-open">
    <label class="nav-toggle" for="nav-open" aria-label="Menu" role="button"
           aria-controls="nav-links" aria-expanded="false">
      <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" focusable="false">
        <path class="bar-top" d="M3 6h18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
        <path class="bar-mid" d="M3 12h18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
        <path class="bar-bot" d="M3 18h18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      </svg>
    </label>
    <nav class="nav-links" id="nav-links">
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
        # The two faces are SELF-HOSTED, declared in styles.css. They were
        # linked from fonts.googleapis.com for a day, which broke
        # test_no_external_resource_calls -- a test that names fonts.googleapis
        # explicitly, so the site's no-third-party rule was deliberate and I
        # walked through it. Self-hosting also removes the failure mode the
        # design doc itself listed ("if Google Fonts is slow or blocked the page
        # falls back"), and stops an EU site handing every visitor's IP to
        # Google for a font.
        #
        # Preloaded rather than merely declared: an @font-face in the stylesheet
        # is not requested until the CSS is parsed AND a glyph needs it, which
        # is the same two-round-trip delay the old comment here complained about
        # @import causing. Only the two Latin faces the first screenful uses.
        # NOT asset_url(): the @font-face in styles.css asks for the plain
        # path, and a preload of a DIFFERENT url (…woff2?v=hash) is not the
        # same request. The browser would fetch both and warn that the
        # preloaded font went unused. Fonts do not need the cache-busting
        # anyway -- changing one means a new filename.
        '  <link rel="preload" href="fonts/familjen-grotesk-400-latin.woff2"'
        ' as="font" type="font/woff2" crossorigin>',
        '  <link rel="preload" href="fonts/ibm-plex-mono-400-latin.woff2"'
        ' as="font" type="font/woff2" crossorigin>',
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
        f'  <link rel="stylesheet" href="{asset_url("styles.css")}">',
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
    scripts = "\n".join(f'  <script src="{asset_url(s)}"></script>'
                        for s in meta["scripts"])
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


RELEASE_RE = re.compile(r'<p class="ver">(v[0-9][0-9.]*)</p>')
ENTRY_RE = re.compile(r'<article class="release">')


def fill_release_stats(body: str) -> str:
    """Substitute {{releases}} and {{latest_release}} in the changelog.

    deploy.py PREPENDS each new release into the changelog source, so any figure
    about the release history typed by hand goes stale the next time a version
    ships -- silently, because nothing reads it back. Derived here instead, from
    the entries actually on the page.

    The count comes from the ENTRIES, not the version lines: the five oldest
    entries predate versioned releases and carry no <p class="ver">, so counting
    those undercounts the history by five and calls the sixth-oldest release the
    first one.
    """
    if "{{releases}}" not in body and "{{latest_release}}" not in body:
        return body
    vers = RELEASE_RE.findall(body)
    if not vers:
        return body
    return (body.replace("{{releases}}", str(len(ENTRY_RE.findall(body))))
                .replace("{{latest_release}}", vers[0]))


def build(check: bool = False) -> list[str]:
    changed = []
    for src in sorted(SRC.glob("*.html")):
        meta, body = parse_front_matter(src.read_text())
        body = fill_release_stats(body)
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
