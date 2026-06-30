from seestar_processor import APP_NAME, __version__
from seestar_processor.ui.about import about_html, help_html


def test_about_has_name_version_and_tools():
    text = about_html()
    assert APP_NAME in text
    assert __version__ in text
    assert "GraXpert" in text and "RC-Astro" in text


def test_help_covers_flow_and_requirements():
    text = help_html()
    assert "Import" in text and "Stretch" in text and "Export" in text
    assert "GraXpert" in text  # mentions the required tool
