"""A picture export before Stretch, in a wide colour space, and mono + wide.

The single-picture export converted the LINEAR data into Display P3 / Adobe RGB
/ ProPhoto and only then stretched it (display_data inside save_tiff), so the
file was up to 0.11 off what the canvas showed (review find 2026-10-12) — and
disagreed with the Starless + Stars pair, which already stretched first. The
canvas shows display_data; the file must be display_data, converted.
"""
import numpy as np
import pytest

pytest.importorskip("PySide6")
import tifffile  # noqa: E402

from nocturne.core.colour import EIGHT_BIT_SPACES, SPACES, convert  # noqa: E402
from nocturne.core.export import _to_uint, display_data  # noqa: E402
from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.history.project import Project  # noqa: E402
from nocturne.ui import file_dialogs  # noqa: E402
from nocturne.ui.main_window import MainWindow  # noqa: E402
from nocturne.ui.pipeline import path_stages  # noqa: E402
from nocturne.ui.step_panels import EXPORT_FORMATS, build_panel  # noqa: E402

WIDE = [s for s in SPACES if s != "sRGB"]


def _linear_rgb() -> np.ndarray:
    # Faint sky with a colour gradient and two tinted stars: the stretch is far
    # from the identity and the channels differ, so convert∘stretch and
    # stretch∘convert cannot coincide by accident.
    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[:40, :48]
    lin = np.full((40, 48, 3), 0.02) + rng.normal(0, 0.003, (40, 48, 3))
    lin[..., 0] += 0.01 * xx / 48
    for cy, cx in ((10, 12), (28, 34)):
        lin += (0.6 * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / 4.0))[..., None] * [1.0, 0.8, 0.6]
    return np.clip(lin, 0, 1).astype(np.float32)


def _stretched_rgb() -> np.ndarray:
    return (np.random.default_rng(3).random((40, 48, 3)) * 0.8 + 0.1).astype(np.float32)


def _window(qtbot, tmp_path, img: AstroImage, *, linked=True):
    win = MainWindow(settings_path=str(tmp_path / "s.json"), check_updates=False, telemetry=False)
    win._async_enabled = False
    qtbot.addWidget(win)
    win._source_label = "x.fits"
    win.project = Project(img, str(tmp_path / "cache"))
    win._view_linked = linked
    return win


def _export_tiff(win, monkeypatch, path, space):
    monkeypatch.setattr(file_dialogs, "save_file", lambda *a, **k: (str(path), ""))
    win.export_final("TIFF (16-bit)", space)
    return tifffile.imread(str(path))


@pytest.mark.parametrize("linked", [True, False])
@pytest.mark.parametrize("space", WIDE)
def test_a_linear_wide_export_is_the_canvas_converted(qtbot, tmp_path, monkeypatch, space, linked):
    img = AstroImage(_linear_rgb(), is_linear=True, metadata={})
    win = _window(qtbot, tmp_path, img, linked=linked)
    got = _export_tiff(win, monkeypatch, tmp_path / "out.tiff", space).astype(np.int64)
    shown = display_data(img, linked=linked)            # what the canvas shows
    want = _to_uint(convert(shown, space), 16).astype(np.int64)
    assert np.abs(got - want).max() <= 1, (
        f"{space}: file is {np.abs(got - want).max()} 16-bit levels off the canvas, converted")


def _old_formula(img: AstroImage, space: str, linked: bool) -> np.ndarray:
    """What main wrote for the cases that must NOT change: sRGB (no conversion,
    display_data inside save_tiff) and an already-stretched image (clip, then
    convert; save_tiff's display_data is a clip of an in-range result)."""
    if space == "sRGB":
        return _to_uint(display_data(img, linked=linked), 16)
    return _to_uint(np.clip(convert(img.data, space), 0, 1), 16)


@pytest.mark.parametrize("linear,space", [(True, "sRGB")] + [(False, s) for s in SPACES])
def test_srgb_and_stretched_exports_are_unchanged(qtbot, tmp_path, monkeypatch, linear, space):
    data = _linear_rgb() if linear else _stretched_rgb()
    img = AstroImage(data, is_linear=linear, metadata={})
    win = _window(qtbot, tmp_path, img)
    got = _export_tiff(win, monkeypatch, tmp_path / "out.tiff", space)
    assert np.array_equal(got, _old_formula(img, space, True))


def test_the_split_pair_and_the_single_export_agree_before_stretch(qtbot, tmp_path, monkeypatch):
    """The pair stretched first all along; the single file now does the same,
    so Screen(starless, stars) in P3 equals the single P3 file."""
    img = AstroImage(_linear_rgb(), is_linear=True, metadata={})
    win = _window(qtbot, tmp_path, img)
    single = _export_tiff(win, monkeypatch, tmp_path / "one.tiff", "Display P3") / 65535
    out = tmp_path / "split"; out.mkdir()
    monkeypatch.setattr(file_dialogs, "choose_folder", lambda *a, **k: str(out))
    # A deterministic split, so the test does not depend on any tool installed.
    win._split_tagged = lambda src: (AstroImage(src.data * 0.7, is_linear=False, metadata={}),
                                     AstroImage(1 - (1 - src.data) / (1 - src.data * 0.7),
                                                is_linear=False, metadata={}), "test")
    win.export_final("Starless + Stars (two TIFFs)", "Display P3")
    sl = tifffile.imread(out / "starless.tif") / 65535
    st = tifffile.imread(out / "stars.tif") / 65535
    # Screen in P3's encoding is not Screen in sRGB's, so compare each layer's
    # sRGB-domain recombination through the same conversion instead.
    back = lambda a: convert(a.astype(np.float32), "sRGB", frm="Display P3")
    recombined = 1 - (1 - back(sl)) * (1 - back(st))
    assert np.abs(recombined - back(single)).max() < 3e-3


# --- mono + a wide space ---------------------------------------------------

def _panel(qtbot, **kw):
    stage = next(s for s in path_stages() if s.id == "export")
    p = build_panel(stage, **kw)
    qtbot.addWidget(p)
    return p


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_mono_greys_out_the_wide_spaces_on_every_format(qtbot, fmt):
    p = _panel(qtbot, mono=True)
    p.format_box.setCurrentText(fmt)
    for b in p.space_box.buttons():
        b.click()                              # a greyed button cannot choose
    enabled = [b.isEnabled() for b in p.space_box.buttons()]
    assert enabled == [s in EIGHT_BIT_SPACES for s in SPACES]
    assert p.space_box.currentText() == "sRGB"


def test_mono_starts_on_srgb_even_on_tiff(qtbot):
    p = _panel(qtbot, mono=True)
    assert p.format_box.currentText().startswith("TIFF")
    assert [b.isEnabled() for b in p.space_box.buttons()] == [s == "sRGB" for s in SPACES]


def test_colour_keeps_every_space_on_tiff(qtbot):
    p = _panel(qtbot, mono=False)
    p.format_box.setCurrentText("TIFF (16-bit)")
    assert all(b.isEnabled() for b in p.space_box.buttons())


@pytest.mark.parametrize("mono", [True, False])
def test_the_window_tells_the_panel_whether_the_picture_is_mono(qtbot, tmp_path, mono):
    # No open route yields a 2-D picture today (a 2-D FITS debayers, a grey
    # TIFF is widened to three channels), so the project is set directly: the
    # rule must hold for whatever 2-D data a future route brings.
    data = _linear_rgb()
    img = AstroImage(data[..., 0].copy() if mono else data, is_linear=True, metadata={})
    win = _window(qtbot, tmp_path, img)
    assert (win.project.current().data.ndim == 2) is mono
    win._go_to_id("export", user_initiated=False)
    win._panel.format_box.setCurrentText("TIFF (16-bit)")
    assert [b.isEnabled() for b in win._panel.space_box.buttons()] == [
        (s == "sRGB") or not mono for s in SPACES]


@pytest.mark.parametrize("space", WIDE)
def test_mono_wide_is_refused_with_a_reason_not_a_crash(qtbot, tmp_path, space):
    img = AstroImage(_linear_rgb()[..., 0].copy(), is_linear=True, metadata={})
    win = _window(qtbot, tmp_path, img)
    with pytest.raises(ValueError, match="sRGB"):
        win._prepare_for_export(img, space)


@pytest.mark.parametrize("linear", [True, False])
def test_mono_srgb_still_exports_unchanged(qtbot, tmp_path, monkeypatch, linear):
    data = _linear_rgb()[..., 1].copy() if linear else _stretched_rgb()[..., 1].copy()
    img = AstroImage(data, is_linear=linear, metadata={})
    win = _window(qtbot, tmp_path, img)
    got = _export_tiff(win, monkeypatch, tmp_path / "m.tiff", "sRGB")
    assert np.array_equal(got, _old_formula(img, "sRGB", True))


def test_mono_says_why_the_wide_spaces_are_greyed(qtbot):
    assert "A mono picture exports in sRGB." in _panel(qtbot, mono=True).space_note.text()
    assert "mono" not in _panel(qtbot, mono=False).space_note.text()


def test_a_non_export_rebuild_loads_no_pixels_for_the_mono_question(qtbot, tmp_path, monkeypatch):
    """project.current() is a full np.load (~0.3 s on a 33 MP drizzle); the
    mono question must not pay it on every step change."""
    img = AstroImage(_linear_rgb()[..., 0].copy(), is_linear=True, metadata={})
    win = _window(qtbot, tmp_path, img)
    # Levels: the panel itself reads no pixels (Crop and Stretch do, for
    # their own reasons), so any call here is the mono question's.
    win._go_to_id("levels", user_initiated=False)
    calls = []
    real = win.project.current
    monkeypatch.setattr(win.project, "current", lambda: calls.append(1) or real())
    win._rebuild_panel()
    assert calls == [], f"project.current() called {len(calls)}x on a Levels rebuild"
    win._go_to_id("export", user_initiated=False)
    calls.clear()
    win._rebuild_panel()
    assert [b.isEnabled() for b in win._panel.space_box.buttons()] == [s == "sRGB" for s in SPACES]
