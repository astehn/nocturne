"""site/cron/download_tally.php must never reach the web root.

It reads Apache's access log, which holds every visitor's IP, and it is meant
to run as root from /etc/cron.d. Published, it would be a URL anyone could
request. The include list is an allowlist that never names cron/, which is the
first guard; `cron/` in the exclude list is the second, because rsync applies
excludes even to explicitly named sources. Both are checked, in both configs --
see test_planner_deploy.py for why the local one matters as much as the example.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT / "packaging"))

pytestmark = pytest.mark.skipif(
    not (SITE / "cron" / "download_tally.php").exists(),
    reason="site/ is decoupled and gitignored -- only validated when present locally",
)

CONFIGS = [ROOT / "packaging" / "deploy.example.toml",
           ROOT / "packaging" / "deploy.local.toml"]


def _website(path):
    import tomllib
    with open(path, "rb") as f:
        return tomllib.load(f)["website"]


@pytest.mark.parametrize("path", [p for p in CONFIGS if p.exists()], ids=lambda p: p.name)
def test_nothing_under_cron_is_published(path):
    import deploy
    w = _website(path)
    cfg = deploy.DeployConfig(
        repo="x/y", ssh_host="h", remote_path="/var/www/n", owner="www-data:www-data",
        dir_mode="755", file_mode="644", include=list(w["include"]),
        exclude=list(deploy.REQUIRED_EXCLUDES))
    cron = (SITE / "cron").resolve()
    published = [Path(p).resolve() for p in deploy._resolve_includes(cfg, SITE)]
    leaked = [p for p in published if p == cron or cron in p.parents or p in cron.parents]
    assert not leaked, f"{path.name} would publish {leaked}"


@pytest.mark.parametrize("path", [p for p in CONFIGS if p.exists()], ids=lambda p: p.name)
def test_cron_is_also_excluded(path):
    assert "cron/" in _website(path)["exclude"], (
        f"{path.name}: add \"cron/\" to [website].exclude -- the allowlist alone is one "
        "mistyped glob from publishing a script that reads the access log")
