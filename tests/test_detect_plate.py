"""Does this JPEG have a Share title plate burned into it?

Spec §2.3. A plated row renders no <figcaption> (its caption is in the pixels)
and can never be a planner representative.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT / "packaging"))

pytestmark = pytest.mark.skipif(
    not (SITE / "img" / "showcase").exists(),
    reason="site/ is decoupled and gitignored — only validated when present locally",
)

detect_plate = pytest.importorskip("detect_plate")
SHOWCASE = SITE / "img" / "showcase"

# All ten, named. A glob would pass on an empty directory, and "the pictures
# vanished" must fail loudly.
SHOWCASE_STEMS = (
    "ic1396a-drizzle-1975x10s-329min-original",
    "m16-drizzle-333x10s-56min-original",
    "m17-drizzle-238x10s-40min-original",
    "m31-mosaic-285x10s-48min-new-original",
    "m8-drizzle-434x10s-72min-original",
    "ngc281-drizzle-1233x10s-206min-original",
    "ngc6888-drizzle-183x10s-30min-original",
    "ngc6992-drizzle-202x10s-34min-original",
    "ngc7000-drizzle-163x20s-54min-original",
    "ngc7635-643x20s-214min-2x-original",
)
assert len(SHOWCASE_STEMS) == 10, "all ten, or some keep their plates unnoticed"


def _starfield(rng):
    """Dark sky with isolated bright points — no horizontal structure."""
    import numpy as np
    a = rng.normal(12, 4, (700, 1100)).clip(0, 255)
    ys = rng.integers(0, 700, 400)
    xs = rng.integers(0, 1100, 400)
    a[ys, xs] = 240
    return a


def test_every_showcase_image_is_present_at_both_sizes():
    missing = [f"{s}-{n}.jpg" for s in SHOWCASE_STEMS for n in (1100, 2400)
               if not (SHOWCASE / f"{s}-{n}.jpg").exists()]
    assert missing == [], f"missing showcase files: {missing}"


@pytest.mark.parametrize("stem", SHOWCASE_STEMS)
def test_detects_the_plate_on_todays_plated_showcase(stem):
    """The POSITIVE case, and the thing that proves the detector works at all.

    When Andreas re-exports one of these without a plate, this flips for that
    stem — move it to a clean list rather than deleting the assertion. A stem
    expected plated that reads clean means the detector has gone blind, which
    would publish a duplicated caption with nothing failing."""
    assert detect_plate.has_plate(SHOWCASE / f"{stem}-1100.jpg") is True


def test_a_clean_starfield_reads_clean(tmp_path):
    """The NEGATIVE case. Without it `has_plate` could return True always and
    every assertion above would still pass — the toothless-by-symmetry failure
    this repo has hit before."""
    np = pytest.importorskip("numpy")
    from PIL import Image
    a = _starfield(np.random.default_rng(7))
    out = tmp_path / "clean.jpg"
    Image.fromarray(a.astype("uint8"), "L").convert("RGB").save(out, "JPEG", quality=92)
    assert detect_plate.has_plate(out) is False


@pytest.mark.parametrize("anchor", ["left", "centre", "right"])
def test_detects_a_plate_at_any_horizontal_placement(anchor, tmp_path):
    """Share places the plate left, centre or right. M 31's is bottom-RIGHT,
    and a centre-only measurement missed it entirely — which is why the
    detector scans windows across the width."""
    np = pytest.importorskip("numpy")
    from PIL import Image, ImageDraw
    a = _starfield(np.random.default_rng(7))
    img = Image.fromarray(a.astype("uint8"), "L").convert("RGB")
    x = {"left": 60, "centre": 430, "right": 820}[anchor]
    d = ImageDraw.Draw(img)
    d.text((x, 540), "M 16", fill=(255, 255, 255))
    d.text((x - 40, 578), "Eagle Nebula", fill=(235, 235, 235))
    d.line((x, 566, x + 150, 566), fill=(210, 210, 210))
    d.text((x - 50, 606), "55m  333 x 10s  9 Aug 2026  Nocturne", fill=(190, 190, 190))
    out = tmp_path / f"plated-{anchor}.jpg"
    img.save(out, "JPEG", quality=92)
    assert detect_plate.has_plate(out) is True


def test_a_degenerate_image_does_not_raise(tmp_path):
    """The seeder runs over whatever is in the folder."""
    from PIL import Image
    out = tmp_path / "tiny.jpg"
    Image.new("RGB", (4, 4), (0, 0, 0)).save(out, "JPEG")
    assert detect_plate.has_plate(out) is False


def test_m31_clears_by_a_MARGIN_not_by_one_row():
    """The test that actually justifies the sliding window.

    M 31's plate is bottom-RIGHT on a wide mosaic. Measured 2026-09-21:
    whole-row variance finds exactly 3 rows — equal to _MIN_ROWS, so one JPEG
    re-encode from reading clean. The windowed scan finds 28.

    A boolean assertion passes under both, which is why the placement tests
    above did NOT fail when the window was mutated away. This one does.
    """
    rows = detect_plate.plate_rows(
        SHOWCASE / "m31-mosaic-285x10s-48min-new-original-1100.jpg")
    assert rows >= 10, (
        f"M 31 clears by only {rows} rows — the detector is back to whole-row "
        "variance and is one re-encode from calling a plated image clean")
