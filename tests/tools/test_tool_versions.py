import subprocess
import time

import pytest

from nocturne.tools.probe import VERSION_ARGV, tool_version


def test_a_slow_tool_cannot_hang_the_caller():
    """MEASURED on Andreas's machine 2026-09-22: ASTAP `-h` timed out after 60
    SECONDS, while GraXpert `-v` and StarNet2 `--version` answered instantly.
    Probing every tool when a report dialog opens would freeze the app for a
    minute on any machine with ASTAP."""
    seen = {}

    def slow(argv, timeout=None):
        # What subprocess.run itself does when a tool does not answer: wait the
        # deadline, then raise. A fake that only slept would prove nothing
        # about the probe -- the deadline is enforced by the runner, so the
        # thing under test is that the probe HANDS its deadline over and
        # survives the result.
        seen["timeout"] = timeout
        time.sleep(timeout)
        raise subprocess.TimeoutExpired(argv, timeout)

    started = time.monotonic()
    assert tool_version("/x/astap", ["-h"], timeout=0.2, runner=slow) == ""
    assert time.monotonic() - started < 2.0, "the probe did not give up"
    assert seen["timeout"] == 0.2, "the probe kept its deadline to itself"


def test_the_default_deadline_is_seconds_not_probe_binarys_minute():
    """The regression this exists to catch is reusing probe_binary's 60 s: a
    person is waiting for a dialog to open while this runs."""
    seen = {}

    def note(argv, timeout=None):
        seen["timeout"] = timeout
        return 0, "v1\n", ""

    tool_version("/x/graxpert", ["-v"], runner=note)
    assert seen["timeout"] <= 3.0, seen


def test_a_version_line_is_returned_whole():
    def fast(argv, timeout=None):
        return 0, "GraXpert version: 3.0.2 release: Umbriel\nmore\n", ""
    assert tool_version("/x/graxpert", ["-v"], runner=fast) == \
        "GraXpert version: 3.0.2 release: Umbriel"


def test_a_tool_that_answers_on_stderr_is_still_read():
    def onerr(argv, timeout=None):
        return 0, "", "starnet2  version: 2.5.2\n"
    assert tool_version("/x/starnet2", ["--version"], runner=onerr) == \
        "starnet2  version: 2.5.2"


def test_a_failure_is_empty_not_an_exception():
    def boom(argv, timeout=None):
        raise OSError("no such file")
    assert tool_version("/gone", ["-v"], runner=boom) == ""


@pytest.mark.parametrize("field", ["graxpert_path", "rcastro_path", "starnet_path"])
def test_every_tool_with_a_known_probe_is_listed(field):
    assert field in VERSION_ARGV


def test_astap_is_listed_as_having_no_usable_probe():
    """Not an oversight. Andreas: "we cant cover all bases anyways i think."
    Listing it with an empty argv is the difference between "we know it cannot
    be probed" and "somebody forgot"."""
    assert VERSION_ARGV.get("astap_path") == []
