"""A step with a choice of engine has to say which one it used.

2026-09-22. Andreas cleared RC-Astro to exercise the StarNet2 path, watched
Deconvolution finish instantly, and concluded the star separation had fallen
back to the free splitter. It had not — Deconvolution has no splitter at all.
Elapsed time was the only signal the app gave him about which path ran, and it
pointed at the wrong step.

`_split_tagged` already computed "StarX" / "StarNet2" / "free" at the moment the
choice is made, and three surfaces showed it. These tests push the same answer
into every step that has a choice, INCLUDING the RC-Astro-or-built-in axis that
misled him, and pin that it is recorded where the choice happens rather than
re-derived from settings afterwards.
"""
import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.steps.star_split import splitter_name


def _img(h=24, w=24):
    a = np.full((h, w, 3), 0.2, np.float32)
    a[12, 12] = 0.9
    return AstroImage(a, is_linear=False, metadata={"OBJECT": "M 42"})


class _FakeSplitter:
    """Stands in for RCAstro or StarNet — both expose remove_stars."""

    def __init__(self, name):
        self.__class__ = type(name, (_FakeSplitter,), {})
        self._n = name

    def remove_stars(self, img, runner=None):
        z = AstroImage(np.zeros_like(img.data), is_linear=img.is_linear,
                       metadata=dict(img.metadata))
        return img, z


def test_the_three_engine_names_match_the_ones_already_in_use():
    """`_split_tagged` has said "StarX" / "StarNet2" / "free" since 2026-09-18
    and Saturation's log line prints it. A second vocabulary for the same three
    things would make two log lines about one split disagree."""
    from nocturne.tools.rcastro import RCAstro
    from nocturne.tools.starnet import StarNet
    assert splitter_name(RCAstro("/x")) == "StarX"
    assert splitter_name(StarNet("/x")) == "StarNet2"
    assert splitter_name(None) == "free"


@pytest.mark.parametrize("build,option", [
    (lambda sp: __import__("nocturne.steps.star_reduction",
                           fromlist=["x"]).StarReductionStep(sp), 0.5),
    (lambda sp: __import__("nocturne.steps.color_balance_step",
                           fromlist=["x"]).ColorBalanceStep(sp), None),
    (lambda sp: __import__("nocturne.steps.saturation_step",
                           fromlist=["x"]).SaturationStep(sp), (0.5, 0.4)),
    (lambda sp: __import__("nocturne.steps.green_fringe",
                           fromlist=["x"]).GreenFringeStep(sp), 0.5),
])
@pytest.mark.parametrize("cls,expected", [
    ("RCAstro", "StarX"), ("StarNet", "StarNet2"), (None, "free")])
def test_a_splitter_step_records_the_engine_it_used(build, option, cls, expected):
    """The first version of this never called apply(). It constructed a step and
    asserted `last_engine is None` — the CLASS DEFAULT — so replacing every
    `self.last_engine = ...` with `pass` left it passing. Found by an
    adversarial review after the branch was called finished.

    Parametrised over the engine as well as the step, because a fixture that
    only ever sees one splitter cannot tell "records what it used" from
    "records a constant".
    """
    splitter = _FakeSplitter(cls) if cls else None
    step = build(splitter)
    assert step.last_engine is None, "nothing has run yet"
    step.apply(_img(), step.default_option() if option is None else option)
    assert step.last_engine == expected


def test_deconvolution_records_which_of_its_two_paths_ran():
    """THE one that misled him. Deconvolution never splits stars — it is
    BlurXTerminator or an in-process unsharp mask, and nothing said which."""
    from nocturne.steps.deconvolution_step import DeconvolutionStep
    free = DeconvolutionStep(None)
    free.apply(_img(), "medium")
    assert free.last_engine == "free"


def test_deconvolution_names_blurx_not_starx():
    """RC-Astro is three tools. A Deconvolution line reading "(StarX)" would
    name the wrong one, which is worse than naming none — and this step is
    already the one people misread. Asserted through behaviour, because a
    source scan also matches the word in a comment explaining the distinction.
    """
    from nocturne.steps.deconvolution_step import DeconvolutionStep

    class _FakeRC:
        def deconvolve(self, img, *, sharpen_stars, sharpen_nonstellar, runner=None):
            return img

    step = DeconvolutionStep(_FakeRC())
    step.apply(_img(), "medium")
    assert step.last_engine == "BlurX"


def test_the_log_line_reports_the_STEP_not_the_current_settings(qtbot, tmp_path):
    """Read off the step, never re-derived at log time.

    Settings can change while a step is in flight — a GraXpert denoise takes
    minutes — so asking `rcastro_valid` here would report a choice that was
    never made. This drives them APART on purpose: the settings say RC-Astro,
    the step says it ran StarNet2, and the line must say StarNet2.

    Behavioural rather than a source scan. Scanning `_log_step` for
    "rcastro_valid" also matches the docstring explaining why it must not be
    there — which is how the first version of this test passed for the wrong
    reason and then failed on a comment.
    """
    import numpy as np
    from nocturne.settings import Settings
    from nocturne.ui.main_window import MainWindow

    win = MainWindow(settings_path=str(tmp_path / "s.json"))
    qtbot.addWidget(win)
    win.settings = Settings(rcastro_path="/pretend/rc-astro")

    class _Ran:
        last_engine = "StarNet2"

    img = _img()
    win._log_step("star_reduction", "medium", img, img, _Ran())
    line = win.log_panel.entries()[-1] if hasattr(win.log_panel, "entries") \
        else win.log_panel.toPlainText().splitlines()[-1]
    assert "StarNet2" in line, line
    assert "StarX" not in line, line


def test_noise_reduction_records_what_RAN_not_what_was_asked_for():
    """The option is a preference. With GraXpert installed and RC-Astro absent
    it says "rcastro" and GraXpert runs anyway — the log line used to print the
    preference, so it named an engine that never ran. That exact mismatch had
    already caused one bug (_busy_label_for's missing GraXpert warning)."""
    from nocturne.steps.noise_sharpen import NoiseSharpenStep

    class _FakeGX:
        def denoise(self, img, level, runner=None):
            return img

    step = NoiseSharpenStep(None, _FakeGX())          # asked for RC-Astro...
    step.apply(_img(), {"engine": "rcastro", "level": "medium"})
    assert step.last_engine == "GraXpert", "...but GraXpert is what ran"

    bare = NoiseSharpenStep(None, None)
    bare.apply(_img(), {"engine": "rcastro", "level": "medium"})
    assert bare.last_engine == "free"


def test_the_rendered_lines_read_correctly(qtbot, tmp_path):
    """Rendered, not reasoned about. The first version of this produced
    "Noise Reduction (medium (rcastro) (GraXpert))" — the option's PREFERENCE
    and the engine that ran, side by side, disagreeing — and
    "Deconvolution (medium (free))", which names a price rather than a method.
    Neither was visible from the code; both were obvious in one render."""
    from nocturne.ui.main_window import MainWindow

    win = MainWindow(settings_path=str(tmp_path / "s.json"))
    qtbot.addWidget(win)
    img = _img()
    cases = [
        ("star_reduction", "medium", "StarNet2", "Star Reduction (medium (StarNet2))"),
        ("deconvolution", "medium", "free", "Deconvolution (medium (built-in))"),
        ("deconvolution", "medium", "BlurX", "Deconvolution (medium (BlurX))"),
        ({}, None, None, None),
    ]
    for sid, opt, eng, expected in cases:
        if expected is None:
            continue
        win._log_step(sid, opt, img, img, type("S", (), {"last_engine": eng})())
        assert expected in win.log_panel.toPlainText().splitlines()[-1]

    # The preference must not appear beside what ran.
    win._log_step("noise_sharpen", {"engine": "rcastro", "level": "medium"},
                  img, img, type("S", (), {"last_engine": "GraXpert"})())
    line = win.log_panel.toPlainText().splitlines()[-1]
    assert "Noise Reduction (medium (GraXpert))" in line, line
    assert "rcastro" not in line, line

    # A step with no choice is untouched.
    win._log_step("stretch", "medium", img, img, type("S", (), {"last_engine": None})())
    assert win.log_panel.toPlainText().splitlines()[-1].count("(") == 1


def test_the_dialog_driven_tools_name_the_engine_too(qtbot, tmp_path):
    """Narrowband and Colour Balance run no Step, so they have no last_engine.
    They publish their tag into the shared split cache and the line reads it
    back — still the value recorded where the choice was made."""
    from nocturne.ui.main_window import MainWindow

    win = MainWindow(settings_path=str(tmp_path / "s.json"))
    qtbot.addWidget(win)
    img = _img()

    assert win._split_engine_for(img) == "", "nothing has split yet"

    win._remember_split(img, img, img, "StarNet2")
    assert win._split_engine_for(img) == " (StarNet2)"

    win._remember_split(img, img, img, "free")
    assert win._split_engine_for(img) == " (built-in)", \
        "the log is read by a person; 'free' names a price, not a method"


def test_a_tool_handed_a_cached_split_reports_no_engine_of_its_own(qtbot, tmp_path):
    """An untagged cache entry means a surface published a split without saying
    which tool made it. "" is the honest answer — the same rule that keeps
    Saturation silent at neb 0.00, where nothing separated at all."""
    from nocturne.ui.main_window import MainWindow

    win = MainWindow(settings_path=str(tmp_path / "s.json"))
    qtbot.addWidget(win)
    img = _img()
    win._remember_split(img, img, img)          # no tag
    assert win._split_engine_for(img) == ""
