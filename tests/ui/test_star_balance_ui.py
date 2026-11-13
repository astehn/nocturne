"""Star balance in the window: the panel's words, the log line, the unlinked
warning, and what a reopened old project shows."""
import numpy as np
from PySide6.QtWidgets import QPushButton

from nocturne.core.color import ColorSettings
from nocturne.core.image import AstroImage

from tests.core.test_star_balance import _field
from tests.ui.test_main_window import _window


def _star_window(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_image(AstroImage(_field(n_stars=150), is_linear=True,
                              metadata={"focal_length": 160.0, "pixel_size": 2.9}), "field")
    return win


def test_the_method_buttons_read_star_balance_and_photometric(qtbot, tmp_path):
    win = _star_window(qtbot, tmp_path)
    win._go_to_id("color")
    names = [b.text() for b in win._panel.method_box.findChildren(QPushButton)]
    assert names == ["Star balance", "Photometric (SPCC)"]
    assert win._panel.method_box.currentText() == "Star balance"
    assert win._panel.commit_option().method == "star"


def test_applying_colour_logs_the_gains_and_star_count(qtbot, tmp_path):
    win = _star_window(qtbot, tmp_path)
    win._go_to_id("color")
    win.apply_current(ColorSettings(method="star")); qtbot.wait(50)
    line = [l for l in win.log_panel.text().splitlines() if " Color" in l]
    assert line, win.log_panel.text()
    import re
    assert re.search(r" · R \d\.\d\d · G 1\.00 · B \d\.\d\d · \d+ stars", line[-1]), line[-1]


def test_unlinked_stretch_after_star_balance_warns_it_was_discarded(qtbot, tmp_path):
    win = _star_window(qtbot, tmp_path)
    win._go_to_id("color")
    win.apply_current(ColorSettings(method="star")); qtbot.wait(50)
    assert win.project.entries()[-1][1].ran == "star", "fixture: star balance ran"
    shown = []
    win._show_notice = shown.append
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.24, "linked": False}); qtbot.wait(50)
    assert shown and "star balance" in shown[-1], shown
    assert shown[-1] == "Unlinked stretch: the colour calibration (star balance) was discarded."


def test_no_warning_when_colour_fell_back_to_sky(qtbot, tmp_path):
    win = _star_window(qtbot, tmp_path)
    win._go_to_id("color")
    win.project.record_precomputed("Color", {"method": "star", "ran": "sky"},
                                   win.project.current())
    assert win._spcc_was_applied() is False


def test_an_old_sky_project_opens_on_color_showing_star_balance_nothing_pending(
        qtbot, tmp_path):
    win = _star_window(qtbot, tmp_path)
    win.project.record_precomputed("Color", {"neutralize_background": True,
                                             "remove_green": False, "method": "sky"},
                                   win.project.current())
    win._go_to_id("color")
    assert win._panel.method_box.currentText() == "Star balance"
    assert win._controls_match_commit("color") is True
    assert win._has_pending() is False


def test_busy_labels(qtbot, tmp_path):
    win = _star_window(qtbot, tmp_path)
    labels = {}
    for m in ("star", "photometric"):
        labels[m] = win._busy_label_for("color", ColorSettings(method=m), win.project.current())
    assert labels["star"] == "Balancing colour…"


def test_the_color_help_teaches_star_balance():
    from nocturne.ui import help_content as h
    body = h.topic("color").body
    assert "Star balance" in body
    assert "Sky balance</b> (the default)" not in body


def test_a_recorded_dict_that_ran_star_balance_counts_as_calibrated(qtbot, tmp_path):
    """A reopened project / Auto Enhance records the serialized dict, whose
    "ran" key _committed_option must not strip for Colour."""
    win = _star_window(qtbot, tmp_path)
    for rec, name in (({"method": "star", "ran": "star", "version": 1}, "star balance"),
                      ({"method": "star", "ran": "sky", "version": 1}, None),
                      ({"method": "photometric", "ran": "photometric",
                        "fell_back": False}, "SPCC")):
        win.project.record_precomputed("Color", rec, win.project.current())
        assert win._colour_calibration_name() == name, rec
