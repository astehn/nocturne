"""The include list is an ALLOWLIST resolved by a non-recursive glob.

`include = ["*.html", "styles.css", "*.js", ...]` matches `site/planner.js` but
NOT `site/vendor/astronomy.min.js` (a subdirectory) and NOT
`site/planner-targets.json` (no pattern covers .json at all). A page whose
assets are missing from this list works in local preview and 404s in
production, with nothing failing anywhere in between.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT / "packaging"))

pytestmark = pytest.mark.skipif(
    not (SITE / "index.html").exists(),
    reason="site/ is decoupled and gitignored -- only validated when present locally",
)

PLANNER_ASSETS = [
    "planner.html",
    "planner.js",
    "planner-engine.js",
    "planner-targets.json",
    "vendor/astronomy.min.js",
]


def _example_include() -> list[str]:
    import tomllib
    with open(ROOT / "packaging" / "deploy.example.toml", "rb") as f:
        return list(tomllib.load(f)["website"]["include"])


def test_the_example_config_would_ship_every_planner_asset():
    import deploy
    cfg = deploy.DeployConfig(
        repo="x/y", ssh_host="h", remote_path="/var/www/n", owner="www-data:www-data",
        dir_mode="755", file_mode="644", include=_example_include(),
        exclude=list(deploy.REQUIRED_EXCLUDES),
    )
    resolved = {Path(p).relative_to(SITE).as_posix()
                for p in deploy._resolve_includes(cfg, SITE)
                if Path(p).is_file()}
    # directory entries resolve to the directory itself; expand them
    dirs = [Path(p) for p in deploy._resolve_includes(cfg, SITE) if Path(p).is_dir()]
    for d in dirs:
        for f in d.rglob("*"):
            if f.is_file():
                resolved.add(f.relative_to(SITE).as_posix())
    missing = [a for a in PLANNER_ASSETS if a not in resolved]
    assert not missing, (
        f"these would NOT deploy and the live page would 404 them: {missing}")


def test_the_vendored_library_is_pinned_and_intact():
    lib = SITE / "vendor" / "astronomy.min.js"
    assert lib.exists(), "astronomy-engine must be vendored, never loaded from a CDN"
    assert lib.stat().st_size == 116424, (
        "astronomy-engine 2.1.19 is 116424 bytes; a different size means the pin "
        "moved or the file was edited")
