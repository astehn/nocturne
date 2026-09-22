"""The published retention promise and the sweep that performs it must agree.

privacy.html says the diagnostic log is deleted when the report is deleted, or
after 28 days, whichever comes first. The first half is the admin delete; the
second is cleanup.php. A promise nothing performs is the failure mode this site
has already had once — a draft claimed "what you saw in the form is all that
reached the server" while the schema stored an IP.

site/ is gitignored and deploys by rsync, so these read the working copy.
"""
import re
from pathlib import Path

import pytest

SITE = Path(__file__).parent.parent / "site"
pytestmark = pytest.mark.skipif(not SITE.is_dir(), reason="site/ is local-only")


def test_the_sweep_clears_the_diagnostic_log():
    """Without this, the page promises an expiry that never happens."""
    php = (SITE / "cleanup.php").read_text()
    assert re.search(r"UPDATE reports SET diag_log = NULL", php), \
        "cleanup.php never clears diag_log"
    assert "RETENTION_DAYS" in php.split("diag_log = NULL")[1][:400], \
        "the diag_log sweep does not use the same clock as everything else"


def test_the_privacy_page_states_BOTH_clocks():
    """The attachment expires at 28 days; the log expires at 28 days OR when
    the report is deleted, whichever is sooner. A reader will assume one clock
    unless told, and these are related but not identical."""
    prose = (SITE / "_src" / "privacy.html").read_text()
    assert "whichever comes first" in prose, "the two clocks are not distinguished"
    assert "28 days" in prose


def test_the_privacy_page_does_not_still_claim_the_app_sends_nothing():
    """It said the diagnostics "travel to the page in a way your browser never
    transmits to the server". True of the web form, and FALSE since Nocturne
    posts the report itself. Andreas on the last version of this: "we are now
    actively lying in several places on the website"."""
    prose = (SITE / "_src" / "privacy.html").read_text()
    assert "your browser never transmits" not in prose


def test_the_page_says_the_web_form_sends_no_log():
    """The asymmetry is deliberate and a reader should not have to infer it."""
    prose = (SITE / "_src" / "privacy.html").read_text()
    assert "Reporting from the support page sends" in prose


def test_the_generated_pages_match_their_sources():
    """site/*.html is GENERATED from site/_src/. Editing the output silently
    reverts on the next build, so the copy above is only real if it reached
    the built page."""
    for name in ("privacy.html", "support.html"):
        # Whitespace-collapsed: the phrase wraps across lines in the built
        # page, and a literal match failed on the line break rather than on
        # anything real.
        built = re.sub(r"\s+", " ", (SITE / name).read_text())
        assert "diagnostic log" in built, f"{name} was not rebuilt"
