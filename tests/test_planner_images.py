"""Guards for planner target images.

site/ is gitignored and deploys by rsync, so these read the working copy.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SITE = ROOT / "site"
pytestmark = pytest.mark.skipif(not SITE.is_dir(), reason="site/ is local-only")


def test_the_wall_writes_a_320_derivative():
    """The collapsed card is 64px (48 on mobile). Without this it is served a
    900px JPEG — twenty times the bytes, on the one page that gets opened in a
    field."""
    php = (SITE / "admin" / "wall.php").read_text(encoding="utf-8")
    sizes = re.search(r"foreach \(\[(.*?)\] as \$edge", php, re.S)
    assert sizes, "the derivative loop moved; find it and update this guard"
    assert "320" in sizes.group(1), "the approval loop does not write a 320px file"


def test_the_showcase_writes_a_320_derivative():
    py = (ROOT / "packaging" / "build_showcase.py").read_text(encoding="utf-8")
    assert "320" in py, "build_showcase.py does not produce a 320px size"
