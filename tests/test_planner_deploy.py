"""The include list is an ALLOWLIST resolved by a non-recursive glob.

`include = ["*.html", "styles.css", "*.js", ...]` matches `site/planner.js` but
NOT `site/vendor/astronomy.min.js` (a subdirectory) and NOT
`site/planner-targets.json` (no pattern covers .json at all). A page whose
assets are missing from this list works in local preview and 404s in
production, with nothing failing anywhere in between.

Both `deploy.example.toml` and `deploy.local.toml` are checked: the example
documents the include list and is what a fresh clone / new deploy host copies
from, the local config is the one that actually deploys this machine's site --
and only the example can be committed (`deploy.local.toml` is gitignored). A
guard that only checked the example could pass green while the real deploy
still silently dropped an asset, which is exactly the false assurance this
test exists to prevent.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
EXAMPLE_TOML = ROOT / "packaging" / "deploy.example.toml"
LOCAL_TOML = ROOT / "packaging" / "deploy.local.toml"
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


def _include_list(toml_path: Path) -> list[str]:
    import tomllib
    with open(toml_path, "rb") as f:
        return list(tomllib.load(f)["website"]["include"])


def _resolved_files(include: list[str]) -> set[str]:
    """Resolve an include list against site/ the way deploy.py actually would."""
    import deploy
    cfg = deploy.DeployConfig(
        repo="x/y", ssh_host="h", remote_path="/var/www/n", owner="www-data:www-data",
        dir_mode="755", file_mode="644", include=include,
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
    return resolved


def test_the_example_config_would_ship_every_planner_asset():
    resolved = _resolved_files(_include_list(EXAMPLE_TOML))
    missing = [a for a in PLANNER_ASSETS if a not in resolved]
    assert not missing, (
        f"these would NOT deploy and the live page would 404 them: {missing}")


@pytest.mark.skipif(
    not LOCAL_TOML.exists(),
    reason="the real deploy config is gitignored; only checked on a machine that deploys",
)
def test_the_LOCAL_config_would_ship_every_planner_asset():
    """deploy.local.toml, not deploy.example.toml, is the config that actually
    deploys this machine's site. The example test above only proves the
    documented reference is correct -- it says nothing about what a real
    `deploy.py` run would do here, since deploy.local.toml can drift from the
    example independently (and already had before this task: ping.php,
    cleanup.php, fonts/, robots.txt, sitemap.xml exist there but not in the
    example). Checking only the example would let this exact regression --
    an asset silently missing from production -- pass green.
    """
    resolved = _resolved_files(_include_list(LOCAL_TOML))
    missing = [a for a in PLANNER_ASSETS if a not in resolved]
    assert not missing, (
        f"these would NOT deploy and the live page would 404 them: {missing}")


def test_the_vendored_library_is_pinned_and_intact():
    lib = SITE / "vendor" / "astronomy.min.js"
    assert lib.exists(), "astronomy-engine must be vendored, never loaded from a CDN"
    assert lib.stat().st_size == 116424, (
        "astronomy-engine 2.1.19 is 116424 bytes; a different size means the pin "
        "moved or the file was edited")
