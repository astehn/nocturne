

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


def test_a_step_absent_from_the_recipe_map_is_still_named_in_the_report():
    """Starless Levels is deliberately NOT recipe-capturable (see
    tests/test_recipe.py), and `_serialize` reaches `_NAME_TO_STAGE` — so the
    thing to check is that dropping it there did not turn the report into raw
    ids. It does not: the report is written from the recorded NAME, and a
    tuple option is serialised without consulting the map at all."""
    import datetime
    from nocturne.core.provenance import build_report
    r = build_report([("Starless Levels", (0.1, 0.8))], {}, app_version="0.24.0",
                     date=datetime.date(2026, 9, 9))
    assert "Starless Levels" in r
    assert "starless_levels" not in r
    # Both values still recorded — now BY NAME. They were printed as a bare
    # "values: 0.1, 0.8" until 2026-09-17, which for this tool is its entire
    # content with no way to tell which number is which.
    assert "- black point: 0.1" in r
    assert "- white point: 0.8" in r


def test_positional_options_are_named_not_bare_numbers():
    """`values: 0.071, 1.0, 1.0` made the reader guess. The names are the ones
    beside the sliders in step_panels.py, so the report and the control the user
    moved agree."""
    import datetime
    from nocturne.core.provenance import build_report
    r = build_report([("Levels", [0.071, 1.0, 0.98]), ("Saturation", [0.5, 0.15])],
                     {}, app_version="0.33.0", date=datetime.date(2026, 9, 17))
    for line in ("- black point: 0.071", "- midtones: 1.0", "- white point: 0.98",
                 "- saturation: 0.5", "- nebula boost: 0.15"):
        assert line in r, line
    assert "values:" not in r


def test_a_tool_that_gains_a_number_falls_back_instead_of_mislabelling():
    """The failure mode this must not have: three names against four values,
    silently naming the wrong ones and dropping the new one. A wrong report is
    worse than a terse one."""
    import datetime
    from nocturne.core.provenance import build_report
    r = build_report([("Levels", [0.1, 0.2, 0.3, 0.4])], {}, app_version="0.33.0",
                     date=datetime.date(2026, 9, 17))
    assert "- values: 0.1, 0.2, 0.3, 0.4" in r
    assert "black point" not in r


def test_the_footer_attributes_the_version_to_the_report_not_the_image():
    """"Nocturne 0.33.0 · report generated ..." read as "made with 0.33.0",
    which for a project processed months earlier and opened today is false — in
    the one document whose whole purpose is to be an authoritative record."""
    import datetime
    from nocturne.core.provenance import build_report
    r = build_report([("Stretch", 0.3)], {}, app_version="0.33.0",
                     date=datetime.date(2026, 9, 17), saved_version="0.28.0")
    assert "Report generated by Nocturne 0.33.0 on 17 September 2026" in r
    assert "project last saved by Nocturne 0.28.0" in r


def test_the_saved_version_is_omitted_when_it_adds_nothing():
    """A project saved by the running build, or never saved at all, must not
    grow a second version line saying the same thing twice."""
    import datetime
    from nocturne.core.provenance import build_report
    same = build_report([("Stretch", 0.3)], {}, app_version="0.33.0",
                        date=datetime.date(2026, 9, 17), saved_version="0.33.0")
    none = build_report([("Stretch", 0.3)], {}, app_version="0.33.0",
                        date=datetime.date(2026, 9, 17))
    assert "last saved" not in same
    assert "last saved" not in none


def test_star_spikes_records_all_six_of_its_controls():
    """It recorded `""` until 2026-09-17 — a tool added after the provenance
    feature, wired to `run_step` (which demands an option) with nothing chosen
    to put in it. The report said "Star Spikes" and stopped."""
    import datetime
    from nocturne.core.provenance import build_report
    params = {"length": 0.5, "count": 9, "angle": 30.0,
              "intensity": 1.0, "variation": 0.35, "colour": 1.2}
    r = build_report([("Star Spikes", params)], {}, app_version="0.33.0",
                     date=datetime.date(2026, 9, 17))
    for k, v in params.items():
        assert f"- {k}: {v}" in r, k
