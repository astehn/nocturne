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


def test_deleting_a_submission_also_clears_its_planner_images():
    """The failure being guarded against is specific: a planner card still
    showing a photograph whose owner asked for it to be taken down. The app's
    own help promises 'a published one can be taken down by asking'.

    The task brief pointed this at admin.php, using the report-delete path's
    variable name ($rid) as its example. The actual submission delete —
    `DELETE FROM submissions WHERE id = ?` — lives in wall.php's `remove`
    action (site/admin/wall.php), using $sid; admin.php has no submission
    delete path at all. Checked with
    `grep -rn "DELETE FROM submissions" site/` before writing this against
    the real file rather than the one the brief named.
    """
    php = (SITE / "admin" / "wall.php").read_text(encoding="utf-8")
    # the submission delete path must touch planner_images before it commits
    assert "planner_images" in php, "the delete path does not clear associations"


def test_the_artifact_is_not_in_the_deploy_allowlist():
    """It is SERVER-GENERATED. Listing it would let a site publish overwrite it
    with whatever is (not) in the local tree. rsync runs without --delete, so an
    unlisted server-side file survives untouched — the same arrangement
    uploads/ relies on."""
    for name in ("deploy.local.toml", "deploy.example.toml"):
        p = ROOT / "packaging" / name
        if not p.is_file():
            continue
        assert "planner-images.json" not in p.read_text(encoding="utf-8"), \
            f"{name} lists planner-images.json; a deploy would clobber it"
