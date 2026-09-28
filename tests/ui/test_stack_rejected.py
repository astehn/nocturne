"""Stack's rejected folder (spec 2026-09-27 decision 7, §5, §7).

His ORIGINAL subs are what this moves. Every test here builds its own folder
inside tmp_path — never a real capture folder — and checks bytes and mtimes,
not just names.
"""
import os

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from nocturne.settings import Settings
from nocturne.stacking.frames import discover_subs
from nocturne.stacking.grade import REASON_NOT_RAW, FrameStats
from nocturne.stacking.reject_move import MANIFEST_NAME, read_manifest
from nocturne.ui import theme
from nocturne.ui.frame_browser import COL_VERDICT, MOVED_TEXT
from nocturne.ui.stack_dialog import StackDialog

REJECTED = ("Light_01.fit", "Light_03.fit")
AS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
QUESTION_2 = ("Move 2 rejected frames into Sh2-108/rejected? Nothing is deleted; "
              "you can move them back.")


def tree(root):
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames + dirnames:
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, root)
            if os.path.islink(p):
                out[rel] = ("link", os.readlink(p))
            elif os.path.isfile(p):
                with open(p, "rb") as fh:
                    out[rel] = (fh.read(), os.stat(p).st_mtime_ns)
            else:
                out[rel] = ("dir",)
    return out


def outside_rejected(snap):
    prefix = os.path.join("Sh2-108", "rejected")
    return {k: v for k, v in snap.items() if not k.startswith(prefix)}


def _folder(tmp_path, n=6):
    folder = tmp_path / "Sh2-108"
    folder.mkdir()
    paths = []
    for i in range(n):
        p = folder / f"Light_{i:02d}.fit"
        p.write_bytes(bytes([65 + i]) * (200 + i))
        stamp = 1_600_000_000_000_000_000 + i * 1_000_000_000
        os.utime(p, ns=(stamp, stamp))
        paths.append(str(p))
    return folder, paths


def _runner(rejected=REJECTED, errors=(), calls=None):
    """Grades by name: the `rejected` subs at FWHM 3.2 (judge rejects them
    as soft against 2.5), the `errors` as already-stacked masters."""
    def run(paths, on_progress=None, strictness="normal"):
        if calls is not None:
            calls.append(sorted(paths))
        stats = []
        for p in sorted(paths):
            name = os.path.basename(p)
            if name in errors:
                stats.append(FrameStats(p, 0, 0.0, 0.0, 0.0, False, reason_code="not_raw",
                                        reason=REASON_NOT_RAW, error=True))
            else:
                stats.append(FrameStats(p, 800, 3.2 if name in rejected else 2.5,
                                        1000.0, 0.5, True, exposure=10.0))
        return stats
    return run


def _blank(_path):
    return np.zeros((8, 8, 3), np.float32)


def _graded(qtbot, folder, runner=None, answer=True, **kw):
    d = StackDialog(Settings(), **kw)
    qtbot.addWidget(d)
    d.browser.preview_controller.loader = _blank
    d._grade_runner = runner or _runner()
    asked = []
    d._confirm = lambda title, text: (asked.append(text), answer)[1]
    d.folder_edit.setText(str(folder))
    d.grade()
    qtbot.waitUntil(lambda: not d._busy, timeout=3000)
    return d, asked


def _choose_output(d, path):
    folder, name = os.path.split(str(path))
    d.save_to_edit.setText(folder)
    d.save_to_edit.textEdited.emit(folder)
    d.name_edit.setText(name)
    d.name_edit.textEdited.emit(name)


# --- only when asked --------------------------------------------------------------

def test_nothing_moves_until_he_asks(qtbot, tmp_path):
    folder, _paths = _folder(tmp_path)
    before = tree(tmp_path)
    d, asked = _graded(qtbot, folder)
    d.strictness_box.setCurrentText("Strict")
    d.strictness_box.setCurrentText("Normal")
    assert tree(tmp_path) == before and asked == []
    s = d.verdict_strip
    assert s.move_btn.text() == "Move 2 frames to rejected/…" and not s.move_btn.isHidden()
    assert s.back_btn.isHidden()


def test_the_count_is_the_frames_not_ticked_right_now(qtbot, tmp_path):
    folder, _paths = _folder(tmp_path)
    d, _ = _graded(qtbot, folder)
    d.browser.set_checked(1, True)            # re-ticked a rejected frame: it stays
    assert d.verdict_strip.move_btn.text() == "Move 1 frame to rejected/…"
    d.browser.set_checked(0, False)           # unticked a kept one: it goes
    assert d.verdict_strip.move_btn.text() == "Move 2 frames to rejected/…"
    d.verdict_strip.move_btn.click()
    assert sorted(os.listdir(folder / "rejected")) == [MANIFEST_NAME, "Light_00.fit",
                                                        "Light_03.fit"]


def test_the_question_names_the_count_and_the_folder(qtbot, tmp_path):
    folder, _paths = _folder(tmp_path)
    d, asked = _graded(qtbot, folder)
    d.verdict_strip.move_btn.click()
    assert asked == [QUESTION_2]


def test_saying_no_moves_nothing(qtbot, tmp_path):
    folder, _paths = _folder(tmp_path)
    before = tree(tmp_path)
    d, asked = _graded(qtbot, folder, answer=False)
    d.verdict_strip.move_btn.click()
    assert asked == [QUESTION_2] and tree(tmp_path) == before
    assert d.verdict_strip.move_btn.text() == "Move 2 frames to rejected/…"


# --- moving -------------------------------------------------------------------------

def test_yes_moves_exactly_the_unticked_frames_byte_for_byte(qtbot, tmp_path):
    folder, _paths = _folder(tmp_path)
    before = tree(tmp_path)
    d, _ = _graded(qtbot, folder)
    d.verdict_strip.move_btn.click()
    after = tree(tmp_path)
    for name in REJECTED:
        assert (after[os.path.join("Sh2-108", "rejected", name)]
                == before[os.path.join("Sh2-108", name)]), name
        assert os.path.join("Sh2-108", name) not in after
    for k, v in before.items():
        if not any(n in k for n in REJECTED):
            assert after[k] == v, k
    assert "Moved 2 frames into Sh2-108/rejected" in d.verdict_strip.message.text()


def test_moved_frames_stay_listed_greyed_and_out_of_the_stack(qtbot, tmp_path):
    """Review Focus 5: ticking everything afterwards still stacks none of them."""
    folder, _paths = _folder(tmp_path)
    d, _ = _graded(qtbot, folder)
    d.verdict_strip.move_btn.click()
    b = d.browser
    assert b.cell_text(1, COL_VERDICT) == MOVED_TEXT == b.cell_text(3, COL_VERDICT)
    assert d._stats[1].path == str(folder / "rejected" / "Light_01.fit")
    b.select_all()
    b.set_checked(3, True)
    assert not b.is_checked(1) and not b.is_checked(3)
    captured = {}

    def fake_stack(opts, on_progress=None):
        captured["include"] = list(opts.include)
        raise RuntimeError("stop here")

    d._stack_runner = fake_stack
    _choose_output(d, tmp_path / "m.fits")
    d.run()
    qtbot.waitUntil(lambda: "include" in captured, timeout=3000)
    assert sorted(os.path.basename(p) for p in captured["include"]) == [
        "Light_00.fit", "Light_02.fit", "Light_04.fit", "Light_05.fit"]
    assert not any(f"{os.sep}rejected{os.sep}" in p for p in captured["include"])


def test_the_preview_reads_a_moved_frame_from_its_new_home(qtbot, tmp_path):
    folder, _paths = _folder(tmp_path)
    loads = []
    d, _ = _graded(qtbot, folder)
    d.browser.preview_controller.loader = lambda p: (loads.append(p), _blank(p))[1]
    d.browser.set_current_row(1)
    qtbot.waitUntil(lambda: str(folder / "Light_01.fit") in loads,
                    timeout=2000)
    d.verdict_strip.move_btn.click()
    qtbot.waitUntil(lambda: str(folder / "rejected" / "Light_01.fit") in loads,
                    timeout=2000)


def test_the_button_becomes_move_them_back(qtbot, tmp_path):
    folder, _paths = _folder(tmp_path)
    d, _ = _graded(qtbot, folder)
    d.verdict_strip.move_btn.click()
    assert d.verdict_strip.move_btn.isHidden()
    assert d.verdict_strip.back_btn.text() == "Move them back (2)"
    assert not d.verdict_strip.back_btn.isHidden()


def test_error_frames_stay_where_they_are(qtbot, tmp_path):
    folder, _paths = _folder(tmp_path)
    before = tree(tmp_path)
    d, _ = _graded(qtbot, folder, runner=_runner(errors=("Light_05.fit",)))
    assert d.verdict_strip.move_btn.text() == "Move 2 frames to rejected/…"
    d.verdict_strip.move_btn.click()
    key = os.path.join("Sh2-108", "Light_05.fit")
    assert tree(tmp_path)[key] == before[key]
    assert not (folder / "rejected" / "Light_05.fit").exists()


# --- moving back ----------------------------------------------------------------------

def test_move_them_back_restores_every_byte_and_mtime(qtbot, tmp_path):
    folder, _paths = _folder(tmp_path)
    before = tree(tmp_path)
    d, _ = _graded(qtbot, folder)
    d.verdict_strip.move_btn.click()
    d.verdict_strip.back_btn.click()
    assert outside_rejected(tree(tmp_path)) == before
    assert read_manifest(str(folder)) == []
    s = d.verdict_strip
    assert s.back_btn.isHidden() and s.move_btn.text() == "Move 2 frames to rejected/…"
    assert d._stats[1].path == str(folder / "Light_01.fit")
    assert d.browser.cell_text(1, COL_VERDICT).startswith("Soft stars")
    d.browser.set_checked(1, True)
    assert d.browser.is_checked(1)
    assert s.message.text() == "Moved 2 frames back."


def test_reopening_offers_them_back_without_grading_them(qtbot, tmp_path):
    folder, paths = _folder(tmp_path)
    before = tree(tmp_path)
    d1, _ = _graded(qtbot, folder)
    d1.verdict_strip.move_btn.click()
    calls = []
    d2, _ = _graded(qtbot, folder, runner=_runner(calls=calls))
    assert calls == [[p for p in paths if os.path.basename(p) not in REJECTED]], (
        "graded the frames in rejected/")
    assert d2.verdict_strip.back_btn.text() == "Move them back (2)"
    assert not d2.verdict_strip.back_btn.isHidden()
    d2.verdict_strip.back_btn.click()
    assert "Measuring 2 frames that came back" in d2.verdict_strip.message.text(), (
        "the promise while the partial re-grade is still running")
    qtbot.waitUntil(lambda: len(calls) == 2 and not d2._busy, timeout=3000)
    # Fix round 1, I2: only the two restored frames that weren't already
    # listed are measured — not the whole folder, and not a re-measure of
    # the four frames already on screen.
    assert calls[1] == sorted(str(folder / n) for n in REJECTED)
    assert len(d2.browser.frames()) == 6
    assert outside_rejected(tree(tmp_path)) == before
    # m1: the promise does not outlive the measure — once it succeeds, the
    # strip reads the move's own outcome, not "Measuring…" for ever.
    assert d2.verdict_strip.message.text() == "Moved 2 frames back."


def test_with_every_frame_moved_the_folder_still_offers_them_back(qtbot, tmp_path):
    """Review Focus 4: nothing kept at all, then the folder opened again."""
    folder, paths = _folder(tmp_path)
    d1, asked = _graded(qtbot, folder)
    d1.browser.select_none()
    d1.verdict_strip.move_btn.click()
    assert asked == ["Move 6 rejected frames into Sh2-108/rejected? Nothing is "
                     "deleted; you can move them back."]
    assert discover_subs(str(folder)) == []
    calls = []
    d2, _ = _graded(qtbot, folder, runner=_runner(calls=calls))
    assert calls == [] and "No .fit subs" in d2.status.text()
    assert not d2.verdict_strip.isHidden()
    assert d2.verdict_strip.back_btn.text() == "Move them back (6)"
    d2.verdict_strip.back_btn.click()
    qtbot.waitUntil(lambda: len(calls) == 1 and not d2._busy, timeout=3000)
    assert calls[0] == paths


def test_a_frame_moved_back_by_hand_is_not_offered_again(qtbot, tmp_path):
    """Review Focus 6: the record is out of date."""
    folder, _paths = _folder(tmp_path)
    d1, _ = _graded(qtbot, folder)
    d1.verdict_strip.move_btn.click()
    os.rename(folder / "rejected" / "Light_01.fit", folder / "Light_01.fit")   # Finder
    by_hand = (folder / "Light_01.fit").read_bytes()
    d2, _ = _graded(qtbot, folder)
    assert d2.verdict_strip.back_btn.text() == "Move them back (1)"
    d2.verdict_strip.back_btn.click()
    qtbot.waitUntil(lambda: not d2._busy, timeout=3000)
    assert (folder / "Light_03.fit").exists()
    assert (folder / "Light_01.fit").read_bytes() == by_hand
    assert read_manifest(str(folder)) == []
    assert "1 frame had already been moved back by hand" in d2.verdict_strip.message.text()


# --- refusals ----------------------------------------------------------------------------

def test_a_name_already_in_rejected_stops_everything(qtbot, tmp_path):
    """Review Focus 2."""
    folder, _paths = _folder(tmp_path)
    (folder / "rejected").mkdir()
    (folder / "rejected" / "Light_03.fit").write_bytes(b"his older Light_03")
    before = tree(tmp_path)
    d, _ = _graded(qtbot, folder)
    d.verdict_strip.move_btn.click()
    assert tree(tmp_path) == before
    msg = d.verdict_strip.message.text()
    assert "Light_03.fit" in msg and "nothing was moved" in msg
    assert d.browser.cell_text(1, COL_VERDICT) != MOVED_TEXT


@pytest.mark.skipif(AS_ROOT, reason="root ignores permissions")
def test_a_read_only_folder_moves_nothing_and_says_why(qtbot, tmp_path):
    """Review Focus 1."""
    folder, _paths = _folder(tmp_path)
    d, _ = _graded(qtbot, folder)
    before = tree(tmp_path)
    os.chmod(folder, 0o555)
    try:
        d.verdict_strip.move_btn.click()
    finally:
        os.chmod(folder, 0o755)
    assert tree(tmp_path) == before
    assert "Can't write in Sh2-108" in d.verdict_strip.message.text()
    assert "Can't write in Sh2-108" in d.status.text()


def test_a_damaged_record_is_reported_and_nothing_moves(qtbot, tmp_path):
    folder, _paths = _folder(tmp_path)
    (folder / "rejected").mkdir()
    (folder / "rejected" / MANIFEST_NAME).write_text("{ not json")
    before = tree(tmp_path)
    d, _ = _graded(qtbot, folder)
    assert "damaged" in d.verdict_strip.message.text()
    assert d.verdict_strip.back_btn.isHidden()
    d.verdict_strip.move_btn.click()
    assert tree(tmp_path) == before
    assert "damaged" in d.verdict_strip.message.text()


def test_the_buttons_are_dead_while_busy(qtbot, tmp_path):
    folder, _paths = _folder(tmp_path)
    d, _ = _graded(qtbot, folder)
    d.verdict_strip.move_btn.click()          # something to move back, too
    before = tree(tmp_path)
    d._set_busy(True)
    s = d.verdict_strip
    assert not s.move_btn.isEnabled() and not s.back_btn.isEnabled()
    s.back_btn.click()
    d._move_rejected()
    d._move_back()
    assert tree(tmp_path) == before
    d._set_busy(False)
    assert s.back_btn.isEnabled()


def test_a_running_background_stack_blocks_moving(qtbot, tmp_path):
    """Review Focus 8: a queued stack may be reading these very subs."""
    folder, _paths = _folder(tmp_path)
    before = tree(tmp_path)
    d, asked = _graded(qtbot, folder, queue_busy=lambda: True)
    d.verdict_strip.move_btn.click()
    assert tree(tmp_path) == before and asked == []
    assert "background stack is running" in d.verdict_strip.message.text()


def test_the_move_acts_on_the_graded_folder_not_the_retyped_one(qtbot, tmp_path):
    """Review Focus 7."""
    folder, _paths = _folder(tmp_path)
    other = tmp_path / "Other"
    other.mkdir()
    d, asked = _graded(qtbot, folder)
    d.folder_edit.setText(str(other))         # typed, not graded
    d.verdict_strip.move_btn.click()
    assert asked == [QUESTION_2]
    assert sorted(os.listdir(folder / "rejected")) == [MANIFEST_NAME, "Light_01.fit",
                                                        "Light_03.fit"]
    assert os.listdir(other) == []


# --- fix round 1 (review, Ruling R6) -------------------------------------------------

def test_move_back_regrades_the_graded_folder_not_the_retyped_one(qtbot, tmp_path):
    """I1: the Folder field can be retyped after grading; the frames move_back
    restores must be measured from the folder they actually came from, and
    the outcome message must survive that measurement, not get wiped by a
    'folder changed' clear meant for an actual folder switch."""
    folder, _paths = _folder(tmp_path)
    d1, _ = _graded(qtbot, folder)
    d1.verdict_strip.move_btn.click()
    other = tmp_path / "Other"
    other.mkdir()
    for i in range(3):
        (other / f"O_{i}.fit").write_bytes(b"x" * 100)
    calls = []
    d2, _ = _graded(qtbot, folder, runner=_runner(calls=calls))
    d2.folder_edit.setText(str(other))          # retyped, not graded
    d2.verdict_strip.back_btn.click()
    assert "Measuring 2 frames that came back" in d2.verdict_strip.message.text(), (
        "the promise while the partial re-grade is still running")
    qtbot.waitUntil(lambda: len(calls) == 2 and not d2._busy, timeout=3000)
    assert calls[1] == sorted(str(folder / n) for n in REJECTED), (
        "regraded the retyped folder instead of the graded one")
    assert not any(str(other) in p for p in calls[1])
    # m1: the promise does not survive the measure finishing.
    assert d2.verdict_strip.message.text() == "Moved 2 frames back."


def test_move_back_keeps_hand_ticks_while_restoring_an_earlier_session(qtbot, tmp_path):
    """I2: a partial re-grade of only the newly-restored frames must not
    disturb a hand tick already made on a frame that was already listed."""
    folder, _paths = _folder(tmp_path)
    d1, _ = _graded(qtbot, folder)
    d1.verdict_strip.move_btn.click()               # Light_01, Light_03 -> rejected/
    # d2 grades the 4 remaining subs with a DIFFERENT grader verdict, so he
    # has something to overrule by hand: Light_02 rejected, Light_04 kept.
    d2, _ = _graded(qtbot, folder, runner=_runner(
        rejected=("Light_01.fit", "Light_03.fit", "Light_02.fit")))
    b = d2.browser
    names = [os.path.basename(s.path) for s in d2._stats]
    b.set_checked(names.index("Light_02.fit"), True)     # ticked back in by hand
    b.set_checked(names.index("Light_04.fit"), False)    # unticked by hand
    d2.verdict_strip.back_btn.click()
    qtbot.waitUntil(lambda: not d2._busy, timeout=3000)
    after = {os.path.basename(s.path): s.included for s in d2._stats}
    assert after["Light_02.fit"] is True, "the hand tick to keep it was lost"
    assert after["Light_04.fit"] is False, "the hand tick to drop it was lost"
    listed = {os.path.basename(s.path) for s in d2._stats}
    assert listed == {f"Light_{i:02d}.fit" for i in range(6)}, "the restored frames "\
        "did not appear"
    assert len(d2.browser.frames()) == 6


def test_a_known_damaged_record_refuses_before_asking(qtbot, tmp_path):
    """m3: pending_back already raised while grading (that is why the back
    button stayed hidden — see test_a_damaged_record_is_reported_and_nothing_moves).
    Move must refuse the SAME way, before asking, not after he has already
    said yes to a move that cannot happen."""
    folder, _paths = _folder(tmp_path)
    (folder / "rejected").mkdir()
    (folder / "rejected" / MANIFEST_NAME).write_text("{ not json")
    before = tree(tmp_path)
    d, asked = _graded(qtbot, folder)
    d.verdict_strip.move_btn.click()
    assert asked == [], "asked him to move although the record is known damaged"
    assert tree(tmp_path) == before
    assert "damaged" in d.verdict_strip.message.text()


def test_the_damaged_message_clears_once_the_record_is_fixed(qtbot, tmp_path):
    """m4: the folder never changes when he fixes the record by hand and
    measures again, so the 'folder changed' clear in grade()/_on_graded never
    fires — without its own fix the complaint sat there forever."""
    folder, _paths = _folder(tmp_path)
    (folder / "rejected").mkdir()
    (folder / "rejected" / MANIFEST_NAME).write_text("{ not json")
    d, _ = _graded(qtbot, folder)
    assert "damaged" in d.verdict_strip.message.text()
    os.unlink(folder / "rejected" / MANIFEST_NAME)
    d.grade()
    qtbot.waitUntil(lambda: not d._busy, timeout=3000)
    assert "damaged" not in d.verdict_strip.message.text()


def test_a_frame_deleted_from_rejected_by_hand_is_dropped_not_left_moved(qtbot, tmp_path):
    """m6: move_back cannot find this name anywhere — not in rejected/, not
    at home — because it was deleted by hand. The row must stop describing a
    moved frame that points at a file which no longer exists anywhere."""
    folder, _paths = _folder(tmp_path)
    d, _ = _graded(qtbot, folder)
    d.verdict_strip.move_btn.click()
    os.unlink(folder / "rejected" / "Light_01.fit")     # gone, not just moved back
    before = [os.path.basename(s.path) for s in d._stats]
    d.verdict_strip.back_btn.click()
    after = [os.path.basename(s.path) for s in d._stats]
    assert "Light_01.fit" in before
    assert "Light_01.fit" not in after, "still listed as a moved frame pointing at nothing"
    assert len(after) == len(before) - 1
    assert (folder / "Light_03.fit").exists()          # the OTHER restored frame: fine
    assert "no longer in rejected" in d.verdict_strip.message.text()


def test_m2_a_frame_deleted_from_rejected_by_hand_updates_the_verdict(qtbot, tmp_path):
    """m2: remove_frames drops the row for a frame move_back could not find
    anywhere (deleted from rejected/ by hand); the verdict it feeds must be
    rebuilt too, or it goes on counting a frame the list no longer has."""
    folder, _paths = _folder(tmp_path)
    d, _ = _graded(qtbot, folder)
    d.verdict_strip.move_btn.click()
    assert "4 of 6" in d.verdict_strip.details_text()
    os.unlink(folder / "rejected" / "Light_01.fit")     # gone, not just moved back
    d.verdict_strip.back_btn.click()
    assert "4 of 5" in d.verdict_strip.details_text(), (
        "the verdict kept counting the frame remove_frames dropped")


def test_i1_reopened_verdict_says_how_many_are_still_in_rejected(qtbot, tmp_path):
    """I1: a folder reopened with some of its frames still parked in
    rejected/ from an earlier session is graded on only what's left at the
    top, so its verdict describes an easier night than the one he actually
    shot unless it says why. The line goes away once they are moved back."""
    folder, _paths = _folder(tmp_path)
    d1, _ = _graded(qtbot, folder)
    d1.verdict_strip.move_btn.click()               # Light_01, Light_03 -> rejected/
    d1.close()
    d2, _ = _graded(qtbot, folder)                   # reopen: 4 listed at top
    assert ("2 more frames are in rejected/ and are not counted here."
            in d2.verdict_strip.details_text())
    d2.verdict_strip.back_btn.click()
    qtbot.waitUntil(lambda: not d2._busy, timeout=3000)
    assert "more frame" not in d2.verdict_strip.details_text()


def test_i1_singular_wording_for_exactly_one(qtbot, tmp_path):
    """I1's own spec: singular wording for exactly one frame left behind."""
    folder, _paths = _folder(tmp_path)
    d1, _ = _graded(qtbot, folder)
    d1.browser.set_checked(1, True)     # both grader-rejected frames ticked
    d1.browser.set_checked(3, True)     # back in
    d1.browser.set_checked(0, False)    # one kept frame unticked: the only mover
    assert d1.verdict_strip.move_btn.text() == "Move 1 frame to rejected/…"
    d1.verdict_strip.move_btn.click()
    d1.close()
    d2, _ = _graded(qtbot, folder)
    assert ("1 more frame is in rejected/ and is not counted here."
            in d2.verdict_strip.details_text())


def test_new1_same_session_move_does_not_claim_listed_frames_are_uncounted(
        qtbot, tmp_path):
    """NEW-1 (scoped re-review): a name the manifest lists is not necessarily
    missing from the verdict's count — a frame moved THIS session is still a
    row in self._stats (moved=True), and build_verdict counts it by the
    grader's own reason, not by whether it has been moved. Reproduced as the
    reviewer found it: grade, move, then touch Strictness (which calls
    _update_verdict again over the SAME list, moved rows and all) — before
    the fix this claimed the very frames "Rejected: 2 soft" just counted were
    also "not counted here"."""
    folder, _paths = _folder(tmp_path)
    d, _ = _graded(qtbot, folder)
    d.verdict_strip.move_btn.click()          # Light_01, Light_03 -> rejected/
    d.strictness_box.setCurrentText("Strict")
    details = d.verdict_strip.details_text()
    assert "Rejected: 2 soft" in details, "fixture lost its moved, listed rejects"
    assert "more frame" not in details, (
        "claimed frames it just counted as rejected were also not counted")


def test_ask_yes_no_defaults_to_cancel(qtbot, tmp_path, monkeypatch):
    """m8: proven at the real QMessageBox seam, not just through the
    injectable `_confirm` every other test in this file answers through."""
    from PySide6.QtWidgets import QMessageBox

    got = {}

    def fake_question(parent, title, text, buttons, default):
        got.update(title=title, text=text, buttons=buttons, default=default)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    folder, _paths = _folder(tmp_path)
    before = tree(tmp_path)
    d, _ = _graded(qtbot, folder)
    d._confirm = d._ask_yes_no          # the real seam, not the test's own override
    d.verdict_strip.move_btn.click()
    assert got["default"] == QMessageBox.StandardButton.Cancel
    assert got["buttons"] & QMessageBox.StandardButton.Yes
    assert tree(tmp_path) == before


# --- fix round 2 (review, Ruling R7) -------------------------------------------------

def _fits_folder(tmp_path, n=6, name="Sh2-108"):
    """Like _folder, but real minimal FITS headers (FOCALLEN/XPIXSZ/XBINNING)
    so read_pixel_scale has something real to read — the synthetic garbage
    bytes _folder() writes give every header read a clean failure, which
    would make N1's pixel-scale assertion trivially true for the wrong
    reason."""
    from astropy.io import fits

    folder = tmp_path / name
    folder.mkdir()
    paths = []
    for i in range(n):
        p = folder / f"Light_{i:02d}.fit"
        hdu = fits.PrimaryHDU(np.zeros((8, 8), dtype=np.float32))
        hdu.header["FOCALLEN"] = 250.0
        hdu.header["XPIXSZ"] = 2.9
        hdu.header["XBINNING"] = 1
        hdu.writeto(str(p), overwrite=True)
        paths.append(str(p))
    return folder, paths


def test_moving_everything_back_from_empty_runs_a_full_grade(qtbot, tmp_path):
    """N1 (Ruling R7): reopening a folder with nothing left at the top, then
    Move them back, must run the SAME full grade an ordinary folder-open
    does — scan_pointings, read_pixel_scale, _read_frame_shape,
    _update_drizzle_note — because nothing was listed yet, so there is no
    hand tick to protect. The partial re-grade (fix round 1's mechanism,
    correct when something IS already listed) runs none of those."""
    folder, _paths = _fits_folder(tmp_path)
    d1, _ = _graded(qtbot, folder)
    d1.browser.select_none()
    d1.verdict_strip.move_btn.click()           # everything -> rejected/
    d2, _ = _graded(qtbot, folder)               # reopens to nothing at top
    assert d2._stats == [] and d2._pixel_scale is None
    calls = []

    def fake_scan(scan_folder=None):
        calls.append(scan_folder)
        d2.mosaic_check.setEnabled(True)
        d2.mosaic_check.setText("Stack as mosaic — 2 pointings")

    d2.scan_pointings = fake_scan
    d2.verdict_strip.back_btn.click()
    qtbot.waitUntil(lambda: not d2._busy, timeout=3000)
    assert calls == [str(folder)], (
        "scan_pointings must run once, on the FULL re-grade of the graded folder")
    assert d2.mosaic_check.isEnabled(), "Mosaic stayed disabled after the full re-grade"
    assert d2._pixel_scale is not None, "the pixel scale went missing"
    assert len(d2._stats) == 6


def test_moving_some_back_when_something_is_already_listed_stays_partial(qtbot, tmp_path):
    """N1's flip side: when frames ARE already listed, the partial re-grade
    (fix round 1, I2) must still be the one that runs — a full re-grade here
    would be the regression fix round 1 fixed, resetting hand ticks."""
    folder, _paths = _fits_folder(tmp_path)
    d1, _ = _graded(qtbot, folder)
    d1.verdict_strip.move_btn.click()            # Light_01, Light_03 -> rejected/
    d2, _ = _graded(qtbot, folder)                # 4 frames listed at top
    assert d2._stats != []
    calls = []
    d2.scan_pointings = lambda scan_folder=None: calls.append(scan_folder)
    d2.verdict_strip.back_btn.click()
    qtbot.waitUntil(lambda: not d2._busy, timeout=3000)
    assert calls == [], "ran a full grade (and so scan_pointings) although frames were already listed"
    assert len(d2._stats) == 6


def test_chart_current_follows_a_removed_row(qtbot, tmp_path):
    """N2 (Ruling R7): after a row is dropped (m6), the chart's own idea of
    "current" must follow the list's current row, not go on pointing at
    whatever x-position used to be highlighted — which after a removal can
    belong to a different frame entirely, or none."""
    folder, _paths = _folder(tmp_path)
    d, _ = _graded(qtbot, folder)
    d.verdict_strip.move_btn.click()
    b = d.browser
    b.set_current_row(5)
    os.unlink(folder / "rejected" / "Light_01.fit")     # gone, not just moved back
    d.verdict_strip.back_btn.click()
    assert b.chart.current_row() == b.current_row()
    assert b.preview_name.text() == "Light_05.fit"


def test_partial_grade_failure_replaces_the_measuring_message(qtbot, tmp_path):
    """N3 (Ruling R7): a partial re-grade that fails must not leave
    "Measuring N frames that came back…" standing as an unfulfilled promise —
    move_back's rename already happened, synchronously, before this async
    measure even started, so the frames really are back in the folder."""
    folder, _paths = _folder(tmp_path)
    d1, _ = _graded(qtbot, folder)
    d1.verdict_strip.move_btn.click()            # Light_01, Light_03 -> rejected/
    calls = []
    base = _runner(calls=calls)

    def run(p, on_progress=None, strictness="normal"):
        if calls:                                # the SECOND call: fail it
            calls.append(p)
            raise OSError("disk went away")
        return base(p, on_progress, strictness)  # the first (initial) grade: succeed

    d2, _ = _graded(qtbot, folder, runner=run)
    d2.verdict_strip.back_btn.click()
    qtbot.waitUntil(lambda: not d2._busy, timeout=3000)
    assert len(calls) == 2, "the partial grade never ran"
    msg = d2.verdict_strip.message.text()
    assert "back in the folder" in msg and "grade again" in msg
    assert "Measuring" not in msg
    # m1/R2-2: a real failure's reason travels with it, so a bug report
    # carries the cause instead of just "grade again".
    assert "disk went away" in msg
    # The rename is real and already happened — nothing here pretends otherwise.
    assert (folder / "Light_01.fit").exists() and (folder / "Light_03.fit").exists()


def test_full_grade_failure_after_all_moved_reopen_replaces_the_measuring_message(
        qtbot, tmp_path):
    """m1/T6 R2-1: the SAME promise-replacement the partial path gets must
    also apply to the full re-grade an all-moved reopen falls back to — it
    is the other of the two paths "Measuring…" can be left standing on."""
    folder, _paths = _folder(tmp_path)
    d1, _ = _graded(qtbot, folder)
    d1.browser.select_none()
    d1.verdict_strip.move_btn.click()            # everything -> rejected/

    def failing_runner(paths, on_progress=None, strictness="normal"):
        raise OSError("disk went away")

    d2, _ = _graded(qtbot, folder, runner=failing_runner)   # reopens to nothing at top
    assert d2._stats == []
    d2.verdict_strip.back_btn.click()
    assert "Measuring 6 frames that came back" in d2.verdict_strip.message.text(), (
        "the promise while the full re-grade is still running")
    qtbot.waitUntil(lambda: not d2._busy, timeout=3000)
    msg = d2.verdict_strip.message.text()
    assert "back in the folder" in msg and "grade again" in msg
    assert "Measuring" not in msg
    assert "disk went away" in msg
    # The rename already happened, synchronously, before this failed grade
    # even started — the frames really are back in the folder.
    assert all((folder / f"Light_{i:02d}.fit").exists() for i in range(6))


def test_full_grade_success_after_all_moved_reopen_clears_the_measuring_message(
        qtbot, tmp_path):
    """m1: the success-side twin of the test above — the full re-grade path
    must also stop saying "Measuring…" once the grade it started actually
    finishes, replacing it with the move's own outcome."""
    folder, _paths = _folder(tmp_path)
    d1, _ = _graded(qtbot, folder)
    d1.browser.select_none()
    d1.verdict_strip.move_btn.click()            # everything -> rejected/
    d2, _ = _graded(qtbot, folder)                # reopens to nothing at top
    assert d2._stats == []
    d2.verdict_strip.back_btn.click()
    assert "Measuring 6 frames that came back" in d2.verdict_strip.message.text(), (
        "the promise while the full re-grade is still running")
    qtbot.waitUntil(lambda: not d2._busy, timeout=3000)
    assert d2.verdict_strip.message.text() == "Moved 6 frames back."
    assert len(d2._stats) == 6


# --- I1 (final fix wave, 2026-09-28): the verdict must not pay for a move's
# report line, at the 1280x800 floor -------------------------------------------------

@pytest.fixture
def styled():
    """The real stylesheet, not the bare offscreen default. Its padding is
    part of what tips a move's report line over the 740 px floor at all --
    unstyled, `_folder`'s six frames never reach the fold chain's verdict
    step, and the guard below would pass whether or not the fix is there
    (measured 2026-09-28 while building the mutation proof)."""
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(theme.build_stylesheet())
    yield
    app.setStyleSheet(before)


def _graded_at_740(qtbot, folder, runner=None, answer=True):
    """Like `_graded`, but shown at the 1280x800 floor (740 px of room)
    BEFORE grading -- the order a real open takes, and the one that
    reproduces I1: it is grading AFTER the show that grows the dialog
    through its settled minimum, the same path a move's report later
    grows it through again."""
    d = StackDialog(Settings())
    qtbot.addWidget(d)
    d.browser.preview_controller.loader = _blank
    d._grade_runner = runner or _runner()
    asked = []
    d._confirm = lambda title, text: (asked.append(text), answer)[1]
    d._available_height = lambda: 740
    d.resize(1280, 700)
    d.show()
    qtbot.waitExposed(d)
    d.folder_edit.setText(str(folder))
    d.grade()
    qtbot.waitUntil(lambda: not d._busy, timeout=3000)
    qtbot.wait(50)          # let the settled fit land
    return d, asked


def test_move_does_not_compact_the_verdict_at_the_1280_floor(qtbot, tmp_path, styled):
    """I1: at 740 px of room, the move's report line used to tip the dialog
    a few pixels past the floor, and _refit recovered the height by
    compacting the verdict to its headline -- so the facts he just asked to
    see vanish at the exact moment he acts on them. Fixed by keeping the
    verdict step out of `_refit`'s squeeze (`allow_verdict_squeeze=False`):
    the frame list gives up the height instead, and the grade-time fit
    (`_on_graded`, unaffected here) keeps its own right to compact the
    verdict for genuinely new content."""
    folder, _paths = _folder(tmp_path)
    d, _ = _graded_at_740(qtbot, folder)
    assert not d.verdict_strip.is_compact(), "fixture already needed the fold -- not testing the move"
    assert d.verdict_strip.details_shown()
    d.verdict_strip.move_btn.click()
    qtbot.wait(50)
    assert d.verdict_strip.details_shown(), "the move collapsed the verdict to its headline"
    assert not d.verdict_strip.is_compact()
    assert d.height() <= 740, f"{d.height()} px on a 740 px screen"


def test_move_back_does_not_compact_the_verdict_at_the_1280_floor(qtbot, tmp_path, styled):
    """I1, the same for Move back: its own report line must not cost the
    verdict its facts either."""
    folder, _paths = _folder(tmp_path)
    d, _ = _graded_at_740(qtbot, folder)
    d.verdict_strip.move_btn.click()
    qtbot.wait(50)
    assert d.verdict_strip.details_shown() and not d.verdict_strip.is_compact()
    d.verdict_strip.back_btn.click()
    qtbot.wait(50)
    assert d.verdict_strip.details_shown(), "move back collapsed the verdict to its headline"
    assert not d.verdict_strip.is_compact()
    assert d.height() <= 740, f"{d.height()} px on a 740 px screen"


def _reopened_with_zero_slack(qtbot, folder):
    """A folder reopened with the dialog pinned EXACTLY to its own natural
    minimum (chart folded, no message yet) — the same boundary condition
    I1's own repro needed. A spacious re-open first measures that natural
    minimum; the real dialog is then built pinned to it from the start, so
    the very next byte of growth is what I1/R8 are about, not a fixture
    that merely happens to be big enough."""
    probe = StackDialog(Settings())
    qtbot.addWidget(probe)
    probe._available_height = lambda: 4000
    probe.browser.preview_controller.loader = _blank
    probe._grade_runner = _runner()
    probe.folder_edit.setText(str(folder))
    probe.show()
    qtbot.waitExposed(probe)
    probe.grade()
    qtbot.waitUntil(lambda: not probe._busy, timeout=3000)
    qtbot.wait(50)
    panel = probe.browser.chart_panel
    panel.blockSignals(True)
    panel.set_folded(True)
    panel.blockSignals(False)
    room = probe._natural_minimum_height()
    probe.close()

    d = StackDialog(Settings())
    qtbot.addWidget(d)
    d.browser.preview_controller.loader = _blank
    d._grade_runner = _runner()
    d._available_height = lambda: room
    d.resize(1280, 700)
    d.show()
    qtbot.waitExposed(d)
    d.folder_edit.setText(str(folder))
    d.grade()
    qtbot.waitUntil(lambda: not d._busy, timeout=3000)
    qtbot.wait(50)
    return d, room


def test_move_back_after_a_reopen_does_not_compact_the_verdict_at_the_1280_floor(
        qtbot, tmp_path, styled):
    """R8: the same bug as I1, reached through a different door.
    Reopening a folder with frames still parked in rejected/ from an
    earlier session, then pressing "Move them back", merges the restored
    names in through `_on_restored_graded` -- a grade-time fit, not
    `_refit`, so it kept `allow_verdict_squeeze`'s default. But this merge
    is not "genuinely new content": the list gains rows for free (no extra
    height) and the verdict gets SHORTER ("Not counted N more in
    rejected/" leaves) -- the only thing that grew the dialog here is the
    same lingering "Moved N frames back." report line I1 already covers,
    just reached through this door instead."""
    folder, _paths = _folder(tmp_path)
    d1, _ = _graded(qtbot, folder)
    d1.verdict_strip.move_btn.click()          # Light_01, Light_03 -> rejected/
    d1.close()
    d2, room = _reopened_with_zero_slack(qtbot, folder)   # reopen: 4 listed, 2 parked
    assert d2.verdict_strip.back_btn.isVisible(), "fixture: nothing parked in rejected/"
    assert d2.verdict_strip.details_shown() and not d2.verdict_strip.is_compact()
    d2.verdict_strip.back_btn.click()
    qtbot.waitUntil(lambda: not d2._busy, timeout=3000)
    qtbot.wait(50)
    assert d2.verdict_strip.details_shown(), "the merge collapsed the verdict to its headline"
    assert not d2.verdict_strip.is_compact()
    assert d2.height() <= room, f"{d2.height()} px on a {room} px screen"


def test_showing_the_chart_at_740_may_compact_the_verdict_but_details_recovers_it(
        qtbot, tmp_path, styled):
    """M8: "▸ Show chart" is his own click, not a resize the code sprung on
    him behind his back (I1 above) -- so it is allowed to run the same fold
    chain a grade does (help -> options -> chart -> verdict), verdict
    included, if the chart alone does not leave enough room. What must
    still hold either way: the dialog stays on screen, and "details ▸" --
    his very next click -- gets the facts straight back."""
    folder, _paths = _folder(tmp_path)
    d, _ = _graded_at_740(qtbot, folder)
    panel = d.browser.chart_panel
    assert panel.is_folded()
    panel.fold_btn.click()
    qtbot.wait(50)
    assert not panel.is_folded(), "folded again behind his back"
    assert d.height() <= 740, f"{d.height()} px on a 740 px screen"
    if d.verdict_strip.is_compact():
        d.verdict_strip.more_btn.click()
        qtbot.wait(50)
        assert d.verdict_strip.details_shown(), "'details ▸' did not bring the facts back"
        assert d.height() <= 740
