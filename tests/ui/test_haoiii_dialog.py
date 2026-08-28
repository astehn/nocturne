import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from nocturne.settings import Settings  # noqa: E402
from nocturne.stacking.grade import FrameStats  # noqa: E402
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
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 2, timeout=2000)


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
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 3, timeout=2000)
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
        return sum(1 for r in range(d.table.rowCount())
                   if d.table.item(r, 0).checkState() == Qt.CheckState.Checked)

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
    d.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)   # a good frame, dropped by hand
    d.strictness_box.setCurrentText("Relaxed")                  # would re-include it
    assert d.table.item(0, 0).checkState() == Qt.CheckState.Unchecked
    assert d._stats[0].included is False, "and the stats must agree with the table"


def test_trim_can_be_turned_off(qtbot, tmp_path):
    """Stack lets you keep the ragged edge; on a 2 MP sensor those pixels are
    worth having. Ha/OIII always cropped, with no say in it."""
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    assert d.crop_check.isChecked(), "trimming stays the default"
    captured = {}
    d._extract_runner = lambda opts, **kw: (captured.setdefault("opts", opts),
                                            _FakeResult())[1]
    d.output_edit.setText(str(tmp_path / "m.fits"))
    d._on_graded([_stats(f"/x/{i}.fit", 1.0) for i in range(4)])
    d.crop_check.setChecked(False)
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
    kept = sum(1 for r in range(d.table.rowCount())
               if d.table.item(r, 0).checkState() == Qt.CheckState.Checked)
    assert kept == 8, f"table must show the Strict verdict, showed {kept} of 10 kept"
