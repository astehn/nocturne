from dataclasses import dataclass

import pytest

pytest.importorskip("PySide6")
from nocturne.ui.solve_panel import SolvePanel  # noqa: E402


@dataclass
class _FakeResult:
    center_ra_deg: float
    center_dec_deg: float
    wcs: object = None


def _wcs(w=1920, h=1080, scale=0.0005556, mirrored=False):
    from astropy.wcs import WCS
    wc = WCS(naxis=2)
    wc.wcs.crpix = [w / 2, h / 2]
    wc.wcs.crval = [314.8208333333334, 44.528888888888886]
    sign = 1.0 if mirrored else -1.0
    wc.wcs.cd = [[sign * scale, 0], [0, scale]]
    wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wc


# --- layers -----------------------------------------------------------------

def test_default_layers(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    assert panel.layers() == {
        "objects": True, "stars": True, "grid": False,
        "compass": True, "scale": True, "by_type": False,
    }


def test_toggling_a_layer_emits_the_complete_dict(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.layersChanged, timeout=1000) as blocker:
        panel.layer_checks["grid"].setChecked(True)
    emitted = blocker.args[0]
    assert emitted == {
        "objects": True, "stars": True, "grid": True,
        "compass": True, "scale": True, "by_type": False,
    }
    # not a delta -- every key is present even though only one changed
    assert set(emitted) == {"objects", "stars", "grid", "compass", "scale", "by_type"}


def test_toggling_a_layer_updates_the_accessor(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    panel.layer_checks["by_type"].setChecked(True)
    assert panel.layers()["by_type"] is True


# --- density ------------------------------------------------------------

def test_density_defaults_to_balanced(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    assert panel.density() == "balanced"


def test_changing_density_emits_and_updates_accessor(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.densityChanged, timeout=1000) as blocker:
        panel.density_box.setCurrentIndex(0)   # "Minimal"
    assert blocker.args[0] == "minimal"
    assert panel.density() == "minimal"


# --- state / header -------------------------------------------------------

def test_set_state_drives_the_badge_text(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    panel.set_state("not_solved")
    assert "Not solved" in panel.header_btn.text()
    panel.set_state("solving")
    assert "Solving…" in panel.header_btn.text()
    panel.set_state("solved")
    assert "Solved" in panel.header_btn.text()
    panel.set_state("cached")
    assert "Cached" in panel.header_btn.text()
    panel.set_state("stale")
    assert "Needs re-solve" in panel.header_btn.text()


def test_collapsed_header_shows_the_state_on_one_line(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    panel.set_state("solved")
    panel.header_btn.click()   # collapse (starts expanded)
    assert panel.header_btn.text() == "Plate solve · Solved ▸"
    assert panel.content.isHidden()


def test_clicking_the_header_toggles_expansion(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    assert not panel.content.isHidden()
    panel.header_btn.click()
    assert panel.content.isHidden()
    panel.header_btn.click()
    assert not panel.content.isHidden()


# --- action row -------------------------------------------------------------

def test_resolve_button_emits_resolve_requested(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.resolveRequested, timeout=1000):
        panel.resolve_btn.click()


def test_resolve_button_disabled_while_solving(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    panel.set_state("solving")
    assert not panel.resolve_btn.isEnabled()
    panel.set_state("solved")
    assert panel.resolve_btn.isEnabled()
    assert panel.resolve_btn.text() == "Re-solve"


# --- result card --------------------------------------------------------

def test_result_card_formats_ra_dec_sexagesimally(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    res = _FakeResult(center_ra_deg=314.8208333333334, center_dec_deg=44.528888888888886)
    panel.set_result(res, "NGC 7000 · North America Nebula", (1080, 1920),
                      pixscale=2.14, elapsed=3.1, cached=True)
    text = panel.result_label.text()
    assert "20h 59m 17s" in text
    assert "+44° 31′ 44″" in text
    assert "NGC 7000 · North America Nebula" in text


def test_result_card_reports_fov_pixscale_solver_elapsed_and_cache_state(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    res = _FakeResult(center_ra_deg=0.0, center_dec_deg=0.0)
    panel.set_result(res, "", (1080, 1920), pixscale=2.14, elapsed=3.1, cached=True)
    text = panel.result_label.text()
    assert "2.14″/px" in text
    assert "ASTAP" in text
    assert "3.1 s" in text
    assert "reused from cache" in text


def test_result_card_reports_freshly_solved_when_not_cached(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    res = _FakeResult(center_ra_deg=0.0, center_dec_deg=0.0)
    panel.set_result(res, "", (1080, 1920), pixscale=2.14, elapsed=1.0, cached=False)
    assert "freshly solved" in panel.result_label.text()
    assert "reused from cache" not in panel.result_label.text()


def test_result_card_never_shows_a_quality_or_confidence_score(qtbot):
    # The ASTAP parser discards match count, star count and residual, so
    # there is no metric to show -- a fabricated "Good" score would be worse
    # than nothing. This must hold for every state the card can render.
    panel = SolvePanel()
    qtbot.addWidget(panel)
    res = _FakeResult(center_ra_deg=314.82, center_dec_deg=44.53, wcs=_wcs())
    panel.set_result(res, "NGC 7000 · North America Nebula", (1080, 1920),
                      pixscale=2.14, elapsed=3.1, cached=True)
    text = panel.result_label.text().lower()
    assert "quality" not in text
    assert "confidence" not in text


def test_result_card_shows_north_orientation_when_wcs_present(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    res = _FakeResult(center_ra_deg=314.82, center_dec_deg=44.53, wcs=_wcs())
    panel.set_result(res, "", (1080, 1920), pixscale=2.0, elapsed=1.0, cached=False)
    assert "N -180.0°" in panel.result_label.text()   # see FITS_Y_DOWN correction


def test_result_card_never_claims_parity(qtbot):
    """Parity is deliberately absent.

    is_mirrored() derives from the same screen convention as the projection, so
    it inverted when FITS_Y_DOWN was corrected, and it reported "mirrored" on a
    Seestar frame the user verified against Stellarium as NOT mirrored. This is
    the panel that tells you whether to trust the solve; an unverified claim
    there is worse than a missing field.
    """
    panel = SolvePanel()
    qtbot.addWidget(panel)
    res = _FakeResult(center_ra_deg=314.82, center_dec_deg=44.53, wcs=_wcs())
    panel.set_result(res, "", (1080, 1920), pixscale=2.0, elapsed=1.0, cached=False)
    assert "mirrored" not in panel.result_label.text().lower()



def test_result_card_says_when_the_scale_was_assumed(qtbot):
    """A file with no optics in its header still solves, using the Seestar
    profile's plate scale — but the card must admit the assumption, because on
    data from another instrument that assumption is wrong."""
    panel = SolvePanel()
    qtbot.addWidget(panel)
    res = _FakeResult(center_ra_deg=314.82, center_dec_deg=44.53, wcs=_wcs())
    panel.set_result(res, "", (1080, 1920), pixscale=2.0, elapsed=1.0, cached=False,
                     scale_source="profile")
    assert "assumed" in panel.result_label.text().lower()


def test_result_card_stays_quiet_when_the_header_supplied_the_scale(qtbot):
    panel = SolvePanel()
    qtbot.addWidget(panel)
    res = _FakeResult(center_ra_deg=314.82, center_dec_deg=44.53, wcs=_wcs())
    panel.set_result(res, "", (1080, 1920), pixscale=2.0, elapsed=1.0, cached=False,
                     scale_source="header")
    assert "assumed" not in panel.result_label.text().lower()



def test_the_panel_has_no_object_list_control(qtbot):
    """The list shows itself on the canvas once a solve lands and follows the
    Annotations pill. A button here was a second switch for something the pill
    already governs, sitting a long way from the thing it controlled."""
    panel = SolvePanel()
    qtbot.addWidget(panel)
    assert not hasattr(panel, "objects_toggle")
    assert not hasattr(panel, "set_object_count")
    assert not hasattr(panel, "objectListToggled")
