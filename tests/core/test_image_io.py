"""Reading a TIFF, and deciding whether it is still linear.

Why the decision is measured rather than asked: people bring masters from Siril,
APP and DeepSkyStacker — often a 32-bit float TIFF that is STILL LINEAR and wants
the whole pipeline — and finished pictures that want only the toolbar tools. The
user usually cannot say which they have; that is rather the point of asking us.
"""
import os

import numpy as np
import pytest
import tifffile

from nocturne.core.fits_io import load_fits
from nocturne.core.image import AstroImage
from nocturne.core.image_io import LINEAR_P999_MAX, load_tiff, looks_linear
from nocturne.core.stretch import apply_stretch

MASTERS = [
    "/Volumes/Work/Astro/IC 1396A_sub/IC1396A_drizzle_1975x10s_329min.fits",
    "/Volumes/Work/Astro/NGC 6888/Stacked_183_NGC 6888_10.0s_LP_20260811-235732.fit",
]


def _synthetic_linear():
    """Crushed near zero with a sparse bright tail — the shape of real linear
    astro data, so these run without the Astro drive attached."""
    rng = np.random.default_rng(0)
    d = np.clip(rng.normal(0.02, 0.005, (400, 300, 3)), 0, 1).astype(np.float32)
    d[10:14, 10:14] = 0.9        # stars: 0.004% of pixels, far under p99.9
    return d


def test_linear_data_reads_as_linear():
    assert looks_linear(_synthetic_linear()) is True


def test_a_stretch_at_any_amount_reads_as_stretched():
    """p99.9 was chosen over the median because the median moves 0.10 -> 0.45
    across this range, so its margin collapses at the dark end."""
    img = AstroImage(_synthetic_linear(), is_linear=True)
    for amount in (0.0, 0.3, 1.0):
        for linked in (True, False):
            out = apply_stretch(img, amount, linked=linked).data
            assert looks_linear(out) is False, (amount, linked)


@pytest.mark.parametrize("path", MASTERS)
def test_real_masters_and_their_stretches(path):
    """The evidence for the threshold. Skipped when the drive is not attached."""
    if not os.path.exists(path):
        pytest.skip("master not available")
    img = load_fits(path)
    assert looks_linear(img.data) is True
    assert looks_linear(apply_stretch(img, 0.30).data) is False


def test_the_threshold_keeps_its_margin():
    """10x above every linear measurement, 4x below every stretched one. An edit
    that narrows it should have to come back and disagree with the numbers."""
    assert LINEAR_P999_MAX == 0.20


def test_a_16bit_tiff_normalises_like_a_fits(tmp_path):
    """0-65535 must land on the same footing as a float file, or the statistic
    means something different for each."""
    p = tmp_path / "s.tif"
    tifffile.imwrite(str(p), (_synthetic_linear() * 65535).astype(np.uint16))
    img = load_tiff(str(p))
    assert img.data.max() <= 1.0
    assert img.is_linear is True


def test_a_32bit_stretched_tiff_reads_as_stretched(tmp_path):
    st = apply_stretch(AstroImage(_synthetic_linear(), is_linear=True), 0.3).data
    p = tmp_path / "st.tif"
    tifffile.imwrite(str(p), st.astype(np.float32))
    assert load_tiff(str(p)).is_linear is False


def test_a_mono_tiff_is_promoted_to_three_channels(tmp_path):
    p = tmp_path / "m.tif"
    tifffile.imwrite(str(p), (_synthetic_linear()[..., 0] * 65535).astype(np.uint16))
    img = load_tiff(str(p))
    assert img.data.ndim == 3 and img.data.shape[2] == 3


def test_an_alpha_channel_is_dropped(tmp_path):
    """Photoshop writes RGBA readily. A fourth channel downstream would be read
    as data by everything that indexes [..., :3] and ignored inconsistently."""
    rgba = np.dstack([_synthetic_linear(), np.ones((400, 300), np.float32)])
    p = tmp_path / "a.tif"
    tifffile.imwrite(str(p), rgba.astype(np.float32))
    assert load_tiff(str(p)).data.shape[2] == 3


def test_non_finite_samples_do_not_poison_the_verdict(tmp_path):
    """_normalize zeroes them FIRST and its docstring records why the order
    matters — one NaN previously left a 16-bit frame completely unscaled."""
    d = _synthetic_linear(); d[0, 0] = np.nan
    p = tmp_path / "n.tif"
    tifffile.imwrite(str(p), d)
    img = load_tiff(str(p))
    assert np.isfinite(img.data).all()
    assert img.is_linear is True


def test_a_file_that_is_not_a_tiff_raises(tmp_path):
    p = tmp_path / "x.tif"; p.write_text("not a tiff")
    with pytest.raises(Exception):
        load_tiff(str(p))


def test_core_stays_qt_free():
    """core/ imports no Qt, by rule. A reader is exactly the place that gets
    this wrong, because Qt has a perfectly good image loader."""
    import pathlib
    src = pathlib.Path("nocturne/core/image_io.py").read_text()
    assert "PySide6" not in src and "QtGui" not in src


# --- the layouts other stackers actually write ---------------------------
# Found by writing the variants rather than waiting for a bug report: Siril, APP
# and DeepSkyStacker do not all write TIFFs the way Nocturne's own tests did.

def test_a_planar_tiff_is_transposed_not_sliced(tmp_path):
    """A TIFF may store channels as separate PLANES, which tifffile returns as
    (C, H, W). The alpha-drop then sliced the WIDTH to three columns: a 240x180
    frame came back (3, 240, 3) — three pixels of garbage — and the
    linear/stretched verdict was wrong too, because the mangled data has
    different statistics. Both symptoms are in this assertion.
    """
    d = _synthetic_linear()
    p = tmp_path / "planar.tif"
    tifffile.imwrite(str(p), d.transpose(2, 0, 1), planarconfig="separate")
    img = load_tiff(str(p))
    assert img.data.shape == d.shape
    assert img.is_linear is True


def test_an_interleaved_tiff_is_left_alone(tmp_path):
    """The guard on the guard: transposing planar files must not transpose the
    ordinary ones."""
    d = _synthetic_linear()
    p = tmp_path / "flat.tif"
    tifffile.imwrite(str(p), d)
    assert load_tiff(str(p)).data.shape == d.shape


@pytest.mark.parametrize("label,kwargs", [
    ("deflate", {"compression": "deflate"}),
    ("tiled", {"tile": (64, 64)}),
])
def test_compressed_and_tiled_files_read(tmp_path, label, kwargs):
    p = tmp_path / f"{label}.tif"
    tifffile.imwrite(str(p), _synthetic_linear(), **kwargs)
    assert load_tiff(str(p)).is_linear is True


def test_big_endian_16_bit_reads(tmp_path):
    p = tmp_path / "be.tif"
    tifffile.imwrite(str(p), (_synthetic_linear() * 65535).astype(">u2"))
    img = load_tiff(str(p))
    assert img.data.max() <= 1.0 and img.is_linear is True


def test_a_junk_icc_profile_does_not_break_the_read(tmp_path):
    """Eight bytes of nothing is not a profile. It must not stop the file
    opening, and must not be acted on.

    This said "the help says it is ignored" until 2026-09-20, when profiles
    stopped being ignored — and the help still said so for as long as it took
    review to notice. A test docstring that quotes the docs is a tripwire for
    exactly that drift; this one fired and nobody read it.
    """
    p = tmp_path / "icc.tif"
    tifffile.imwrite(str(p), _synthetic_linear(),
                     extratags=[(34675, 1, 8, b"\x00" * 8, True)])
    img = load_tiff(str(p))
    assert img.data.shape == (400, 300, 3)
    assert img.metadata.get("colour_space") is None


# --- embedded colour profiles ------------------------------------------------
#
# A FITS file is photon counts and has no source colour space — that is the
# reasoning in core/colour.py, and it is right for the pipeline. A TIFF is not
# photon counts. It is a finished, tagged image that genuinely HAS a source
# space, and it was the one case the rule never considered.
#
# Andreas, 2026-09-20, after exporting ProPhoto, editing in Photoshop and
# reopening: *"the colors are all wrong."* Measured on his Veil Nebula master:
# the page showed it 5.0 levels short of red and 5.6 levels long of blue, mean
# dE2000 6.8 across the frame, 6.5 on the background alone. A neutral grey went
# blue, which is the whole-image cast he reported.
#
# core/export.py:22 already documents this exact bug in the MIRROR direction:
# "Photoshop and every other reader assigns its OWN working space to an
# untagged file — which is why a correct M 16 export rendered dark in
# Photoshop: sRGB data read as ProPhoto." We fixed it on the way out by
# embedding the profile, and then did the identical thing to files we open.


def _tagged(path, data, space):
    """Write a TIFF carrying a real ICC profile for `space`.

    The bytes come from nocturne.colour_profiles, which needs Qt — fine in a
    test, and deliberately impossible inside core/ (see test_core_stays_qt_free).
    That constraint is why load_tiff identifies a profile by PARSING it rather
    than by byte-matching against our own.
    """
    from nocturne.colour_profiles import icc_bytes
    blob = icc_bytes(space)
    tifffile.imwrite(str(path), data, extratags=[(34675, 1, len(blob), blob, True)])
    return blob


def test_a_prophoto_tiff_is_converted_to_srgb(tmp_path):
    """The defect, in one test.

    The numbers in a ProPhoto file mean different colours than the same numbers
    in an sRGB file. Reading them as sRGB is not a rounding error — ProPhoto's
    primaries are far wider and its whitepoint is D50 against sRGB's D65, and
    the whitepoint alone is what sends a neutral blue.
    """
    from nocturne.core.colour import convert
    from nocturne.core.image_io import _normalize
    src = _synthetic_linear()
    p = tmp_path / "pp.tif"
    _tagged(p, src, "ProPhoto RGB")
    got = load_tiff(str(p)).data
    # _normalize runs BEFORE colour, so the expectation must start from its
    # output. Comparing against the raw array fails for a reason that has
    # nothing to do with the profile.
    want = convert(_normalize(src), to="sRGB", frm="ProPhoto RGB")
    assert np.allclose(got, np.clip(want, 0.0, 1.0), atol=2e-3), \
        "a ProPhoto file must be re-encoded into the space the pipeline works in"
    assert not np.allclose(got, _normalize(src), atol=2e-3), \
        "and it must actually differ from the unconverted numbers, or this proves nothing"


def test_a_mid_grey_comes_back_at_the_brightness_it_left(tmp_path):
    """The real defect, after TWO wrong characterisations of it.

    First I wrote this asserting a neutral stays neutral. It passed against the
    unfixed loader: both spaces put grey on the diagonal, so it could never
    fail. Then I assumed the export itself broke neutrality and measured a
    cast — using colour.RGB_to_XYZ directly, which does NOT adapt between
    ProPhoto's D50 and sRGB's D65. core/colour.py uses BRADFORD, so neutrals
    survive the export intact (spread 7e-05).

    What actually goes wrong is TONE. ProPhoto's transfer curve is gamma 1.8
    against sRGB's ~2.2, so a mid grey exported at 0.5 carries the number
    0.4247, and reading that back as sRGB shows it AS 0.4247 — the picture
    comes back dark. Measured on his Veil master: every channel shifted up by
    4.5 to 7.2 8-bit levels once corrected, mean dE2000 4.4, worst 10.8. Red
    moves most, so there is a mild cast riding on top, but the dominant term is
    brightness.

    core/export.py:22 describes the same mechanism in the other direction — "a
    correct M 16 export rendered dark in Photoshop: sRGB data read as ProPhoto".
    Same gamma mismatch, mirrored.
    """
    from nocturne.core.colour import convert
    # A white reference, so _normalize is a no-op and the grey's own value
    # survives to be asserted. Without it, _normalize rescales a flat patch to
    # full range and the brightness under test is destroyed before the colour
    # code ever runs — which is how this fixture failed the first time.
    src = np.full((32, 32, 3), 0.5, np.float32)
    src[0, 0] = 1.0
    exported = convert(src, to="ProPhoto RGB", frm="sRGB")
    assert abs(float(exported[5, 5].mean()) - 0.5) > 0.05, (
        "if ProPhoto encoded mid grey at 0.5 there would be no bug: the whole "
        "defect is that the number changes while the colour does not")

    p = tmp_path / "g.tif"
    _tagged(p, exported, "ProPhoto RGB")
    patch = load_tiff(str(p)).data[5, 5]
    assert abs(float(patch.mean()) - 0.5) < 0.01, (
        f"mid grey came back at {patch.mean():.4f}; unfixed it reads 0.4247, "
        f"which is the picture opening dark")
    assert float(patch.max() - patch.min()) < 0.01, "and it must still be neutral"


def test_an_UNTAGGED_tiff_is_left_exactly_alone(tmp_path):
    """The guarantee that matters more than the fix.

    Every project saved before today, every FITS-derived export, and every
    file from a tool that does not tag, all depend on this path being
    untouched. His own combined2.tif — Photoshop-saved with the profile
    deliberately stripped — is the real-world case.

    Asserting UNCHANGED rather than "differs from the ProPhoto answer",
    per CLAUDE.md: the weaker form passes while the code writes a third,
    different wrong value.
    """
    from nocturne.core.image_io import _normalize
    src = _synthetic_linear()
    p = tmp_path / "u.tif"
    tifffile.imwrite(str(p), src)                      # no extratags: no profile
    got = load_tiff(str(p)).data
    # NOT `src` itself: _normalize already rescales float data, so comparing
    # against the raw array asserts something that was never true and fails for
    # a reason unrelated to colour. The baseline is everything the loader does
    # APART from colour.
    assert np.array_equal(got, _normalize(src).astype(np.float32)), \
        "an untagged TIFF must come out exactly as it does today"


def test_an_srgb_tagged_tiff_is_RECOGNISED_and_then_left_alone(tmp_path):
    """Two claims, and the first is the one that matters.

    The earlier version asserted only that the pixels were unchanged — which
    passes identically against a loader that ignores ICC profiles entirely. It
    was asserting the FALLBACK, so it could not tell "recognised as sRGB, no
    conversion needed" from "not recognised, nothing done". It therefore could
    not see that the v4 description parser was returning mojibake for sRGB.
    """
    from nocturne.core.image_io import _normalize
    src = _synthetic_linear()
    p = tmp_path / "s.tif"
    _tagged(p, src, "sRGB")
    img = load_tiff(str(p))
    assert img.metadata.get("colour_space") == "sRGB", \
        "it must be IDENTIFIED, not merely left alone by accident"
    assert np.allclose(img.data, _normalize(src), atol=1e-6)


@pytest.mark.parametrize("space", ["sRGB", "Display P3", "Adobe RGB", "ProPhoto RGB"])
def test_every_space_nocturne_can_EXPORT_can_be_read_back(tmp_path, space):
    """The round trip, for all four — because it worked for exactly one.

    The ICC v4 `mluc` record is lang(2) country(2) length(4) offset(4) after a
    16-byte header, so length sits at 20 and offset at 24. Reading them at 16
    and 20 takes the ASCII "enUS" as the length. ProPhoto RGB still came out
    right, because its name is exactly twelve characters and the wrong offset
    landed on bytes str.strip() removes. sRGB, Display P3 and Adobe RGB all
    returned mojibake and were silently not converted — Adobe RGB opened
    0.4961 against the 0.5 it was saved at, with no note in the panel.

    Every test at the time used ProPhoto, so the whole feature rested on the
    one space that worked by accident. Parametrised for that reason: the next
    space added to SPACES gets covered by adding its name here.
    """
    from nocturne.core.colour import convert
    grey = np.full((32, 32, 3), 0.5, np.float32)
    grey[0, 0] = 1.0                      # white reference: keeps _normalize a no-op
    exported = convert(grey, to=space, frm="sRGB")
    p = tmp_path / "rt.tif"
    _tagged(p, exported, space)
    img = load_tiff(str(p))
    assert img.metadata.get("colour_space") == space, \
        f"{space} was not identified from its own embedded profile"
    patch = img.data[5, 5]
    assert abs(float(patch.mean()) - 0.5) < 0.01, \
        f"{space} round-tripped mid grey to {patch.mean():.4f}, not 0.5"


def test_an_unrecognised_profile_is_left_alone(tmp_path):
    """Fail safe, not clever.

    A profile we cannot identify means we do not know what the numbers mean.
    Converting on a guess would be worse than the status quo; leaving them is
    exactly as wrong as today and no more.
    """
    from nocturne.core.image_io import _normalize, _icc_description
    from nocturne.colour_profiles import icc_bytes
    src = _synthetic_linear()

    # A STRUCTURALLY VALID profile with a name we do not know. The earlier
    # version used 132 zero bytes, which fails the header check and returns
    # before the alias lookup is ever reached — so the path this test is named
    # for was never exercised. Built by renaming a real profile in place.
    blob = bytearray(icc_bytes("ProPhoto RGB"))
    # EXACTLY as long as "ProPhoto RGB" — twelve characters. A longer name
    # would overflow the desc tag into whatever follows it and the profile
    # would stop parsing for a reason unrelated to what is being tested.
    name = "Frobnitz RGB".encode("utf-16-be")
    count = int.from_bytes(blob[128:132], "big")
    for i in range(count):
        o = 132 + i * 12
        if blob[o:o + 4] != b"desc":
            continue
        st = int.from_bytes(blob[o + 4:o + 8], "big")
        lo = st + int.from_bytes(blob[st + 24:st + 28], "big")
        blob[st + 20:st + 24] = len(name).to_bytes(4, "big")
        blob[lo:lo + len(name)] = name
        break
    blob = bytes(blob)
    assert _icc_description(blob) == "Frobnitz RGB", "fixture did not take"

    p = tmp_path / "odd.tif"
    tifffile.imwrite(str(p), src, extratags=[(34675, 1, len(blob), blob, True)])
    img = load_tiff(str(p))
    assert np.array_equal(img.data, _normalize(src).astype(np.float32)), \
        "an unknown profile means unknown numbers: do not touch them"
    # But DO say so. Silence here is the same failure the whole change is
    # about — an image that may look wrong with nothing explaining why.
    assert img.metadata.get("colour_space") == "Frobnitz RGB"
    assert "not a profile nocturne knows" in img.metadata["colour_note"].lower()


def test_the_conversion_is_recorded_where_the_user_can_see_it(tmp_path):
    """A file whose numbers changed on load is worth being told about.

    Different in kind from the target/gain/exposure a TIFF legitimately lacks:
    this is not invented provenance, it is a fact about what we did.
    """
    p = tmp_path / "pp.tif"
    _tagged(p, _synthetic_linear(), "ProPhoto RGB")
    md = load_tiff(str(p)).metadata
    assert md.get("colour_space") == "ProPhoto RGB"
    assert "converted" in str(md.get("colour_note", "")).lower()

    q = tmp_path / "u.tif"
    tifffile.imwrite(str(q), _synthetic_linear())
    assert load_tiff(str(q)).metadata == {}, \
        "an untagged file says nothing, exactly as before"


def test_the_colour_note_actually_reaches_the_import_panel(tmp_path):
    """Written because the first version of this did NOT.

    load_tiff recorded `colour_space` and `colour_note` in metadata, and a test
    called "recorded where the user can see it" passed — but import_summary()
    builds the panel from an explicit list of keys and colour was not among
    them, so nothing displayed it. The metadata was real and invisible, which
    is the worst of both: a test asserting a promise the app did not keep.
    """
    from nocturne.core.fits_io import import_summary
    p = tmp_path / "pp.tif"
    _tagged(p, _synthetic_linear(), "ProPhoto RGB")
    html = import_summary(load_tiff(str(p)).metadata, assume_instrument=False)
    assert "ProPhoto RGB" in html, "the panel must name the space the file declared"
    assert "Colour" in html

    q = tmp_path / "u.tif"
    tifffile.imwrite(str(q), _synthetic_linear())
    assert "Colour" not in import_summary(load_tiff(str(q)).metadata,
                                          assume_instrument=False), \
        "an untagged TIFF says nothing about colour, because nothing was done"


def test_a_hostile_tag_count_cannot_hang_the_app(tmp_path):
    """A profile is attacker-controlled data and slicing does not raise.

    `blob[128:132] = 0xFFFFFFFF` declares 4.3 billion tags. Nothing in Python
    objects: a slice past the end returns short data rather than throwing, so
    `except Exception` never fires and the loop simply runs — measured at
    roughly ten minutes of pure-Python slicing inside load_tiff, with no cancel
    point and no window repaint. The count is now bounded by what the blob can
    physically hold.
    """
    import time
    from nocturne.core.image_io import _icc_description
    blob = b"\x00" * 36 + b"acsp" + b"\x00" * 88 + b"\xff\xff\xff\xff" + b"\x00" * 64
    t0 = time.monotonic()
    assert _icc_description(blob) == ""
    assert time.monotonic() - t0 < 1.0, "the tag count is not bounded"


def test_a_profile_that_is_not_even_a_profile_is_rejected_early(tmp_path):
    """Every ICC profile carries 'acsp' at byte 36. Without that check the
    parser walks arbitrary bytes and can only fail by luck."""
    from nocturne.core.image_io import _icc_description
    assert _icc_description(b"\x00" * 200) == ""
    assert _icc_description(b"") == ""


def test_a_string_typed_icc_tag_cannot_stop_a_file_opening(tmp_path):
    """A colour profile must never be able to prevent an image loading.

    If a writer types tag 34675 as ASCII rather than UNDEFINED, tifffile hands
    back a `str`, and `bytes(str)` raises TypeError: "string argument without
    an encoding". With that call outside the guard, a file that opened fine
    before this feature existed would have stopped opening at all — a strictly
    worse outcome than the bug being fixed.
    """
    src = _synthetic_linear()
    p = tmp_path / "strtag.tif"
    tifffile.imwrite(str(p), src, extratags=[(34675, 2, 5, b"hello", True)])
    img = load_tiff(str(p))                      # must not raise
    assert img.data.shape == (400, 300, 3)
    assert img.metadata.get("colour_space") is None


def test_a_multi_page_tiff_reads_its_FIRST_page(tmp_path):
    """Pinning a silent improvement, so it cannot be silently undone.

    The old path called `tifffile.imread(path)`, which stacks every page: a
    five-page file came back as a (5, H, W, 3) array, `_channels_last` then saw
    5 in the leading axis and the result was a few pixels of garbage. Reading
    `pages[0]` — needed anyway to reach the ICC tag — fixes that as a side
    effect. Nobody asked for it and no test covered it, which is exactly how it
    would get reverted.
    """
    page = (_synthetic_linear() * 65535).astype(np.uint16)
    p = tmp_path / "multi.tif"
    with tifffile.TiffWriter(str(p)) as tw:
        for _ in range(5):
            tw.write(page)
    img = load_tiff(str(p))
    assert img.data.shape == (400, 300, 3), \
        f"a five-page TIFF must read as one image, got {img.data.shape}"
