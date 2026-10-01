"""Move rejected subs into <folder>/rejected/ and back.

These are his ORIGINAL subs. Andreas, 2026-09-27: "we need to be very
vigilant and careful … but it's a feature worth having". The rules (spec
2026-09-27 §5), each pinned by tests/stacking/test_reject_move.py:

- Only files the caller graded, only directly inside the folder, only into
  folder/rejected/.
- Never overwrite: a name already in rejected/ stops everything before the
  first rename, and every name is checked again right before its own rename —
  atomically where the OS offers it (renamex_np/RENAME_EXCL on macOS,
  renameat2/RENAME_NOREPLACE on Linux, via ctypes), so nothing can land in
  the gap between the check and a plain os.rename.
- Rename only. On one volume a rename is atomic and leaves the bytes and
  the mtime alone; across volumes it FAILS (EXDEV), where the standard
  library's copy-then-delete move helper would quietly copy and delete.
  Nothing here copies, and nothing of his is deleted.
- A failure part-way puts back what was moved, and says so — but a rename can
  also complete on a network share and still raise (a timeout arriving after
  the server finished). Every place that catches a rename failure asks the
  filesystem, not the exception, whether the file actually landed before
  deciding what to roll back or report: never left in rejected/ unrecorded,
  never reported as still there when it is already home.
- The record (rejected/.nocturne-moved.json) is written BEFORE the first
  rename, atomically (temp file + os.replace), so a crash mid-way leaves a
  record that over-states — never one that forgets a moved file.
- The record is untrusted on the way back: only bare file names are acted on,
  only inside rejected/, and a damaged record stops everything — and says how
  to recover (move the files back by hand, then delete or rename the record).
- Links: a sub, or rejected/ itself, that resolves elsewhere is refused, even
  when the link's target is a sibling folder next door.
- Two spellings of one file (a case variant or NFC/NFD form, on a filesystem
  that treats them as the same entry) are deduplicated before anything
  moves — by inode AND casefolded/NFD name together, so a hard link under a
  genuinely different name, or a share that synthesises a shared st_ino for
  two different files, still moves both, never silently dropping one — and
  the "did it secretly land" filesystem check never claims a destination
  that is really a different wanted file's already-moved self. A vanished
  file surfaces as the same RejectMoveError as any other missing file, never
  a raw OSError. A move back into the capture folder is a no-replace rename
  too, for the same reason a move into rejected/ is.
"""
from __future__ import annotations

import ctypes
import errno
import json
import os
import tempfile
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

REJECTED_DIR = "rejected"
MANIFEST_NAME = ".nocturne-moved.json"
_VERSION = 1

try:
    _libc = ctypes.CDLL(None, use_errno=True)
except OSError:                                   # no libc to load from: exotic platform
    _libc = None

# Errno values meaning "the OS doesn't offer a no-replace rename here" (an
# old kernel, or a filesystem — a network share is the real case — that
# doesn't support the flag), as opposed to "there is a collision" (EEXIST).
_NO_REPLACE_UNAVAILABLE = {errno.ENOTSUP, errno.EINVAL, errno.ENOSYS}
if hasattr(errno, "EOPNOTSUPP"):
    _NO_REPLACE_UNAVAILABLE.add(errno.EOPNOTSUPP)


class RejectMoveError(Exception):
    """Refused, or failed with everything put back — or, when putting back
    failed too, with every leftover named and recorded. str() is the
    sentence for the user."""


@dataclass
class MoveBackResult:
    restored: list[str] = field(default_factory=list)       # back in the folder now
    already_back: list[str] = field(default_factory=list)   # found back already (by hand)
    taken: list[str] = field(default_factory=list)          # the name is in use again
    refused: list[str] = field(default_factory=list)        # not a plain file in rejected/
    missing: list[str] = field(default_factory=list)        # in neither place
    failed: str = ""                                         # an OSError stopped it part-way


def home_folder(path: str) -> str:
    """The capture folder a sub belongs to: its own folder, or — for one
    moved into <folder>/rejected/ — the folder rejected/ sits in."""
    parent = os.path.dirname(os.path.abspath(path))
    if os.path.basename(parent) == REJECTED_DIR:
        return os.path.dirname(parent)
    return parent


def describe_names(names, limit: int = 3) -> str:
    names = list(names)
    if len(names) <= limit:
        return ", ".join(names)
    return f"{', '.join(names[:limit])} and {len(names) - limit} more"


# A caller listing two folders that share a name ("d1/M 31_sub",
# "d2/M 31_sub") says how each is to be named in the messages below; left to
# the basename they read as one folder (delivery C review, item 3).
_LABELS: ContextVar[dict] = ContextVar("reject_move_labels", default={})


@contextmanager
def folder_labels(labels: dict[str, str]):
    """Name these folders so in every message written inside the block."""
    token = _LABELS.set({os.path.normpath(os.path.abspath(k)): v
                         for k, v in labels.items()})
    try:
        yield
    finally:
        _LABELS.reset(token)


def _label(folder: str) -> str:
    key = os.path.normpath(os.path.abspath(folder))
    return _LABELS.get().get(key) or os.path.basename(key)


def _where(folder: str) -> str:
    return f"{_label(folder)}/{REJECTED_DIR}"


def _bare_name(name) -> bool:
    return (isinstance(name, str) and name not in ("", ".", "..")
            and "/" not in name and "\\" not in name and "\x00" not in name
            and name != MANIFEST_NAME)


def _damaged(folder: str) -> str:
    return (f"The record of moved frames in {_where(folder)} ({MANIFEST_NAME}) is "
            "damaged, so Nocturne will not move anything there or back. Move the "
            "files back by hand if you need them, then delete or rename "
            f"{MANIFEST_NAME} in {_where(folder)} — Nocturne will start a fresh "
            "record next time and trust it again.")


def _cannot_write(folder: str, exc: Exception) -> str:
    why = getattr(exc, "strerror", None) or str(exc)
    return (f"Can't write in {_label(folder)} ({why}) — nothing was moved. Is it "
            "read-only, or on a network drive that refuses changes?")


def _safe_rejected_dir(folder: str, create: bool) -> str | None:
    """rejected/ as a real folder directly inside `folder`, or None when it is
    absent and `create` is False."""
    folder = os.path.abspath(folder)
    path = os.path.join(folder, REJECTED_DIR)
    linked = (f"{_where(folder)} is a link to another place, so Nocturne will not "
              "move anything there or back.")
    if os.path.islink(path):
        raise RejectMoveError(linked)
    if not os.path.lexists(path):
        if not create:
            return None
        try:
            os.mkdir(path)
        except OSError as exc:
            raise RejectMoveError(_cannot_write(folder, exc)) from exc
    if not os.path.isdir(path):
        raise RejectMoveError(f"{_label(folder)} has a file called {REJECTED_DIR}, "
                              "not a folder — nothing was moved.")
    if os.path.dirname(os.path.realpath(path)) != os.path.realpath(folder):
        raise RejectMoveError(linked)
    return path


def read_manifest(folder: str) -> list[dict]:
    """The record's entries, [{"name", "moved_at"}]; [] when there is none.
    Raises RejectMoveError when it exists and cannot be trusted."""
    rej = _safe_rejected_dir(folder, create=False)
    if rej is None:
        return []
    path = os.path.join(rej, MANIFEST_NAME)
    if not os.path.lexists(path):
        return []
    if os.path.islink(path) or not os.path.isfile(path):
        raise RejectMoveError(_damaged(folder))
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise RejectMoveError(_damaged(folder)) from exc
    moved = data.get("moved") if isinstance(data, dict) else None
    if (not isinstance(data, dict) or data.get("version") != _VERSION
            or not isinstance(moved, list)):
        raise RejectMoveError(_damaged(folder))
    entries = []
    for e in moved:
        if (not isinstance(e, dict) or not _bare_name(e.get("name"))
                or not isinstance(e.get("moved_at"), str)):
            raise RejectMoveError(_damaged(folder))
        entries.append({"name": e["name"], "moved_at": e["moved_at"]})
    if len({e["name"] for e in entries}) != len(entries):
        raise RejectMoveError(_damaged(folder))
    return entries


def _stored_measurements(rej: str) -> dict[str, dict]:
    """{name: measured block} as the record holds it now, so a rewrite keeps
    the measurements read_manifest (names only, on purpose) leaves out.
    Never raises: losing a chart dot must never stop a move."""
    try:
        with open(os.path.join(rej, MANIFEST_NAME), encoding="utf-8") as fh:
            data = json.load(fh)
        out = {}
        for e in data.get("moved", []):
            if isinstance(e, dict) and isinstance(e.get("name"), str) \
                    and isinstance(e.get("measured"), dict):
                out[e["name"]] = e["measured"]
        return out
    except Exception:
        return {}


def _keep_measured(rej: str, entries: list[dict]) -> list[dict]:
    """Entries from read_manifest, with their stored measurements put back."""
    stored = _stored_measurements(rej)
    return [dict(e, measured=stored[e["name"]]) if e["name"] in stored else e
            for e in entries]


def _write_manifest(rej: str, entries: list[dict]) -> None:
    fd, tmp = tempfile.mkstemp(prefix=MANIFEST_NAME + ".", suffix=".tmp", dir=rej)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"version": _VERSION, "moved": entries}, fh, indent=1,
                      ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, os.path.join(rej, MANIFEST_NAME))
    except BaseException:
        # Our own half-written temp file — never one of his.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def pending_back(folder: str) -> list[str]:
    """Names the record lists that are plain files in rejected/ now: what
    "Move them back" would put back."""
    if not os.path.isdir(folder):
        return []
    entries = read_manifest(folder)
    rej = os.path.join(os.path.abspath(folder), REJECTED_DIR)
    out = []
    for e in entries:
        p = os.path.join(rej, e["name"])
        if os.path.isfile(p) and not os.path.islink(p):
            out.append(e["name"])
    return out


def _put_back(moved: dict[str, str], dest_label: str) -> dict[str, str]:
    """Undo `moved`, newest first. Returns what could NOT be put back.
    `dest_label` names the capture folder, for a collision message."""
    stuck: dict[str, str] = {}
    for src, dst in reversed(list(moved.items())):
        if os.path.lexists(src):
            stuck[src] = dst      # something new has its old name: never overwrite it
            continue
        try:
            _rename_no_replace(dst, src, dest_label)
        except OSError:
            # A NAS can complete the rename and still raise (e.g. a timeout
            # after the server was done): ask the filesystem, not the
            # exception, whether it actually landed.
            if os.path.lexists(src) and not os.path.lexists(dst):
                continue
            stuck[src] = dst
    return stuck


def _failed(folder: str, exc: OSError, stuck: dict[str, str]) -> str:
    what = os.path.basename(exc.filename) if getattr(exc, "filename", None) else "a frame"
    text = f"Could not move {what} ({exc.strerror or exc})."
    if not stuck:
        return text + " Everything already moved was put back — nothing changed."
    names = describe_names(sorted(os.path.basename(p) for p in stuck))
    one = len(stuck) == 1
    return (text + f" {names} could not be put back and {'is' if one else 'are'} still "
            f"in {_where(folder)}; Move them back will find {'it' if one else 'them'}.")


def _native_no_replace_rename(src: str, dst: str, dest: str) -> bool:
    """Try the OS's own exclusive rename. True on success; False when the
    primitive isn't offered here (missing symbol, old kernel, or a
    filesystem — a network share is the real case — that refuses the flag),
    so the caller should fall back. Raises FileExistsError for a genuine
    collision (`dest` names the destination folder in the message), or the
    underlying OSError for anything else."""
    if _libc is None:
        return False
    s, d = os.fsencode(src), os.fsencode(dst)
    if hasattr(_libc, "renamex_np"):                       # macOS
        ctypes.set_errno(0)
        rc = _libc.renamex_np(s, d, 0x4)                   # RENAME_EXCL
        err = ctypes.get_errno()
    elif hasattr(_libc, "renameat2"):                       # Linux
        AT_FDCWD, RENAME_NOREPLACE = -100, 1
        ctypes.set_errno(0)
        rc = _libc.renameat2(AT_FDCWD, s, AT_FDCWD, d, RENAME_NOREPLACE)
        err = ctypes.get_errno()
    else:
        return False
    if rc == 0:
        return True
    if err == errno.EEXIST:
        raise FileExistsError(errno.EEXIST,
                              f"a file with this name appeared in {dest}", dst)
    if err in _NO_REPLACE_UNAVAILABLE:
        return False
    raise OSError(err, os.strerror(err), src)


def _rename_no_replace(src: str, dst: str, dest: str) -> None:
    """Rename src to dst, refusing to replace an existing dst — atomically,
    where the OS offers it, so nothing can land in the gap between a check
    and a plain os.rename. Falls back to check-then-os.rename where that
    primitive is missing or the filesystem refuses the flag; either way
    a collision raises FileExistsError naming the destination folder (`dest`
    — 'rejected/' for the forward move, the capture folder for a move back)."""
    if _native_no_replace_rename(src, dst, dest):
        return
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST,
                              f"a file with this name appeared in {dest}", dst)
    os.rename(src, dst)


def _already_claimed(dst: str, moved: dict[str, str]) -> bool:
    """True when `dst` is the SAME file (by inode, not spelling) as a
    destination already recorded in `moved` — a case-insensitive or
    NFC/NFD-insensitive filesystem can make a second spelling's destination
    path look like it exists when it is really the first spelling's already-
    moved file."""
    for existing in moved.values():
        try:
            if os.path.samefile(dst, existing):
                return True
        except OSError:
            continue
    return False


def _measured_entry(m) -> dict | None:
    """What the chart needs to draw a moved frame, or None. Only finite
    numbers and plain strings: the record is JSON his other tools may read."""
    import math
    if not isinstance(m, dict):
        return None
    fwhm, stars = m.get("fwhm"), m.get("star_count")
    if not isinstance(fwhm, (int, float)) or isinstance(fwhm, bool) or not math.isfinite(fwhm):
        return None
    out = {"captured": m["captured"].isoformat() if isinstance(m.get("captured"), datetime)
           else None,
           "fwhm": float(fwhm),
           "star_count": int(stars) if isinstance(stars, int) and not isinstance(stars, bool)
           else 0,
           "reason": m.get("reason") if isinstance(m.get("reason"), str) else ""}
    return out


def read_moved_history(folder: str) -> list[dict]:
    """The measurements of frames still in rejected/, for the chart only.

    Deliberately NOT read_manifest: that one is the safety path (Move them
    back) and stays strict about names and nothing else. This one never
    raises — a damaged record is the safety path's to report — and skips
    anything it cannot use. Each item: path (in rejected/), captured (aware
    datetime or None), fwhm, star_count, reason. (Andreas, 2026-10-01: a
    reopened folder had no dots at all for the frames he moved.)"""
    import math
    try:
        rej = _safe_rejected_dir(folder, create=False)
        if rej is None:
            return []
        path = os.path.join(rej, MANIFEST_NAME)
        if os.path.islink(path) or not os.path.isfile(path):
            return []
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        moved = data.get("moved") if isinstance(data, dict) else None
        if not isinstance(moved, list):
            return []
        out = []
        for e in moved:
            if not isinstance(e, dict) or not _bare_name(e.get("name")):
                continue
            m = e.get("measured")
            if not isinstance(m, dict):
                continue
            fwhm = m.get("fwhm")
            if (not isinstance(fwhm, (int, float)) or isinstance(fwhm, bool)
                    or not math.isfinite(fwhm)):
                continue
            p = os.path.join(rej, e["name"])
            if not os.path.isfile(p) or os.path.islink(p):
                continue
            captured = None
            if isinstance(m.get("captured"), str):
                try:
                    captured = datetime.fromisoformat(m["captured"])
                except ValueError:
                    captured = None
                if captured is not None and captured.tzinfo is None:
                    captured = None
            stars = m.get("star_count")
            out.append({"path": p, "captured": captured, "fwhm": float(fwhm),
                        "star_count": stars if isinstance(stars, int)
                        and not isinstance(stars, bool) else 0,
                        "reason": m.get("reason") if isinstance(m.get("reason"), str) else ""})
        return out
    except Exception:
        return []


def move_to_rejected(folder: str, paths: Iterable[str], graded: Iterable[str],
                     now: datetime | None = None,
                     measured: dict | None = None) -> dict[str, str]:
    """Move `paths` into folder/rejected/. Returns {old path: new path}.

    `measured` ({path: {captured, fwhm, star_count, reason}}) is optional and
    is only ever READ back by read_moved_history, for the chart; nothing that
    moves a file depends on it.

    `graded` is every path the caller graded; anything else is refused. On any
    refusal or failure nothing stays moved (RejectMoveError) — unless putting
    a file back failed too, and then the error names it and the record keeps it.
    """
    folder = os.path.abspath(folder)
    real_folder = os.path.realpath(folder)
    graded_set = {os.path.abspath(p) for p in graded}
    wanted: list[str] = []
    for p in dict.fromkeys(os.path.abspath(x) for x in paths):
        name = os.path.basename(p)
        if p not in graded_set:
            raise RejectMoveError(f"{name} was not graded in this window — nothing was moved.")
        if os.path.dirname(p) != folder or not _bare_name(name):
            raise RejectMoveError(f"{name} is not directly inside {_label(folder)} — "
                                  "nothing was moved.")
        if os.path.islink(p) or not os.path.isfile(p):
            raise RejectMoveError(f"{name} is a link, or is no longer there — "
                                  "nothing was moved.")
        if os.path.dirname(os.path.realpath(p)) != real_folder:
            raise RejectMoveError(f"{name} is stored outside {_label(folder)} — "
                                  "nothing was moved.")
        wanted.append(p)
    # Two spellings of one file (a case variant, or NFC/NFD, on a filesystem
    # that treats them as the same entry) are the same inode AND the same
    # name once normalized: keep only the first spelling given, before
    # anything moves. Otherwise the second spelling's rename genuinely fails
    # (its source is already gone once the first spelling moved it) in a way
    # the filesystem check below cannot tell apart from "it secretly
    # succeeded" — see _already_claimed. Requiring the name too (not inode
    # alone) means a hard link under a genuinely different name — or two
    # different files a network share happens to report the same st_ino for
    # — still move as separate entries, never silently dropped.
    seen_keys: set[tuple[tuple[int, int], str]] = set()
    deduped: list[str] = []
    for p in wanted:
        try:
            st = os.stat(p)
        except OSError as exc:
            # It existed a moment ago (the validation loop above checked),
            # but a file can vanish in the gap; this must surface the same
            # way, not as a raw OSError the caller doesn't catch.
            raise RejectMoveError(f"{os.path.basename(p)} is a link, or is no "
                                  "longer there — nothing was moved.") from exc
        norm_name = unicodedata.normalize("NFD", os.path.basename(p)).casefold()
        key = ((st.st_dev, st.st_ino), norm_name)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(p)
    wanted = deduped
    if not wanted:
        return {}
    earlier = read_manifest(folder)              # damaged: stop before anything moves
    rej = _safe_rejected_dir(folder, create=True)
    taken = [os.path.basename(p) for p in wanted
             if os.path.lexists(os.path.join(rej, os.path.basename(p)))]
    if taken:
        raise RejectMoveError(
            f"{describe_names(taken)} {'is' if len(taken) == 1 else 'are'} already in "
            f"{_where(folder)} — nothing was moved, so nothing was overwritten.")
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    names = {os.path.basename(p) for p in wanted}
    # An entry for a name that is moving again describes a file that came back
    # by hand: it is not in rejected/, or `taken` would have stopped us.
    kept_entries = _keep_measured(rej, [e for e in earlier if e["name"] not in names])
    new_entries = []
    for p in wanted:
        entry = {"name": os.path.basename(p), "moved_at": stamp}
        m = _measured_entry((measured or {}).get(p))
        if m is not None:
            entry["measured"] = m
        new_entries.append(entry)
    try:
        _write_manifest(rej, kept_entries + new_entries)
    except (OSError, ValueError) as exc:
        # ValueError: a name that came from surrogateescape-decoded non-UTF-8
        # bytes (a foreign-formatted network share) can't be re-encoded by a
        # plain UTF-8 json.dump — UnicodeEncodeError, not an OSError.
        raise RejectMoveError(_cannot_write(folder, exc)) from exc
    moved: dict[str, str] = {}
    try:
        for p in wanted:
            dst = os.path.join(rej, os.path.basename(p))
            _rename_no_replace(p, dst, _where(folder))
            moved[p] = dst
    except OSError as exc:
        # A NAS can complete a rename and still raise afterwards (e.g. a
        # timeout arriving after the server was done): ask the filesystem,
        # not the bookkeeping, whether this file actually landed before
        # rolling back — otherwise it sits in rejected/ unrecorded. But never
        # claim a destination that is really a DIFFERENT wanted file's
        # already-moved self (a case-insensitive or NFC/NFD-insensitive
        # filesystem can make this file's destination path look like it
        # exists when `wanted`'s dedup already accounted for it).
        if (not os.path.lexists(p) and os.path.lexists(dst)
                and not _already_claimed(dst, moved)):
            moved[p] = dst
        stuck = _put_back(moved, _label(folder))
        stuck_names = {os.path.basename(p) for p in stuck}
        try:
            _write_manifest(rej, kept_entries
                            + [e for e in new_entries if e["name"] in stuck_names])
        except (OSError, ValueError):
            pass     # the write-ahead record still names them all: over-states, never forgets
        raise RejectMoveError(_failed(folder, exc, stuck)) from exc
    return moved


def move_back(folder: str) -> MoveBackResult:
    """Put back exactly what the record lists. A name in use again stays in
    rejected/ with its entry; an entry is removed only once its file is back."""
    folder = os.path.abspath(folder)
    result = MoveBackResult()
    rej = _safe_rejected_dir(folder, create=False)
    if rej is None:
        return result
    entries = read_manifest(folder)
    keep: list[dict] = []
    for e in entries:
        name = e["name"]
        src, dst = os.path.join(rej, name), os.path.join(folder, name)
        in_rejected, at_home = os.path.lexists(src), os.path.lexists(dst)
        if at_home and not in_rejected:
            result.already_back.append(name)        # back already, by hand
            continue
        if not in_rejected:
            result.missing.append(name)
        elif os.path.islink(src) or not os.path.isfile(src):
            result.refused.append(name)
        elif at_home:
            result.taken.append(name)
        elif not result.failed:
            try:
                _rename_no_replace(src, dst, _label(folder))
            except OSError as exc:
                # Mirrors move_to_rejected: a rename-back can complete on the
                # far end and still raise. Ask the filesystem before
                # reporting it as stuck in rejected/ — it may already be home.
                if not os.path.lexists(src) and os.path.lexists(dst):
                    result.restored.append(name)
                    continue
                result.failed = (f"Could not move {name} back ({exc.strerror or exc}); "
                                 f"it is still in {_where(folder)}.")
            else:
                result.restored.append(name)
                continue
        keep.append(e)
    if len(keep) != len(entries):
        try:
            _write_manifest(rej, _keep_measured(rej, keep))
        except (OSError, ValueError) as exc:
            why = getattr(exc, "strerror", None) or str(exc)
            result.failed = result.failed or (
                f"The frames are back, but the record in {_where(folder)} could not be "
                f"updated ({why}). Moving them back again will find them already back.")
    return result
