"""StarNet2 as a free star/starless split.

Design: docs/superpowers/specs/2026-09-18-starnet2-integration.md. Measured on a
real NGC 7635 master 2026-09-18 — the free fallback leaves 40.3% of star flux
where StarNet2 leaves 20.9%, and the 1:1 crops are not close.
"""
import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.settings import Settings
from nocturne.steps.factory import _splitter
from nocturne.tools.starnet import StarNet


def _img(h=16, w=16):
    a = np.full((h, w, 3), 0.2, np.float32)
    a[8, 8] = 0.9
    return AstroImage(a, is_linear=False, metadata={"OBJECT": "M 42"})


def test_it_asks_for_both_outputs_and_the_star_layer_is_unscreened(tmp_path):
    """`--unscreen` is the whole reason this is a drop-in: it writes the star
    layer in the SCREEN-compatible form every caller in this app recombines
    with. RCAstro.remove_stars documents the same contract, down to the flag
    name — the plain (subtractive) star layer recombines wrong, dimming and
    puffing stars even at zero reduction."""
    seen = {}
    import tifffile

    def fake_runner(args, **kw):
        seen["args"] = args
        out = args[args.index("--output") + 1]
        stars = args[args.index("--unscreen") + 1]
        src = tifffile.imread(args[args.index("--input") + 1])
        tifffile.imwrite(out, src)
        tifffile.imwrite(stars, np.zeros_like(src))

    StarNet("/fake/starnet2").remove_stars(_img(), runner=fake_runner)
    assert "--unscreen" in seen["args"], "without this the star layer recombines wrong"
    assert "--output" in seen["args"] and "--input" in seen["args"]
    assert seen["args"][0] == "/fake/starnet2"


def test_it_carries_metadata_and_linearity_through(tmp_path):
    """The tool changes pixels, not headers. Its output files have no metadata
    at all, so without this the target name and everything else is lost."""
    import tifffile

    def fake_runner(args, **kw):
        src = tifffile.imread(args[args.index("--input") + 1])
        tifffile.imwrite(args[args.index("--output") + 1], src)
        tifffile.imwrite(args[args.index("--unscreen") + 1], np.zeros_like(src))

    src = _img()
    starless, stars = StarNet("/fake").remove_stars(src, runner=fake_runner)
    assert starless.metadata == {"OBJECT": "M 42"} and stars.metadata == {"OBJECT": "M 42"}
    assert starless.is_linear is src.is_linear


def test_a_run_that_writes_nothing_is_an_error_not_an_empty_image(tmp_path):
    """The usual failure is a copied executable without its weights package
    beside it. That must say so, not hand back a blank frame that looks like a
    star-free image."""
    with pytest.raises(RuntimeError, match="weights"):
        StarNet("/fake").remove_stars(_img(), runner=lambda args, **kw: None)


def test_it_leaves_nothing_behind(tmp_path, monkeypatch):
    """Temp files go in a temp directory that is removed — never beside the
    user's own files."""
    import tempfile, tifffile, os
    made = []
    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kw: made.append(real_mkdtemp(**kw)) or made[-1])

    def fake_runner(args, **kw):
        src = tifffile.imread(args[args.index("--input") + 1])
        tifffile.imwrite(args[args.index("--output") + 1], src)
        tifffile.imwrite(args[args.index("--unscreen") + 1], np.zeros_like(src))

    StarNet("/fake").remove_stars(_img(), runner=fake_runner)
    assert made and not os.path.exists(made[0]), "the temp directory survived"


def test_rc_astro_still_wins_when_both_are_installed(tmp_path):
    """The user paid for StarXTerminator and it is still the best. StarNet2 is
    the answer for everyone else, not a replacement for it."""
    from nocturne.tools.rcastro import RCAstro
    rc = tmp_path / "rc-astro"; rc.write_text("#!/bin/sh\n"); rc.chmod(0o755)
    sn = tmp_path / "starnet2"; sn.write_text("#!/bin/sh\n"); sn.chmod(0o755)
    both = Settings(rcastro_path=str(rc), starnet_path=str(sn))
    assert isinstance(_splitter(both), RCAstro)
    assert isinstance(_splitter(Settings(starnet_path=str(sn))), StarNet)
    assert _splitter(Settings()) is None, "nothing installed falls back to core/starless"


# --- progress, added 2026-09-19 ---------------------------------------------
#
# A split is 2.9 s on a master and ~38 s on a drizzled frame, six times that on
# the Linux CPU build, and it showed NOTHING throughout. Andreas: *"no progress
# indicators at all when separating stars with StarNet2"*.

@pytest.mark.parametrize("line, expected", [
    ("Working: 11.1%", 11.1),
    ("Working: 100.0%", 100.0),
    ("Working:  22.2 %", 22.2),
    ("Working: 5%", 5.0),
    ("Working: Done! ", None),
    ("Reading input from /tmp/in.tif...", None),
    ("", None),
    (None, None),
])
def test_parse_progress_reads_a_percentage_only_when_it_is_progress(line, expected):
    from nocturne.tools.starnet import parse_progress
    assert parse_progress(line) == expected


def test_a_percentage_that_is_not_progress_is_not_mistaken_for_one():
    """The non-quiet output is full of other numbers — it prints value ranges
    with their own percentages. Anchoring on the word is what keeps
    `below_zero=0 (0%)` from reporting the split as 0% complete forever."""
    from nocturne.tools.starnet import parse_progress
    assert parse_progress("physical_range=[3770,56844] below_zero=0 (0%)") is None
    assert parse_progress("above_one=0 (0%) type_normalized_range=[0.05,0.86]") is None


def test_it_does_not_ask_the_tool_to_be_quiet():
    """The regression that started this. `--quiet` was passed from the first
    version, and MEASURED 2026-09-19 it makes StarNet2 print one newline and
    nothing else — so there was never any progress to miss. The silence was
    requested, not absent.

    Asserted as "the flag is not sent" rather than "some progress arrived",
    because a fake runner can always be made to emit a line; only the argv says
    what the real tool would have been told."""
    import tifffile
    seen = {}

    def fake_runner(args, **kw):
        seen["args"] = args
        out = args[args.index("--output") + 1]
        stars = args[args.index("--unscreen") + 1]
        src = tifffile.imread(args[args.index("--input") + 1])
        tifffile.imwrite(out, src)
        tifffile.imwrite(stars, np.zeros_like(src))

    StarNet("/fake").remove_stars(_img(), runner=fake_runner)
    assert "--quiet" not in seen["args"], \
        "--quiet silences the progress output entirely; that was the bug"


def test_progress_reaches_the_cancel_token_sink_as_the_tool_prints_it():
    """End of the chain: the tool's line -> parse -> report_progress -> the
    ambient token's sink, which is what the busy panel draws. Reported as a
    percentage of 100, matching GraXpert, so one bar serves both."""
    import tifffile
    from nocturne.core.tasks import CancelToken, set_ambient, clear_ambient

    got = []
    token = CancelToken()
    token.on_progress = lambda done, total: got.append((done, total))

    def fake_runner(args, on_line=None, **kw):
        # exactly what the real tool emits, carriage returns and all
        for text in ("Reading input from in.tif...", "Working: 11.1%",
                     "Working: 55.6%", "Working: 100.0%", "Working: Done! "):
            on_line(text)
        out = args[args.index("--output") + 1]
        stars = args[args.index("--unscreen") + 1]
        src = tifffile.imread(args[args.index("--input") + 1])
        tifffile.imwrite(out, src)
        tifffile.imwrite(stars, np.zeros_like(src))

    set_ambient(token)
    try:
        StarNet("/fake").remove_stars(_img(), runner=fake_runner)
    finally:
        clear_ambient()

    assert got == [(11, 100), (56, 100), (100, 100)], \
        "every tile update should reach the sink, and nothing else should"


# --- the codec that was never in the bundle (2026-09-22) --------------------
#
# Reported by a user four releases after StarNet2 shipped: every split died on
# "could not import name 'lzw_decode' from 'imagecodecs'". Nothing here could
# have caught it — the fake runners above write UNCOMPRESSED TIFF, so the LZW
# decode this tool depends on was never exercised by any test, in any build.

def test_it_reads_back_the_lzw_tiff_the_real_tool_writes(tmp_path):
    """StarNet2 writes LZW-compressed 16-bit TIFF. A fixture that writes
    uncompressed TIFF proves the round trip works with the one compression the
    real tool never uses — which is exactly how four releases shipped a split
    that could not read its own output."""
    import tifffile

    src = _img(32, 32)

    def lzw_runner(args, on_line=None, **kw):
        data = tifffile.imread(args[args.index("--input") + 1])
        tifffile.imwrite(args[args.index("--output") + 1], data, compression="lzw")
        tifffile.imwrite(args[args.index("--unscreen") + 1],
                         np.zeros_like(data), compression="lzw")

    starless, stars = StarNet("/fake").remove_stars(src, runner=lzw_runner)
    assert np.allclose(starless.data, src.data, atol=2e-5), \
        "the LZW round trip should return the pixels StarNet2 was given"
    assert not stars.data.any()


def test_the_bundle_collects_the_codec_that_decodes_it():
    """imagecodecs loads each codec with importlib.import_module, so
    PyInstaller's static analysis sees NONE of them: the shipped app carried
    the package with one of its sixty extension modules and `import
    imagecodecs` succeeded anyway. Only collecting it explicitly brings
    `_imcd`, where lzw_decode lives."""
    from pathlib import Path
    spec = (Path(__file__).parent.parent / "packaging" / "nocturne.spec").read_text()
    collected = spec.split("for pkg in (")[1].split(")")[0]
    assert "imagecodecs" in collected, \
        "the spec does not collect imagecodecs — star separation cannot work in the bundle"


def test_collecting_imagecodecs_actually_brings_the_lzw_module():
    """The guard above checks the spec says a word. This checks the word still
    does the job: `lzw_decode` is not in a module called `_lzw`, it is in
    `_imcd`, and a restructured imagecodecs could leave the spec line looking
    correct while the codec goes missing again."""
    from PyInstaller.utils.hooks import collect_all
    _datas, binaries, hidden = collect_all("imagecodecs")
    assert "imagecodecs._imcd" in hidden, \
        "collect_all no longer names the module that provides lzw_decode"
    assert binaries, "collect_all brought no shared libraries for imagecodecs"
