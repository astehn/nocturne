import numpy as np
import pytest

pytest.importorskip("PySide6")
from astropy.io import fits  # noqa: E402
from nocturne.settings import Settings  # noqa: E402
from nocturne.ui.combine_dialog import CombineDialog  # noqa: E402


def _mono(path, value, shape=(32, 32), **cards):
    hdu = fits.PrimaryHDU(np.full(shape, value, np.float32))
    hdu.header["STACKCNT"] = 20
    for k, v in cards.items():
        hdu.header[k] = v
    hdu.writeto(path, overwrite=True)
    return str(path)


def _blob_file(path, cy, shape=(64, 64)):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    blob = (np.exp(-(((yy - cy) ** 2 + (xx - 32) ** 2) / 18.0)) * 1000 + 10).astype(np.float32)
    hdu = fits.PrimaryHDU(blob)
    hdu.header["STACKCNT"] = 20
    hdu.writeto(path, overwrite=True)
    return str(path)


def test_the_dialog_says_what_it_takes_and_what_comes_out(qtbot):
    d = CombineDialog(Settings())
    qtbot.addWidget(d)
    blurb = d.blurb.text().lower()
    assert "narrowband" in blurb, "it must say where the palette is chosen"
    for w in (d.ha_edit, d.oiii_edit, d.balance_slider):
        assert w.toolTip(), "every control needs a tooltip"


def test_balance_starts_matched(qtbot):
    d = CombineDialog(Settings())
    qtbot.addWidget(d)
    assert d.balance_slider.value() == d.balance_slider.maximum()
    assert "matched" in d.balance_label.text().lower()


def test_the_balance_label_names_both_ends(qtbot):
    """'as measured' and 'matched to Ha' are what the help explains; a bare
    percentage would mean nothing to someone meeting this for the first time."""
    d = CombineDialog(Settings())
    qtbot.addWidget(d)
    d.balance_slider.setValue(0)
    assert d.balance_label.text() == "as measured"
    d.balance_slider.setValue(50)
    assert "50" in d.balance_label.text()
    d.balance_slider.setValue(100)
    assert d.balance_label.text() == "matched to Ha"


def test_mismatched_sizes_are_refused_by_name(qtbot, tmp_path):
    d = CombineDialog(Settings())
    qtbot.addWidget(d)
    d.ha_edit.setText(_mono(tmp_path / "ha.fits", 0.8, (32, 32)))
    d.oiii_edit.setText(_mono(tmp_path / "oiii.fits", 0.2, (16, 16)))
    d.run()
    qtbot.waitUntil(lambda: "32" in d.status.text(), timeout=3000)
    assert "16" in d.status.text(), f"both sizes must be named: {d.status.text()!r}"


def test_the_same_file_twice_is_refused(qtbot, tmp_path):
    d = CombineDialog(Settings())
    qtbot.addWidget(d)
    p = _mono(tmp_path / "ha.fits", 0.8)
    d.ha_edit.setText(p)
    d.oiii_edit.setText(p)
    d.run()
    assert "same file" in d.status.text().lower()


def test_a_raw_sub_is_refused_with_a_readable_reason(qtbot, tmp_path):
    """The refusal a user is most likely to hit: a raw sub is 2D too, so it
    looks the same from the outside."""
    d = CombineDialog(Settings())
    qtbot.addWidget(d)
    hdu = fits.PrimaryHDU(np.zeros((32, 32), np.float32))
    hdu.header["BAYERPAT"] = "GRBG"          # raw sub: no STACKCNT
    hdu.writeto(tmp_path / "sub.fit", overwrite=True)
    d.ha_edit.setText(str(tmp_path / "sub.fit"))
    d.oiii_edit.setText(_mono(tmp_path / "oiii.fits", 0.2))
    d.run()
    qtbot.waitUntil(lambda: "raw sub" in d.status.text().lower(), timeout=3000)


def test_an_aligned_pair_never_mentions_alignment(qtbot, tmp_path):
    """Silence is the point: every pair the extractor writes is aligned, and a
    warning nobody needs teaches people to ignore warnings."""
    d = CombineDialog(Settings())
    qtbot.addWidget(d)
    d.ha_edit.setText(_blob_file(tmp_path / "ha.fits", 32.0))
    d.oiii_edit.setText(_blob_file(tmp_path / "oiii.fits", 32.0))
    d.check_alignment()
    qtbot.waitUntil(lambda: d.status.text() == "Ready.", timeout=3000)
    assert not d.align_row.isVisible(), "an aligned pair must not raise a warning"


def test_a_misaligned_pair_says_how_far_off_and_offers_to_fix_it(qtbot, tmp_path):
    d = CombineDialog(Settings())
    qtbot.addWidget(d)
    d.show()
    d.ha_edit.setText(_blob_file(tmp_path / "ha.fits", 32.0))
    d.oiii_edit.setText(_blob_file(tmp_path / "oiii.fits", 36.0))
    d.check_alignment()
    qtbot.waitUntil(lambda: d.align_row.isVisible(), timeout=3000)
    assert "4" in d.status.text(), f"the offset must be stated: {d.status.text()!r}"
    assert d.align_check.isChecked(), "aligning is the default once an offset is found"


def test_a_successful_combine_hands_the_master_on(qtbot, tmp_path):
    got = {}
    d = CombineDialog(Settings(), on_master=lambda img: got.setdefault("img", img))
    qtbot.addWidget(d)
    d.ha_edit.setText(_mono(tmp_path / "ha.fits", 0.8))
    d.oiii_edit.setText(_mono(tmp_path / "oiii.fits", 0.2))
    d.run()
    qtbot.waitUntil(lambda: "img" in got, timeout=3000)
    assert got["img"].data.shape == (32, 32, 3) and got["img"].is_linear


def test_the_combined_master_carries_the_source_provenance(qtbot, tmp_path):
    """Same requirement the extractor's master has: name the camera and filter,
    or a reloaded master cannot identify itself."""
    got = {}
    d = CombineDialog(Settings(), on_master=lambda img: got.setdefault("img", img))
    qtbot.addWidget(d)
    d.ha_edit.setText(_mono(tmp_path / "ha.fits", 0.8,
                            INSTRUME="ZWO Seestar S30 Pro", FILTER="LP", OBJECT="M 16"))
    d.oiii_edit.setText(_mono(tmp_path / "oiii.fits", 0.2))
    d.run()
    qtbot.waitUntil(lambda: "img" in got, timeout=3000)
    meta = got["img"].metadata
    assert meta.get("instrument") == "ZWO Seestar S30 Pro"
    assert meta.get("filter") == "LP" and meta.get("target") == "M 16"


def _centroid(a):
    a = np.clip(a.astype(np.float64) - np.median(a), 0, None)
    rows, cols = np.indices(a.shape)
    tot = a.sum()
    return (float((rows * a).sum() / tot), float((cols * a).sum() / tot))


def test_ticking_align_actually_moves_the_oiii_plane(qtbot, tmp_path):
    """Offering to align and then not doing it would be worse than not offering.
    Removing the alignment call passed every other test here: they check that the
    warning appears and the box is ticked, never that anything happens."""
    got = {}
    d = CombineDialog(Settings(), on_master=lambda img: got.setdefault("img", img))
    qtbot.addWidget(d)
    d.show()
    d.ha_edit.setText(_blob_file(tmp_path / "ha.fits", 32.0))
    d.oiii_edit.setText(_blob_file(tmp_path / "oiii.fits", 36.0))   # 4 px away
    d.check_alignment()
    qtbot.waitUntil(lambda: d.align_row.isVisible(), timeout=3000)

    d.align_check.setChecked(True)
    d.run()
    qtbot.waitUntil(lambda: "img" in got, timeout=3000)
    data = got["img"].data
    ha_row = _centroid(data[..., 0])[0]
    oiii_row = _centroid(data[..., 1])[0]
    assert abs(ha_row - oiii_row) < 0.5, (
        f"the gases are still {abs(ha_row - oiii_row):.2f} px apart — "
        "Align was ticked and did nothing")


def test_declining_to_align_leaves_the_planes_where_they_were(qtbot, tmp_path):
    """The offer is an offer. Someone who knows the two frames are genuinely of
    different things must be able to say no and get what they asked for."""
    got = {}
    d = CombineDialog(Settings(), on_master=lambda img: got.setdefault("img", img))
    qtbot.addWidget(d)
    d.show()
    d.ha_edit.setText(_blob_file(tmp_path / "ha.fits", 32.0))
    d.oiii_edit.setText(_blob_file(tmp_path / "oiii.fits", 36.0))
    d.check_alignment()
    qtbot.waitUntil(lambda: d.align_row.isVisible(), timeout=3000)

    d.align_check.setChecked(False)
    d.run()
    qtbot.waitUntil(lambda: "img" in got, timeout=3000)
    data = got["img"].data
    gap = abs(_centroid(data[..., 0])[0] - _centroid(data[..., 1])[0])
    assert gap > 3.0, f"unticking Align should have left the {gap:.2f} px offset alone"
