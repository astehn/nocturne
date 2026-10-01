"""The move record also keeps each moved frame's MEASUREMENTS, so a reopened
folder can still draw the night's end on the chart, in grey (Andreas,
2026-10-01: on reopen the moved frames had no dot at all). The safety path —
read_manifest and Move them back — reads only names, exactly as before."""
import json
import os
from datetime import datetime, timezone

from nocturne.stacking import reject_move as rm
from nocturne.stacking.reject_move import MANIFEST_NAME, REJECTED_DIR

from tests.stacking.test_reject_move import night, rej, tree  # noqa: F401

T = datetime(2026, 10, 1, 5, 54, 49, tzinfo=timezone.utc)


def _measured(paths):
    return {os.path.abspath(p): {"captured": T, "fwhm": 2.6, "star_count": 812,
                                 "reason": "Stars trailed"} for p in paths}


def _record(folder):
    with open(os.path.join(rej(folder), MANIFEST_NAME), encoding="utf-8") as fh:
        return json.load(fh)


def test_the_record_keeps_the_measurements(night):
    folder, paths = night
    rm.move_to_rejected(folder, paths[:2], paths, measured=_measured(paths[:2]))
    rec = _record(folder)
    assert rec["version"] == 1, "older Nocturne versions must still read it"
    m = rec["moved"][0]["measured"]
    assert m == {"captured": T.isoformat(), "fwhm": 2.6, "star_count": 812,
                 "reason": "Stars trailed"}


def test_the_safety_reader_is_unchanged(night):
    """Move them back reads names and times only; the extra block is ignored."""
    folder, paths = night
    rm.move_to_rejected(folder, paths[:2], paths, measured=_measured(paths[:2]))
    assert all(set(e) == {"name", "moved_at"} for e in rm.read_manifest(folder))


def test_move_back_still_restores_everything_exactly(night, tmp_path):
    folder, paths = night
    before = tree(str(tmp_path))
    rm.move_to_rejected(folder, paths[:3], paths, measured=_measured(paths[:3]))
    rm.move_back(folder)
    after = {k: v for k, v in tree(str(tmp_path)).items()
             if REJECTED_DIR not in k.split(os.sep)}
    assert after == {k: v for k, v in before.items()}


def test_history_lists_what_is_still_in_rejected(night):
    folder, paths = night
    rm.move_to_rejected(folder, paths[:2], paths, measured=_measured(paths[:2]))
    hist = rm.read_moved_history(folder)
    assert sorted(h["path"] for h in hist) == sorted(
        os.path.join(os.path.abspath(rej(folder)), os.path.basename(p)) for p in paths[:2])
    h = hist[0]
    assert h["captured"] == T and h["fwhm"] == 2.6 and h["star_count"] == 812
    assert h["reason"] == "Stars trailed"


def test_a_frame_put_back_by_hand_drops_out_of_the_history(night):
    folder, paths = night
    rm.move_to_rejected(folder, paths[:2], paths, measured=_measured(paths[:2]))
    name = os.path.basename(paths[0])
    os.rename(os.path.join(rej(folder), name), paths[0])
    assert [os.path.basename(h["path"]) for h in rm.read_moved_history(folder)] == [
        os.path.basename(paths[1])]


def test_old_records_and_frames_moved_without_measurements_have_no_history(night):
    folder, paths = night
    rm.move_to_rejected(folder, paths[:2], paths)
    assert rm.read_moved_history(folder) == []


def test_the_history_reader_never_raises(night):
    """Chart-only: a damaged record is the safety path's business to report."""
    folder, paths = night
    rm.move_to_rejected(folder, paths[:1], paths, measured=_measured(paths[:1]))
    with open(os.path.join(rej(folder), MANIFEST_NAME), "w") as fh:
        fh.write("{not json")
    assert rm.read_moved_history(folder) == []
    assert rm.read_moved_history(os.path.join(folder, "nowhere")) == []


def test_junk_values_are_skipped_not_trusted(night):
    folder, paths = night
    rm.move_to_rejected(folder, paths[:3], paths, measured=_measured(paths[:3]))
    rec = _record(folder)
    rec["moved"][0]["measured"]["fwhm"] = "NaN"
    rec["moved"][1]["measured"] = ["not", "a", "dict"]
    with open(os.path.join(rej(folder), MANIFEST_NAME), "w") as fh:
        json.dump(rec, fh)
    assert [os.path.basename(h["path"]) for h in rm.read_moved_history(folder)] == [
        rec["moved"][2]["name"]]


def test_non_finite_measurements_are_not_written(night):
    folder, paths = night
    bad = _measured(paths[:1])
    bad[os.path.abspath(paths[0])]["fwhm"] = float("nan")
    rm.move_to_rejected(folder, paths[:1], paths, measured=bad)
    assert "measured" not in _record(folder)["moved"][0]


def test_a_second_move_keeps_the_first_batchs_measurements(night):
    folder, paths = night
    rm.move_to_rejected(folder, paths[:2], paths, measured=_measured(paths[:2]))
    rm.move_to_rejected(folder, paths[2:3], paths, measured=_measured(paths[2:3]))
    assert len(rm.read_moved_history(folder)) == 3


def test_a_partial_move_back_keeps_the_rest_measured(night, monkeypatch):
    """Move them back rewrites the record with what stayed; what stayed keeps
    its measurements."""
    folder, paths = night
    rm.move_to_rejected(folder, paths[:3], paths, measured=_measured(paths[:3]))
    # One of them is put back by hand, then Move them back runs for the rest:
    # a stale entry is dropped, the record rewritten.
    name = os.path.basename(paths[0])
    os.rename(os.path.join(rej(folder), name), paths[0])
    blocker = paths[1]                       # make one move-back refuse: name taken
    with open(blocker, "wb") as fh:
        fh.write(b"someone else's file")
    try:
        rm.move_back(folder)
    except rm.RejectMoveError:
        pass
    still = [os.path.basename(h["path"]) for h in rm.read_moved_history(folder)]
    assert os.path.basename(paths[1]) in still, "what stayed lost its measurements"
