"""A preset's (and Auto Enhance's) log line for a step says what a manual
Apply of the same option says, plus the run's suffix.

His log of 2026-10-14: the hand-applied Narrowband on M 8 read
"Narrowband (HOO (StarNet2))" and Starless Levels "(black 0.00 / white 0.92
(StarNet2))"; the same steps from a preset read "Narrowband (StarNet2)" and
"Starless Levels (StarNet2)". The run mapped names back to stages through the
stepper's STEP_NAME, which has no tool steps, and the tools formatted their own
lines inline — two formatters that had drifted.
"""
import numpy as np
import pytest
pytest.importorskip("PySide6")

from nocturne.core.auto_enhance import AutoRun
from nocturne.core.image import AstroImage
from nocturne.recipe import deserialize_option, serialize_option
from tests.ui.test_main_window import _make_fits
from tests.ui.test_preset_apply import _win

SUFFIX = " — Preset (Lagoon HOO)"


def _open(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    return win


def _body(win) -> str:
    """The last log line without its time stamp."""
    return win.log_panel.entries()[-1].split(" ", 1)[1]


def _last(win) -> str:
    """The last line without its Δ, which only a manual Apply measures."""
    return _body(win).split(" · Δ")[0]


def _run_line(win, stage, name, option, engine) -> str:
    img = win.project.current().copy()
    run = AutoRun([(name, serialize_option(stage, option), img)], [], [engine],
                  stages=(stage,))
    win._record_auto_run(run, "Preset (Lagoon HOO)")
    return _body(win)


def _layers(win):
    cur = win.project.current()
    stars = AstroImage(np.zeros_like(cur.data), is_linear=cur.is_linear,
                       metadata=dict(cur.metadata))
    return cur, stars


# Each driver applies by hand with the splitter state of `tag`: "StarNet2", or
# None for a machine with no star tool. It returns what a run of the same step
# would record: (stage, name, option, the engine tag its step reports).

def _narrowband(win, tag):
    from nocturne.core.narrowband import NarrowbandParams
    cur = win.project.current()
    if tag:
        win._remember_split(cur, cur, cur, tag)
    # With no tool the dialog renders the whole image and publishes no split.
    opt = NarrowbandParams(palette="HOO")
    win._apply_narrowband(cur.copy(), opt)
    return "narrowband", "Narrowband", opt, tag or "free"


def _starless_levels(win, tag):
    win._starless_levels_path = tag or "free"
    win._apply_starless_levels(win.project.current().copy(), (0.0, 0.92))
    return "starless_levels", "Starless Levels", (0.0, 0.92), tag or "free"


def _color_balance(win, tag):
    cur = win.project.current()
    win._remember_split(cur, cur, cur, tag or "free")
    opt = deserialize_option("color_balance", {"midtones": [0.1, 0.0, -0.05]})
    win._apply_color_balance(cur.copy(), opt)
    return "color_balance", "Colour Balance", opt, tag or "free"


def _star_spikes(win, tag):
    opt = {"length": 0.5, "count": 4, "angle": 45.0, "intensity": 0.6,
           "variation": 0.2, "colour": 0.5}
    win._apply_star_spikes(win.project.current().copy(), opt)
    return "star_spikes", "Star Spikes", opt, None


def _tint(win, tag):
    win._apply_tint_step(0.10, -0.05)
    return "tint", "Colour Tint", (0.10, -0.05), None


def _remove_green(win, tag):
    win._remove_green(0.75)
    return "remove_green", "De-green Sky", 0.75, None


def _green_fringe(win, tag):
    cur, stars = _layers(win)
    win._fringe_ready = True
    # No tool: the panel's own mask layers (kind "mask"), as _fringe_split makes.
    if tag:
        win._fringe_layers = ("sig", "split", cur, stars, tag)
    else:
        from nocturne.core.starless import star_mask
        from nocturne.steps.green_fringe import FRINGE_MASK_SCALE
        win._fringe_layers = ("sig", "mask", cur, star_mask(cur, FRINGE_MASK_SCALE), "")
    win._apply_green_fringe(1.0)
    return "green_fringe", "De-green Stars", 1.0, tag or "free"


def _star_reduction(win, tag):
    cur, stars = _layers(win)
    win._sr_ready = True
    win._sr_layers = ("sig", cur, stars, tag or "free")
    win._apply_star_reduction(0.20)
    return "star_reduction", "Star Reduction", 0.20, tag or "free"


def _star_colour_tap(win, tag):
    cur, stars = _layers(win)
    win._split_tagged = lambda img: (img, stars, tag or "free")
    win._enhance("Star Colour")
    return "enhance", "Star Colour", "", tag or "free"


def _vibrance_tap(win, tag):
    win._enhance("Vibrance")
    return "enhance", "Vibrance", "", None


MANUAL = [_narrowband, _starless_levels, _color_balance, _star_spikes, _tint,
          _remove_green, _green_fringe, _star_reduction, _star_colour_tap, _vibrance_tap]


@pytest.mark.parametrize("tag", ["StarNet2", None], ids=["starnet2", "no-tool"])
@pytest.mark.parametrize("manual", MANUAL, ids=lambda f: f.__name__.strip("_"))
def test_a_run_logs_what_a_manual_apply_logs(qtbot, tmp_path, manual, tag):
    win = _open(qtbot, tmp_path)
    n = len(win.log_panel.entries())
    stage, name, option, engine = manual(win, tag)
    assert len(win.log_panel.entries()) == n + 1, "the manual apply did not log"
    by_hand = _last(win)
    assert by_hand.startswith(name), by_hand
    assert _run_line(win, stage, name, option, engine) == by_hand + SUFFIX


@pytest.mark.parametrize("manual, words", [
    (_narrowband, "Narrowband (HOO)"),
    (_green_fringe, "De-green Stars (on (star mask))"),
    (_starless_levels, "Starless Levels (black 0.00 / white 0.92 (built-in))"),
    (_star_reduction, "Star Reduction (0.20 (built-in))"),
], ids=["narrowband", "green_fringe", "starless_levels", "star_reduction"])
def test_with_no_star_tool_the_line_says_what_ran(qtbot, tmp_path, manual, words):
    """Narrowband with no splitter renders the whole image — nothing split, so
    no engine; De-green Stars works in a star mask, and says so on both paths."""
    win = _open(qtbot, tmp_path)
    stage, name, option, engine = manual(win, None)
    assert _last(win) == words
    assert _run_line(win, stage, name, option, engine) == words + SUFFIX


@pytest.mark.parametrize("tag", ["StarNet2", "free"])
def test_saturation_run_matches_the_manual_words(qtbot, tmp_path, tag):
    """The manual Apply needs a ready nebula boost; its line is _sat_log_option."""
    win = _open(qtbot, tmp_path)
    cur, stars = _layers(win)
    win._sat_layers = (win._sr_sig(cur), cur, stars, tag)
    by_hand = "Saturation (" + win._sat_log_option(0.50, 0.20) + ")"
    assert _run_line(win, "saturation", "Saturation", (0.50, 0.20), tag) \
        == by_hand + SUFFIX


def test_the_lines_from_his_log_carry_their_values(qtbot, tmp_path):
    """The exact words of his manual M 8 applies, now from a preset run."""
    win = _open(qtbot, tmp_path)
    from nocturne.core.narrowband import NarrowbandParams
    assert _run_line(win, "narrowband", "Narrowband", NarrowbandParams(palette="HOO"),
                     "StarNet2") == "Narrowband (HOO (StarNet2))" + SUFFIX
    assert _run_line(win, "starless_levels", "Starless Levels", (0.0, 0.92),
                     "StarNet2") == ("Starless Levels (black 0.00 / white 0.92 "
                                     "(StarNet2))" + SUFFIX)


def test_a_real_run_carries_its_stage_ids(tmp_path):
    from nocturne.core.auto_enhance import run_auto_plan
    from nocturne.settings import Settings
    a = np.full((16, 16, 3), 0.3, np.float32)
    base = AstroImage(a, is_linear=False, metadata={})
    run = run_auto_plan(base, [("starless_levels", (0.0, 0.9)), ("enhance", "Vibrance")],
                        Settings(), levels_auto=False)
    assert run.stages == ("starless_levels", "enhance")


def test_the_preset_summary_does_not_report_starnet2_as_a_fallback(qtbot, tmp_path, monkeypatch):
    """His summary said the star steps "used Nocturne (free star split)" under
    lines saying StarNet2 ran. The summary now asks the same resolver, and
    StarNet2 is not a substitute."""
    from tests.fake_tool import fake_tool
    from tests.ui.test_preset_apply import STEPS, _box, _choose, _setup
    from nocturne.tools.starnet import StarNet

    def split(self, img, runner=None):
        return img, AstroImage(np.zeros_like(img.data), is_linear=img.is_linear,
                               metadata=dict(img.metadata))
    monkeypatch.setattr(StarNet, "remove_stars", split)
    steps = STEPS + [{"stage": "star_reduction", "option": 0.2},
                     {"stage": "starless_levels", "option": [0.0, 0.92]}]
    win, p = _setup(qtbot, tmp_path, steps=steps)
    win.settings.starnet_path = str(fake_tool(tmp_path / "starnet2"))
    _choose(win, p); _box(win); win._apply_crop()
    out = win.output_panel.toPlainText()
    # StarNet2 is a legitimate choice: not reported as a substitute, and no
    # nag about RC-Astro (ruling 2026-10-15). Each step's line names it.
    assert "used" not in out and "RC-Astro" not in out, out
    assert "free star split" not in out, out
    log = [e.split(" ", 1)[1] for e in win.log_panel.entries()]
    assert "Star Reduction (0.20 (StarNet2)) — Preset (M 8)" in log, log
    assert ("Starless Levels (black 0.00 / white 0.92 (StarNet2)) — Preset (M 8)"
            in log), log


def test_the_preset_summary_reports_the_built_in_split_as_a_fallback(qtbot, tmp_path):
    from tests.ui.test_preset_apply import STEPS, _box, _choose, _setup
    steps = STEPS + [{"stage": "star_reduction", "option": 0.2},
                     {"stage": "starless_levels", "option": [0.0, 0.92]}]
    win, p = _setup(qtbot, tmp_path, steps=steps)
    _choose(win, p); _box(win); win._apply_crop()
    out = win.output_panel.toPlainText()
    assert ("Star Reduction and Starless Levels used Nocturne (free star split): "
            "no star tool set up (StarXTerminator or StarNet2).") in out, out


def test_the_preset_summary_names_no_splitter_for_steps_that_split_nothing(qtbot, tmp_path):
    """Saturation with no nebula boost and Star Reduction at 0 separate no
    stars, so the summary must not say they "used Nocturne (free star split)",
    nor suggest a better splitter for them (2026-10-15)."""
    from tests.ui.test_preset_apply import STEPS, _box, _choose, _setup
    steps = STEPS + [{"stage": "saturation", "option": [0.6, 0.0]},
                     {"stage": "star_reduction", "option": 0.0}]
    win, p = _setup(qtbot, tmp_path, steps=steps)
    _choose(win, p); _box(win); win._apply_crop()
    out = win.output_panel.toPlainText()
    assert "Applied preset" in out, out
    assert "used" not in out and "free star split" not in out, out
    assert "cleaner stars" not in out, out


def test_the_preset_summary_still_names_the_split_when_one_ran(qtbot, tmp_path):
    from tests.ui.test_preset_apply import STEPS, _box, _choose, _setup
    steps = STEPS + [{"stage": "saturation", "option": [0.6, 0.3]},
                     {"stage": "star_reduction", "option": 0.0}]
    win, p = _setup(qtbot, tmp_path, steps=steps)
    _choose(win, p); _box(win); win._apply_crop()
    out = win.output_panel.toPlainText()
    assert ("Saturation used Nocturne (free star split): "
            "no star tool set up (StarXTerminator or StarNet2).") in out, out
    assert "cleaner stars" in out, out
