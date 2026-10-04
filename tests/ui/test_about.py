import json

from nocturne.ui.about import load_contributors, about_html


def test_load_contributors_ships_valid_data():
    data = load_contributors()
    assert isinstance(data, dict)
    assert data["built_with"], "built_with is populated"
    assert data["creator"]["name"]


def test_load_contributors_bad_path_is_safe():
    data = load_contributors("/no/such/file.json")
    assert isinstance(data, dict)                 # safe minimal fallback, no raise
    assert "creator" in data


def test_about_html_has_all_credits():
    html = about_html()
    assert "Andreas" in html
    assert "not a developer" in html.lower()
    assert "Claude (Anthropic)" in html
    for lib in ("PySide6", "NumPy", "astropy", "astroalign", "SEP", "Pillow"):
        assert lib in html
    assert "GraXpert" in html and "RC-Astro" in html
    assert "Photon Donors" in html


def test_no_donors_shows_the_invitation():
    from nocturne.ui.about import load_contributors
    data = dict(load_contributors(), photon_donors=[])
    assert "Be the first" in about_html(data)     # empty donors -> invite line


def test_about_html_lists_a_donor_when_present(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({
        "creator": {"name": "X", "role": "Y"}, "ai": "Z",
        "built_with": [{"name": "NumPy", "what": "n"}],
        "works_with": [], "photon_donors": ["Jane Nebula"],
    }))
    html = about_html(load_contributors(str(p)))
    assert "Jane Nebula" in html
    assert "Be the first" not in html


def test_about_credits_exactly_the_fonts_that_ship():
    """The SIL OFL requires the licence to travel with the binaries; naming the
    families is the other half of the courtesy. Pinned to what is actually
    bundled, so a family added or dropped cannot leave About lying."""
    from nocturne.ui.fonts import FONT_DIR, PLATE_FAMILIES

    html = about_html()
    assert "SIL Open Font License" in html
    for _label, family in PLATE_FAMILIES:
        assert family in html, f"{family} ships with the app but is not credited"
        stem = family.replace(" ", "").lower()
        assert (FONT_DIR / f"OFL-{stem}.txt").is_file(), f"no licence ships for {family}"
    credited = {f["name"] for f in load_contributors()["fonts"]}
    assert credited == {fam for _l, fam in PLATE_FAMILIES}


def test_the_shipped_donors_are_credited():
    """The site promises an in-app credit as a Photon Donor (index 'Lend your
    light'); the first two donations arrived 2026-10-04."""
    from nocturne.ui.about import about_html
    page = about_html()
    assert "Matt Boylan" in page and "Alvaro Vaquero" in page
    assert "Be the first to lend your light" not in page
    assert "&quot;big rig&quot;" in page, "a donor's quotes are escaped as text"
