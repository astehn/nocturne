"""Moving into rejected/ with frames from several folders (spec 2026-09-28
§9.7): each frame into ITS OWN folder's rejected/, with every §5 safety rule
per folder. His original subs are what this moves: every folder here is
built under tmp_path, and bytes and mtimes are checked, not just names."""
import json
import os
import time

import numpy as np
import pytest

from nocturne.settings import Settings
from nocturne.stacking.capture_time import read_capture_time
from nocturne.stacking.grade import FrameStats
from nocturne.stacking.reject_move import MANIFEST_NAME, read_manifest
from nocturne.ui.stack_dialog import StackDialog
from tests.ui.test_stack_add_folder import _generic, _seestar_folder
from tests.ui.test_stack_rejected import tree


@pytest.fixture(autouse=True)
def stockholm(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Stockholm")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


SOFT = ("223100", "223300")          # the second and fourth sub of each folder


def _runner(paths, on_progress=None, strictness="normal"):
    """The SOFT subs — and _generic's Light_001.fit — at FWHM 3.2, which
    judge() rejects against 2.5."""
    out = []
    for p in sorted(paths):
        name = os.path.basename(p)
        soft = any(t in name for t in SOFT) or name == "Light_001.fit"
        s = FrameStats(p, 800, 3.2 if soft else 2.5, 1000.0, 0.5, True, exposure=10.0)
        s.captured = read_capture_time(p)
        out.append(s)
    return out


def _dialog(qtbot, first, *more, answer=True):
    d = StackDialog(Settings())
    qtbot.addWidget(d)
    d._available_height = lambda: 4000
    d.browser.preview_controller.loader = lambda p: np.zeros((8, 8, 3), np.float32)
    d._grade_runner = _runner
    asked = []
    d._confirm = lambda title, text: (asked.append(text), answer)[1]
    d.folder_edit.setText(str(first))
    d.grade()
    qtbot.waitUntil(lambda: not d._busy, timeout=3000)
    for folder in more:
        d.add_folder(str(folder))
        qtbot.waitUntil(lambda: not d._busy, timeout=3000)
    return d, asked


def _two(tmp_path):
    a = _seestar_folder(tmp_path, "Sh2-108", "20260921")
    b = _seestar_folder(tmp_path, "night 2", "20260926")
    return a, b


def _rejected(folder):
    rej = folder / "rejected"
    return sorted(n for n in os.listdir(rej) if n != MANIFEST_NAME) if rej.exists() else []


def test_each_frame_goes_into_its_own_folders_rejected(qtbot, tmp_path):
    a, b = _two(tmp_path)
    before = tree(tmp_path)
    d, asked = _dialog(qtbot, a, b)
    assert d.verdict_strip.move_btn.text() == "Move 4 frames to rejected/…"
    d.verdict_strip.move_btn.click()
    assert asked == ["Move 4 rejected frames — 2 into Sh2-108/rejected, 2 into "
                     "night 2/rejected? Nothing is deleted; you can move them back."]
    assert _rejected(a) == [f"Light_SH2-108_10.0s_LP_20260921-{t}.fit" for t in SOFT]
    assert _rejected(b) == [f"Light_SH2-108_10.0s_LP_20260926-{t}.fit" for t in SOFT]
    assert [e["name"] for e in read_manifest(str(a))] == _rejected(a)
    assert [e["name"] for e in read_manifest(str(b))] == _rejected(b)
    after = tree(tmp_path)
    for folder in (a, b):
        for name in _rejected(folder):
            rel_old = os.path.relpath(folder / name, tmp_path)
            rel_new = os.path.relpath(folder / "rejected" / name, tmp_path)
            assert after[rel_new] == before[rel_old], "bytes or mtime changed"
    untouched = {k: v for k, v in after.items() if "rejected" not in k}
    assert untouched == {k: v for k, v in before.items()
                         if os.path.basename(k) not in _rejected(a) + _rejected(b)}
    assert d.status.text() == ("Moved 2 frames into Sh2-108/rejected and 2 frames into "
                               "night 2/rejected. Nothing was deleted.")


def test_one_folder_asks_exactly_as_before(qtbot, tmp_path):
    a, _b = _two(tmp_path)
    d, asked = _dialog(qtbot, a)
    d.verdict_strip.move_btn.click()
    assert asked == ["Move 2 rejected frames into Sh2-108/rejected? Nothing is deleted; "
                     "you can move them back."]


def test_the_same_names_in_two_folders_never_collide(qtbot, tmp_path):
    a = _generic(tmp_path / "first", ["2026-09-21T20:30:00", "2026-09-21T20:31:00"] * 3)
    b = _generic(tmp_path / "second", ["2026-09-26T20:30:00", "2026-09-26T20:31:00"] * 3)
    d, _asked = _dialog(qtbot, a, b)
    assert len(d._stats) == 12
    d.verdict_strip.move_btn.click()
    assert _rejected(a) == ["Light_001.fit"] and _rejected(b) == ["Light_001.fit"]
    assert (a / "rejected" / "Light_001.fit").read_bytes() != b"" \
        and not (a / "Light_001.fit").exists() and not (b / "Light_001.fit").exists()
    d.verdict_strip.back_btn.click()
    assert _rejected(a) == [] and _rejected(b) == []
    assert (a / "Light_001.fit").exists() and (b / "Light_001.fit").exists()
    assert d.status.text().startswith("Moved 2 frames back.")


def test_a_collision_in_one_folder_leaves_the_folder_before_it_done(qtbot, tmp_path):
    a, b = _two(tmp_path)
    (b / "rejected").mkdir()
    blocker = b / "rejected" / "Light_SH2-108_10.0s_LP_20260926-223100.fit"
    blocker.write_bytes(b"his own file")
    d, _asked = _dialog(qtbot, a, b)
    snap_b = tree(b)
    d.verdict_strip.move_btn.click()
    assert _rejected(a) == [f"Light_SH2-108_10.0s_LP_20260921-{t}.fit" for t in SOFT]
    assert tree(b) == snap_b, "night 2 was touched"
    assert d.status.text().startswith("Moved 2 frames into Sh2-108/rejected. Nothing was "
                                      "deleted. night 2: ")
    assert "nothing was moved" in d.status.text()
    assert sum(1 for s in d._stats if s.moved) == 2
    assert d.verdict_strip.back_btn.text() == "Move them back (2)"


def test_move_them_back_serves_every_folder(qtbot, tmp_path):
    a, b = _two(tmp_path)
    before = tree(tmp_path)
    d, _asked = _dialog(qtbot, a, b)
    d.verdict_strip.move_btn.click()
    assert d.verdict_strip.back_btn.text() == "Move them back (4)"
    d.verdict_strip.back_btn.click()
    after = tree(tmp_path)
    for folder in (a, b):
        assert _rejected(folder) == []
    assert {k: v for k, v in after.items() if "rejected" not in k} == before
    assert not any(s.moved for s in d._stats)
    assert d.status.text().startswith("Moved 4 frames back.")


def test_reopened_both_folders_offer_theirs_back_and_count_what_is_parked(qtbot, tmp_path):
    a, b = _two(tmp_path)
    d1, _ = _dialog(qtbot, a, b)
    d1.verdict_strip.move_btn.click()
    d1.close()
    d2, _ = _dialog(qtbot, a)
    assert d2.verdict_strip.back_btn.text() == "Move them back (2)"
    d2.add_folder(str(b))
    qtbot.waitUntil(lambda: not d2._busy, timeout=3000)
    assert d2.verdict_strip.back_btn.text() == "Move them back (4)"
    assert ("Not counted", "4 more in rejected/") in d2.verdict_strip.fact_pairs()
    d2.verdict_strip.back_btn.click()
    qtbot.waitUntil(lambda: not d2._busy, timeout=3000)
    assert len(d2._stats) == 12 and _rejected(a) == [] and _rejected(b) == []
    assert ("Not counted", "4 more in rejected/") not in d2.verdict_strip.fact_pairs()


def test_a_damaged_record_in_one_folder_stops_the_move_before_asking(qtbot, tmp_path):
    a, b = _two(tmp_path)
    d, asked = _dialog(qtbot, a, b)
    (b / "rejected").mkdir()
    (b / "rejected" / MANIFEST_NAME).write_text("{not json")
    before = tree(tmp_path)
    d.verdict_strip.move_btn.click()
    assert asked == [] and tree(tmp_path) == before
    assert "damaged" in d.status.text()


def test_a_damaged_record_in_one_folder_still_lets_the_other_move_back(qtbot, tmp_path):
    """The damaged one is the FIRST folder, so the second is still served."""
    a, b = _two(tmp_path)
    d, _asked = _dialog(qtbot, a, b)
    d.verdict_strip.move_btn.click()
    manifest = a / "rejected" / MANIFEST_NAME
    manifest.write_text("{not json")
    snap_a = tree(a)
    d.verdict_strip.back_btn.click()
    assert _rejected(b) == [] and tree(a) == snap_a
    assert d.status.text().startswith("Moved 2 frames back.")
    assert "damaged" in d.status.text()


def test_a_refusal_in_the_first_folder_stops_before_the_next_is_touched(qtbot, tmp_path):
    """One failure is one thing to read: nothing after it is attempted, so
    he is never left with a half he did not see coming."""
    a, b = _two(tmp_path)
    (a / "rejected").mkdir()
    (a / "rejected" / "Light_SH2-108_10.0s_LP_20260921-223100.fit").write_bytes(b"his")
    d, _asked = _dialog(qtbot, a, b)
    before = tree(tmp_path)
    d.verdict_strip.move_btn.click()
    assert tree(tmp_path) == before
    assert d.status.text().startswith("Sh2-108: ") and "nothing was moved" in d.status.text()
    assert not any(s.moved for s in d._stats)
