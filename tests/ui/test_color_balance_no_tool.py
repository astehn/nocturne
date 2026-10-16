"""Colour Balance with no star tool: every path does what the dialog showed.

With neither StarXTerminator nor StarNet2 the dialog adjusts the WHOLE image
(stars included) and says so — but ColorBalanceStep, which presets, recipes and
batches replay, ran the free split and screened the stars back (2026-10-15
review find). Ruling: the step follows the dialog. And a free split left in the
shared cache by Saturation must not make the dialog split either, or the
manual Apply would differ from a preset of the same options.
"""
import numpy as np
import pytest

pytest.importorskip("PySide6")

from nocturne.core.color_balance import Balance, apply_balance  # noqa: E402
from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.core.mask import range_mask  # noqa: E402
from nocturne.core.narrowband import screen  # noqa: E402
from nocturne.settings import Settings  # noqa: E402
from nocturne.steps.color_balance_step import ColorBalanceStep  # noqa: E402
from nocturne.steps.factory import make_step  # noqa: E402

OPTS = {"shadows": [0.0, 0.0, 0.0], "midtones": [0.25, 0.0, -0.2],
        "highlights": [-0.1, 0.0, 0.15], "preserve_lum": True, "strength": 1.0,
        "lo": 0.0, "hi": 1.0, "feather": 0.08, "invert": False}


def _img():
    rng = np.random.default_rng(4)
    data = np.clip(rng.normal(0.3, 0.08, (48, 48, 3)), 0, 1).astype(np.float32)
    for y, x in ((10, 10), (30, 36), (40, 8)):
        data[y - 1:y + 2, x - 1:x + 2] = (0.95, 0.9, 0.8)   # stars the free split finds
    return AstroImage(data, is_linear=False, metadata={})


def _whole(img, o=OPTS):
    b = Balance(shadows=tuple(o["shadows"]), midtones=tuple(o["midtones"]),
                highlights=tuple(o["highlights"]), preserve_lum=o["preserve_lum"],
                strength=o["strength"])
    m = range_mask(img.data.mean(axis=2), o["lo"], o["hi"], feather=o["feather"])
    return apply_balance(img, b, m).data


def test_with_no_tool_the_step_adjusts_the_whole_image():
    img = _img()
    out = make_step("color_balance", Settings()).apply(img, dict(OPTS))
    assert np.array_equal(out.data, _whole(img))


class _FakeSplitter:
    """A deterministic 'tool': half the light is stars."""
    def remove_stars(self, img, runner=None):
        sl = AstroImage(img.data * 0.5, is_linear=img.is_linear, metadata=dict(img.metadata))
        st = AstroImage(1 - (1 - img.data) / (1 - img.data * 0.5),
                        is_linear=img.is_linear, metadata=dict(img.metadata))
        return sl, st


def test_with_a_tool_the_stars_are_still_held_aside_unchanged():
    """The with-tool path, by the formula main computes: split, balance the
    starless layer in its own band, screen the untouched stars back."""
    img = _img()
    step = ColorBalanceStep(_FakeSplitter())
    out = step.apply(img, dict(OPTS))
    sl, st = _FakeSplitter().remove_stars(img)
    want = screen(_whole(sl), np.clip(st.data, 0.0, 1.0))
    assert np.array_equal(out.data, want)
    assert step.last_engine == "StarNet2"


def test_the_dialog_with_no_tool_composes_what_the_step_replays(qtbot):
    """End to end: the dialog as the window opens it with no tool and no cached
    split, a real adjustment, its full-resolution Apply vs a recipe replay."""
    from nocturne.ui.color_balance_dialog import ColorBalanceDialog
    img = _img()
    got = {}
    d = ColorBalanceDialog(Settings(), img, on_apply=lambda r, o: got.update(r=r, o=o))
    qtbot.addWidget(d)
    d.show()
    d.set_balance_for_test(tone="midtones", red=25, blue=-20)
    d._apply()
    qtbot.waitUntil(lambda: "r" in got, timeout=5000)
    replay = make_step("color_balance", Settings()).apply(img, got["o"])
    assert np.abs(got["r"].data - replay.data).max() < 1e-6


# --- the window: a cached free split must not reach the dialog ----------------

def _window_with_cached_free_split(qtbot, tmp_path, monkeypatch, *, tool):
    from tests.ui.test_main_window import _make_fits, _window
    from nocturne.ui import color_balance_dialog as cbd
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.project.run_step(make_step("stretch", win.settings), make_step("stretch", win.settings).default_option())
    cur = win.project.current()
    assert not cur.is_linear
    stars = AstroImage(np.zeros_like(cur.data), is_linear=False, metadata={})
    win._remember_split(cur, cur, stars, "free")        # as Saturation leaves it
    if tool:
        monkeypatch.setattr("nocturne.ui.main_window.preferred_splitter", lambda s: _FakeSplitter())
    seen = {}

    class Spy:
        def __init__(self, settings, base, **kw):
            seen.update(kw, base=base)
        def exec(self):
            return 0
    monkeypatch.setattr(cbd, "ColorBalanceDialog", Spy)
    win._open_color_balance()
    return win, seen


def test_no_tool_a_cached_free_split_is_not_handed_to_the_dialog(qtbot, tmp_path, monkeypatch):
    win, seen = _window_with_cached_free_split(qtbot, tmp_path, monkeypatch, tool=False)
    assert seen["starless"] is None and seen["stars"] is None


def test_with_a_tool_a_cached_tool_split_is_still_handed_over(qtbot, tmp_path, monkeypatch):
    win, seen = _window_with_cached_free_split(qtbot, tmp_path, monkeypatch, tool=True)
    # "free" is not what the tool would make, so it is not reused either...
    assert seen["starless"] is None
    # ...but a split the tool made is, unchanged from before.
    cur = win.project.current()
    sl, st = _FakeSplitter().remove_stars(cur)
    win._remember_split(cur, sl, st, "StarNet2")
    win._open_color_balance()
    assert seen["starless"] is sl and seen["stars"] is st


def test_no_tool_the_manual_line_names_no_splitter(qtbot, tmp_path):
    """A free split in the cache did not touch this Apply: no engine named."""
    from tests.ui.test_main_window import _make_fits, _window
    from nocturne.recipe import deserialize_option
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    cur = win.project.current()
    win._remember_split(cur, cur, cur, "free")
    win._apply_color_balance(cur.copy(), deserialize_option("color_balance", dict(OPTS)))
    line = win.log_panel.entries()[-1]
    assert "built-in" not in line and "free" not in line, line


def test_no_tool_even_a_tool_made_split_in_the_cache_is_not_used(qtbot, tmp_path, monkeypatch):
    """StarNet2 split this picture, then was removed from Settings: the step
    can no longer split, so the dialog must not either."""
    win, seen = _window_with_cached_free_split(qtbot, tmp_path, monkeypatch, tool=False)
    cur = win.project.current()
    sl, st = _FakeSplitter().remove_stars(cur)
    win._remember_split(cur, sl, st, "StarNet2")
    win._open_color_balance()
    assert seen["starless"] is None and seen["stars"] is None
