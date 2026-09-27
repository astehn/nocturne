"""Moving rejected subs into rejected/ and back (spec 2026-09-27 §5, §7).

These are the safety rules for his ORIGINAL subs. Every test works inside
tmp_path ONLY — nothing here may ever be pointed at a real capture folder.
"""
import errno
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

import pytest

from nocturne.stacking import reject_move as rm
from nocturne.stacking.frames import discover_subs
from nocturne.stacking.reject_move import (MANIFEST_NAME, REJECTED_DIR,
                                           RejectMoveError, describe_names,
                                           move_back, move_to_rejected,
                                           pending_back, read_manifest)

NOW = datetime(2026, 9, 27, 21, 30, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 28, 21, 30, tzinfo=timezone.utc)
AS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def tree(root):
    """Every entry under root: (bytes, mtime_ns) for a file, the target for a
    link, "dir" for a folder. Links are recorded, never followed."""
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


def without_rejected(snap):
    prefix = os.path.join("Sh2-108", REJECTED_DIR)
    return {k: v for k, v in snap.items() if not k.startswith(prefix)}


@pytest.fixture
def night(tmp_path):
    """Six subs with distinct bytes and distinct, fixed mtimes, and one file
    OUTSIDE the folder that nothing may ever touch."""
    folder = tmp_path / "Sh2-108"
    folder.mkdir()
    paths = []
    for i in range(6):
        p = folder / f"Light_{i:02d}.fit"
        p.write_bytes(bytes([65 + i]) * (300 + i))
        stamp = 1_600_000_000_000_000_000 + i * 1_000_000_000
        os.utime(p, ns=(stamp, stamp))
        paths.append(str(p))
    (tmp_path / "outside.fit").write_bytes(b"not in the folder")
    return str(folder), paths


def rej(folder):
    return os.path.join(folder, REJECTED_DIR)


# --- moving ----------------------------------------------------------------

def test_it_moves_exactly_the_given_files_and_touches_nothing_else(night, tmp_path):
    folder, paths = night
    before = tree(tmp_path)
    moved = move_to_rejected(folder, [paths[1], paths[3]], paths, now=NOW)
    assert moved == {paths[1]: os.path.join(rej(folder), "Light_01.fit"),
                     paths[3]: os.path.join(rej(folder), "Light_03.fit")}
    after = tree(tmp_path)
    for i in (1, 3):
        name = f"Light_0{i}.fit"
        assert after[os.path.join("Sh2-108", REJECTED_DIR, name)] == before[os.path.join("Sh2-108", name)]
        assert os.path.join("Sh2-108", name) not in after
    untouched = {k: v for k, v in before.items() if "Light_01" not in k and "Light_03" not in k}
    assert {k: after[k] for k in untouched} == untouched


def test_it_renames_and_never_copies(night):
    folder, paths = night
    inode = os.stat(paths[1]).st_ino
    moved = move_to_rejected(folder, [paths[1]], paths, now=NOW)
    assert os.stat(moved[paths[1]]).st_ino == inode, "a copy, not a rename"


def test_the_module_cannot_copy_or_delete_his_files():
    with open(rm.__file__, encoding="utf-8") as fh:
        src = fh.read()
    assert "shutil" not in src
    for forbidden in ("os.remove(", "rmdir(", "rmtree(", "copyfile(", "copy2("):
        assert forbidden not in src, forbidden
    # The one unlink removes Nocturne's OWN half-written manifest temp file.
    assert src.count("os.unlink(") == 1 and "os.unlink(tmp)" in src
    # m1: a native no-replace rename (renamex_np / renameat2, via ctypes) is
    # allowed — it is still just a RENAME, never a copy or a delete of one of
    # his files — but nothing may reach for a native delete to sidestep the
    # os.unlink guard above.
    for forbidden in ("libc.unlink(", "libc.remove(", "libc.rmdir(", "unlink_np("):
        assert forbidden not in src, forbidden


def test_no_replace_rename_refuses_a_dest_that_appeared_after_the_check(night):
    """m1: the file that lands in rejected/ between the up-front collision
    check and this file's own rename must not be silently replaced — proven
    against the real OS primitive on this Mac, not a Python-level check."""
    folder, paths = night
    os.mkdir(rej(folder))
    dst = os.path.join(rej(folder), "Light_01.fit")
    with open(dst, "wb") as fh:
        fh.write(b"intruder, arrived after the up-front check passed")
    with pytest.raises(FileExistsError, match="appeared in Sh2-108/rejected"):
        rm._rename_no_replace(paths[1], dst, rm._where(folder))
    with open(dst, "rb") as fh:
        assert fh.read() == b"intruder, arrived after the up-front check passed"
    assert os.path.isfile(paths[1])   # never moved


def test_no_replace_rename_fallback_also_refuses(night, monkeypatch):
    """The check-then-os.rename fallback (used where the OS offers no native
    no-replace rename) must refuse a collision too."""
    folder, paths = night
    os.mkdir(rej(folder))
    dst = os.path.join(rej(folder), "Light_01.fit")
    with open(dst, "wb") as fh:
        fh.write(b"intruder")
    monkeypatch.setattr(rm, "_native_no_replace_rename", lambda src, dst, dest: False)
    with pytest.raises(FileExistsError):
        rm._rename_no_replace(paths[1], dst, rm._where(folder))
    with open(dst, "rb") as fh:
        assert fh.read() == b"intruder"
    assert os.path.isfile(paths[1])


def test_no_replace_rename_into_the_capture_folder_refuses_too(night):
    """N2: move_back's own rename (into the capture folder, not rejected/)
    goes through the same no-replace helper — a file appearing at home
    between the check and the move-back rename must not be replaced, and the
    collision message names the capture folder, not rejected/."""
    folder, paths = night
    move_to_rejected(folder, [paths[1]], paths, now=NOW)
    with open(paths[1], "wb") as fh:
        fh.write(b"a new Light_01, arrived after the check passed")
    parked = os.path.join(rej(folder), "Light_01.fit")
    with pytest.raises(FileExistsError, match=r"appeared in Sh2-108(?!/)"):
        rm._rename_no_replace(parked, paths[1], rm._label(folder))
    with open(paths[1], "rb") as fh:
        assert fh.read() == b"a new Light_01, arrived after the check passed"
    assert os.path.isfile(parked)


def test_a_round_trip_calls_no_delete_at_all(night, monkeypatch):
    folder, paths = night
    calls = []
    monkeypatch.setattr(rm.os, "unlink", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(rm.os, "remove", lambda *a, **k: calls.append(a))
    move_to_rejected(folder, [paths[1], paths[3]], paths, now=NOW)
    move_back(folder)
    assert calls == []


def test_the_record_names_each_file_and_when_and_leaves_no_temp_file(night):
    folder, paths = night
    move_to_rejected(folder, [paths[1], paths[3]], paths, now=NOW)
    with open(os.path.join(rej(folder), MANIFEST_NAME), encoding="utf-8") as fh:
        data = json.load(fh)
    assert data == {"version": 1, "moved": [
        {"name": "Light_01.fit", "moved_at": "2026-09-27T21:30:00+00:00"},
        {"name": "Light_03.fit", "moved_at": "2026-09-27T21:30:00+00:00"}]}
    assert sorted(os.listdir(rej(folder))) == [MANIFEST_NAME, "Light_01.fit", "Light_03.fit"]


def test_the_record_is_replaced_atomically(night, monkeypatch):
    folder, paths = night
    replaced = []
    real = os.replace
    monkeypatch.setattr(rm.os, "replace", lambda a, b: (replaced.append((a, b)), real(a, b))[1])
    move_to_rejected(folder, [paths[1]], paths, now=NOW)
    assert len(replaced) == 1
    tmp, dst = replaced[0]
    assert dst == os.path.join(rej(folder), MANIFEST_NAME)
    assert os.path.dirname(tmp) == rej(folder), "temp file on another folder: not atomic"


def test_a_record_write_that_fails_moves_nothing_and_keeps_the_old_record(night, tmp_path, monkeypatch):
    folder, paths = night
    move_to_rejected(folder, [paths[1]], paths, now=NOW)
    before = tree(tmp_path)

    def full_disk(*_a, **_k):
        raise OSError("No space left on device")

    monkeypatch.setattr(rm.json, "dump", full_disk)
    with pytest.raises(RejectMoveError, match="nothing was moved"):
        move_to_rejected(folder, [paths[3]], paths, now=LATER)
    assert tree(tmp_path) == before, "moved a file, or left a temp file, or changed the record"


def test_a_manifest_write_that_hits_a_bad_name_moves_nothing(night, tmp_path, monkeypatch):
    """m4: a name from surrogateescape-decoded non-UTF-8 bytes (a foreign-
    formatted network share) can't be re-encoded by a plain UTF-8 json.dump —
    UnicodeEncodeError, a ValueError, not an OSError. Simulated here: APFS
    won't let us create the literal byte sequence to reproduce it for real."""
    folder, paths = night
    before = tree(tmp_path)

    def bad_name(*_a, **_k):
        raise UnicodeEncodeError("utf-8", "\udce9", 0, 1, "surrogates not allowed")

    monkeypatch.setattr(rm.json, "dump", bad_name)
    with pytest.raises(RejectMoveError, match="nothing was moved"):
        move_to_rejected(folder, [paths[1]], paths, now=NOW)
    # An empty rejected/ can be left behind by a first-move failure (m5,
    # accepted as harmless per Ruling R2) — nothing else may change.
    assert without_rejected(tree(tmp_path)) == without_rejected(before)
    assert not os.path.exists(os.path.join(rej(folder), MANIFEST_NAME))


def test_moving_more_later_adds_to_the_record(night):
    folder, paths = night
    move_to_rejected(folder, [paths[1]], paths, now=NOW)
    move_to_rejected(folder, [paths[3]], paths, now=LATER)
    assert [e["name"] for e in read_manifest(folder)] == ["Light_01.fit", "Light_03.fit"]


def test_moving_a_file_again_replaces_its_stale_entry(night):
    """Moved, then put back by hand, then moved again: one entry, the new one."""
    folder, paths = night
    move_to_rejected(folder, [paths[1]], paths, now=NOW)
    os.rename(os.path.join(rej(folder), "Light_01.fit"), paths[1])       # by hand
    move_to_rejected(folder, [paths[1]], paths, now=LATER)
    assert read_manifest(folder) == [{"name": "Light_01.fit",
                                      "moved_at": "2026-09-28T21:30:00+00:00"}]


def test_nothing_to_move_creates_nothing(night, tmp_path):
    folder, paths = night
    before = tree(tmp_path)
    assert move_to_rejected(folder, [], paths, now=NOW) == {}
    assert tree(tmp_path) == before


def test_rejected_frames_are_never_listed_again(night):
    """discover_subs is not recursive: rejected/ is invisible to the next grade."""
    folder, paths = night
    move_to_rejected(folder, [paths[1], paths[3]], paths, now=NOW)
    assert discover_subs(folder) == [paths[0], paths[2], paths[4], paths[5]]


# --- N1: two spellings of one file are the same inode -----------------------

def test_case_variant_spellings_of_one_file_are_moved_once(night):
    """N1: 'Light_01.fit' and 'light_01.fit' are the SAME file on
    case-insensitive APFS. Passing both must move it once, under the first
    spelling given, with one manifest entry — not a doubled entry, an
    original silently renamed out from under him, and a false 'still in
    rejected' (the destination path for the 2nd spelling looked like it
    existed because it case-insensitively matched the 1st spelling's
    already-moved file)."""
    folder, paths = night
    alias = os.path.join(folder, "light_01.fit")
    assert os.path.isfile(alias)          # same file, case-insensitive filesystem
    with open(paths[1], "rb") as fh:
        original_bytes = fh.read()
    moved = move_to_rejected(folder, [paths[1], alias], paths + [alias], now=NOW)
    assert moved == {paths[1]: os.path.join(rej(folder), "Light_01.fit")}
    assert read_manifest(folder) == [{"name": "Light_01.fit",
                                      "moved_at": "2026-09-27T21:30:00+00:00"}]
    assert sorted(os.listdir(rej(folder))) == [MANIFEST_NAME, "Light_01.fit"]
    result = move_back(folder)
    assert result.restored == ["Light_01.fit"]
    assert (result.taken, result.refused, result.missing, result.failed) == ([], [], [], "")
    with open(paths[1], "rb") as fh:
        assert fh.read() == original_bytes
    assert read_manifest(folder) == []


def test_nfd_and_nfc_spellings_of_one_file_are_moved_once(night):
    """The NFD/NFC pairing named in the ruling: macOS resolves both
    spellings of an accented name to the same file, the same way APFS
    resolves a case variant."""
    folder, paths = night
    nfd_name = unicodedata.normalize("NFD", "Åé.fit")
    nfd_path = os.path.join(folder, nfd_name)
    with open(nfd_path, "wb") as fh:
        fh.write(b"nfd-bytes")
    on_disk = next(n for n in os.listdir(folder)
                   if n not in {os.path.basename(p) for p in paths})
    on_disk_path = os.path.join(folder, on_disk)
    nfc_path = os.path.join(folder, unicodedata.normalize("NFC", "Åé.fit"))
    assert os.path.isfile(nfc_path)       # same file under the other spelling
    graded = paths + [on_disk_path, nfc_path]
    moved = move_to_rejected(folder, [on_disk_path, nfc_path], graded, now=NOW)
    assert moved == {on_disk_path: os.path.join(rej(folder), on_disk)}
    assert read_manifest(folder) == [{"name": on_disk, "moved_at":
                                      "2026-09-27T21:30:00+00:00"}]
    result = move_back(folder)
    assert result.restored == [on_disk]
    assert (result.taken, result.refused, result.missing, result.failed) == ([], [], [], "")
    with open(on_disk_path, "rb") as fh:
        assert fh.read() == b"nfd-bytes"
    assert read_manifest(folder) == []


def test_already_claimed_detects_a_same_file_destination_under_another_spelling(night):
    """N1(b), direct: the guard inside the I1 branch is os.path.samefile
    against every destination already in `moved` — proven against the
    function itself, since the `wanted` dedup (N1a) already removes every
    input that would exercise this from move_to_rejected's own call path
    (both fixes close the same event: a second spelling of an already-moved
    file)."""
    folder, paths = night
    rej_dir = rej(folder)
    os.mkdir(rej_dir)
    dst1 = os.path.join(rej_dir, "Light_01.fit")
    os.rename(paths[1], dst1)
    same_file_other_spelling = os.path.join(rej_dir, "light_01.fit")
    assert rm._already_claimed(same_file_other_spelling, {paths[1]: dst1}) is True
    dst3 = os.path.join(rej_dir, "Light_03.fit")
    assert rm._already_claimed(dst3, {paths[1]: dst1}) is False
    assert rm._already_claimed(dst1, {}) is False


# --- R4: dedup hardening — stat failure, and inode alone is not enough ------

def test_a_file_that_vanishes_between_validation_and_dedup_is_refused(night, tmp_path, monkeypatch):
    """The dedup's os.stat(p) can raise a raw OSError if the file vanishes in
    the gap after the validation loop already confirmed it existed. Task 6
    catches only RejectMoveError, so this must surface as one, not escape."""
    folder, paths = night
    before = tree(tmp_path)
    real_stat = os.stat
    hit = []

    def vanish(p, *a, **k):
        if (sys._getframe(1).f_code.co_name == "move_to_rejected"
                and os.fspath(p) == paths[1] and not hit):
            hit.append(1)
            os.rename(paths[1], paths[1] + ".gone")
        return real_stat(p, *a, **k)

    monkeypatch.setattr(rm.os, "stat", vanish)
    with pytest.raises(RejectMoveError, match="Light_01.fit is a link, or is no longer there"):
        move_to_rejected(folder, [paths[1], paths[2]], paths, now=NOW)
    monkeypatch.undo()
    os.rename(paths[1] + ".gone", paths[1])       # restore the fixture for the comparison
    assert tree(tmp_path) == before
    assert not os.path.exists(rej(folder))        # dedup runs before rejected/ is created


def test_two_different_names_sharing_a_synthetic_inode_both_move(night, monkeypatch):
    """R4 fix 2: a share can synthesise the same st_ino for two genuinely
    different files. Dedup must require the (casefolded, NFD-normalized)
    NAME to match too, or it silently drops one of them — dropping a file
    he asked to reject, with no error at all, is worse than not deduping."""
    folder, paths = night
    real_stat = os.stat

    class FakeStat:
        def __init__(self, st):
            self.st_dev, self.st_ino, self.st_mode = st.st_dev, 42, st.st_mode

    def fake(p, *a, **k):
        st = real_stat(p, *a, **k)
        path = os.fspath(p)
        if os.path.dirname(path) == folder and os.path.basename(path).startswith("Light"):
            return FakeStat(st)
        return st

    monkeypatch.setattr(rm.os, "stat", fake)
    moved = move_to_rejected(folder, [paths[1], paths[2]], paths, now=NOW)
    monkeypatch.undo()
    assert moved == {paths[1]: os.path.join(rej(folder), "Light_01.fit"),
                     paths[2]: os.path.join(rej(folder), "Light_02.fit")}
    assert sorted(os.listdir(rej(folder))) == [MANIFEST_NAME, "Light_01.fit", "Light_02.fit"]
    assert [e["name"] for e in read_manifest(folder)] == ["Light_01.fit", "Light_02.fit"]


def test_hard_linked_names_both_move_as_separate_entries(night):
    """A hard link is genuinely two directory entries sharing one real inode
    but different names — not a spelling of the same file — so both must
    move under their own names, not collapse to one."""
    folder, paths = night
    hl = os.path.join(folder, "Light_hl.fit")
    os.link(paths[1], hl)
    graded = paths + [hl]
    moved = move_to_rejected(folder, [paths[1], hl], graded, now=NOW)
    assert moved == {paths[1]: os.path.join(rej(folder), "Light_01.fit"),
                     hl: os.path.join(rej(folder), "Light_hl.fit")}
    assert sorted(os.listdir(rej(folder))) == [MANIFEST_NAME, "Light_01.fit", "Light_hl.fit"]


# --- refusals: nothing moves -------------------------------------------------

def _refused(tmp_path, act, match):
    before = tree(tmp_path)
    with pytest.raises(RejectMoveError, match=match):
        act()
    assert tree(tmp_path) == before


def test_a_file_that_was_not_graded_is_refused(night, tmp_path):
    folder, paths = night
    _refused(tmp_path, lambda: move_to_rejected(folder, [paths[1]], paths[2:], now=NOW),
             "not graded")


def test_a_file_outside_the_folder_is_refused(night, tmp_path):
    folder, paths = night
    outside = str(tmp_path / "outside.fit")
    sub = os.path.join(folder, "deeper")
    os.mkdir(sub)
    deep = os.path.join(sub, "x.fit")
    with open(deep, "wb") as fh:
        fh.write(b"deep")
    for p in (outside, deep):
        _refused(tmp_path, lambda p=p: move_to_rejected(folder, [p], paths + [p], now=NOW),
                 "not directly inside")


def test_a_link_to_a_file_elsewhere_is_refused(night, tmp_path):
    folder, paths = night
    link = os.path.join(folder, "Light_link.fit")
    os.symlink(str(tmp_path / "outside.fit"), link)
    _refused(tmp_path, lambda: move_to_rejected(folder, [link], paths + [link], now=NOW),
             "link")


def test_a_rejected_folder_that_is_a_link_is_refused(night, tmp_path):
    folder, paths = night
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(str(elsewhere), rej(folder))
    _refused(tmp_path, lambda: move_to_rejected(folder, [paths[1]], paths, now=NOW), "link")
    _refused(tmp_path, lambda: move_back(folder), "link")
    with pytest.raises(RejectMoveError):
        pending_back(folder)
    assert os.listdir(elsewhere) == []
    os.remove(rej(folder))

    # A sibling folder next door, not somewhere external: the "does rejected/'s
    # real parent equal the capture folder" check does NOT catch this (a
    # sibling's parent IS the capture folder either way) — only the islink
    # check does. Both absolute and relative link spellings.
    flats = os.path.join(folder, "flats")
    os.mkdir(flats)
    os.symlink(flats, rej(folder))                      # absolute link
    _refused(tmp_path, lambda: move_to_rejected(folder, [paths[1]], paths, now=NOW), "link")
    assert os.listdir(flats) == []
    os.remove(rej(folder))

    os.symlink("flats", rej(folder))                     # relative link
    _refused(tmp_path, lambda: move_to_rejected(folder, [paths[1]], paths, now=NOW), "link")
    assert os.listdir(flats) == []


def test_a_file_called_rejected_is_refused(night, tmp_path):
    folder, paths = night
    with open(rej(folder), "wb") as fh:
        fh.write(b"a file, not a folder")
    _refused(tmp_path, lambda: move_to_rejected(folder, [paths[1]], paths, now=NOW),
             "not a folder")


def test_a_name_already_in_rejected_stops_everything(night, tmp_path):
    folder, paths = night
    os.mkdir(rej(folder))
    with open(os.path.join(rej(folder), "Light_03.fit"), "wb") as fh:
        fh.write(b"an older Light_03 he put here himself")
    _refused(tmp_path,
             lambda: move_to_rejected(folder, [paths[1], paths[3]], paths, now=NOW),
             r"Light_03\.fit is already in Sh2-108/rejected — nothing was moved")


def test_a_name_that_appears_mid_way_is_never_overwritten(night, tmp_path, monkeypatch):
    folder, paths = night
    intruder = os.path.join(rej(folder), "Light_03.fit")
    real = rm._rename_no_replace
    done = []

    def rename_then_intrude(src, dst, dest):
        real(src, dst, dest)
        if not done:
            done.append(1)
            with open(intruder, "wb") as fh:
                fh.write(b"intruder")

    before = tree(tmp_path)
    monkeypatch.setattr(rm, "_rename_no_replace", rename_then_intrude)
    with pytest.raises(RejectMoveError, match="nothing changed"):
        move_to_rejected(folder, [paths[1], paths[3]], paths, now=NOW)
    monkeypatch.undo()
    with open(intruder, "rb") as fh:
        assert fh.read() == b"intruder"
    assert without_rejected(tree(tmp_path)) == without_rejected(before)


@pytest.mark.skipif(AS_ROOT, reason="root ignores permissions")
def test_a_read_only_folder_moves_nothing_and_says_so(night, tmp_path):
    folder, paths = night
    os.chmod(folder, 0o555)
    try:
        _refused(tmp_path, lambda: move_to_rejected(folder, [paths[1]], paths, now=NOW),
                 "Can't write in Sh2-108")
    finally:
        os.chmod(folder, 0o755)


@pytest.mark.skipif(AS_ROOT, reason="root ignores permissions")
def test_a_read_only_rejected_folder_moves_nothing(night, tmp_path):
    folder, paths = night
    os.mkdir(rej(folder))
    os.chmod(rej(folder), 0o555)
    try:
        _refused(tmp_path, lambda: move_to_rejected(folder, [paths[1]], paths, now=NOW),
                 "Can't write in Sh2-108")
    finally:
        os.chmod(rej(folder), 0o755)


# --- failure part-way: roll back ------------------------------------------------

def test_a_failure_part_way_puts_everything_back(night, tmp_path, monkeypatch):
    """A network share refusing the third rename (EXDEV) — or any OSError."""
    folder, paths = night
    before = tree(tmp_path)
    real = rm._rename_no_replace
    calls = []

    def flaky(src, dst, dest):
        calls.append((src, dst))
        if len(calls) == 3:
            raise OSError(errno.EXDEV, "Cross-device link", src)
        real(src, dst, dest)

    monkeypatch.setattr(rm, "_rename_no_replace", flaky)
    with pytest.raises(RejectMoveError, match="Light_05.fit.*nothing changed"):
        move_to_rejected(folder, [paths[1], paths[3], paths[5]], paths, now=NOW)
    monkeypatch.undo()
    assert without_rejected(tree(tmp_path)) == before
    assert read_manifest(folder) == []
    assert sorted(os.listdir(rej(folder))) == [MANIFEST_NAME]


def test_a_roll_back_that_fails_names_what_is_left_and_records_it(night, tmp_path, monkeypatch):
    """N2: both the forward move AND the roll-back now share the one
    _rename_no_replace seam, so one mock with one call counter covers both."""
    folder, paths = night
    before = tree(tmp_path)
    real = rm._rename_no_replace
    calls = []

    def flaky(src, dst, dest):
        calls.append(1)
        if len(calls) in (3, 4):        # the 3rd move fails; so does putting Light_03 back
            raise OSError(errno.EIO, "Input/output error", src)
        real(src, dst, dest)

    monkeypatch.setattr(rm, "_rename_no_replace", flaky)
    with pytest.raises(RejectMoveError, match=r"Light_03\.fit could not be put back"):
        move_to_rejected(folder, [paths[1], paths[3], paths[5]], paths, now=NOW)
    monkeypatch.undo()
    assert [e["name"] for e in read_manifest(folder)] == ["Light_03.fit"]
    assert pending_back(folder) == ["Light_03.fit"]
    move_back(folder)
    assert without_rejected(tree(tmp_path)) == before


# --- I1: a rename that succeeds but raises anyway (a NAS timeout) ---------------

def test_a_rename_that_succeeds_but_still_raises_is_rolled_back_all_the_way_home(
        night, tmp_path, monkeypatch):
    """A network share can complete the 2nd rename and still raise ETIMEDOUT
    afterwards. The bookkeeping never saw it land — the filesystem must be
    asked, or the file sits in rejected/ unrecorded while the error claims
    'nothing changed'."""
    folder, paths = night
    before = tree(tmp_path)
    real = rm._rename_no_replace
    calls = []

    def lying(src, dst, dest):
        calls.append((src, dst))
        real(src, dst, dest)                             # the far end completes it
        if len(calls) == 2:
            raise OSError(errno.ETIMEDOUT, "Operation timed out", src)

    monkeypatch.setattr(rm, "_rename_no_replace", lying)
    with pytest.raises(RejectMoveError, match="nothing changed"):
        move_to_rejected(folder, [paths[1], paths[3], paths[5]], paths, now=NOW)
    monkeypatch.undo()
    assert without_rejected(tree(tmp_path)) == before
    assert read_manifest(folder) == []
    assert sorted(os.listdir(rej(folder))) == [MANIFEST_NAME]


def test_a_rename_that_secretly_succeeds_during_rollback_is_also_reported_home(
        night, tmp_path, monkeypatch):
    """The put-back rename can ALSO complete and then raise (a second NAS
    timeout, undoing the undo): _put_back must report it home too, not stuck.
    N2: the forward move and the roll-back share one seam, so one mock does."""
    folder, paths = night
    before = tree(tmp_path)
    real = rm._rename_no_replace
    calls = []

    def flaky(src, dst, dest):
        calls.append(1)
        real(src, dst, dest)
        if len(calls) in (2, 3):
            raise OSError(errno.ETIMEDOUT, "Operation timed out", src)

    monkeypatch.setattr(rm, "_rename_no_replace", flaky)
    with pytest.raises(RejectMoveError, match="nothing changed"):
        move_to_rejected(folder, [paths[1], paths[3], paths[5]], paths, now=NOW)
    monkeypatch.undo()
    assert without_rejected(tree(tmp_path)) == before
    assert read_manifest(folder) == []
    assert sorted(os.listdir(rej(folder))) == [MANIFEST_NAME]


def test_a_rename_that_succeeds_but_raises_and_truly_cannot_be_rolled_back(
        night, tmp_path, monkeypatch):
    """The forward rename secretly succeeds then raises; putting it back
    fails for real this time (no rename happens): the file must stay both
    recorded and named in the error, never silently unrecorded. N2: the
    forward move and the roll-back share one seam, so one mock does."""
    folder, paths = night
    real = rm._rename_no_replace
    calls = []

    def flaky(src, dst, dest):
        calls.append(1)
        if len(calls) == 2:
            real(src, dst, dest)                        # completes despite raising
            raise OSError(errno.ETIMEDOUT, "Operation timed out", src)
        if os.path.basename(dst) == "Light_03.fit":
            raise OSError(errno.EIO, "Input/output error", src)   # never really happens
        real(src, dst, dest)

    monkeypatch.setattr(rm, "_rename_no_replace", flaky)
    with pytest.raises(RejectMoveError, match=r"Light_03\.fit could not be put back"):
        move_to_rejected(folder, [paths[1], paths[3], paths[5]], paths, now=NOW)
    monkeypatch.undo()
    assert [e["name"] for e in read_manifest(folder)] == ["Light_03.fit"]
    assert pending_back(folder) == ["Light_03.fit"]
    assert os.path.isfile(os.path.join(rej(folder), "Light_03.fit"))
    move_back(folder)
    assert not os.path.exists(os.path.join(rej(folder), "Light_03.fit"))
    assert os.path.isfile(paths[3])


def test_move_back_rename_that_succeeds_but_raises_is_reported_as_home(night, monkeypatch):
    """Mirrors the forward case inside move_back's own rename: a NAS can
    complete the move-back and still raise. Must be reported as restored,
    never as 'still in rejected'."""
    folder, paths = night
    move_to_rejected(folder, [paths[1]], paths, now=NOW)
    real = rm._rename_no_replace

    def lying(src, dst, dest):
        real(src, dst, dest)
        raise OSError(errno.ETIMEDOUT, "Operation timed out", src)

    monkeypatch.setattr(rm, "_rename_no_replace", lying)
    result = move_back(folder)
    monkeypatch.undo()
    assert result.restored == ["Light_01.fit"] and result.failed == ""
    assert read_manifest(folder) == [] and pending_back(folder) == []
    assert os.path.isfile(paths[1])


# --- moving back -----------------------------------------------------------------

def test_a_round_trip_is_byte_identical_with_the_same_mtimes(night, tmp_path):
    folder, paths = night
    before = tree(tmp_path)
    move_to_rejected(folder, [paths[1], paths[3]], paths, now=NOW)
    assert pending_back(folder) == ["Light_01.fit", "Light_03.fit"]
    result = move_back(folder)
    assert result.restored == ["Light_01.fit", "Light_03.fit"]
    assert (result.already_back, result.taken, result.refused,
            result.missing, result.failed) == ([], [], [], [], "")
    assert without_rejected(tree(tmp_path)) == before
    assert read_manifest(folder) == [] and pending_back(folder) == []


def test_move_back_moves_only_what_the_record_lists(night):
    folder, paths = night
    move_to_rejected(folder, [paths[1]], paths, now=NOW)
    other = os.path.join(rej(folder), "his_own.fit")
    with open(other, "wb") as fh:
        fh.write(b"he put this here")
    move_back(folder)
    with open(other, "rb") as fh:
        assert fh.read() == b"he put this here"
    assert not os.path.exists(os.path.join(folder, "his_own.fit"))


def test_move_back_refuses_a_name_that_is_taken_again(night):
    folder, paths = night
    move_to_rejected(folder, [paths[1], paths[3]], paths, now=NOW)
    with open(paths[3], "wb") as fh:
        fh.write(b"a new Light_03")
    parked = os.path.join(rej(folder), "Light_03.fit")
    with open(parked, "rb") as fh:
        parked_bytes = fh.read()
    result = move_back(folder)
    assert result.restored == ["Light_01.fit"] and result.taken == ["Light_03.fit"]
    with open(paths[3], "rb") as fh:
        assert fh.read() == b"a new Light_03"
    with open(parked, "rb") as fh:
        assert fh.read() == parked_bytes
    assert [e["name"] for e in read_manifest(folder)] == ["Light_03.fit"]
    assert pending_back(folder) == ["Light_03.fit"]


def test_a_file_appearing_at_home_mid_way_is_not_replaced_by_move_back(night, monkeypatch):
    """N2: move_back's rename into the capture folder now goes through the
    same no-replace helper as the forward move. Simulate the race window: a
    file appears at home in the instant this call represents, and it must be
    refused, not silently overwritten by a plain os.rename."""
    folder, paths = night
    move_to_rejected(folder, [paths[1]], paths, now=NOW)
    real = rm._rename_no_replace

    def race(src, dst, dest):
        with open(dst, "wb") as fh:
            fh.write(b"a new file, arrived in the race window")
        return real(src, dst, dest)

    monkeypatch.setattr(rm, "_rename_no_replace", race)
    result = move_back(folder)
    monkeypatch.undo()
    assert result.restored == [] and "Could not move Light_01.fit back" in result.failed
    with open(paths[1], "rb") as fh:
        assert fh.read() == b"a new file, arrived in the race window"
    assert os.path.isfile(os.path.join(rej(folder), "Light_01.fit"))


def test_a_file_appearing_at_home_mid_way_is_not_replaced_by_rollback(night, tmp_path, monkeypatch):
    """N2: _put_back's rename-back (rolling back a failed forward move) is a
    no-replace rename too, not just move_back's own rename."""
    folder, paths = night
    real = rm._rename_no_replace
    calls = []

    def flaky(src, dst, dest):
        calls.append(1)
        if len(calls) == 2:
            raise OSError(errno.EIO, "Input/output error", src)   # Light_03 forward fails
        if len(calls) == 3:
            # race window during roll-back: a new Light_01 appears at home
            # right as _put_back attempts to rename it back.
            with open(dst, "wb") as fh:
                fh.write(b"a new Light_01, arrived in the race window")
        return real(src, dst, dest)

    monkeypatch.setattr(rm, "_rename_no_replace", flaky)
    with pytest.raises(RejectMoveError, match=r"Light_01\.fit could not be put back"):
        move_to_rejected(folder, [paths[1], paths[3]], paths, now=NOW)
    monkeypatch.undo()
    with open(paths[1], "rb") as fh:
        assert fh.read() == b"a new Light_01, arrived in the race window"
    assert os.path.isfile(os.path.join(rej(folder), "Light_01.fit"))


def test_a_file_moved_back_by_hand_is_dropped_not_overwritten(night):
    """Review Focus 6: the record is out of date."""
    folder, paths = night
    move_to_rejected(folder, [paths[1], paths[3]], paths, now=NOW)
    os.rename(os.path.join(rej(folder), "Light_01.fit"), paths[1])       # Finder
    with open(paths[1], "rb") as fh:
        by_hand = fh.read()
    assert pending_back(folder) == ["Light_03.fit"]
    result = move_back(folder)
    assert result.restored == ["Light_03.fit"] and result.already_back == ["Light_01.fit"]
    with open(paths[1], "rb") as fh:
        assert fh.read() == by_hand
    assert read_manifest(folder) == []


def test_a_file_gone_from_rejected_keeps_its_entry(night):
    folder, paths = night
    move_to_rejected(folder, [paths[1], paths[3]], paths, now=NOW)
    os.remove(os.path.join(rej(folder), "Light_01.fit"))      # tmp_path only: deleted by hand
    assert pending_back(folder) == ["Light_03.fit"]
    result = move_back(folder)
    assert result.missing == ["Light_01.fit"] and result.restored == ["Light_03.fit"]
    assert [e["name"] for e in read_manifest(folder)] == ["Light_01.fit"]


def test_something_that_is_not_a_plain_file_is_left_alone(night):
    folder, paths = night
    move_to_rejected(folder, [paths[1]], paths, now=NOW)
    parked = os.path.join(rej(folder), "Light_01.fit")
    os.remove(parked)
    os.mkdir(parked)
    result = move_back(folder)
    assert result.refused == ["Light_01.fit"] and os.path.isdir(parked)
    assert not os.path.exists(paths[1])


def test_a_failure_moving_back_stops_and_keeps_the_rest_recorded(night, monkeypatch):
    folder, paths = night
    move_to_rejected(folder, [paths[1], paths[3]], paths, now=NOW)

    def refuse(src, dst, dest):
        raise OSError(errno.EACCES, "Permission denied", src)

    monkeypatch.setattr(rm, "_rename_no_replace", refuse)
    result = move_back(folder)
    monkeypatch.undo()
    assert result.restored == [] and "Could not move Light_01.fit back" in result.failed
    assert pending_back(folder) == ["Light_01.fit", "Light_03.fit"]


def test_move_back_with_no_rejected_folder_does_nothing(night, tmp_path):
    folder, _paths = night
    before = tree(tmp_path)
    result = move_back(folder)
    assert result.restored == [] and tree(tmp_path) == before
    assert pending_back(folder) == [] and pending_back(str(tmp_path / "nowhere")) == []


# --- the record is untrusted input ------------------------------------------------

@pytest.mark.parametrize("record", [
    {"version": 1, "moved": [{"name": "../../outside.fit", "moved_at": "x"}]},
    {"version": 1, "moved": [{"name": "../Light_00.fit", "moved_at": "x"}]},
    {"version": 1, "moved": [{"name": "/etc/hosts", "moved_at": "x"}]},
    {"version": 1, "moved": [{"name": "deeper/Light_00.fit", "moved_at": "x"}]},
    {"version": 1, "moved": [{"name": "..", "moved_at": "x"}]},
    {"version": 1, "moved": [{"name": "", "moved_at": "x"}]},
    {"version": 1, "moved": [{"name": MANIFEST_NAME, "moved_at": "x"}]},
    {"version": 1, "moved": [{"name": "Light_01.fit"}]},
    {"version": 1, "moved": ["Light_01.fit"]},
    {"version": 1, "moved": [{"name": "Light_01.fit", "moved_at": "x"},
                             {"name": "Light_01.fit", "moved_at": "y"}]},
    {"version": 2, "moved": []},
    {"moved": []},
    ["Light_01.fit"],
    "this is not JSON",
])
def test_a_record_that_cannot_be_trusted_is_never_followed(night, tmp_path, record):
    folder, paths = night
    os.mkdir(rej(folder))
    with open(os.path.join(rej(folder), "Light_01.fit"), "wb") as fh:
        fh.write(b"parked")
    with open(os.path.join(rej(folder), MANIFEST_NAME), "w", encoding="utf-8") as fh:
        fh.write(record if isinstance(record, str) else json.dumps(record))
    for act in (lambda: move_back(folder), lambda: pending_back(folder),
                lambda: move_to_rejected(folder, [paths[2]], paths, now=NOW)):
        _refused(tmp_path, act, "damaged")


def test_a_record_that_is_a_link_is_not_trusted(night, tmp_path):
    folder, paths = night
    os.mkdir(rej(folder))
    decoy = tmp_path / "decoy.json"
    decoy.write_text(json.dumps({"version": 1, "moved": [{"name": "Light_00.fit",
                                                          "moved_at": "x"}]}))
    os.symlink(str(decoy), os.path.join(rej(folder), MANIFEST_NAME))
    _refused(tmp_path, lambda: move_back(folder), "damaged")


def test_the_damaged_message_says_how_to_recover(night):
    """m7: the damaged-record message must tell him what to actually do —
    move the files back by hand, then clear the record — not just refuse."""
    folder, paths = night
    os.mkdir(rej(folder))
    with open(os.path.join(rej(folder), MANIFEST_NAME), "w", encoding="utf-8") as fh:
        fh.write("not json")
    with pytest.raises(RejectMoveError,
                       match=f"delete or rename {re.escape(MANIFEST_NAME)}"):
        read_manifest(folder)


def test_describe_names_keeps_a_long_list_short():
    assert describe_names(["a.fit"]) == "a.fit"
    assert describe_names(["a", "b", "c"]) == "a, b, c"
    assert describe_names(["a", "b", "c", "d", "e"]) == "a, b, c and 2 more"
