

def test_the_engines_section_says_what_the_record_says_ran():
    """A history line reading "Star Reduction 0.40" cannot say whether
    StarXTerminator or the free split produced it. The section reports what
    the record says, and that the record does not say, rather than reading
    today's tool setup as though it had been in force then (2026-10-16)."""
    import datetime
    from nocturne.core.provenance import build_report
    from nocturne.settings import Settings
    entries = [("Crop", None), ("Star Reduction", 0.4), ("Stretch", 0.6)]
    r = build_report(entries, {}, app_version="0.24.0", date=datetime.date(2026, 9, 2),
                     settings=Settings())
    engines = r.split("## Engines")[1]
    assert "- Star Reduction: not recorded" in engines
    # a step with no engine choice must not appear there
    assert "Stretch" not in engines and "Crop" not in engines


def test_the_engines_section_ignores_the_current_setup():
    """The audit's contradiction: "Color — photometric" in the steps and
    "Color: Nocturne (sky balance)" under Engines, because ASTAP was not set
    up on the machine making the report. The same history gives the same
    section whatever is installed."""
    import datetime
    from nocturne.core.provenance import build_report
    from nocturne.settings import Settings
    entries = [("Color", {"method": "photometric", "fell_back": False}), ("Background", "strong"),
               ("Noise Reduction", {"engine": "rcastro", "level": "strong", "ran": "rcastro"})]
    bare = build_report(entries, {}, app_version="1", date=datetime.date(2026, 10, 16),
                        settings=Settings())
    none = build_report(entries, {}, app_version="1", date=datetime.date(2026, 10, 16))
    assert bare == none
    engines = bare.split("## Engines")[1]
    assert "- Color: **ASTAP + Gaia**" in engines
    assert "- Background: **GraXpert**" in engines
    assert "- Noise Reduction: **NoiseXTerminator**" in engines
    assert "sky balance" not in engines and "built-in" not in engines


def test_the_report_is_wired_to_what_it_reads():
    """The dialog passes the CURRENT state's metadata (an upscaled copy's
    origin lives there) and the source label (a Combine opened before it
    recorded its inputs is known only by it)."""
    from pathlib import Path
    src = (Path(__file__).parents[2] / "nocturne" / "ui" / "main_window.py").read_text(encoding="utf-8")
    # Up to the blank line, not to the first ")" — the call spans lines and
    # closes parens inside it.
    call = src.split("report = build_report(")[1].split("\n\n")[0]
    assert "source_label=self._source_label" in call, call
    assert "saved_version=self._saved_app_version" in call, call


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
    # By the dialog's own labels and units (star_spikes_dialog._on_change).
    for line in ("- length: 0.50", "- intensity: 100%", "- number of stars: 9",
                 "- rotation: 30°", "- variation: 35%", "- star colour: ×1.20"):
        assert line in r, line


def test_the_stretch_headline_says_linked_or_unlinked():
    """The linkage changes what a stretch does to colour; the summary line
    says it, as the log does (his ask, 2026-09-27)."""
    import datetime
    from nocturne.core.provenance import build_report
    for linked, word in ((True, "Stretch — 0.12 linked"), (False, "Stretch — 0.12 unlinked")):
        r = build_report([("Stretch", {"amount": 0.12, "linked": linked})], {},
                         app_version="0.42.0", date=datetime.date(2026, 9, 29))
        assert word in r, r


def test_a_photometric_entry_without_the_record_is_not_called_a_run():
    """Before 2026-10-16 a successful calibration wrote no fell_back key, and
    before 0.44 a fallback wrote none either: a missing key cannot be read
    as "ASTAP + Gaia ran"."""
    import datetime
    from nocturne.core.provenance import build_report
    r = build_report([("Color", {"method": "photometric"})], {}, app_version="1",
                     date=datetime.date(2026, 10, 16))
    line = [ln for ln in r.splitlines() if ln.startswith("- Color:")][0]
    assert "**ASTAP + Gaia**" not in line and "not recorded" in line


def test_star_steps_that_never_split_without_a_tool_are_not_said_to_have():
    """Narrowband and Colour Balance work on the whole image without a star
    tool, De-green Stars inside a star mask (receipt._FALLBACKS)."""
    import datetime
    from nocturne.core.provenance import build_report
    r = build_report([("Narrowband", {"palette": "HOO"}), ("De-green Stars", 1.0),
                      ("Star Reduction", 0.3)], {}, app_version="1",
                     date=datetime.date(2026, 10, 16))
    eng = r.split("## Engines")[1]
    assert "- Narrowband: not recorded" in eng and "whole image" in eng
    assert "- De-green Stars: not recorded" in eng and "star mask" in eng
    assert "- Star Reduction: not recorded — the stars were separated by" in eng
