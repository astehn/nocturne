"""The Capture section says what the file already holds — filter, gain, focal
length, the nights it spans, the file's name, the stacker's trim choice — and
nothing it does not (2026-10-17)."""
import datetime

import numpy as np
from astropy.io import fits

from nocturne.core.fits_io import load_fits
from nocturne.core.provenance import build_report

_META = {"target": "IC 1805", "exposure": 10.0, "frames": 331, "creator": "ZWO Seestar S30 Pro",
         "filter": "LP", "gain": 200, "focal_length": 160.0,
         "date": "2026-08-26T20:06:00", "date_end": "2026-08-27T03:24:00", "trimmed": False}


def _capture(meta, source_label=None) -> str:
    r = build_report([], meta, app_version="x", date=datetime.date(2026, 10, 17),
                     source_label=source_label)
    return r.split("## Capture\n")[1].split("\n\n")[0]


def test_everything_the_file_holds_is_said():
    cap = _capture(_META, "IC1805_331x10s_55min.fits")
    assert cap.splitlines() == [
        "- Target: IC 1805",
        "- Total integration: 55m 10s (331 × 10s)",
        "- Camera: Sony IMX585 (ZWO Seestar S30 Pro)",
        "- Filter: LP (dual-band)",
        "- Gain: 200",
        "- Focal length: 160 mm",
        "- Captured: 26\u201327 Aug 2026",
        "- Source file: IC1805\\_331x10s\\_55min.fits",
        "- Stacked with \u201cTrim the ragged edges\u201d: off",
    ]


def test_nothing_is_invented_for_a_file_that_holds_nothing():
    cap = _capture({})
    assert cap.splitlines() == ["- Camera: Sony IMX585 (assumed — no camera in the file)"]


def test_a_broadband_filter_is_named_as_written():
    assert "- Filter: IRCUT\n" in _capture({"filter": "IRCUT"}) + "\n"


def test_one_night_is_one_date():
    assert "- Captured: 9 Aug 2026" in _capture({"date": "2026-08-09T23:06:58",
                                                  "date_end": "2026-08-09T23:09:33"})


def test_an_unreadable_date_is_still_said_as_written():
    assert "- Captured: sometime" in _capture({"date": "sometime"})


def test_the_source_is_a_name_never_a_path():
    assert "- Source file: m8.fit" in _capture({}, "/Users/someone/Astro/m8.fit")
    assert "- Source file: m8.fits" in _capture({}, "C:\\Users\\someone\\m8.fits")


def test_a_label_that_is_not_a_file_is_not_called_one():
    for label in ("stacked master", "combined narrowband", "", None):
        assert "Source file" not in _capture({}, label)


def test_trimmed_on_is_said():
    assert "Trim the ragged edges\u201d: on" in _capture({"trimmed": True})


def test_the_trimmed_card_is_read_from_the_file(tmp_path):
    for value in (True, False):
        hdu = fits.PrimaryHDU(np.ones((3, 8, 8), dtype=np.float32))
        hdu.header["TRIMMED"] = value
        path = tmp_path / f"m{value}.fits"
        hdu.writeto(str(path))
        assert load_fits(str(path)).metadata["trimmed"] is value
    plain = tmp_path / "plain.fits"
    fits.PrimaryHDU(np.ones((3, 8, 8), dtype=np.float32)).writeto(str(plain))
    assert "trimmed" not in load_fits(str(plain)).metadata
