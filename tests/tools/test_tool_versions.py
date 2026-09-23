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


# --- the version is not always the first line (measured 2026-09-22) --------

def test_it_finds_a_version_that_is_not_on_the_first_line():
    """MEASURED on Andreas's RC-Astro 2.6.9. `--no-banner --help` prints:

        Astronomical image processing tools
        Version 2.6.9 (build 727, ga2033f5b, 2026-09-08)

    The first non-empty line is a DESCRIPTION. Reporting it as the version
    would have put "Astronomical image processing tools" in every ticket from
    every RC-Astro user — plausible-looking and useless, which is the worst
    kind of wrong in a diagnostic.
    """
    def rcastro(argv, timeout=None):
        return 0, ("Astronomical image processing tools\n"
                   "Version 2.6.9 (build 727, ga2033f5b, 2026-09-08)\n"), ""
    assert tool_version("/x/rc-astro", ["--no-banner", "--help"], runner=rcastro) == \
        "Version 2.6.9 (build 727, ga2033f5b, 2026-09-08)"


def test_the_tools_that_DO_answer_on_the_first_line_are_unchanged():
    """Breaks the symmetry: a rule that always took the second line would pass
    the test above and break these two, which were measured the same day."""
    def graxpert(argv, timeout=None):
        return 0, "GraXpert version: 3.0.2 release: Umbriel\nother stuff\n", ""

    def starnet(argv, timeout=None):
        return 0, "", "starnet2  version: 2.5.2\n"

    assert tool_version("/x/g", ["-v"], runner=graxpert) == \
        "GraXpert version: 3.0.2 release: Umbriel"
    assert tool_version("/x/s", ["--version"], runner=starnet) == \
        "starnet2  version: 2.5.2"


def test_output_with_no_version_anywhere_falls_back_to_the_first_line():
    """Still better than nothing: which tools are installed is the diagnostic,
    and an unrecognised banner at least identifies the build."""
    def odd(argv, timeout=None):
        return 0, "some tool, no version here\n", ""
    assert tool_version("/x/o", ["-v"], runner=odd) == "some tool, no version here"


def test_a_logging_preamble_is_stripped():
    """MEASURED against the real GraXpert 3.0.2, which answers `-v` with

        2026-09-22 18:21:11,063 MainProcess root INFO     GraXpert version: 3.0.2 release: Umbriel

    Fifty characters of its own log framing in front of the four that matter.
    The summary block exists to be read in five seconds; this is the kind of
    noise that stops it being read at all.

    Only a line that STARTS with a date is touched, so a tool whose version
    genuinely begins with something else is left alone."""
    def graxpert(argv, timeout=None):
        return 0, ("2026-09-22 18:21:11,063 MainProcess root INFO     "
                   "GraXpert version: 3.0.2 release: Umbriel\n"), ""
    assert tool_version("/x/g", ["-v"], runner=graxpert) == \
        "GraXpert version: 3.0.2 release: Umbriel"


def test_a_version_that_merely_contains_digits_is_not_mistaken_for_a_preamble():
    def odd(argv, timeout=None):
        return 0, "2026 Edition version 4\n", ""
    assert tool_version("/x/o", ["-v"], runner=odd) == "2026 Edition version 4"
