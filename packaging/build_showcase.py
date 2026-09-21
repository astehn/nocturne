"""Generate the Gallery page from a folder of SHARED images.

    .venv/bin/python packaging/build_showcase.py ["~/Desktop/Finished Astro Images"]

Separate from build_gallery.py on purpose, decided with Andreas 2026-09-17: the
landing page's strip stays exactly as it is, sourced from its own folder, and
this builds a dedicated page from a different one. Two pages, two folders, no
shared state — merging them would have shown the same targets twice at
different processing.

WHAT MAKES THIS PAGE DIFFERENT, and why it needs almost no HTML: every picture
here is a Share export, so the caption is BURNED INTO THE IMAGE — target, common
name, integration, frame count, date, camera. A figcaption under it would print
the same words a second time, so there is none. The facts still reach the alt
text, where a screen reader and a search engine can read what the plate says.

Adding a picture is dropping a Share export in the folder and re-running this.
Nothing in site/_src/gallery.html is hand-maintained.

Run separately from a deploy, exactly like build_gallery.py and
build_samples.py: it reads a folder on the Desktop, and a release must not
depend on that.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
OUT_IMG = SITE / "img" / "showcase"
PAGE = SITE / "_src" / "gallery.html"

# Reused rather than re-derived: one definition of how a filename becomes facts.
sys.path.insert(0, str(ROOT / "packaging"))
from build_gallery import (  # noqa: E402
    COMMON, facts_from_filename, read_skips, target_from_name,
)

GRID_EDGE = 1100       # what the page shows; larger than the strip's 900, the
                       # pictures being the entire point of this page
FULL_EDGE = 2400       # what the lightbox opens
QUALITY = 82


def _slug(stem: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")


def _pretty_integration(total_s: int) -> str:
    h, m = divmod(round(total_s / 60), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def alt_text(stem: str) -> str:
    """What the burned-in plate says, for anyone who cannot see it.

    Not decoration: this is the only machine-readable copy of the caption on the
    page, so it carries the target and the capture facts rather than "an
    astrophotograph".
    """
    target = target_from_name(re.sub(r"_(drizzle|mosaic|Original|2x|fix)\b", " ", stem,
                                     flags=re.I)).strip()
    facts = facts_from_filename(stem)
    bits = [f"{target} photographed with a ZWO Seestar and finished in Nocturne"]
    if facts.get("frames"):
        bits.append(f"{facts['frames']} × {facts['per_sub_s']}s"
                    f" · {_pretty_integration(facts['total_s'])} total integration")
    return " — ".join(bits)


def write_sizes(src: pathlib.Path, slug: str) -> dict:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None          # the M 31 mosaic is 8984 × 5990
    OUT_IMG.mkdir(parents=True, exist_ok=True)
    out = {}
    with Image.open(src) as im:
        im = im.convert("RGB")
        for edge, key in ((GRID_EDGE, "grid"), (FULL_EDGE, "full")):
            c = im.copy()
            c.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            dest = OUT_IMG / f"{slug}-{edge}.jpg"
            c.save(dest, "JPEG", quality=QUALITY, optimize=True, progressive=True)
            out[key] = {"src": f"img/showcase/{dest.name}", "w": c.width,
                        "h": c.height, "bytes": dest.stat().st_size}
    return out


def collect(source: pathlib.Path) -> list[dict]:
    skips = read_skips(source)
    entries = []
    for img in sorted(source.iterdir()):
        if img.suffix.lower() not in (".jpg", ".jpeg", ".png") or img.name.startswith("."):
            continue
        if img.name in skips:
            print(f"  skipping {img.name} (listed in skip.txt)")
            continue
        slug = _slug(img.stem)
        print(f"  {img.name}")
        entries.append({"slug": slug, "source": img.name, "stem": img.stem,
                        "alt": alt_text(img.stem),
                        "images": write_sizes(img, slug)})
    return entries


# --- seeding the wall (2026-09-21) -------------------------------------
# Spec 2.2: the gallery becomes a database-backed page, so Andreas's own
# pictures must live in the same table as everyone else's. Two sources for one
# page drift, and the symptom of that drift is a caption under the wrong
# picture.
#
# This module keeps its job of READING his folder and resolving the facts; what
# changes is where the result goes -- a `submissions` row rather than an HTML
# figure.

# His byline on the wall. A seeded row needs one like every other row; `handle`
# is NOT NULL and the page renders it, so an empty one is a blank byline beside
# real ones.
SEED_HANDLE = "@andreas"

# Every picture on the wall is his, and he owns an S30 Pro and nothing else, so
# this is a fact about the seeded rows rather than a guess. (The S50 material in
# the training set is licensed public data and never reaches the gallery.)
SEED_INSTRUMENT = "ZWO Seestar S30 Pro"

# SEEDING READS THE DERIVED JPEGs, not the Desktop source folder collect()
# uses. Deliberate: these rows point at img/showcase/... URLs, so the deployed
# files ARE the truth being recorded, the seed runs without that folder
# mounted, and the tests run anywhere. (It also cannot accidentally pick up a
# working file: build_gallery.py's folder holds diagnostics like
# M16_COMPARE_input_corners_after, and every seeded row is `approved`.)
SHOWCASE = SITE / "img" / "showcase"


def collect_showcase() -> list[dict]:
    """Entries for the ten curated wall images, in `collect()`'s shape.

    Facts come from the FILENAME, which is Andreas's own labelling of his own
    export -- "ngc7000-drizzle-163x20s-54min-original" -- and is the only
    record of them now that the burned plates are being removed. `captured_on`
    stays empty rather than being inferred: a date that is not in the filename
    would be invented, and the caption renders without one.
    """
    entries = []
    for thumb in sorted(SHOWCASE.glob(f"*-{GRID_EDGE}.jpg")):
        stem = thumb.stem[: -len(f"-{GRID_EDGE}")]
        full = SHOWCASE / f"{stem}-{FULL_EDGE}.jpg"
        if not full.exists():
            print(f"  skipping {stem}: no {FULL_EDGE}px version", file=sys.stderr)
            continue
        e = {"slug": stem, "source": f"{stem}.jpg",
             "target": target_from_name(stem),
             "instrument": SEED_INSTRUMENT, "captured_on": ""}
        e.update({k: v for k, v in facts_from_filename(stem).items() if v})
        e["images"] = {
            "grid": {"src": f"img/showcase/{thumb.name}",
                     "bytes": thumb.stat().st_size},
            "full": {"src": f"img/showcase/{full.name}",
                     "bytes": full.stat().st_size},
        }
        entries.append(e)
    return entries


def seed_rows(entries: list[dict]) -> list[dict]:
    """One `submissions` row per gallery entry, keyed by COLUMN NAME.

    Every field is named explicitly rather than copied from the entry. That is
    not style: `collect()` carries whatever the FITS header happened to hold,
    and a location key reaching a public table is the one leak this feature
    must not have. Copying would make that leak the default.

    `catalogue_id` stays NULL -- the site matches it server-side so the mapping
    can improve without an app release (spec 4).
    """
    rows = []
    for e in entries:
        images = e.get("images") or {}
        grid = images.get("grid") or {}
        full = images.get("full") or {}
        rows.append({
            "handle": SEED_HANDLE,
            "target": e.get("target") or None,
            "catalogue_id": None,
            "integration_s": e.get("total_s"),
            "frames": e.get("frames"),
            "sub_s": e.get("per_sub_s"),
            "captured_on": e.get("captured_on") or None,
            "instrument": e.get("instrument") or None,
            "stored_2000": full.get("src"),
            "stored_900": grid.get("src"),
            "orig_filename": e.get("source") or f"{e.get('slug', '')}.jpg",
            "size_bytes": full.get("bytes") or grid.get("bytes") or 0,
            "status": "approved",
        })
    return rows


def _sql_value(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    # Backslash AND quote: MariaDB treats both as escapes by default, and a
    # target like "Barnard's Loop" is a real name that would otherwise end the
    # statement early.
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def seed_sql(entries: list[dict]) -> str:
    """INSERT statements for the seeded rows.

    Emitted as text rather than executed: the generator runs on Andreas's Mac
    and the database is on the VPS, so printing SQL to pipe over ssh is both
    simpler than a tunnel and reviewable before it runs.
    """
    rows = seed_rows(entries)
    if not rows:
        return ""
    cols = list(rows[0])
    out = ["-- Seeded from the gallery folder by build_gallery.py --seed.",
           "-- Review before piping; these rows are status='approved' and go",
           "-- straight onto the public wall."]
    for r in rows:
        values = ", ".join(_sql_value(r[c]) for c in cols)
        out.append(f"INSERT INTO submissions ({', '.join(cols)}) VALUES ({values});")
    return "\n".join(out) + "\n"


def caption_html(stem: str) -> str:
    """The figcaption's inner markup, from the filename's own facts.

    THE MARKUP CONTRACT: gallery_render.php renders the same three elements for
    a submitted row, so the static fallback page and the dynamic wall cannot
    look like two different pages. Classes are the ones styles.css already has
    -- .frame-target, .frame-common, .frame-data were written for this and had
    never been used, because the plate made them unnecessary.

    Parts are collected and joined, so a picture whose filename carries no
    numbers renders a name and nothing else rather than a dangling separator.
    """
    clean = re.sub(r"_(drizzle|mosaic|Original|2x|fix)\b", " ", stem, flags=re.I)
    target = target_from_name(clean).strip()
    facts = facts_from_filename(stem)
    out = f'<span class="frame-target">{target}</span>'
    common = COMMON.get(target, "")
    if common:
        out += f'<span class="frame-common">{common}</span>'
    bits = []
    if facts.get("frames") and facts.get("per_sub_s"):
        bits.append(f"{facts['frames']} &times; {facts['per_sub_s']:g}s")
    if facts.get("total_s"):
        bits.append(_pretty_integration(facts["total_s"]))
    if bits:
        out += f'<span class="frame-data">{" &middot; ".join(bits)}</span>'
    # The byline, as the dynamic wall renders for every row. On this page it is
    # always his -- the fallback shows his pictures -- but it must be PRESENT,
    # or the two renderings differ by a line and a database outage visibly
    # changes the page rather than only its source.
    out += f'<span class="frame-by">{SEED_HANDLE}</span>'
    return out


def figure(e: dict) -> str:
    """`.frame` inside `.gallery` — the landing strip's own classes.

    Reused rather than invented: they already carry the multicol masonry, the
    `a.frame-img` hook lightbox.js binds to, and the hover transition. A new
    class would have been a second implementation of all three, free to drift.

    IT NOW CARRIES A FIGCAPTION. It did not until 2026-09-21, and the reason is
    in this module's docstring: every picture was a Share export with the
    caption burned into the pixels, so a rendered one would have said the same
    words twice. Andreas is replacing all ten with unannotated exports, which
    removes the only copy of those facts from the page -- so they come back as
    text, where they are selectable, translatable, and readable at tile size.
    """
    g, f = e["images"]["grid"], e["images"]["full"]
    return (
        f'        <figure class="frame">\n'
        f'          <a href="{f["src"]}" class="frame-img">\n'
        f'            <img src="{g["src"]}" width="{g["w"]}" height="{g["h"]}"\n'
        f'                 loading="lazy" decoding="async" alt="{e["alt"]}">\n'
        f'          </a>\n'
        f'          <figcaption>{caption_html(e["stem"])}</figcaption>\n'
        f'        </figure>\n')


def page_html(entries: list[dict]) -> str:
    figures = "".join(figure(e) for e in entries).rstrip("\n")
    return f"""---
title: Gallery — images made with Nocturne on a ZWO Seestar
description: Finished astrophotographs from a ZWO Seestar, stacked and processed in Nocturne. Every picture states its own integration time and frame count.
scripts: main.js, lightbox.js
---
<main id="top">
    <section class="page-head">
      <div class="wrap prose">
        <p class="eyebrow">Gallery</p>
        <h1>Made with Nocturne</h1>
        <p>Every picture here came off a ZWO Seestar and was stacked and finished in
          Nocturne — no other editor. Each one carries its own capture data, so you can
          see what a given number of ten-second frames actually buys you.</p>
      </div>
    </section>

    <section class="section-shot">
      <div class="wrap-wide">
        <div class="gallery">
<!-- SHOWCASE:START -->
{figures}
        <!-- SHOWCASE:END -->
        </div>
      </div>
    </section>

    <section class="s-statement">
      <div class="wrap">
        <p>Every one of these started as a folder of ten-second frames from a
          telescope that costs less than a lens.</p>
        <cite>What the pictures are actually showing</cite>
      </div>
    </section>
</main>
"""


def prune(entries: list[dict]) -> list[str]:
    """Delete derivatives that no longer belong to a picture on the page.

    Without this a replaced or skipped image leaves its JPEGs behind for ever:
    the site rsync deliberately runs WITHOUT --delete (deploy.local.toml says
    so, to protect server-only files), so anything published once stays
    published. Swapping M 31 on 2026-09-18 left the old 8 MB mosaic's two files
    on the server, reachable by URL, after the page had stopped linking them.
    """
    keep = {pathlib.Path(v["src"]).name
            for e in entries for v in e["images"].values()}
    gone = []
    for f in sorted(OUT_IMG.glob("*.jpg")):
        if f.name not in keep:
            f.unlink()
            gone.append(f.name)
    return gone


def main() -> int:
    source = pathlib.Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else \
        pathlib.Path.home() / "Desktop" / "Finished Astro Images"
    if not source.is_dir():
        print(f"no such folder: {source}")
        return 2
    print(f"reading {source}")
    entries = collect(source)
    if not entries:
        print("  no images found")
        return 1
    PAGE.write_text(page_html(entries))
    pruned = prune(entries)
    total = sum(e["images"]["grid"]["bytes"] for e in entries)
    print(f"wrote {PAGE.relative_to(ROOT)} — {len(entries)} pictures, "
          f"{total / 1e6:.1f} MB above the fold (grid sizes)")
    for name in pruned:
        print(f"  pruned {name} (no longer on the page)")
    if pruned:
        print("  NOTE: the site rsync has no --delete, so remove these from the "
              "server by hand as well")
    print("now run: .venv/bin/python packaging/build_site.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
