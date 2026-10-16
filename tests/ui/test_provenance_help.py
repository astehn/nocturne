"""The help claimed the report shows "exactly how the image was made". It
records this project's steps; export settings, and the history before an
Upscale copy or a Combine, are not in it (audit 2026-10-16)."""
import datetime

from nocturne.core.provenance import build_report
from nocturne.ui.help_content import topic


def test_the_help_promises_only_what_the_report_holds():
    body = topic("provenance").body
    assert "exactly how" not in body
    for words in ("Export settings", "Upscale Crop", "Combine", "not recorded"):
        assert words in body, words


def test_the_words_the_help_quotes_are_the_reports_own():
    """"not recorded" is what the help tells the reader to look for."""
    r = build_report([("Deconvolution", "medium")], {}, app_version="x",
                     date=datetime.date(2026, 10, 16))
    assert "- Deconvolution: not recorded" in r


def test_the_upscale_help_no_longer_says_the_copy_has_no_record():
    body = topic("upscale").body
    assert "with no record of the processing" not in body
    assert "records the upscale itself" in body
