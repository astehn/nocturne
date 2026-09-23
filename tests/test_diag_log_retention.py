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


# --- the reader (2026-09-23) -------------------------------------------------
#
# The log moved out of the table cell into a panel over the page. That is a
# retention question and not only a layout one: the cell was so cramped that
# Andreas was pasting the text into another application to read it, and a copy
# on a laptop is the one place the promise above cannot reach. His words:
# "having to copy and paste the text into another application kind of beats the
# purpose and all of a sudden we cant guarantee that the retention rules are
# not broken".

ADMIN = SITE / "admin" / "admin.php"


def _code_only(text: str) -> str:
    """`text` with its // comment lines removed.

    Every assertion below has to read CODE. The first version of the innerHTML
    guard scanned the raw source and failed on the comment that says "never
    innerHTML" — a test matching its own explanatory prose, which is how four
    guards on this branch passed or failed for the wrong reason on 2026-09-22.
    """
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("//"))


def _session_cell() -> str:
    """The Session column's markup — the branch that renders a stored log."""
    src = ADMIN.read_text()
    start = src.index("if (!empty($r['diag_log']))")
    return _code_only(src[start:src.index("from the website", start)])


def test_the_log_is_never_offered_as_a_file():
    """No download link and no separate URL: a retention promise can only cover
    the server, and either of those puts a copy somewhere policy cannot follow.
    download.php serves ATTACHMENTS, which expire on their own clock — linking
    the log through it would be the same mistake wearing an existing name."""
    cell = _session_cell()
    assert "download.php" not in cell
    assert "<a " not in cell and "href" not in cell, \
        "the session log must open in the page, not at a URL of its own"


def test_the_reader_moves_the_log_as_TEXT_never_as_MARKUP():
    """Anyone can POST to support.php, so a diag_log is attacker-supplied
    however machine-generated it looks. h() escapes it once into the hidden
    node; reading it back with innerHTML would undo exactly that and execute
    whatever a reporter chose to send."""
    src = ADMIN.read_text()
    reader = _code_only(src[src.index("id=\"logbox\""):])
    assert "innerHTML" not in reader, "the reader assigns markup, not text"
    assert "pre.textContent = src.textContent" in reader


def test_the_stored_log_is_escaped_where_it_is_rendered():
    assert "<pre class=\"full\" hidden><?= h($r['diag_log']) ?></pre>" in _session_cell()


def test_the_preview_shows_the_summary_not_the_session():
    """The preview exists so the standing questions need no click. It must come
    from the helper, which stops at the first timestamped line — pasting the
    log's first N lines straight into the cell would spill the session into
    every row and undo the reason the reader exists."""
    assert "nocturne_diag_preview($r['diag_log'])" in _session_cell()
