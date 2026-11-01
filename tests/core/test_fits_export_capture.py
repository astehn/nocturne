"""A FITS exported from Nocturne keeps the capture's own header.

His 947-frame mosaic, cropped and exported 2026-11-01, came back with 11 cards
of 36: frame count, exposure, dates, object, filter, gain and pointing gone,
so the reopened file no longer said "947 frames"."""
import numpy as np
from astropy.io import fits

from nocturne.core.export import capture_cards, save_fits
from nocturne.core.fits_io import load_fits, resolve_integration

# The capture cards his mosaic master carried (values as written by the stacker).
MOSAIC = {
    "NSUBS": 947, "STACKCNT": 947, "EXPTIME": 9470.0, "OBJECT": "NGC 7000",
    "FILTER": "LP", "INSTRUME": "Seestar S30 Pro", "CREATOR": "ZWO Seestar S30 Pro",
    "DATE-OBS": "2026-10-17T21:18:07", "DATE-END": "2026-10-18T00:01:12",
    "GAIN": 80, "RA": 314.75, "DEC": 44.3, "FOCALLEN": 160.0, "XPIXSZ": 2.9,
    "CCD-TEMP": 21.5, "LIVETIME": 9470.0,
    # A full plate solve of the UNCROPPED frame: stale after any crop.
    "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN", "CRPIX1": 6694.0, "CRPIX2": 7307.0,
    "CRVAL1": 314.75, "CRVAL2": 44.3, "CD1_1": -0.0002, "CD1_2": 0.0, "CD2_1": 0.0,
    "CD2_2": 0.0002,
}
KEPT = ("exposure", "gain", "target", "frames", "temp", "date", "date_end",
        "livetime", "creator", "filter", "ra", "dec")


def _master(tmp_path, cards=MOSAIC, name="master.fits"):
    hdu = fits.PrimaryHDU((np.random.rand(3, 32, 40)).astype(np.float32))
    for k, v in cards.items():
        hdu.header[k] = v
    p = tmp_path / name
    hdu.writeto(str(p))
    return p


def _export(tmp_path, meta):
    img = load_fits(str(_master(tmp_path, {}, "pixels.fits")))
    img.metadata = meta
    out = tmp_path / "out.fits"
    save_fits(img, str(out), header=capture_cards(meta))
    return out


def test_an_export_reopens_with_the_same_capture_details(tmp_path):
    before = load_fits(str(_master(tmp_path))).metadata
    out = _export(tmp_path, before)
    after = load_fits(str(out)).metadata
    assert {k: after.get(k) for k in KEPT} == {k: before.get(k) for k in KEPT}
    assert after["frames"] == 947


def test_integration_reads_the_same_after_export(tmp_path):
    before = load_fits(str(_master(tmp_path))).metadata
    after = load_fits(str(_export(tmp_path, before))).metadata
    assert resolve_integration(after) == resolve_integration(before)


def test_the_source_plate_solve_is_not_copied(tmp_path):
    # After a crop the old reference pixel points at the wrong sky; only a solve
    # made on the exported image may be written (main_window adds it).
    before = load_fits(str(_master(tmp_path))).metadata
    h = fits.getheader(str(_export(tmp_path, before)))
    for card in ("CTYPE1", "CRPIX1", "CRVAL1", "CD1_1", "CD2_2"):
        assert card not in h


def test_sexagesimal_pointing_keeps_its_card_names(tmp_path):
    cards = {"OBJCTRA": "20 59 00", "OBJCTDEC": "+44 18 00", "STACKCNT": 12}
    before = load_fits(str(_master(tmp_path, cards, "s.fits"))).metadata
    h = fits.getheader(str(_export(tmp_path, before)))
    assert (h["OBJCTRA"], h["OBJCTDEC"]) == ("20 59 00", "+44 18 00")
    assert "RA" not in h and "DEC" not in h


def test_missing_or_empty_values_write_no_card():
    assert capture_cards({}) == {}
    assert capture_cards({"target": "", "gain": None, "temp": float("nan")}) == {}


def test_a_name_with_non_ascii_letters_still_exports(tmp_path):
    # astropy refuses non-ASCII header text: the export failed outright.
    meta = {"target": "Ångström Nebula", "filter": "Hα\nline"}
    cards = capture_cards(meta)
    assert cards["OBJECT"] == "Angstrom Nebula" and cards["FILTER"] == "H line"
    img = load_fits(str(_master(tmp_path, {}, "pixels.fits")))
    save_fits(img, str(tmp_path / "out.fits"), header=cards)


def test_infinite_numbers_write_no_card():
    assert capture_cards({"exposure": float("inf"), "temp": float("-inf")}) == {}


def test_a_file_date_is_not_promoted_to_a_capture_date(tmp_path):
    # DATE is when the FILE was written; the loader falls back to it.
    meta = load_fits(str(_master(tmp_path, {"DATE": "2026-11-01T12:00:00"}, "d.fits"))).metadata
    cards = capture_cards(meta)
    assert cards.get("DATE") == "2026-11-01T12:00:00" and "DATE-OBS" not in cards


def test_a_combine_count_does_not_turn_a_file_into_a_master(tmp_path):
    # STACKCNT is what is_stacked_master reads: written for a file that only
    # had NCOMBINE, a reopened 2D sub would be taken for a master.
    src = _master(tmp_path, {"NCOMBINE": 5}, "n.fits")
    assert capture_cards(load_fits(str(src)).metadata) == {"NCOMBINE": 5}


def test_trimmed_round_trips(tmp_path):
    before = load_fits(str(_master(tmp_path, {"STACKCNT": 3, "TRIMMED": True}, "t.fits"))).metadata
    after = load_fits(str(_export(tmp_path, before))).metadata
    assert after["trimmed"] == before["trimmed"]


def test_pointing_is_cleaned_like_the_other_cards():
    assert capture_cards({"ra": "20h59m ", "dec": "+44°18'"}) == {"OBJCTRA": "20h59m", "OBJCTDEC": "+4418'"}
    assert capture_cards({"ra": float("inf"), "dec": 44.3}) == {}
