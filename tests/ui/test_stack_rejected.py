"""Stack's rejected folder (spec 2026-09-27 decision 7, §5, §7).

His ORIGINAL subs are what this moves. Every test here builds its own folder
inside tmp_path — never a real capture folder — and checks bytes and mtimes,
not just names.
"""
import os

import numpy as np
import pytest

from nocturne.settings import Settings
from nocturne.stacking.frames import discover_subs
from nocturne.stacking.grade import REASON_NOT_RAW, FrameStats
from nocturne.stacking.reject_move import MANIFEST_NAME, read_manifest
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
    qtbot.waitUntil(lambda: bool(loads) and loads[-1] == str(folder / "Light_01.fit"),
                    timeout=2000)
    d.verdict_strip.move_btn.click()
    qtbot.waitUntil(lambda: loads[-1] == str(folder / "rejected" / "Light_01.fit"),
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
    qtbot.waitUntil(lambda: len(calls) == 2 and not d2._busy, timeout=3000)
    assert calls[1] == paths and len(d2.browser.frames()) == 6
    assert outside_rejected(tree(tmp_path)) == before
    assert "Measuring the folder again" in d2.verdict_strip.message.text()


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
