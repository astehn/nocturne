

def test_the_report_names_which_engine_ran(tmp_path):
    """A history line reading "Star Reduction 0.40" cannot say whether
    StarXTerminator or the free split produced it, and the two differ
    materially. The report says."""
    import datetime
    from nocturne.core.provenance import build_report
    from nocturne.settings import Settings
    entries = [("Crop", None), ("Star Reduction", 0.4), ("Stretch", 0.6)]
    r = build_report(entries, {}, app_version="0.24.0", date=datetime.date(2026, 9, 2),
                     settings=Settings())
    assert "## Engines" in r
    assert "Star Reduction" in r and "free star split" in r
    assert "RC-Astro is not configured" in r
    # a step with no engine choice must not appear there
    engines = r.split("## Engines")[1]
    assert "Stretch" not in engines and "Crop" not in engines


def test_the_engines_section_is_omitted_rather_than_guessed(tmp_path):
    """Without settings the report cannot know which engine ran, so it says
    nothing instead of inventing a default."""
    import datetime
    from nocturne.core.provenance import build_report
    r = build_report([("Star Reduction", 0.4)], {}, app_version="0.24.0",
                     date=datetime.date(2026, 9, 2))
    assert "## Engines" not in r


def test_the_report_is_wired_to_the_real_settings():
    """The section is worthless if the dialog never passes settings — that is
    how a feature ships looking complete and reporting nothing."""
    from pathlib import Path
    src = (Path(__file__).parents[2] / "nocturne" / "ui" / "main_window.py").read_text()
    # Up to the blank line, not to the first ")" — the call spans three lines
    # and `self.project.entries()` closes a paren inside it, which truncated
    # the first version of this test to nothing.
    call = src.split("report = build_report(")[1].split("\n\n")[0]
    assert "settings=self.settings" in call, f"settings not passed:\n{call}"


def test_the_engines_section_does_not_claim_to_know_what_ran_historically():
    """Nothing in a history records the tool configuration in force when a step
    was applied. A report produced after RC-Astro was uninstalled would describe
    the free split even for a step StarXTerminator performed — so the section
    must say it describes the CURRENT setup rather than implying otherwise."""
    import datetime
    from nocturne.core.provenance import build_report
    from nocturne.settings import Settings
    r = build_report([("Star Reduction", 0.4)], {}, app_version="0.24.0",
                     date=datetime.date(2026, 9, 2), settings=Settings())
    section = r.split("## Engines")[1]
    assert "current tool configuration" in section
