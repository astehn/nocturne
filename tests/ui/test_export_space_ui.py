"""Choosing the export colour space, and the 8-bit restriction.

Andreas' decision: wide gamut only for 16-bit TIFF. Adobe RGB spreads the same
256 levels over a larger volume, so an 8-bit file in one has visibly coarser
gradients — and astro images are mostly smooth gradients, the worst case for
banding. PNG is the share-and-publish format, where sRGB is what every viewer
expects anyway.
"""
import pytest

pytest.importorskip("PySide6")
from nocturne.core.colour import EIGHT_BIT_SPACES, SPACES  # noqa: E402
from nocturne.ui.pipeline import path_stages  # noqa: E402
from nocturne.ui.step_panels import (  # noqa: E402
    EXPORT_FORMATS, SIXTEEN_BIT_FORMATS, build_panel,
)


def _panel(qtbot, **kw):
    stage = next(s for s in path_stages() if s.id == "export")
    p = build_panel(stage, **kw)
    qtbot.addWidget(p)
    return p


def test_the_panel_offers_every_space(qtbot):
    p = _panel(qtbot)
    offered = [p.space_box.itemText(i) for i in range(p.space_box.count())]
    assert offered == list(SPACES)


def test_it_defaults_to_srgb(qtbot):
    """sRGB is what the numbers already mean, and a user who never opens the
    dropdown must get exactly today's behaviour plus a correct tag."""
    p = _panel(qtbot)
    assert p.space_box.currentText() == "sRGB"


def test_choosing_png_restricts_the_space_to_srgb(qtbot):
    """The restriction is enforced in the WIDGET, not merely hidden: selecting
    PNG must actively pull a wide-gamut choice back to sRGB, or a user who picks
    Adobe RGB first and PNG second gets a banded file."""
    p = _panel(qtbot)
    p.space_box.setCurrentText("Adobe RGB")
    p.format_box.setCurrentText("PNG")
    assert p.space_box.currentText() == "sRGB"
    enabled = [p.space_box.model().item(i).isEnabled()
               for i in range(p.space_box.count())]
    assert enabled == [s in EIGHT_BIT_SPACES for s in SPACES]


def test_tiff_allows_every_space_again(qtbot):
    p = _panel(qtbot)
    p.format_box.setCurrentText("PNG")
    p.format_box.setCurrentText("TIFF (16-bit)")
    assert all(p.space_box.model().item(i).isEnabled()
               for i in range(p.space_box.count()))


def test_the_export_callback_carries_the_space(qtbot):
    """The picker must reach the exporter. A dropdown wired to nothing is the
    exact failure the Open large editor button already shipped with."""
    got = []
    p = _panel(qtbot, on_export=lambda fmt, space: got.append((fmt, space)))
    p.format_box.setCurrentText("TIFF (16-bit)")
    p.space_box.setCurrentText("Display P3")
    p.export_btn.click()
    assert got == [("TIFF (16-bit)", "Display P3")]


def test_the_saved_image_and_its_tag_always_agree(qtbot, tmp_path):
    """Tagging without converting MIS-declares the file, which is worse than
    leaving it untagged: a reader then faithfully renders the wrong thing
    instead of guessing.

    This caught a real slip — a first version of the PNG path converted the
    image to get the profile bytes and then saved the ORIGINAL alongside them.
    Harmless while PNG is restricted to sRGB, wrong the moment that changed.
    """
    import numpy as np
    from nocturne.colour_profiles import icc_bytes
    from nocturne.core.colour import convert
    from nocturne.core.image import AstroImage
    from nocturne.ui.main_window import MainWindow

    win = MainWindow(settings_path=str(tmp_path / "s.json"), check_updates=False)
    qtbot.addWidget(win)
    rng = np.random.default_rng(0)
    data = (rng.random((8, 8, 3)) * 0.6 + 0.2).astype(np.float32)
    img = AstroImage(data, is_linear=False, metadata={})

    for space in ("sRGB", "Adobe RGB", "Display P3"):
        out, icc = win._prepare_for_export(img, space)
        assert icc == icc_bytes(space), f"{space}: wrong profile"
        assert np.allclose(out.data, convert(data, space), atol=1e-6), (
            f"{space}: the pixels were not converted to match the tag")


def test_starless_and_stars_allows_every_space(qtbot):
    """Starless + Stars writes two 16-bit TIFFs, so Andreas' rule — wide gamut
    for 16-bit TIFF — covers it. It did not, because the gate tested
    `fmt.startswith("TIFF")` and this format's label starts with "Starless".
    The export path was always correct; only the widget disagreed.
    """
    p = _panel(qtbot)
    p.space_box.setCurrentText("ProPhoto RGB")
    p.format_box.setCurrentText("Starless + Stars (two TIFFs)")
    assert p.space_box.currentText() == "ProPhoto RGB", "selection was pulled back to sRGB"
    assert all(p.space_box.model().item(i).isEnabled()
               for i in range(p.space_box.count()))


def test_the_sixteen_bit_set_names_real_formats(qtbot):
    """Guard on the constant itself. The wide-gamut gate now reads a set of
    labels, so a format renamed in EXPORT_FORMATS and not here would silently
    lose its wide gamut — the exact failure this replaced, in a new costume.
    """
    assert SIXTEEN_BIT_FORMATS <= set(EXPORT_FORMATS), (
        f"not real formats: {SIXTEEN_BIT_FORMATS - set(EXPORT_FORMATS)}")
