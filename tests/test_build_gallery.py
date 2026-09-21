"""build_gallery.py stops generating HTML and becomes a one-time importer.

Spec §2.2: two sources for one page drift, and the symptom is a caption under
the wrong picture. Andreas's images become rows like everyone else's.

The entry dicts here mirror what `collect()` ACTUALLY produces — `per_sub_s`,
`total_s`, `images["grid"]["src"]` — not an invented shape. The plan's first
draft of this test used names that do not exist in the module, which would have
produced a seeder that passed its tests and inserted nothing.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

build_gallery = pytest.importorskip("build_gallery")

# Exactly the `submissions` columns a seeded row may set. `stored_pending`,
# `ip` and `representative` are deliberately absent: a seeded row was never
# uploaded, has no reporter IP, and is not a planner pick until Andreas says so.
COLUMNS = {"handle", "target", "catalogue_id", "integration_s", "frames",
           "sub_s", "captured_on", "instrument", "stored_2000", "stored_900",
           "orig_filename", "size_bytes", "status"}


def entry(**over):
    """One `collect()` entry, in the shape collect() really returns."""
    e = {
        "slug": "m16-drizzle-333x10s-56min-original",
        "source": "M16_drizzle.jpg",
        "target": "M 16",
        "frames": 333,
        "per_sub_s": 10,
        "total_s": 3330,
        "filter": "IRCUT",
        "facts_from": "master",
        "common": "Eagle Nebula",
        "images": {
            "grid": {"src": "img/gallery/m16-1100.jpg", "w": 1100, "h": 733,
                     "bytes": 113583},
            "full": {"src": "img/gallery/m16-2400.jpg", "w": 2400, "h": 1600,
                     "bytes": 402118},
        },
    }
    e.update(over)
    return e


def test_seed_rows_uses_exactly_the_submissions_column_names():
    rows = build_gallery.seed_rows([entry()])
    assert len(rows) == 1
    extra = set(rows[0]) - COLUMNS
    missing = COLUMNS - set(rows[0])
    assert extra == set(), f"unexpected keys: {extra}"
    assert missing == set(), f"missing keys: {missing}"


def test_seed_rows_maps_the_REAL_collect_keys():
    """per_sub_s -> sub_s, total_s -> integration_s, images[...] -> stored_*.

    Named explicitly because these are the four renames where a typo produces
    a row full of NULLs rather than an error."""
    r = build_gallery.seed_rows([entry()])[0]
    assert r["frames"] == 333
    assert r["sub_s"] == 10
    assert r["integration_s"] == 3330
    assert r["stored_900"] == "img/gallery/m16-1100.jpg"
    assert r["stored_2000"] == "img/gallery/m16-2400.jpg"
    assert r["size_bytes"] == 402118


def test_seeded_rows_are_approved_not_pending():
    """His own pictures are not awaiting his own moderation."""
    assert build_gallery.seed_rows([entry()])[0]["status"] == "approved"


def test_seeded_rows_carry_a_handle():
    """`handle` is NOT NULL and the wall shows it. An empty one would render a
    blank byline beside everyone else's."""
    assert build_gallery.seed_rows([entry()])[0]["handle"].strip() != ""


def test_a_sparse_entry_still_produces_a_row():
    """A mosaic written before 2026-08-16 carries only a WCS, so collect() can
    reach here with no frames, no exposure and no filter. That must be a row
    with NULLs, not a KeyError that stops the import halfway."""
    sparse = {"slug": "x", "target": "M 31",
              "images": {"grid": {"src": "a.jpg", "bytes": 1},
                         "full": {"src": "b.jpg", "bytes": 2}}}
    r = build_gallery.seed_rows([sparse])[0]
    assert r["frames"] is None and r["sub_s"] is None
    assert r["integration_s"] is None
    assert r["stored_900"] == "a.jpg"


def test_catalogue_id_is_left_for_the_SERVER_to_match():
    """§4: the app knows 'NGC 7000'; the site owns the mapping so it can
    improve without an app release. The importer must not pre-empt it."""
    assert build_gallery.seed_rows([entry()])[0]["catalogue_id"] is None


def test_no_location_field_survives_into_a_row():
    """Global constraint: never a location, in any payload or column. collect()
    carries whatever the FITS header held, so the row must be built by naming
    fields, not by copying the entry."""
    r = build_gallery.seed_rows([entry(
        location="Malmö", site="backyard", lat=55.6, lon=13.0,
        sitelat="55.6", sitelong="13.0")])[0]
    blob = " ".join(str(v).lower() for v in r.values())
    for leak in ("malmö", "backyard", "55.6", "13.0"):
        assert leak not in blob, f"{leak!r} reached a submissions row"


def test_seed_sql_quotes_and_escapes():
    """The importer emits SQL to pipe over ssh, so a handle or target with an
    apostrophe must not end the statement — 'Barnard's Loop' is a real target
    name and would otherwise be a syntax error at best."""
    sql = build_gallery.seed_sql([entry(target="Barnard's Loop")])
    assert "Barnard" in sql
    assert "INSERT INTO submissions" in sql
    # The apostrophe must be escaped, not raw.
    assert "Barnard's Loop'" not in sql.replace("\\'", "")


def test_captured_on_is_a_DATE_never_a_time():
    """A capture time says when someone was at their telescope. The date is
    what the caption needs; the rest is a movement record nobody asked for."""
    r = build_gallery.seed_rows([entry(captured_on="2026-08-09")])[0]
    assert r["captured_on"] == "2026-08-09"
    assert ":" not in str(r["captured_on"])


def test_instrument_prefers_CREATOR_over_INSTRUME(monkeypatch):
    """INSTRUME is inconsistent in the wild — 'imx585' on some files, a camera
    name on others. CREATOR names it outright, which is what the app uses."""
    hdr = {"OBJECT": "M 16", "STACKCNT": 100, "EXPTIME": 1000,
           "DATE-OBS": "2026-08-09T23:14:02", "CREATOR": "ZWO Seestar S30 Pro",
           "INSTRUME": "imx585"}

    class _F:
        @staticmethod
        def getheader(_):
            return hdr

    monkeypatch.setitem(sys.modules, "astropy.io", type("m", (), {"fits": _F}))
    facts = build_gallery.facts_from_master(Path("x.fit"))
    assert facts["instrument"] == "ZWO Seestar S30 Pro"
    assert facts["captured_on"] == "2026-08-09"


# --- the source the seeder must read (found the hard way, 2026-09-21) -------

SITE = ROOT / "site"

pytest_showcase = pytest.mark.skipif(
    not (SITE / "img" / "showcase").exists(),
    reason="site/ is decoupled and gitignored",
)


@pytest_showcase
def test_seed_reads_the_CURATED_showcase_not_the_working_folder():
    """The trap. collect() reads ~/Desktop/Astro Images and feeds the HOMEPAGE
    strip from img/gallery/. The wall page uses img/showcase/, curated by hand.

    Pointed at the working folder the seeder produced twelve rows including
    `M16_COMPARE_input_corners_after` — a diagnostic image — and every seeded
    row is status='approved', so it would have gone straight onto the public
    wall."""
    entries = build_gallery.collect_showcase()
    assert len(entries) == 10, f"expected the ten curated images, got {len(entries)}"
    srcs = [e["images"]["grid"]["src"] for e in entries]
    assert all(s.startswith("img/showcase/") for s in srcs), srcs
    assert not any("compare" in s or "corner" in s for s in srcs), \
        "a diagnostic image reached the wall"


@pytest_showcase
def test_every_curated_entry_resolves_its_capture_facts():
    """The filenames are the only record of these numbers once the burned
    plates are gone, so a stem that stops parsing must fail loudly rather than
    publish a picture with a blank caption."""
    for e in build_gallery.collect_showcase():
        assert e["target"], f"{e['slug']}: no target"
        assert e.get("frames"), f"{e['slug']}: no frame count"
        assert e.get("per_sub_s"), f"{e['slug']}: no exposure"


@pytest_showcase
def test_curated_entries_name_the_instrument_but_invent_no_date():
    """Instrument is a fact — every wall picture is his and he owns an S30 Pro
    and nothing else. A capture date is NOT in the filenames, and inferring one
    would be inventing a fact the caption then states."""
    rows = build_gallery.seed_rows(build_gallery.collect_showcase())
    assert {r["instrument"] for r in rows} == {"ZWO Seestar S30 Pro"}
    assert all(r["captured_on"] is None for r in rows)


@pytest_showcase
def test_both_sizes_are_required_before_a_row_is_emitted():
    """stored_2000 is what the lightbox opens. A row with a thumbnail and no
    full size is a tile that fails when clicked."""
    for r in build_gallery.seed_rows(build_gallery.collect_showcase()):
        assert r["stored_900"] and r["stored_2000"]
        assert r["stored_900"] != r["stored_2000"]
