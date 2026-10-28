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
    }), encoding="utf-8")
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


def test_about_shows_credit_line(monkeypatch):
    """Each runnable NR model is credited, beside the model licence that
    actually ships — the models are not GPL, and About must say so."""
    from nocturne.core import nr_models
    from nocturne.ui.about import NR_LICENCE
    models = [nr_models.NRModel("v23.0", "Freja", "/m/freja.nnr", True, kind="nnr",
                                credit="Trained on donated subs & more")]
    monkeypatch.setattr(nr_models, "available", lambda: models)
    html = about_html()
    assert "Trained on donated subs &amp; more" in html      # escaped, not markup
    assert NR_LICENCE.is_file()
    # The licence itself is on the page, word for word, not just its file name:
    # inside a macOS bundle nobody finds the file.
    import html as _html
    text = NR_LICENCE.read_text(encoding="utf-8").strip()
    assert _html.escape(text) in html


def test_about_names_the_licence_file_when_it_cannot_be_read(monkeypatch, tmp_path):
    from nocturne.core import nr_models
    from nocturne.ui import about
    models = [nr_models.NRModel("v23.0", "Freja", "/m/freja.nnr", True, kind="nnr",
                                credit="c")]
    monkeypatch.setattr(nr_models, "available", lambda: models)
    monkeypatch.setattr(about, "NR_LICENCE", tmp_path / "NR-MODEL-LICENCE.txt")
    assert "NR-MODEL-LICENCE.txt" in about_html()


def test_about_does_not_put_tray_models_under_the_model_licence(monkeypatch):
    from nocturne.core import nr_models
    tray = nr_models.NRModel("v9", "Dev", "/t/v9.onnx", False, credit="dev only")
    monkeypatch.setattr(nr_models, "available", lambda: [tray])
    assert "Nocturne NR" not in about_html()


def test_about_has_no_nr_section_without_models(monkeypatch):
    from nocturne.core import nr_models
    monkeypatch.setattr(nr_models, "available", lambda: [])
    assert "Nocturne NR" not in about_html()
