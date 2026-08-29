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


def _gas_file(path, side, rng, *, faint):
    """A realistic dualband pair: Ha carries real structure over modest noise,
    OIII is faint and noise-dominated.

    The asymmetry is the point. The fit's scale is a RATIO of MADs, so shrinking
    two planes with the SAME noise moves both MADs together and the ratio barely
    changes — an equal-noise fixture let two mutations through here. Averaging
    hurts a noise-dominated plane far more than a structured one: measured 56.2%
    apart on this shape, against 0.3% on real LP channel files.
    """
    yy, xx = np.mgrid[0:side, 0:side]
    blob = np.exp(-(((yy - side // 2) ** 2 + (xx - side // 2) ** 2) / (2 * (side / 6.4) ** 2)))
    if faint:
        data = 0.15 + 0.02 * blob + 0.05 * rng.standard_normal((side, side))
    else:
        data = 0.50 + 0.40 * blob + 0.01 * rng.standard_normal((side, side))
    hdu = fits.PrimaryHDU(data.astype(np.float32))
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


def test_the_preview_shows_the_pair_once_both_are_chosen(qtbot, tmp_path):
    """Andreas, 2026-08-29: "would it not be good if we have some kind of preview
    there so the user dont have to do the combine blindly?" The spec excluded one
    on the grounds that the pipeline's preview is the real one — true for a step
    inside the pipeline, wrong for a one-shot entry point where the only way to
    see the balance was to commit to it."""
    d = CombineDialog(Settings())
    qtbot.addWidget(d)
    assert not d.preview.has_image(), "nothing to preview before files are chosen"
    d.ha_edit.setText(_blob_file(tmp_path / "ha.fits", 32.0))
    d.oiii_edit.setText(_blob_file(tmp_path / "oiii.fits", 32.0))
    d.check_alignment()
    qtbot.waitUntil(lambda: d.preview.has_image(), timeout=3000)


def test_moving_the_balance_redraws_the_preview(qtbot, tmp_path):
    """A slider that changes nothing on screen is worse than no preview."""
    d = CombineDialog(Settings())
    qtbot.addWidget(d)
    d.ha_edit.setText(_mono(tmp_path / "ha.fits", 0.8))
    d.oiii_edit.setText(_mono(tmp_path / "oiii.fits", 0.2))
    d.check_alignment()
    qtbot.waitUntil(lambda: d._small is not None, timeout=3000)
    qtbot.waitUntil(lambda: not d._busy, timeout=5000)   # let the worker finish

    shown = []
    d.preview.show_image = lambda img: shown.append(img)
    d.balance_slider.setValue(0)
    qtbot.waitUntil(lambda: len(shown) >= 1, timeout=2000)
    d.balance_slider.setValue(100)
    qtbot.waitUntil(lambda: len(shown) >= 2, timeout=2000)


def test_the_preview_uses_the_same_fit_apply_will(qtbot, tmp_path):
    """The WYSIWYG promise. The fit is a median and a MAD; the preview's planes
    are block-averaged, which lowers the MAD, so measuring the fit on them would
    show the user a balance the Apply does not perform."""
    from nocturne.core.combine import oiii_fit
    from nocturne.core.fits_io import load_mono_master
    from nocturne.ui.combine_dialog import _shrink
    from nocturne.ui.preview import PREVIEW_MAX

    # Bigger than the preview cap, or nothing is shrunk and the two fits agree
    # trivially — a fixture that small let two mutations through.
    side = PREVIEW_MAX * 2
    rng = np.random.default_rng(3)
    ha_p = _gas_file(tmp_path / "ha.fits", side, rng, faint=False)
    oiii_p = _gas_file(tmp_path / "oiii.fits", side, rng, faint=True)
    d = CombineDialog(Settings())
    qtbot.addWidget(d)
    d.ha_edit.setText(ha_p)
    d.oiii_edit.setText(oiii_p)
    d.check_alignment()
    qtbot.waitUntil(lambda: d._fit is not None, timeout=5000)
    qtbot.waitUntil(lambda: not d._busy, timeout=10000)  # let the worker finish

    ha, oiii = load_mono_master(ha_p), load_mono_master(oiii_p)
    full = oiii_fit(ha, oiii)
    small = oiii_fit(_shrink(ha), _shrink(oiii))
    assert not np.isclose(full[0], small[0], rtol=0.10), (
        f"fixture is not discriminating: shrinking moved the scale only from "
        f"{full[0]:.4f} to {small[0]:.4f}")
    assert d._fit == pytest.approx(full), (
        "the preview measured its fit on the shrunken planes, not the real ones")


def test_the_preview_planes_are_averaged_not_sampled(qtbot, tmp_path):
    """Striding to shrink deletes a star field — 253 of 300 synthetic stars gone
    at 8x, and the survivors drawn at full amplitude. The preview must show
    something that looks like the picture."""
    from nocturne.ui.combine_dialog import _shrink
    from nocturne.ui.preview import PREVIEW_MAX
    side = PREVIEW_MAX * 2                      # big enough to actually shrink
    stars = np.zeros((side, side), np.float32)
    stars[::16, ::16] = 1000.0                  # a grid of single-pixel stars
    small = _shrink(stars)
    assert small.shape[0] < side, "the plane was not shrunk at all"
    step = side / small.shape[0]
    assert small.sum() == pytest.approx(stars.sum() / step ** 2, rel=0.05), \
        "flux was not conserved — this is sampling, not averaging"
    assert small.max() < 1000.0, "a block average cannot keep a single pixel's full peak"
    assert (small > 0).sum() == (stars > 0).sum(), \
        "stars went missing — striding would have deleted most of them"


def test_the_preview_renders_with_that_fit_rather_than_remeasuring(qtbot, tmp_path):
    """Measuring the right fit is half of it; the render has to use it. Dropping
    the fit argument from _render_preview left every other test here green — the
    fit was still correct, it just was not the one being drawn."""
    import nocturne.ui.combine_dialog as cd
    rng = np.random.default_rng(11)
    from nocturne.ui.preview import PREVIEW_MAX
    side = PREVIEW_MAX * 2
    d = CombineDialog(Settings())
    qtbot.addWidget(d)
    d.ha_edit.setText(_gas_file(tmp_path / "ha.fits", side, rng, faint=False))
    d.oiii_edit.setText(_gas_file(tmp_path / "oiii.fits", side, rng, faint=True))
    d.check_alignment()
    qtbot.waitUntil(lambda: d._fit is not None, timeout=5000)
    qtbot.waitUntil(lambda: not d._busy, timeout=10000)  # let the worker finish

    seen = {}
    real = cd.combine_gases
    cd.combine_gases = lambda *a, **kw: (seen.setdefault("fit", kw.get("fit")), real(*a, **kw))[1]
    try:
        d._render_preview()
    finally:
        cd.combine_gases = real
    assert seen["fit"] is not None, "the preview re-measured the fit instead of using it"
    assert seen["fit"] == d._fit


def test_the_dialog_fits_a_small_screen(qtbot):
    """1280x800 is the stated floor. A 420px preview minimum opened this at
    777px tall, which does not fit once the menu bar and dock are counted."""
    d = CombineDialog(Settings())
    qtbot.addWidget(d)
    d.show()
    assert d.height() < 740, f"opens {d.height()}px tall"


def test_the_preview_takes_the_extra_room(qtbot):
    """The same mistake as the Ha/OIII dialog, where a missing stretch factor
    gave 237px to a one-line label and squeezed the frame list into 238px."""
    d = CombineDialog(Settings())
    qtbot.addWidget(d)
    d.resize(900, 950)
    d.show()
    qtbot.waitUntil(lambda: d.height() > 800, timeout=2000)
    assert d.preview.height() > 0.5 * d.height(), (
        f"preview got {d.preview.height()} of {d.height()}")
