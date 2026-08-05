"""The sample-data page is generated, so adding a target is dropping a folder in.

Guards the contract that makes that true: facts come from the FITS header (the
record) rather than the filename (a convenience), and a folder missing either
half is skipped rather than producing a half-built card.
"""
import sys
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
import build_samples  # noqa: E402


def _target(root, name, frames=163, per_sub=20.0, obj="NGC 7000", link=True):
    d = root / name
    d.mkdir(parents=True)
    data = np.random.default_rng(0).random((3, 40, 30)).astype(np.float32)
    hdu = fits.PrimaryHDU(data)
    hdu.header["OBJECT"] = obj
    hdu.header["STACKCNT"] = frames
    hdu.header["EXPTIME"] = frames * per_sub
    hdu.header["INSTRUME"] = "ZWO Seestar S30 Pro"
    hdu.header["FILTER"] = "LP"
    hdu.writeto(d / f"{name}_{frames}x{per_sub:g}s.fits")
    Image.new("RGB", (200, 260), (20, 20, 30)).save(d / f"{name}.png")
    if link:
        (d / "Google_Drive.txt").write_text("https://drive.google.com/drive/folders/ABC\n")
    return d


def test_facts_come_from_the_header_not_the_filename(tmp_path):
    """The filename is a convenience and can be renamed by anyone; the header is
    what the stacker actually recorded."""
    d = _target(tmp_path, "NGC7000", frames=163)
    # a filename that disagrees with the header on every count
    for f in d.glob("*.fits"):
        f.rename(d / "totally_different_9x1s.fits")
    targets = build_samples._read_targets(tmp_path)
    assert len(targets) == 1
    assert targets[0]["frames"] == 163
    assert targets[0]["target"] == "NGC 7000"
    assert targets[0]["per_sub_s"] == pytest.approx(20.0)


def test_a_folder_missing_its_preview_is_skipped(tmp_path):
    d = _target(tmp_path, "NGC281")
    for p in d.glob("*.png"):
        p.unlink()
    assert build_samples._read_targets(tmp_path) == []


def test_a_folder_without_a_drive_link_still_offers_the_master(tmp_path):
    """The master is hosted by us and is the download most people want; a
    missing subs link must not cost them the page."""
    _target(tmp_path, "NGC281", link=False)
    targets = build_samples._read_targets(tmp_path)
    assert len(targets) == 1 and targets[0]["subs_url"] == ""
    targets[0]["pw"], targets[0]["ph"] = 100, 100
    card = build_samples._card(targets[0])
    assert "Stacked master" in card
    assert "Google Drive" not in card


def test_preview_is_resized_for_the_web(tmp_path):
    """The originals are 4-6 MB PNGs. The rest of the site's photographs are
    90-310 KB, and a page nobody waits for is a page nobody reads."""
    d = _target(tmp_path, "NGC7000")
    big = d / "NGC7000.png"
    Image.new("RGB", (3840, 2160), (30, 30, 40)).save(big)
    out = tmp_path / "out" / "ngc7000.jpg"
    w, h, size = build_samples._write_preview(big, out)
    assert max(w, h) == build_samples.MAX_EDGE
    assert size < 400 * 1024


def test_page_names_every_target_and_its_downloads(tmp_path):
    _target(tmp_path, "NGC7000", frames=163, obj="NGC 7000")
    _target(tmp_path, "NGC281", frames=91, obj="NGC 281")
    targets = build_samples._read_targets(tmp_path)
    for t in targets:
        t["pw"], t["ph"] = 100, 100
    page = build_samples.render(targets)
    for name in ("NGC 7000", "NGC 281"):
        assert name in page
    assert page.count("Stacked master") == 2
    assert page.count("Google Drive") == 2
    assert "CC&nbsp;BY&nbsp;4.0" in page, "the licence must be stated"
    assert "creativecommons.org/licenses/by/4.0/" in page, \
        "the licence must LINK to its terms, not just name them"
    assert page.startswith("---"), "must carry front matter for build_site"


def test_totals_are_summed_across_targets(tmp_path):
    _target(tmp_path, "A", frames=100, per_sub=20.0)     # 2000 s
    _target(tmp_path, "B", frames=100, per_sub=20.0)     # 2000 s
    targets = build_samples._read_targets(tmp_path)
    for t in targets:
        t["pw"], t["ph"] = 100, 100
    assert "1 h 07 m" in build_samples.render(targets)
