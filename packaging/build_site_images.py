"""Turn a folder of captures into the website's image set.

    .venv/bin/python packaging/build_site_images.py ["~/Desktop/Nocturne site shots"]

Written because the screenshot manifest originally asked Andreas to export at
"2000 px on the long edge, quality 90" and the app can do neither: the main
Export offers TIFF / PNG / FITS at full resolution with no size control, and
Share's JPEG quality is hardwired to 92 (share_render.save_share). Asking a
person to hit numbers their tools do not expose is a spec bug, not a workflow.

So he exports big and lossless-ish once, drops the files here, and this derives
what each page actually needs. One capture per picture, re-derivable at any size
later without asking him to redo anything.

Naming follows the manifest, and the PREFIX picks the treatment:

    ui-*    the application in frame            -> 2200 px long edge
    pic-*   a finished picture, no app          -> 2200 px long edge
    ba-*    one half of a before/after pair     -> 1600 px long edge

A `ba-` file must be `ba-<name>-before` or `ba-<name>-after`, and the two halves
must arrive at IDENTICAL source dimensions. The manifest asks for identical
crops because a pair that differs in framing reads as a trick; checking it here
means the guarantee does not depend on matching a crop box by eye.

Sibling of build_gallery.py and build_samples.py: run it when there are new
captures, not as part of a deploy.
"""
from __future__ import annotations

import collections
import io
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "img"
DEFAULT_SOURCE = "~/Desktop/Nocturne site shots"

# Long edge per prefix, matching what the pages already use: tool-*.jpg are
# 2200 wide, and the enh-* pairs 1536. A pair is shown smaller than a full-width
# screenshot, so it does not need the same pixels.
EDGES = {"ui": 2200, "pic": 2200, "ba": 1600}

# Pairs whose whole point is detail at 100%. Downsizing a 4000 px frame to 1600
# averages away the very noise the "before" is meant to show, so these are CROPPED
# from the centre at native resolution instead of scaled. Both halves get the
# identical rectangle by construction, which is also the manifest's rule.
DETAIL_PAIRS = ("ba-denoise", "ba-drizzle")
DETAIL_CROP = (1600, 1000)
QUALITY = 88          # above the gallery's 82: these carry UI text, not just sky
SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff")

_BA = re.compile(r"^(ba-.+)-(before|after)$")


def prefix_of(stem: str) -> str | None:
    head = stem.split("-", 1)[0]
    return head if head in EDGES else None


def check_pairs(files: list[pathlib.Path]) -> list[str]:
    """Every ba- half must have a partner, and both must be the same size.

    Returns complaints. This is the manifest's "identical crops" rule made
    mechanical: by eye, two exports of the same frame taken minutes apart are
    very easy to get subtly different, and the difference only shows once both
    are on the page side by side.
    """
    from PIL import Image

    halves: dict[str, dict[str, pathlib.Path]] = collections.defaultdict(dict)
    for f in files:
        m = _BA.match(f.stem)
        if m:
            halves[m.group(1)][m.group(2)] = f

    problems = []
    for name, pair in sorted(halves.items()):
        if len(pair) != 2:
            missing = ({"before", "after"} - set(pair)).pop()
            problems.append(f"{name}: no -{missing} half")
            continue
        sizes = {}
        for side, path in pair.items():
            with Image.open(path) as im:
                sizes[side] = im.size
        if sizes["before"] != sizes["after"]:
            problems.append(
                f"{name}: halves are different sizes — "
                f"before {sizes['before'][0]}x{sizes['before'][1]}, "
                f"after {sizes['after'][0]}x{sizes['after'][1]}. "
                "Re-export both from the same crop.")
    return problems


def _to_srgb(im, icc: bytes | None):
    """Convert to sRGB and return the profile to embed.

    Nocturne can export sRGB, Display P3, Adobe RGB or ProPhoto (the colour
    management work of 2026-08-20), and a browser shown untagged pixels assumes
    sRGB. So stripping a ProPhoto profile does not lose a nicety — it renders
    the picture with the wrong primaries, badly desaturated, with nothing on the
    page to say so. Convert rather than merely tag, because the web wants sRGB.
    """
    from PIL import ImageCms
    srgb = ImageCms.createProfile("sRGB")
    srgb_bytes = ImageCms.ImageCmsProfile(srgb).tobytes()
    if not icc:
        return im.convert("RGB"), srgb_bytes
    src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
    if ImageCms.getProfileDescription(src).strip().lower().startswith("srgb"):
        return im.convert("RGB"), icc
    out = ImageCms.profileToProfile(im, src, srgb, outputMode="RGB")
    return out, srgb_bytes


def is_detail(stem: str) -> bool:
    return any(stem.startswith(d) for d in DETAIL_PAIRS)


def _centre_crop(im, size):
    cw, ch = min(size[0], im.width), min(size[1], im.height)
    left, top = (im.width - cw) // 2, (im.height - ch) // 2
    return im.crop((left, top, left + cw, top + ch))


def derive(src: pathlib.Path, edge: int) -> tuple[pathlib.Path, tuple[int, int]]:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(src) as im:
        im, profile = _to_srgb(im, im.info.get("icc_profile"))
        if is_detail(src.stem):
            im = _centre_crop(im, DETAIL_CROP)
        else:
            # thumbnail only ever shrinks, so a capture that arrives smaller
            # than the target is left alone rather than blown up into softness.
            im.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        dest = OUT / f"{src.stem}.jpg"
        im.save(dest, "JPEG", quality=QUALITY, optimize=True,
                progressive=True, icc_profile=profile)
        return dest, im.size


def main(argv: list[str]) -> int:
    source = pathlib.Path(argv[1] if len(argv) > 1 else DEFAULT_SOURCE).expanduser()
    if not source.is_dir():
        print(f"no such folder: {source}")
        return 1

    files, ignored = [], []
    for f in sorted(source.iterdir()):
        if f.name.startswith(".") or f.suffix.lower() not in SUFFIXES:
            continue
        (files if prefix_of(f.stem) else ignored).append(f)

    if ignored:
        print(f"ignored {len(ignored)} file(s) with no ui- / pic- / ba- prefix:")
        for f in ignored:
            print(f"  {f.name}")

    if not files:
        print("nothing to build")
        return 0

    problems = check_pairs(files)
    if problems:
        print("\nPAIR PROBLEMS — nothing written:")
        for p in problems:
            print(f"  {p}")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    for f in files:
        edge = EDGES[prefix_of(f.stem)]
        dest, (w, h) = derive(f, edge)
        kb = dest.stat().st_size // 1024
        print(f"  {dest.name:34s} {w:5d} x {h:<5d} {kb:5d} kB")
    print(f"\nwrote {len(files)} image(s) to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
