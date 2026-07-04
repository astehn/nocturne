import json

from seestar_processor.ui.about import load_contributors, about_html


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
    assert "Be the first" in html                 # empty donors -> invite line


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
