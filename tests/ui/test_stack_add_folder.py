"""Stack's "Add folder…" (spec 2026-09-28 §9.7): subs that live elsewhere,
listed and stacked with these. Every folder here is built under tmp_path —
never a real capture folder."""
import os
import time

import numpy as np
import pytest
from astropy.io import fits

from nocturne.core.tasks import Cancelled
from nocturne.settings import Settings
from nocturne.stacking.capture_time import from_filename, read_capture_time
from nocturne.stacking.grade import FrameStats
from nocturne.stacking.reject_move import move_to_rejected
from nocturne.ui import file_dialogs
from nocturne.ui.stack_dialog import ADD_FOLDER_TEXT, StackDialog


@pytest.fixture(autouse=True)
def stockholm(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Stockholm")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _seestar_folder(root, name, day, n=6, start=0):
    """n subs named as the Seestar names them, a minute apart from 22:30 on
    `day` (a YYYYMMDD string); the name carries the capture time."""
    folder = root / name
    folder.mkdir()
    for i in range(start, start + n):
        (folder / f"Light_SH2-108_10.0s_LP_{day}-22{30 + i:02d}00.fit").write_bytes(b"x" * (100 + i))
    return folder


def _runner(calls=None):
    """Grades by capture time; everything sharp, nothing rejected."""
    def run(paths, on_progress=None, strictness="normal"):
        if calls is not None:
            calls.append(sorted(os.path.basename(p) for p in paths))
        out = []
        for p in sorted(paths):
            s = FrameStats(p, 800, 2.5, 1000.0, 0.5, True, exposure=10.0, target="SH2-108")
            s.captured = read_capture_time(p)
            out.append(s)
        return out
    return run


def _graded(qtbot, folder, calls=None):
    d = StackDialog(Settings())
    qtbot.addWidget(d)
    d._available_height = lambda: 4000
    d.browser.preview_controller.loader = lambda p: np.zeros((8, 8, 3), np.float32)
    d._grade_runner = _runner(calls)
    d.folder_edit.setText(str(folder))
    d.grade()
    qtbot.waitUntil(lambda: not d._busy, timeout=3000)
    return d


def _add(qtbot, d, folder):
    d.add_folder(str(folder))
    qtbot.waitUntil(lambda: not d._busy, timeout=3000)


def test_the_button_waits_for_a_grade(qtbot, tmp_path):
    d = StackDialog(Settings())
    qtbot.addWidget(d)
    assert d.add_folder_btn.text() == ADD_FOLDER_TEXT and not d.add_folder_btn.isEnabled()
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    d = _graded(qtbot, a)
    assert d.add_folder_btn.isEnabled()
    d._set_busy(True)
    assert not d.add_folder_btn.isEnabled()
    d._set_busy(False)
    empty = tmp_path / "empty"
    empty.mkdir()
    d.folder_edit.setText(str(empty))
    d.grade()
    assert not d.add_folder_btn.isEnabled()


def test_browsing_for_a_folder_adds_it(qtbot, tmp_path, monkeypatch):
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    b = _seestar_folder(tmp_path, "Sh2-108 night 2", "20260926")
    d = _graded(qtbot, a)
    monkeypatch.setattr(file_dialogs, "choose_folder", lambda *x, **k: str(b))
    d.add_folder_btn.click()
    qtbot.waitUntil(lambda: not d._busy, timeout=3000)
    assert d.listed_folders() == [str(a), str(b)]


def test_an_added_folder_joins_the_list_the_nights_and_the_name(qtbot, tmp_path):
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    b = _seestar_folder(tmp_path, "Sh2-108 night 2", "20260926")
    d = _graded(qtbot, a)
    d.browser.set_checked(0, False)                 # his tick, before the add
    _add(qtbot, d, b)
    assert len(d._stats) == 12 and d._stats is d.browser.frames()
    assert d._stats[0].included is False and 0 in d.browser.user_touched
    assert [c.text().split(" · ")[0] for c in d.verdict_strip.chips] == ["21 Sep Good",
                                                                         "26 Sep Good"]
    assert d.status.text() == "Keeping 11 of 12 frames — 2 of 2 minutes of light."
    assert d.name_edit.text() == "SH2-108_11x10s_2min.fits"
    assert d.save_to_edit.text() == str(a), "Save to must stay the subs folder"


def test_a_folder_already_listed_is_not_added_again(qtbot, tmp_path):
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    b = _seestar_folder(tmp_path, "b", "20260926")
    calls = []
    d = _graded(qtbot, a, calls)
    _add(qtbot, d, b)
    assert len(calls) == 2
    link = tmp_path / "link-to-a"
    link.symlink_to(a)
    for again in (a, b, link, f"{a}/"):
        d.add_folder(str(again))
        assert not d._busy and len(calls) == 2, again
        assert d.status.text().endswith("are already listed."), again
    assert len(d._stats) == 12


def test_copies_of_listed_subs_are_left_out_by_name_and_time(qtbot, tmp_path):
    """The same sub copied into another folder would count twice in the
    stack. The Seestar names a sub by the second it was taken."""
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    b = tmp_path / "copies"
    b.mkdir()
    for p in sorted(a.iterdir())[:3]:
        (b / p.name).write_bytes(p.read_bytes())
    new = b / "Light_SH2-108_10.0s_LP_20260921-224500.fit"
    new.write_bytes(b"y")
    calls = []
    d = _graded(qtbot, a, calls)
    _add(qtbot, d, b)
    assert calls[-1] == [new.name]
    assert len(d._stats) == 7
    assert d.status.text().endswith("3 subs in copies were left out: already listed "
                                    "(the same name and capture time).")


def test_a_folder_of_nothing_but_copies_adds_nothing(qtbot, tmp_path):
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    b = tmp_path / "copies"
    b.mkdir()
    for p in a.iterdir():
        (b / p.name).write_bytes(p.read_bytes())
    calls = []
    d = _graded(qtbot, a, calls)
    d.add_folder(str(b))
    assert not d._busy, "a grade started"
    assert len(calls) == 1 and len(d._stats) == 6
    assert d.status.text() == ("Every sub in copies is already listed — the same name "
                               "and capture time as one here.")


def _generic(folder, date_obs):
    """Two subs named as another camera names them, with the capture time
    only in the header."""
    folder.mkdir()
    for i, t in enumerate(date_obs):
        hdu = fits.PrimaryHDU(np.zeros((4, 4), np.uint16))
        hdu.header["DATE-OBS"] = t
        hdu.writeto(folder / f"Light_{i:03d}.fit")
    return folder


def test_two_folders_with_the_same_names_list_both_and_say_whose(qtbot, tmp_path):
    a = _generic(tmp_path / "first", ["2026-09-21T20:30:00", "2026-09-21T20:31:00"])
    b = _generic(tmp_path / "second", ["2026-09-26T20:30:00", "2026-09-26T20:31:00"])
    d = _graded(qtbot, a)
    _add(qtbot, d, b)
    assert sorted(os.path.basename(s.path) for s in d._stats) == [
        "Light_000.fit", "Light_000.fit", "Light_001.fit", "Light_001.fit"]
    row = next(i for i, s in enumerate(d._stats) if str(b) in s.path)
    d.browser.set_current_row(row)
    assert d.browser.preview_name.text() == f"second/{os.path.basename(d._stats[row].path)}"


def test_the_preview_header_gains_its_folder_prefix_right_after_add_folder(qtbot, tmp_path):
    """m1 (final review, 2026-09-28): the currently previewed frame's header
    used to keep its bare name until the cursor next moved — it must gain
    the "folder/" prefix the moment a second folder makes names ambiguous,
    with no cursor move at all."""
    a = _generic(tmp_path / "first", ["2026-09-21T20:30:00", "2026-09-21T20:31:00"])
    b = _generic(tmp_path / "second", ["2026-09-26T20:30:00", "2026-09-26T20:31:00"])
    d = _graded(qtbot, a)
    assert d.browser.preview_name.text() == "Light_000.fit"
    _add(qtbot, d, b)
    assert d.browser.preview_name.text() == "first/Light_000.fit"


def test_one_folder_names_its_frames_as_before(qtbot, tmp_path):
    a = _generic(tmp_path / "first", ["2026-09-21T20:30:00", "2026-09-21T20:31:00"])
    d = _graded(qtbot, a)
    assert d.browser.preview_name.text() == "Light_000.fit"


def test_a_rejected_folder_is_not_added(qtbot, tmp_path):
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    rej = _seestar_folder(a, "rejected", "20260921", n=2, start=10)
    calls = []
    d = _graded(qtbot, a, calls)
    d.add_folder(str(rej))
    assert not d._busy, "a grade started"
    assert len(calls) == 1 and len(d._stats) == 6
    assert "Move them back" in d.status.text()


def test_a_symlink_to_a_rejected_folder_is_refused(qtbot, tmp_path):
    """Review I1: the typed-name check alone missed a link pointing AT
    rejected/ — its realpath resolves through the link to one."""
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    rej = _seestar_folder(a, "rejected", "20260921", n=2, start=10)
    link = tmp_path / "link-to-rejected"
    link.symlink_to(rej)
    calls = []
    d = _graded(qtbot, a, calls)
    d.add_folder(str(link))
    assert not d._busy, "a grade started"
    assert len(calls) == 1 and len(d._stats) == 6
    assert "Move them back" in d.status.text()


def test_a_folder_nested_inside_rejected_is_refused(qtbot, tmp_path):
    """Review I1: a folder ANYWHERE inside rejected/ is refused, not only
    one typed as rejected/ itself."""
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    rej = _seestar_folder(a, "rejected", "20260921", n=2, start=10)
    nested = _seestar_folder(rej, "nested", "20260921", n=1, start=20)
    calls = []
    d = _graded(qtbot, a, calls)
    d.add_folder(str(nested))
    assert not d._busy, "a grade started"
    assert len(calls) == 1 and len(d._stats) == 6
    assert "Move them back" in d.status.text()


def test_a_capture_folder_under_an_unrelated_rejected_names_the_real_ancestor(qtbot, tmp_path):
    """T7/edges.py #5 (final review, 2026-09-28): a capture folder that
    merely SITS INSIDE a folder called "rejected" (nothing to do with any
    stack's Move them back) used to be told it itself "holds frames moved
    out of a stack" — false. It must name the actual rejected/ ancestor and
    say the capture folder only sits inside it."""
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    up = tmp_path / "rejected" / "old_M8_sub"
    up.mkdir(parents=True)
    (up / "Light_X_10.0s_LP_20260801-223000.fit").write_bytes(b"x")
    d = _graded(qtbot, a)
    d.add_folder(str(up))
    assert not d._busy, "a grade started"
    assert len(d._stats) == 6
    text = d.status.text()
    assert text.startswith(f"old_M8_sub/ sits inside {tmp_path.name}/rejected/")
    assert "old_M8_sub/ holds" not in text, "must not claim old_M8_sub itself holds anything"
    assert "Move them back" in text


def test_a_damaged_rejected_record_is_shown_not_hidden_as_no_subs(qtbot, tmp_path):
    """T7/m7 (final review, 2026-09-28): a folder whose every sub is already
    in its own rejected/ AND whose manifest is damaged used to read "No .fit
    subs found" — hiding exactly the case R9 exists to surface. It must show
    the record's own damaged-record message."""
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    b = _seestar_folder(tmp_path, "b", "20260926")
    b_paths = sorted(str(p) for p in b.iterdir())
    move_to_rejected(str(b), b_paths, b_paths)
    (b / "rejected" / ".nocturne-moved.json").write_text("{not json")
    d = _graded(qtbot, a)
    d.add_folder(str(b))
    assert not d._busy
    assert "damaged" in d.status.text() and "b/rejected" in d.status.text()
    assert d.listed_folders() == [str(a)], "a damaged folder is not silently listed either"


def test_a_folder_of_only_hard_links_says_already_listed(qtbot, tmp_path):
    """T7 (final review, 2026-09-28): every sub in the added folder resolving
    (by inode) to one already listed used to read "No .fit subs found" —
    they were found, just already here under another name."""
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    b = tmp_path / "hardlinks"
    b.mkdir()
    for p in a.iterdir():
        os.link(p, b / f"copy_{p.name}")
    calls = []
    d = _graded(qtbot, a, calls)
    d.add_folder(str(b))
    assert not d._busy, "a grade started"
    assert len(calls) == 1 and len(d._stats) == 6
    assert d.status.text() == ("Every sub in hardlinks is already listed — the same "
                               "file, under another name, as one here.")


def test_a_folder_without_subs_says_so(qtbot, tmp_path):
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    empty = tmp_path / "nothing here"
    empty.mkdir()
    d = _graded(qtbot, a)
    d.add_folder(str(empty))
    assert d.status.text() == "No .fit subs found in nothing here."
    assert d.listed_folders() == [str(a)]


def test_a_folder_whose_subs_are_all_already_rejected_is_still_listed(qtbot, tmp_path):
    """Ruling R9: a folder fully moved out in an earlier session has nothing
    for discover_subs to find directly inside it. It must not vanish from
    the combined view — it is listed with no rows, its back count counts,
    and Move them back still returns its frames, byte-identical."""
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    b = _seestar_folder(tmp_path, "b", "20260926")
    b_paths = sorted(str(p) for p in b.iterdir())
    move_to_rejected(str(b), b_paths, b_paths)      # simulates an earlier session
    before = {os.path.basename(p): (b / "rejected" / os.path.basename(p)).read_bytes()
              for p in b_paths}
    calls = []
    d = _graded(qtbot, a, calls)
    d.add_folder(str(b))
    assert not d._busy, "nothing to grade"
    assert len(calls) == 1                          # no new grade was started
    assert d.listed_folders() == [str(a), str(b)]
    assert d.status.text() == ("b has no subs left — 6 frames are in b/rejected; "
                               "Move them back returns them.")
    assert d.verdict_strip.back_btn.text() == "Move them back (6)"
    d.verdict_strip.back_btn.click()
    qtbot.waitUntil(lambda: not d._busy, timeout=3000)
    for name, content in before.items():
        assert (b / name).read_bytes() == content
    assert len(d._stats) == 12
    assert sorted(os.path.basename(s.path) for s in d._stats
                 if os.path.dirname(s.path) == str(b)) == sorted(before)


@pytest.mark.parametrize("exc, said", [(Cancelled(), "Cancelled — nothing from b was added."),
                                       (OSError("disk gone"), "Could not add b: disk gone")])
def test_a_failed_add_lists_nothing_and_keeps_the_folder_out(qtbot, tmp_path, exc, said):
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    b = _seestar_folder(tmp_path, "b", "20260926")
    d = _graded(qtbot, a)
    before = list(d._stats)

    def boom(paths, on_progress=None, strictness="normal"):
        raise exc

    d._grade_runner = boom
    _add(qtbot, d, b)
    assert d.status.text() == said
    assert d.listed_folders() == [str(a)] and d._stats == before
    d._grade_runner = _runner()
    _add(qtbot, d, b)                          # and it can be added after all
    assert d.listed_folders() == [str(a), str(b)]


def test_a_new_grade_forgets_the_added_folders(qtbot, tmp_path):
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    b = _seestar_folder(tmp_path, "b", "20260926")
    c = _seestar_folder(tmp_path, "c", "20260927")
    d = _graded(qtbot, a)
    _add(qtbot, d, b)
    d.folder_edit.setText(str(c))
    d.grade()
    qtbot.waitUntil(lambda: not d._busy, timeout=3000)
    assert d.listed_folders() == [str(c)] and len(d._stats) == 6


def test_a_link_to_a_listed_sub_is_not_added_under_another_name(qtbot, tmp_path):
    a = _generic(tmp_path / "first", ["2026-09-21T20:30:00", "2026-09-21T20:31:00"])
    b = tmp_path / "second"
    b.mkdir()
    (b / "other_name.fit").symlink_to(a / "Light_000.fit")
    calls = []
    d = _graded(qtbot, a, calls)
    d.add_folder(str(b))
    assert not d._busy, "a grade started"
    assert len(calls) == 1 and len(d._stats) == 2


def test_a_hard_link_under_another_name_is_not_listed_twice(qtbot, tmp_path):
    """Review m2: a hard link is the SAME file under a second name — not a
    copy, and not something realpath resolves away the way a symlink does."""
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    b = tmp_path / "hardlinks"
    b.mkdir()
    target = sorted(a.iterdir())[0]
    os.link(target, b / "same_frame.fit")
    calls = []
    d = _graded(qtbot, a, calls)
    d.add_folder(str(b))
    assert not d._busy, "a grade started"
    assert len(calls) == 1 and len(d._stats) == 6


def test_a_case_variant_folder_path_is_refused(qtbot, tmp_path):
    """Review m2: on a case-insensitive filesystem (APFS's default) Sh2-108
    and SH2-108 are the same directory entry — a realpath string compare
    misses that; samefile does not. Skipped where the filesystem is
    case-sensitive (real filesystem, not synthetic — detected here)."""
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    variant = os.path.join(os.path.dirname(str(a)), "SH2-108")
    if not (os.path.exists(variant) and os.path.samefile(variant, a)):
        pytest.skip("filesystem is case-sensitive")
    calls = []
    d = _graded(qtbot, a, calls)
    d.add_folder(variant)
    assert not d._busy and len(calls) == 1
    assert d.status.text().endswith("are already listed.")
    assert len(d._stats) == 6


def test_a_cancelled_first_grade_leaves_nothing_to_add_to(qtbot, tmp_path):
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    d = StackDialog(Settings())
    qtbot.addWidget(d)

    def cancelled(paths, on_progress=None, strictness="normal"):
        raise Cancelled()

    d._grade_runner = cancelled
    d.folder_edit.setText(str(a))
    d.grade()
    qtbot.waitUntil(lambda: not d._busy, timeout=3000)
    assert d.status.text() == "Cancelled." and not d.add_folder_btn.isEnabled()


def test_a_second_night_added_at_the_floor_stays_on_screen(qtbot, tmp_path):
    """The added night brings the Nights line: at 1280×800 the dialog folds
    what it must and stays on the screen, the chips on it."""
    from PySide6.QtWidgets import QApplication
    from nocturne.ui import theme
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(theme.build_stylesheet())
    try:
        a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
        b = _seestar_folder(tmp_path, "b", "20260926")
        d = StackDialog(Settings())
        qtbot.addWidget(d)
        d._available_height = lambda: 740
        d.browser.preview_controller.loader = lambda p: np.zeros((8, 8, 3), np.float32)
        d._grade_runner = _runner()
        d.resize(1280, 700)
        d.show()
        qtbot.waitExposed(d)
        d.folder_edit.setText(str(a))
        d.grade()
        qtbot.waitUntil(lambda: not d._busy, timeout=3000)
        assert d.verdict_strip.chips == [] and not d.verdict_strip.is_compact()
        _add(qtbot, d, b)
        qtbot.wait(50)
        assert len(d.verdict_strip.chips) == 2
        assert d.height() <= 740, f"{d.height()} px on a 740 px screen"
        assert all(c.isVisible() for c in d.verdict_strip.chips)
        assert d.verdict_strip.details_shown() and not d.verdict_strip.is_compact()
        assert d.preview.height() >= 220
    finally:
        app.setStyleSheet(before)


def test_added_subs_with_no_name_overlap_never_read_their_header(qtbot, tmp_path, monkeypatch):
    """Review m3: read_capture_time opens the FITS header, on the GUI
    thread. It must run only for a basename that could actually collide
    with one already listed — the ordinary case (a different night, a
    different target) shares no name with what's here and needs no read."""
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    b = _seestar_folder(tmp_path, "b", "20260926")
    from nocturne.ui import stack_dialog
    reads = []
    real = stack_dialog.read_capture_time

    def spy(p):
        reads.append(p)
        return real(p)

    monkeypatch.setattr(stack_dialog, "read_capture_time", spy)
    d = _graded(qtbot, a)
    _add(qtbot, d, b)
    assert reads == []
    assert len(d._stats) == 12


def test_the_pointings_are_read_across_every_listed_folder(qtbot, tmp_path):
    """Two folders can be two pointings: the mosaic check must see both."""
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    b = _seestar_folder(tmp_path, "b", "20260926")
    d = _graded(qtbot, a)
    seen = []
    d.scan_pointings = lambda folder=None, paths=None: seen.append(sorted(paths or []))
    _add(qtbot, d, b)
    assert {os.path.dirname(p) for p in seen[-1]} == {str(a), str(b)}
    assert len(seen[-1]) == 12
