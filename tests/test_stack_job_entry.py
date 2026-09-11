"""`--stack-job` must be handled before any Qt object exists.

The child has no display. If the flag were dispatched after `QApplication` were
constructed, a background job would open a window — and that only shows up when
someone actually backgrounds a stack, which is the one path nobody runs during
development.

The spawn shape is guarded here too, because its frozen branch cannot fail
anywhere a test can watch: in the shipped .app `sys.executable` IS the app
binary, so `-m` would re-launch Nocturne instead of running a job. From source
the opposite holds — a bare interpreter knows neither `-m nocturne` nor the
flag on its own — so the two cases are not variations of one command, they are
opposites, and `job_command` is tested with the frozen flag forced each way
rather than however this test run happens to be launched.
"""
import pathlib
import sys

from nocturne.stacking.job import job_command


def _main_source() -> str:
    root = pathlib.Path(__file__).resolve().parent.parent
    return (root / "nocturne" / "__main__.py").read_text(encoding="utf-8")


def test_the_job_flag_is_handled_before_the_qapplication():
    src = _main_source()
    assert "--stack-job" in src, "no --stack-job dispatch"
    job_at = src.index("--stack-job")
    app_at = src.index("QApplication(sys.argv)")
    assert job_at < app_at, (
        "--stack-job is dispatched after QApplication is constructed, so a "
        "background job would open a window")


def test_the_dispatch_returns_rather_than_falling_through():
    """It must exit, not carry on into the GUI."""
    src = _main_source()
    window = src[src.index("--stack-job"):src.index("QApplication(sys.argv)")]
    assert "SystemExit" in window or "return" in window


def test_a_frozen_build_never_spawns_with_dash_m():
    cmd = job_command("/tmp/opts.json", frozen=True)
    assert "-m" not in cmd, "a frozen build would re-launch the whole app"
    assert cmd == [sys.executable, "--stack-job", "/tmp/opts.json"]


def test_from_source_the_module_has_to_be_named():
    """The mirror image, and the half that breaks every dev run if it is wrong."""
    assert job_command("/tmp/opts.json", frozen=False) == [
        sys.executable, "-m", "nocturne", "--stack-job", "/tmp/opts.json"]


def test_the_default_reads_sys_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert job_command("/tmp/opts.json") == [
        sys.executable, "--stack-job", "/tmp/opts.json"]
