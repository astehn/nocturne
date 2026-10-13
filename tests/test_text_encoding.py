"""Every text file the app reads or writes names its encoding.

Without `encoding=`, Python uses the locale's: UTF-8 on macOS and Linux, so
nothing here ever failed, but cp1252 on Windows. Found by the first Windows run
(2026-10-12): the bundled star catalogue (named_stars.csv) is UTF-8 with Greek
letters in it, and reading it raised UnicodeDecodeError, which took every
plate-solve annotation down with it. Settings and recipes survived only because
json.dump happens to escape to ASCII; the Upscale provenance .txt was written
in cp1252, so a UTF-8 reader showed its dashes and "×" as mojibake.

Child processes are the other half: a tool's output decoded strictly in the
locale's encoding can raise on one stray byte inside the reader, so every
`text=True` call must say what to do with a byte it cannot decode.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "nocturne"


def _mode(call: ast.Call, pos: int):
    for k in call.keywords:
        if k.arg == "mode":
            return k.value.value if isinstance(k.value, ast.Constant) else "?"
    if len(call.args) > pos:
        a = call.args[pos]
        return a.value if isinstance(a, ast.Constant) else "?"
    return "r"


def _offences(path: Path, root: Path = ROOT) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        kws = {k.arg for k in n.keywords}
        f = n.func
        name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
        where = f"{path.relative_to(root).as_posix()}:{n.lineno}"
        # os.open is the low-level call: it returns a file descriptor, has no
        # encoding= to give, and the text layer is the os.fdopen that wraps it.
        if (name == "fdopen" and ast.unparse(f.value) in ("os", "io")) or (
                name == "open" and (isinstance(f, ast.Name) or ast.unparse(f.value) == "io")):
            mode = _mode(n, 1)
            if "encoding" not in kws and not (isinstance(mode, str) and "b" in mode):
                bad.append(f"{where} {name}() without encoding=")
        elif name in ("read_text", "write_text") and "encoding" not in kws:
            bad.append(f"{where} {name}() without encoding=")
        elif name in ("run", "Popen", "check_output") and (
                kws & {"text", "universal_newlines"}) and not kws & {"errors", "encoding"}:
            bad.append(f"{where} subprocess {name}(text=True) without errors=")
    return bad


def test_app_text_io_names_its_encoding():
    bad = [b for p in sorted(APP.rglob("*.py")) for b in _offences(p)]
    assert bad == []


def test_release_tooling_text_io_names_its_encoding():
    """packaging/deploy.py rewrites CHANGELOG.md, whose headings carry "—":
    on Windows it read the file as cp1252 and failed."""
    bad = [b for p in sorted((ROOT / "packaging").glob("*.py")) for b in _offences(p)]
    assert bad == []


def test_the_check_sees_each_shape_it_claims_to(tmp_path):
    """A scanner that finds nothing would pass the test above for ever."""
    src = tmp_path / "nocturne" / "x.py"
    src.parent.mkdir()
    src.write_text(
        "import os, subprocess\n"
        "open(p)\n"
        "open(p, 'w')\n"
        "open(p, 'rb')\n"
        "open(p, encoding='utf-8')\n"
        "os.fdopen(fd, 'w')\n"
        "q.read_text()\n"
        "q.write_text(s)\n"
        "subprocess.run(a, text=True)\n"
        "subprocess.run(a, text=True, errors='replace')\n"
        "fd = os.open(p, os.O_WRONLY | os.O_CREAT, 0o666)\n"
        "io.open(p, 'w')\n", encoding="utf-8")
    lines = sorted(int(b.split(":")[1].split()[0]) for b in _offences(src, tmp_path))
    assert lines == [2, 3, 6, 7, 8, 9, 12]
