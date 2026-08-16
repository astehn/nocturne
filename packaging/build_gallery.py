"""Generate the gallery from a folder of finished pictures.

    .venv/bin/python packaging/build_gallery.py ["~/Desktop/Astro Images"]

Adding an image is dropping a file in that folder and re-running this. Nothing
in site/_src/gallery.html or the index's gallery strip is hand-maintained, so a
picture reaches the site without anyone editing HTML — which is the difference
between the gallery growing when Andreas finishes an image and growing when we
happen to hold a website session.

Facts come from the master FITS wherever one can be matched by filename stem, so
the captions are the capture's own record rather than anyone's memory. Where no
master is found the entry still renders, and the build says so; a `<stem>.txt`
beside the image overrides the caption entirely.

Run separately from a deploy, exactly like build_samples.py: it needs the astro
drive mounted, and a release must not depend on that.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
OUT_IMG = SITE / "img" / "gallery"
MANIFEST = SITE / "_src" / "gallery.json"
INDEX = SITE / "_src" / "index.html"
PAGE = SITE / "_src" / "gallery.html"

MASTER_ROOTS = [pathlib.Path("/Volumes/Work2/Images/Astro/Work"),
                pathlib.Path("/Volumes/Work2/Images/Astro/Archive")]

GRID_EDGE = 900        # what the grid shows
FULL_EDGE = 2000       # what the lightbox opens
QUALITY = 82

START = "<!-- GALLERY:START -->"
END = "<!-- GALLERY:END -->"

# "M45_300x10s_50min" -> M 45 ; "NGC_6888_183x10sec_..." -> NGC 6888
_TARGET = re.compile(r"^(M|NGC|IC|SH|LDN|B|VDB)[_ ]?(\d+[A-Za-z]?)", re.I)

COMMON = {
    "M 8": "The Lagoon Nebula", "M 17": "The Omega Nebula",
    "M 27": "The Dumbbell Nebula", "M 31": "The Andromeda Galaxy",
    "M 33": "The Triangulum Galaxy", "M 45": "The Pleiades",
    "NGC 6888": "The Crescent Nebula", "NGC 6992": "The Veil Nebula",
    "NGC 7000": "The North America Nebula", "NGC 281": "The Pacman Nebula",
    "IC 1396A": "The Elephant's Trunk Nebula",
}


def target_from_name(stem: str) -> str:
    m = _TARGET.match(stem.replace("_", " ").strip())
    if not m:
        return stem.replace("_", " ")
    return f"{m.group(1).upper()} {m.group(2)}"


_FROM_NAME = re.compile(r"(\d{2,4})\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:s|sec|secs)", re.I)


def facts_from_filename(stem: str) -> dict:
    """Frames and exposure as Andreas named them — "M33_640x10sec_..." — used
    only when no master can be matched.

    Not a guess: it is his own labelling of his own export, and the manifest
    records `facts_from` so the two provenances stay distinguishable. The
    alternative was matching a master by target NAME, which would have attached
    a 140-frame master's numbers to a 640-frame export and stated it as fact.
    """
    m = _FROM_NAME.search(stem)
    if not m:
        return {}
    frames, per_sub = int(m.group(1)), float(m.group(2))
    return {"frames": frames, "per_sub_s": round(per_sub),
            "total_s": round(frames * per_sub)}


def find_master(stem: str) -> pathlib.Path | None:
    """The master this picture came from, matched on filename stem. Andreas
    names an export after the master it came from, so this is reliable when it
    hits and silent when it does not."""
    for root in MASTER_ROOTS:
        if not root.is_dir():
            continue
        for ext in ("fits", "fit"):
            hit = next(root.glob(f"*/{stem}.{ext}"), None) or \
                  next(root.glob(f"*/*/{stem}.{ext}"), None)
            if hit:
                return hit
    return None


def facts_from_master(path: pathlib.Path) -> dict:
    from astropy.io import fits
    h = fits.getheader(path)
    frames = h.get("STACKCNT") or h.get("NSUBS")
    exp = h.get("LIVETIME") or h.get("EXPTIME")
    # two conventions live in the wild: our masters store TOTAL integration in
    # EXPTIME, a device master stores the per-sub exposure. Tell them apart by
    # size rather than by which tool wrote the file.
    total = per_sub = None
    if exp and frames:
        exp, frames = float(exp), int(frames)
        if exp > 120:
            total, per_sub = exp, exp / frames
        else:
            per_sub, total = exp, exp * frames
    return {
        "target": str(h.get("OBJECT") or "").strip(),
        "frames": int(frames) if frames else None,
        "per_sub_s": round(per_sub) if per_sub else None,
        "total_s": round(total) if total else None,
        "filter": str(h.get("FILTER") or "").strip(),
        "master": path.name,
    }


def caption(e: dict) -> str:
    """`300 x 10s . 50 min . IRCUT` — the capture's own numbers, which are the
    most credible words on the page and tell a beginner what is enough."""
    bits = []
    if e.get("frames") and e.get("per_sub_s"):
        bits.append(f"{e['frames']} × {e['per_sub_s']:g}s")
    if e.get("total_s"):
        m = round(e["total_s"] / 60)
        bits.append(f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min")
    if e.get("filter"):
        bits.append(e["filter"])
    return " · ".join(bits)


def write_sizes(src: pathlib.Path, slug: str) -> dict:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    out = {}
    OUT_IMG.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = im.convert("RGB")
        for edge, key in ((GRID_EDGE, "grid"), (FULL_EDGE, "full")):
            c = im.copy()
            c.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            dest = OUT_IMG / f"{slug}-{edge}.jpg"
            c.save(dest, "JPEG", quality=QUALITY, optimize=True, progressive=True)
            out[key] = {"src": f"img/gallery/{dest.name}", "w": c.width,
                        "h": c.height, "bytes": dest.stat().st_size}
    return out


def read_skips(source: pathlib.Path) -> set[str]:
    """Filenames listed in skip.txt stay out of the gallery.

    The folder is the source of truth, so the way to exclude a picture should
    not be to delete it — Andreas keeps a cropped and an uncropped M 31, and
    only one belongs on the site. One line per filename, # for comments.
    """
    f = source / "skip.txt"
    if not f.exists():
        return set()
    return {line.strip() for line in f.read_text().splitlines()
            if line.strip() and not line.startswith("#")}


def collect(source: pathlib.Path) -> list[dict]:
    entries = []
    skips = read_skips(source)
    for img in sorted(source.iterdir()):
        if img.suffix.lower() not in (".jpg", ".jpeg", ".png") or img.name.startswith("."):
            continue
        if img.name in skips:
            print(f"  skipping {img.name} (listed in skip.txt)")
            continue
        stem = img.stem
        slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
        e = {"slug": slug, "source": img.name}
        master = find_master(stem)
        if master:
            e.update(facts_from_master(master))
            e["facts_from"] = "master"
        else:
            e.update(facts_from_filename(stem))
            e["facts_from"] = "filename" if e.get("frames") else "none"
        if not e.get("target"):
            e["target"] = target_from_name(stem)
        if e["facts_from"] != "master":
            e["needs_review"] = "no master matched; capture data read from the filename"
        e["common"] = COMMON.get(e["target"], "")
        override = img.with_suffix(".txt")
        if override.exists():
            e["note"] = override.read_text().strip()
        e["images"] = write_sizes(img, slug)
        e["caption"] = caption(e)
        entries.append(e)
    return entries


def figure(e: dict) -> str:
    g, f = e["images"]["grid"], e["images"]["full"]
    title = e["target"] + (f" — {e['common']}" if e["common"] else "")
    alt = f"{title}, photographed with a Seestar and finished in Nocturne"
    cap = e["caption"] or ""
    return (
        f'        <figure class="frame">\n'
        f'          <a href="{f["src"]}" class="frame-img">\n'
        f'            <img src="{g["src"]}" width="{g["w"]}" height="{g["h"]}" '
        f'loading="lazy" decoding="async" alt="{alt}">\n'
        f'          </a>\n'
        f'          <figcaption>\n'
        f'            <span class="frame-target">{e["target"]}</span>'
        + (f'<span class="frame-common">{e["common"]}</span>' if e["common"] else "")
        + (f'<span class="frame-data">{cap}</span>' if cap else "")
        + f'\n          </figcaption>\n'
        f'        </figure>\n')


def strip_html(entries: list[dict]) -> str:
    return ("".join(figure(e) for e in entries)).rstrip("\n")


def inject(entries: list[dict]) -> bool:
    text = INDEX.read_text()
    if START not in text or END not in text:
        print(f"  index.html has no {START} / {END} markers — skipped")
        return False
    head, rest = text.split(START, 1)
    _old, tail = rest.split(END, 1)
    new = f"{head}{START}\n{strip_html(entries)}\n        {END}{tail}"
    if new != text:
        INDEX.write_text(new)
    return True


def main() -> int:
    source = pathlib.Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else \
        pathlib.Path.home() / "Desktop" / "Astro Images"
    if not source.is_dir():
        print(f"no such folder: {source}")
        return 2
    print(f"reading {source}")
    entries = collect(source)
    if not entries:
        print("  no images found")
        return 1

    MANIFEST.write_text(json.dumps(entries, indent=2) + "\n")
    injected = inject(entries)

    total = sum(e["images"]["grid"]["bytes"] + e["images"]["full"]["bytes"] for e in entries)
    print(f"\n{len(entries)} pictures -> {OUT_IMG.relative_to(ROOT)}  "
          f"({total/1e6:.1f} MB total)")
    for e in entries:
        flag = "  ⚠ " + e["needs_review"] if e.get("needs_review") else ""
        print(f"  {e['target']:<10} {e['caption'] or '(no capture data)':<28}"
              f"{e['images']['grid']['bytes']//1024:>5} KB{flag}")
    print(f"\nmanifest: {MANIFEST.relative_to(ROOT)}"
          + ("\nindex.html gallery strip updated" if injected else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
