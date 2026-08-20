"""The large curve editor.

Exists because the inline one is 336 x 240 in the real app and the right pane is
a fixed 400 px, so it cannot be made wider — Andreas: "small and fiddly ...
difficult to see and control what you are actually doing."
"""
import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.core.curves import apply_curve  # noqa: E402
from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.ui.curves_dialog import PRESETS, CurvesDialog, _downscale  # noqa: E402


def _base(h=400, w=600):
    rng = np.random.default_rng(0)
    a = (rng.random((h, w, 3)).astype(np.float32) * 0.3 + 0.12)
    a[:20] = 0.85                       # something bright, so presets have a top end
    return AstroImage(np.clip(a, 0, 1), is_linear=False, metadata={})


def test_the_preview_equals_what_apply_commits(qtbot):
    """The project's central rule. compose() is the ONE path, so a preview can
    never show something Apply would not produce."""
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    dlg.editor.set_points([(0.0, 0.0), (0.4, 0.28), (1.0, 1.0)])
    committed = []
    dlg._on_apply = committed.append
    shown = dlg.compose(dlg._base)
    dlg._apply()
    assert committed, "Apply did not hand the points back"
    assert np.array_equal(apply_curve(dlg._base, committed[0]).data, shown.data)


def test_every_preset_reaches_the_editor(qtbot):
    """Buttons wired to nothing are a classic silent failure — the curve simply
    does not move and the user assumes the preset does nothing."""
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    for label, _fn in PRESETS:
        dlg.editor.set_points([(0.0, 0.0), (1.0, 1.0)])
        dlg.preset_buttons[label].click()
        pts = dlg.points()
        assert pts != [(0.0, 0.0), (1.0, 1.0)], f"{label} left the curve unchanged"


def test_presets_are_measured_from_the_full_image_not_the_preview(qtbot):
    """The presets read percentiles. A decimated copy has different statistics,
    so a preset computed from the preview would commit a curve the user never
    saw derived."""
    big = _base(h=1200, w=1600)
    dlg = CurvesDialog(big); qtbot.addWidget(dlg)
    assert dlg._small.data.shape != big.data.shape, "fixture too small to decimate"
    from nocturne.core.curves import lift_faint_points
    dlg.preset_buttons["Lift faint detail"].click()
    assert dlg.points() == lift_faint_points(big.data)


def test_reset_returns_the_identity_curve(qtbot):
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    dlg.preset_buttons["Add contrast"].click()
    assert dlg.points() != [(0.0, 0.0), (1.0, 1.0)]
    dlg.reset_btn.click()
    assert dlg.points() == [(0.0, 0.0), (1.0, 1.0)]


def test_it_opens_on_the_curve_the_inline_editor_already_had(qtbot):
    """Two surfaces, one state. Opening the dialog must not silently discard a
    curve the user had already shaped in the pane."""
    pts = [(0.0, 0.0), (0.3, 0.42), (1.0, 1.0)]
    dlg = CurvesDialog(_base(), points=pts); qtbot.addWidget(dlg)
    assert dlg.points() == pts


def test_the_preview_is_area_averaged_not_strided(qtbot):
    """Striding throws stars away: measured on three hundred synthetic stars, a
    strided preview lost two hundred and fifty-three of them. A curves preview
    that loses the stars is showing the wrong picture.

    The stars are placed OFF the stride phase deliberately. A first version put
    them every 7 px against a stride of 4, which by coincidence sampled about
    the same FRACTION of stars as of pixels — so the mean barely moved and the
    test passed with striding in place. Verified by mutation: at this offset a
    strided preview contains no stars at all.
    """
    a = np.zeros((400, 400, 3), np.float32)
    a[2::4, 2::4] = 1.0                    # stride 4 samples 0,4,8… — never these
    img = AstroImage(a, is_linear=False, metadata={})
    small = _downscale(img, max_edge=100)  # 400 // 100 -> step 4
    assert small.data.shape[0] < 400
    assert small.data.mean() > 0, "every star was thrown away — this is striding"
    assert abs(small.data.mean() - a.mean()) < a.mean() * 0.1, (
        f"flux not preserved: {small.data.mean():.5f} vs {a.mean():.5f}")


def test_the_editor_in_the_dialog_is_big(qtbot):
    """The entire point of the dialog. 336 px inline; this must be far more."""
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    assert dlg.editor.minimumWidth() >= 500, dlg.editor.minimumWidth()
    assert dlg.editor.minimumHeight() >= 500, dlg.editor.minimumHeight()
