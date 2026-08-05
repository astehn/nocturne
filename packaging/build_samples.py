"""Generate the sample-data page from a folder of target folders.

Adding a target should be dropping a directory in and re-running this — not
editing HTML. So everything on the page is derived:

    <source>/NGC7000/
        NGC7000_163x20s_54min.fits   the stacked master (offered as a download)
        NGC7000_163x20s_54min.png    a representative picture of the result
        Google_Drive.txt             one line: the share link for the subframes
        about.txt                    OPTIONAL: a paragraph about this target

Frame counts and exposures come from the FITS header rather than the filename,
because the filename is a convenience and the header is the record. The filename
is used only for the download's public name.

    .venv/bin/python packaging/build_samples.py [--source DIR] [--check]

Writes `site/_src/sample-data.html` (a normal page fragment, wrapped afterwards
by build_site.py), web-sized JPEGs into `site/img/samples/`, and stages the
masters in `site/data/samples/`.

The masters are staged rather than linked because the deploy config EXCLUDES
`*.fits` from the website rsync — a deliberate guard against ever pushing astro
data to the web root by accident. That guard stays; the samples get their own
explicit upload step instead.
"""
from __future__ import annotations

import argparse
import html
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
IMG_DIR = SITE / "img" / "samples"
DATA_DIR = SITE / "data" / "samples"
PAGE = SITE / "_src" / "sample-data.html"

DEFAULT_SOURCE = pathlib.Path.home() / "Desktop" / "Webpage"

# Web copies of the preview images. The originals are 4-6 MB PNGs; the site's
# other photographs sit between 90 and 310 KB, and a sample page that takes ten
# seconds to load is a sample page nobody scrolls.
MAX_EDGE = 1400
JPEG_QUALITY = 82


def _fits_facts(path: pathlib.Path) -> dict:
    from astropy.io import fits
    with fits.open(path) as hdul:
        header = hdul[0].header
        shape = hdul[0].data.shape
    frames = header.get("STACKCNT")
    total = header.get("LIVETIME") or header.get("EXPTIME")
    height, width = (shape[-2], shape[-1])
    per_sub = (float(total) / float(frames)) if (frames and total) else None
    return {
        "target": str(header.get("OBJECT") or path.stem.split("_")[0]),
        "frames": int(frames) if frames else None,
        "total_s": float(total) if total else None,
        "per_sub_s": per_sub,
        "camera": str(header.get("INSTRUME") or header.get("CREATOR") or ""),
        "filter": str(header.get("FILTER") or ""),
        "width": int(width), "height": int(height),
        "bytes": path.stat().st_size,
    }


def _minutes(seconds: float | None) -> str:
    if not seconds:
        return ""
    m = int(round(seconds / 60))
    return f"{m // 60} h {m % 60:02d} m" if m >= 60 else f"{m} min"


def _read_targets(source: pathlib.Path) -> list[dict]:
    targets = []
    for folder in sorted(p for p in source.iterdir() if p.is_dir()):
        fits_files = sorted([*folder.glob("*.fits"), *folder.glob("*.fit")])
        pngs = sorted([*folder.glob("*.png"), *folder.glob("*.jpg")])
        if not fits_files or not pngs:
            print(f"  skipping {folder.name}: needs one FITS and one preview image")
            continue
        link_file = folder / "Google_Drive.txt"
        about_file = folder / "about.txt"
        facts = _fits_facts(fits_files[0])
        facts.update({
            "slug": folder.name,
            "fits": fits_files[0],
            "preview": pngs[0],
            "subs_url": link_file.read_text().strip().split()[0] if link_file.exists() else "",
            "about": about_file.read_text().strip() if about_file.exists() else "",
        })
        targets.append(facts)
    return targets


def _write_preview(src: pathlib.Path, dest: pathlib.Path) -> tuple[int, int, int]:
    from PIL import Image
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        return im.width, im.height, dest.stat().st_size


def _card(t: dict) -> str:
    e = html.escape
    name = e(t["target"])
    shot = f"{t['frames']} × {t['per_sub_s']:.0f} s" if t["frames"] and t["per_sub_s"] else ""
    facts = [f for f in (
        f"<strong>{shot}</strong>" if shot else "",
        _minutes(t["total_s"]),
        e(t["camera"]) if t["camera"] else "",
        f"{t['width']} × {t['height']}",
    ) if f]
    about = f'<p>{e(t["about"])}</p>' if t["about"] else ""
    subs = (f'<a class="btn btn-ghost" href="{e(t["subs_url"])}" rel="noopener">'
            f'All {t["frames"]} subframes (Google Drive)</a>'
            if t["subs_url"] else "")
    return f"""
        <article class="sample">
          <figure class="sample-shot">
            <img src="img/samples/{t['slug'].lower()}.jpg" alt="{name} processed in Nocturne"
                 width="{t['pw']}" height="{t['ph']}" loading="lazy" decoding="async">
          </figure>
          <div class="sample-body">
            <h3>{name}</h3>
            <p class="fine">{" · ".join(facts)}</p>
            {about}
            <p>
              <a class="btn btn-primary" href="data/samples/{t['fits'].name}">
                Stacked master ({t['bytes'] / 2**20:.0f} MB)</a>
              {subs}
            </p>
          </div>
        </article>"""


def render(targets: list[dict]) -> str:
    cards = "\n".join(_card(t) for t in targets)
    total = sum(t["total_s"] or 0 for t in targets)
    return f"""---
title: Free Seestar sample data — try Nocturne on real captures
description: Real ZWO Seestar data you can download and process yourself — stacked masters and the full subframe sets, free to use. No telescope required to try Nocturne.
image: img/samples/{targets[0]['slug'].lower()}.jpg
article: Free Seestar sample data
scripts: main.js, lightbox.js
---
  <main id="top">
    <section class="subhead">
      <div class="wrap">
        <p class="eyebrow">Free to download</p>
        <h1>Sample data</h1>
        <p class="lead">Real captures from a ZWO Seestar, free for anyone to download and process
        — {_minutes(total)} of it. Use them to try Nocturne before you own a telescope, to follow
        the guide with the same frames it was written from, or to compare your results against
        someone else's on identical data.</p>
      </div>
    </section>

    <section class="section alt">
      <div class="wrap tool-body">
        <p>Each target comes two ways. The <strong>stacked master</strong> is one file, already
        aligned and integrated, and it is what you want if you came to practise processing — open
        it and start at Crop. The <strong>subframes</strong> are every individual exposure, for
        anyone who also wants to practise stacking and frame grading.</p>
        <p class="fine">Licensed <a href="https://creativecommons.org/licenses/by/4.0/"
        rel="noopener">CC&nbsp;BY&nbsp;4.0</a> — use them for anything, including commercially, as
        long as you credit Andreas Stehn. Post your results wherever you like; no need to ask.</p>
      </div>
    </section>

    <section class="section">
      <div class="wrap-wide">
        <div class="samples">{cards}
        </div>
      </div>
    </section>

    <section class="section alt">
      <div class="wrap tool-body">
        <h2>What to do with them</h2>
        <p>If you have never processed astronomical data before, start with
        <a href="how-to-process-seestar-fits.html">how to process Seestar FITS files</a> — it
        explains why the file opens almost black, what each step is for, and what going too far
        looks like. The <a href="guide.html">guide</a> is the shorter tour if you would rather
        just get going.</p>
        <p>You will need Nocturne itself, which is free and open source.</p>
        <p style="margin-top:18px">
          <a class="btn btn-primary big" href="index.html#download">Download Nocturne</a>
          <a class="btn btn-ghost" href="how-to-process-seestar-fits.html">Read the guide first</a>
        </p>
      </div>
    </section>
  </main>
"""


def build(source: pathlib.Path, check: bool = False) -> int:
    if not source.is_dir():
        print(f"source not found: {source}")
        return 1
    targets = _read_targets(source)
    if not targets:
        print(f"no usable target folders in {source}")
        return 1

    for t in targets:
        dest = IMG_DIR / f"{t['slug'].lower()}.jpg"
        if check:
            t["pw"], t["ph"] = MAX_EDGE, MAX_EDGE
            continue
        t["pw"], t["ph"], size = _write_preview(t["preview"], dest)
        print(f"  {t['slug']}: preview {t['pw']}x{t['ph']} -> {size / 1024:.0f} KB")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        staged = DATA_DIR / t["fits"].name
        if not staged.exists() or staged.stat().st_size != t["bytes"]:
            shutil.copy2(t["fits"], staged)
            print(f"  {t['slug']}: staged master {t['bytes'] / 2**20:.0f} MB")

    page = render(targets)
    if check:
        current = PAGE.read_text() if PAGE.exists() else ""
        print("sample-data.html WOULD change" if current != page else "sample-data.html unchanged")
        return 0
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(page)
    print(f"wrote {PAGE.relative_to(ROOT)} with {len(targets)} target(s)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=pathlib.Path, default=DEFAULT_SOURCE)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    return build(args.source, args.check)


if __name__ == "__main__":
    sys.exit(main())
