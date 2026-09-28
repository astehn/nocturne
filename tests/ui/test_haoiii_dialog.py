import os
import time

import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QColor  # noqa: E402
from nocturne.settings import Settings  # noqa: E402
from nocturne.stacking.grade import FrameStats  # noqa: E402
from nocturne.ui.frame_browser import COL_TIME, COL_VERDICT, FrameBrowser  # noqa: E402
from nocturne.ui.haoiii_dialog import HaOIIIDialog  # noqa: E402


class _FakeResult:
    frame_count, rejected, output_path, image = 4, [], "/x/m.fits", object()


def _stats(path, score, included=True):
    return FrameStats(path, 100, 3.0, 0.02, score, included)


def test_grading_fills_table(qtbot, tmp_path):
    (tmp_path / "a.fit").write_text("x")
    (tmp_path / "b.fit").write_text("x")
    dlg = HaOIIIDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, **kw: [
        _stats(str(tmp_path / "a.fit"), 0.4, included=False),
        _stats(str(tmp_path / "b.fit"), 0.9, included=True),
    ]
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.browser.row_count() == 2, timeout=2000)


def test_extract_hands_off_master(qtbot, tmp_path):
    for name in ("low.fit", "mid.fit", "high.fit"):
        (tmp_path / name).write_text("x")
    low, mid, high = (str(tmp_path / n) for n in ("low.fit", "mid.fit", "high.fit"))
    captured, got = {}, {}
    dlg = HaOIIIDialog(Settings(), on_master=lambda img: got.setdefault("img", img))
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, **kw: [
        _stats(low, 0.4), _stats(mid, 0.6), _stats(high, 0.9)]

    class _Img:
        pass

    def fake_extract(opts, on_progress=None):
        captured["opts"] = opts
        if on_progress:
            on_progress(1, 1, "stacking Ha")
        from nocturne.stacking.haoiii import HaOIIIResult
        return HaOIIIResult(_Img(), opts.include, [], len(opts.include), 30.0, opts.output_path)

    dlg._extract_runner = fake_extract
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.browser.row_count() == 3, timeout=2000)
    dlg.output_edit.setText(str(tmp_path / "HaOIII_master.fits"))
    dlg.run()
    qtbot.waitUntil(lambda: "opts" in captured, timeout=2000)
    assert captured["opts"].include[0] == high      # best-first
    qtbot.waitUntil(lambda: "img" in got, timeout=2000)


def test_run_requires_output(qtbot):
    dlg = HaOIIIDialog(Settings())
    qtbot.addWidget(dlg)
    dlg.run()
    assert "output" in dlg.status.text().lower()


def test_the_dialog_says_what_it_takes_and_what_the_master_is_for(qtbot):
    """Andreas commissioned this tool and could not say what subs it takes or
    what to do with its output. The help topic explains all of it, well — it
    just never reaches the person standing in front of the dialog, which had
    zero tooltips and zero descriptive text against Stack's six and one.
    """
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    blurb = d.blurb.text().lower()
    assert "raw" in blurb, "it must say the subs have to be raw/un-debayered"
    assert "narrowband" in blurb, "and what you do with the master afterwards"
    tips = [w.toolTip() for w in (d.folder_edit, d.output_edit,
                                  d.sigma_radio, d.kappa_box)]
    assert all(tips), f"every control needs a tooltip, got {tips}"


def test_strictness_rethresholds_without_regrading(qtbot):
    """Same control Stack has, and the same cheap mechanism: judge() re-decides
    which frames are in from statistics already measured. Grading a folder again
    just to move a threshold would be minutes of work for a dropdown."""
    from nocturne.stacking.grade import FrameStats
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    # A tight cluster with a soft tail: 3.5 and 3.75 sit inside the relaxed gate
    # and outside the strict one, so the three settings must give three answers.
    fwhms = [3.0, 3.3, 2.7, 3.1, 2.9, 3.0, 3.2, 3.5, 3.75, 4.1]
    stats = [FrameStats(path=f"/x/{i}.fit", star_count=100, fwhm=f,
                        background=0.10, score=1.0, included=True)
             for i, f in enumerate(fwhms)]
    regraded = {"n": 0}
    d._grade_runner = lambda *a, **kw: regraded.__setitem__("n", regraded["n"] + 1)
    d._on_graded(stats)

    def kept():
        return sum(1 for r in range(len(d.browser.frames())) if d.browser.is_checked(r))

    d.strictness_box.setCurrentText("Strict")
    strict = kept()
    d.strictness_box.setCurrentText("Normal")
    normal = kept()
    d.strictness_box.setCurrentText("Relaxed")
    relaxed = kept()
    assert (relaxed, normal, strict) == (10, 9, 8)
    assert regraded["n"] == 0, "changing the dropdown must not re-grade the folder"


def test_a_frame_you_ticked_yourself_survives_a_strictness_change(qtbot):
    """Overriding the grader is the whole point of the checkboxes. Stack keeps
    manual ticks when the threshold moves; Ha/OIII would have silently undone them."""
    from nocturne.stacking.grade import FrameStats
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    fwhms = [3.0, 3.3, 2.7, 3.1, 2.9, 3.0, 3.2, 3.5, 3.75, 4.1]
    d._on_graded([FrameStats(path=f"/x/{i}.fit", star_count=100, fwhm=f,
                             background=0.10, score=1.0, included=True)
                  for i, f in enumerate(fwhms)])
    d.browser.set_checked(0, False)                             # a good frame, dropped by hand
    d.strictness_box.setCurrentText("Relaxed")                  # would re-include it
    assert not d.browser.is_checked(0)
    assert d._stats[0].included is False, "and the stats must agree with the table"


def test_trim_is_off_by_default_and_reaches_the_extractor(qtbot, tmp_path):
    """Ha/OIII once always cropped with no say in it; now it offers the choice
    and, since 2026-09-01, defaults to keeping the frame.

    Trimming cannot be undone without re-extracting, while keeping the edges
    costs one click of Trim afterwards — so the recoverable direction is the
    default. Matches Stack, which matters: two dialogs doing the same job should
    not disagree about what happens when you touch nothing."""
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    assert not d.crop_check.isChecked(), "trimming must not be the default"
    captured = {}
    d._extract_runner = lambda opts, **kw: (captured.setdefault("opts", opts),
                                            _FakeResult())[1]
    d.output_edit.setText(str(tmp_path / "m.fits"))
    d._on_graded([_stats(f"/x/{i}.fit", 1.0) for i in range(4)])
    d.run()
    qtbot.waitUntil(lambda: "opts" in captured, timeout=3000)
    assert captured["opts"].autocrop is False


def test_strictness_moved_while_grading_is_honoured(qtbot):
    """grade() reads the dropdown when it starts, and grading a folder takes
    minutes. Move it while the measuring runs and the results used to land judged
    at the old setting, with the dropdown showing something else."""
    from nocturne.stacking.grade import FrameStats
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    fwhms = [3.0, 3.3, 2.7, 3.1, 2.9, 3.0, 3.2, 3.5, 3.75, 4.1]
    # what a "normal" grading pass would have produced, arriving late
    stats = [FrameStats(path=f"/x/{i}.fit", star_count=100, fwhm=f,
                        background=0.10, score=1.0, included=True)
             for i, f in enumerate(fwhms)]
    from nocturne.stacking.grade import judge
    judge(stats, "normal")
    assert sum(s.included for s in stats) == 9, "fixture must start at the normal verdict"

    d.strictness_box.setCurrentText("Strict")   # user changes it mid-grade
    d._on_graded(stats)                         # ... and then the results land
    kept = sum(1 for r in range(len(d.browser.frames())) if d.browser.is_checked(r))
    assert kept == 8, f"table must show the Strict verdict, showed {kept} of 10 kept"


def test_selecting_a_row_previews_that_frame(qtbot):
    """Andreas: "frame previews does not seem to work" — they did not exist here.
    Stack has had one since it was written; Ha/OIII showed the same graded subs
    next to an empty panel, which reads as broken rather than absent."""
    import numpy as np
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    asked = []
    d._preview_ctl.loader = lambda p: (asked.append(p),
                                       np.zeros((8, 8, 3), np.float32))[1]
    d._on_graded([_stats(f"/x/{i}.fit", 1.0) for i in range(3)])
    d.browser.set_current_row(1)
    qtbot.waitUntil(lambda: d.preview.has_image(), timeout=2000)
    assert asked == ["/x/1.fit"], f"previewed {asked}, wanted the selected row"


def test_the_preview_sits_beside_the_table_in_a_splitter(qtbot):
    """The empty area right of the table in the screenshot was unclaimed space.
    It belongs to the preview, and the preview takes the extra width."""
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    sp = d.browser.splitter
    assert sp.count() == 2
    assert sp.widget(0).isAncestorOf(d.browser.view)
    assert sp.widget(1).isAncestorOf(d.preview)
    assert not sp.childrenCollapsible(), "neither side may collapse to nothing"


def test_changing_strictness_does_not_disturb_the_preview(qtbot):
    """Re-thresholding rewrites every checkbox but not the frame list, so the
    preview must keep showing the row the user is on rather than reload or clear."""
    import numpy as np
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    loads = []
    d._preview_ctl.loader = lambda p: (loads.append(p),
                                       np.zeros((8, 8, 3), np.float32))[1]
    fwhms = [3.0, 3.3, 2.7, 3.1, 2.9, 3.0, 3.2, 3.5, 3.75, 4.1]
    from nocturne.stacking.grade import FrameStats
    d._on_graded([FrameStats(path=f"/x/{i}.fit", star_count=100, fwhm=f,
                             background=0.10, score=1.0, included=True)
                  for i, f in enumerate(fwhms)])
    d.browser.set_current_row(2)
    qtbot.waitUntil(lambda: d.preview.has_image(), timeout=2000)
    before = list(loads)
    d.strictness_box.setCurrentText("Strict")
    qtbot.wait(50)
    assert loads == before, f"strictness reloaded the preview: {loads[len(before):]}"
    assert d.preview.has_image(), "and it must still be showing"


def test_the_frame_list_takes_the_extra_height_not_the_blurb(qtbot):
    """Maximised, the dialog handed ~700px of slack equally to the blurb, the
    splitter and the status line: the blurb and the status line were 237px tall
    each for one line of text, and the frame list and preview were squeezed into
    238px. Only the splitter should grow."""
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    d.resize(1400, 1100)
    d.show()
    qtbot.waitUntil(lambda: d.height() > 900, timeout=2000)
    assert d.browser.height() > 0.5 * d.height(), (
        f"the frame list and preview got {d.browser.height()} of {d.height()}")
    assert d.status.height() < 80, (
        f"the one-line status label stretched to {d.status.height()}px")
    natural = d.blurb.heightForWidth(d.blurb.width())
    assert d.blurb.height() <= natural + 12, (
        f"the blurb stretched to {d.blurb.height()}px, needs {natural}px")


def test_a_rejected_frame_says_why(qtbot):
    """The master Andreas had left in his subs folder showed as a row of zeros
    with no reason given — the tool knew it was an already-stacked file and did
    not say so. Stack has carried a Verdict column all along."""
    from nocturne.stacking.grade import FrameStats
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    from nocturne.stacking.grade import REASON_NOT_RAW
    # exactly what grade_frame() returns for a master sitting in the subs folder
    stacked = FrameStats("/x/M16_314x10s.fit", 0, 0.0, 0.0, 0.0, False,
                         reason_code="not_raw", reason=REASON_NOT_RAW, error=True)
    good = _stats("/x/sub.fit", 1.0)
    d._on_graded([stacked, good])
    assert d.browser.headers()[COL_VERDICT] == "Verdict"
    assert d.browser.cell_text(0, COL_VERDICT) == REASON_NOT_RAW
    assert d.browser.cell_text(1, COL_VERDICT) == "OK"
    assert d.browser.cell_tooltip(0, COL_VERDICT), "long verdicts must be readable on hover"


def test_a_rejected_row_is_dimmed_and_a_warned_row_is_amber(qtbot):
    """Colour is what makes a long list scannable — without it you have to read
    every Verdict cell to find the frames that were dropped. Let the real grader
    decide the verdicts rather than setting them by hand: judge() re-derives
    them, so a hand-set reason would just be overwritten and prove nothing."""
    from nocturne.stacking.grade import FrameStats
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    stats = [FrameStats(f"/x/{i}.fit", 100, 3.0, 0.10, 1.0, True) for i in range(8)]
    stats.append(FrameStats("/x/bright.fit", 100, 3.0, 0.40, 0.8, True))  # bright sky
    stats.append(FrameStats("/x/clouds.fit", 5, 3.0, 0.10, 0.1, True))    # few stars
    d._on_graded(stats)
    assert stats[9].reason and stats[8].warning, "fixture must produce both verdicts"

    from nocturne.ui import theme
    def colour(row):
        return d.browser.cell_colour(row, COL_TIME)
    assert colour(9) == QColor(theme.TEXT_FAINT).name(), "rejected row must be dimmed"
    assert colour(8) == QColor(theme.WARNING).name(), "warned row must be amber"
    assert colour(0) == QColor(theme.TEXT).name(), "an ordinary row keeps normal text"


def test_the_verdict_follows_the_strictness_you_choose(qtbot):
    """Moving Strictness re-decides every frame. A checkbox that flips while the
    Verdict beside it still reads OK is worse than no verdict at all."""
    from nocturne.stacking.grade import FrameStats
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    fwhms = [3.0, 3.3, 2.7, 3.1, 2.9, 3.0, 3.2, 3.5, 3.75, 4.1]
    d._on_graded([FrameStats(path=f"/x/{i}.fit", star_count=100, fwhm=f,
                             background=0.10, score=1.0, included=True)
                  for i, f in enumerate(fwhms)])
    d.strictness_box.setCurrentText("Strict")
    for row in range(len(d.browser.frames())):
        ticked = d.browser.is_checked(row)
        verdict = d.browser.cell_text(row, COL_VERDICT)
        assert ticked == (verdict == "OK"), (
            f"row {row}: ticked={ticked} but verdict says {verdict!r}")


def test_separate_channel_files_are_opt_in(qtbot, tmp_path):
    """Off by default: most people want the master and nothing else, and these
    land in the folder the grader reads."""
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    assert not d.channels_check.isChecked()
    assert d.channels_check.toolTip()
    captured = {}
    d._extract_runner = lambda opts, **kw: (captured.setdefault("opts", opts),
                                            _FakeResult())[1]
    d.output_edit.setText(str(tmp_path / "m.fits"))
    d._on_graded([_stats(f"/x/{i}.fit", 1.0) for i in range(4)])
    d.channels_check.setChecked(True)
    d.run()
    qtbot.waitUntil(lambda: "opts" in captured, timeout=3000)
    assert captured["opts"].write_channels is True


def test_both_stackers_agree_on_the_registration_reference(qtbot):
    """Same subs, same settings, different framing — because Stack promoted the
    sharpest frame to the front and Ha/OIII sorted by score alone. Measured on
    80 real M16 subs: (3680, 1976) against (3696, 1984), and identical the
    moment Ha/OIII was handed Stack's reference. Both now use one ordering.

    The score is the wrong question for a reference: it multiplies an unbounded
    star count by bounded quality terms, so at a 2.99x star-count spread its
    correlation with FWHM inverts and it picks a soft frame to align a whole
    session to.
    """
    from nocturne.stacking.grade import FrameStats
    from nocturne.ui.stack_dialog import StackDialog

    # A session where score and sharpness disagree. The FWHM spread is kept
    # tight on purpose: an obviously soft frame is thrown out by judge() before
    # it can compete, so a fixture with one would prove nothing — the first
    # version of this test had FWHM 4.2 here and survived the mutation.
    stats = [
        FrameStats("/x/soft_but_rich.fit", 900, 2.60, 0.10, 0.99, True),
        FrameStats("/x/sharp.fit", 300, 2.10, 0.10, 0.80, True),
        FrameStats("/x/mid_a.fit", 400, 2.50, 0.10, 0.70, True),
        FrameStats("/x/mid_b.fit", 380, 2.55, 0.10, 0.60, True),
        FrameStats("/x/mid_c.fit", 360, 2.58, 0.10, 0.50, True),
    ]
    h = HaOIIIDialog(Settings()); qtbot.addWidget(h)
    h._on_graded(stats)
    s_dlg = StackDialog(Settings()); qtbot.addWidget(s_dlg)
    s_dlg._on_graded(stats)

    ha_order = h._included_best_first()
    st_order = s_dlg._included_paths_best_first()
    assert ha_order[0] == st_order[0], (
        f"Ha/OIII would align to {ha_order[0]}, Stack to {st_order[0]}")
    assert ha_order == st_order, "the two stackers must order frames identically"
    assert ha_order[0] == "/x/sharp.fit", (
        "the reference must be the sharpest frame, not the highest-scoring one")
    assert all(s.included for s in stats), (
        "every frame must survive grading, or the score-leader never competes")


def test_cancel_appears_only_while_working(qtbot):
    """A 1116-frame extract runs for a long time with no way out. Stack has had
    a Cancel button since the task controller landed; this dialog had none."""
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    d.show()
    assert not d._cancel_btn.isVisible(), "Cancel must be hidden when idle"
    d._set_busy(True)
    assert d._cancel_btn.isVisible() and d._cancel_btn.isEnabled()
    d._set_busy(False)
    assert not d._cancel_btn.isVisible()


def test_cancelling_an_extract_reports_it_and_frees_the_dialog(qtbot, tmp_path):
    """The whole point: press Cancel and the run stops, says so, and the dialog
    becomes usable again rather than staying stuck busy."""
    from nocturne.core.tasks import Cancelled, current
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    started = {}

    def slow_extract(opts, **kw):
        started["yes"] = True
        # wait on the clock, not on an iteration count: a bare loop finishes in
        # microseconds and the run is over before the test can press Cancel
        # must expire before the test's 3s waitUntil, so a failing run never
        # leaves a worker alive past teardown
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            tok = current()
            if tok is not None:
                tok.check()          # raises Cancelled once the button is hit
            time.sleep(0.01)
        raise AssertionError("was never cancelled")

    d._extract_runner = slow_extract
    d.output_edit.setText(str(tmp_path / "m.fits"))
    d._on_graded([_stats(f"/x/{i}.fit", 1.0) for i in range(4)])
    d.run()
    qtbot.waitUntil(lambda: started.get("yes"), timeout=3000)
    d._cancel_btn.click()
    qtbot.waitUntil(lambda: d.status.text() == "Cancelled.", timeout=3000)
    assert not d._busy, "the dialog must be usable again after cancelling"
    assert d._stack_btn.isEnabled()


def test_grading_is_cancellable_too(qtbot, tmp_path):
    """Grading a folder is minutes of work on its own — 366 subs took long
    enough to notice — and it ran outside any token."""
    from nocturne.core.tasks import current
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    (tmp_path / "a.fit").write_bytes(b"")      # _discover only needs the names
    (tmp_path / "b.fit").write_bytes(b"")
    seen = {}

    def slow_grade(paths, on_progress=None, **kw):
        tok = current()
        seen["token"] = tok
        # Fail INSIDE the worker rather than letting the test assert and walk
        # away: an assertion in the test body leaves this thread running, and
        # tearing the dialog down under a live worker breaks unrelated tests in
        # full-suite ordering.
        if tok is None:
            raise AssertionError("grading ran with no cancel token in scope")
        # must expire before the test's 3s waitUntil
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            tok = current()
            if tok is not None:
                tok.check()
            time.sleep(0.01)
        raise AssertionError("was never cancelled")

    d._grade_runner = slow_grade
    d.folder_edit.setText(str(tmp_path))
    d.grade()
    qtbot.waitUntil(lambda: "token" in seen, timeout=3000)
    d._cancel_btn.click()
    qtbot.waitUntil(lambda: d.status.text() == "Cancelled.", timeout=3000)


# --- Layout A and the shared browser (spec 2026-09-27 §2.1, §2.2, §2.5) ------

def test_haoiii_hosts_the_same_frame_browser_as_stack(qtbot):
    """Identity, not a copy (spec §7): the drift this exists to stop happened
    once already, when the preview lived only in Stack."""
    from PySide6.QtWidgets import QTableWidget
    from nocturne.ui.stack_dialog import StackDialog
    d = HaOIIIDialog(Settings()); qtbot.addWidget(d)
    s = StackDialog(Settings()); qtbot.addWidget(s)
    assert type(d.browser) is FrameBrowser and type(s.browser) is FrameBrowser
    assert d.findChildren(QTableWidget) == []


def test_haoiii_options_are_the_same_three_groups(qtbot):
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    frames, combine, result = d.options_band.groups
    assert [g.title.text() for g in (frames, combine, result)] == ["FRAMES", "COMBINE", "RESULT"]
    assert frames.isAncestorOf(d.strictness_box)
    assert all(combine.isAncestorOf(w) for w in (d.avg_radio, d.sigma_radio, d.kappa_box))
    assert result.isAncestorOf(d.crop_check) and result.isAncestorOf(d.channels_check)


def test_folding_one_dialog_folds_both(qtbot):
    """One remembered setting: the bands are the same control."""
    from nocturne.ui.stack_dialog import StackDialog
    settings = Settings()
    s = StackDialog(settings); qtbot.addWidget(s)
    s.options_band.set_folded(True)
    d = HaOIIIDialog(settings); qtbot.addWidget(d)
    assert d.options_band.is_folded()
    assert d.options_band.summary_label.text() == (
        "Normal selection · Sigma-clipped, medium rejection · full frame")
    d.channels_check.setChecked(True)
    assert d.options_band.summary_label.text().endswith("separate Ha and OIII files")


def test_the_app_saves_the_haoiii_fold(qtbot, tmp_path, monkeypatch):
    """HaOIIIDialog had no way to persist a setting; _open_haoiii must hand it
    the app's own save, or the fold is forgotten on the next launch."""
    from tests.ui.test_main_window import _window
    win = _window(qtbot, tmp_path)
    captured = {}

    class _Stub:
        def __init__(self, *a, **kw):
            captured.update(kw)

        def exec(self):
            return 0

    monkeypatch.setattr("nocturne.ui.haoiii_dialog.HaOIIIDialog", _Stub)
    win._open_haoiii()
    assert captured.get("on_settings_changed") == win._save_settings


def test_folding_in_haoiii_is_saved_and_folds_stack(qtbot):
    """The other direction: Ha/OIII writes the shared setting and asks the app
    to save it, so Stack opens folded too — and on the next launch."""
    from nocturne.ui.stack_dialog import StackDialog
    settings = Settings(frame_options_folded=False)
    saves = []
    d = HaOIIIDialog(settings, on_settings_changed=lambda: saves.append(
        settings.frame_options_folded))
    qtbot.addWidget(d)
    assert not d.options_band.is_folded(), "fixture must start unfolded"
    d.options_band.set_folded(True)
    assert saves == [True], f"the fold was not handed to the app's save: {saves}"
    s = StackDialog(settings); qtbot.addWidget(s)
    assert s.options_band.is_folded()


def test_a_folder_with_no_subs_forgets_the_last_grade(qtbot, tmp_path, monkeypatch):
    """As in Stack (final review I2): a folder with no subs left the last
    folder's frames listed and extractable."""
    from nocturne.ui import file_dialogs
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir()
    b.mkdir()
    ran = []
    dlg = HaOIIIDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._extract_runner = lambda *x, **k: ran.append(1)
    dlg.folder_edit.setText(str(a))
    dlg.output_edit.setText(str(b / "HaOIII_master.fits"))
    dlg._on_graded([_stats(str(a / f"{i}.fit"), 0.9) for i in range(4)])
    assert dlg.browser.row_count() == 4
    monkeypatch.setattr(file_dialogs, "choose_folder", lambda *x, **k: str(b))
    dlg._browse_folder()
    assert "No .fit subs" in dlg.status.text()
    assert dlg.browser.row_count() == 0 and dlg._stats == []
    dlg.run()
    assert ran == [] and not dlg._busy, "extracted A's frames"
    assert os.listdir(b) == []


def test_a_new_user_opens_haoiii_with_the_options_folded(qtbot):
    """Spec 2026-09-28 §6b: the band starts folded; a saved choice is kept."""
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    assert d.options_band.is_folded()
    kept = HaOIIIDialog(Settings(frame_options_folded=False))
    qtbot.addWidget(kept)
    assert not kept.options_band.is_folded()
