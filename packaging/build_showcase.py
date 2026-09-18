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
    facts_from_filename, read_skips, target_from_name,
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
        entries.append({"slug": slug, "source": img.name,
                        "alt": alt_text(img.stem),
                        "images": write_sizes(img, slug)})
    return entries


def figure(e: dict) -> str:
    """`.frame` inside `.gallery` — the landing strip's own classes.

    Reused rather than invented: they already carry the multicol masonry, the
    `a.frame-img` hook lightbox.js binds to, and the hover transition. A new
    class would have been a second implementation of all three, free to drift.
    No figcaption, because the Share plate inside the picture already says it.
    """
    g, f = e["images"]["grid"], e["images"]["full"]
    return (
        f'        <figure class="frame">\n'
        f'          <a href="{f["src"]}" class="frame-img">\n'
        f'            <img src="{g["src"]}" width="{g["w"]}" height="{g["h"]}"\n'
        f'                 loading="lazy" decoding="async" alt="{e["alt"]}">\n'
        f'          </a>\n'
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
