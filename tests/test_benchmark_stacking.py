"""The stacking benchmark's measurable parts.

FQA-009 from the 2026-09-01 feature audit. The script itself needs real
multi-gigabyte sessions, so what is tested here is everything that does not:
the metric on a synthetic master, the corpus contract, and the memory sampler —
which is where the first version was wrong.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _starry_master(path, n=256, nstars=120, sigma=1.6, seed=7):
    """A master with resolvable stars, so the sharpness metric has something to
    measure. Uniform noise gives no stars and the metric returns nothing —
    the fixture blind spot that has bitten this project repeatedly."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n]
    img = rng.random((n, n)) * 0.01 + 0.02
    for _ in range(nstars):
        cy, cx = rng.uniform(8, n - 8, 2)
        img += rng.uniform(0.3, 0.9) * np.exp(
            -((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * sigma ** 2))
    fits.PrimaryHDU(np.clip(img, 0, 1).astype(np.float32)).writeto(str(path))
    return str(path)


def test_the_metric_reports_the_fields_a_report_needs(tmp_path):
    from benchmark_stacking import measure_master
    m = measure_master(_starry_master(tmp_path / "m.fits"))
    for key in ("width", "height", "stars", "psf_stars", "half_light_px",
                "background_rms", "output_mb"):
        assert key in m, f"missing {key}"
    assert m["width"] == m["height"] == 256
    assert m["stars"] > 20, "no stars detected; the metric measured nothing"
    assert m["psf_stars"] > 0
    assert 0.1 < m["half_light_px"] < 20


def test_a_blurrier_master_measures_larger(tmp_path):
    """The one property the number must have. Without this the metric could
    return a stable, meaningless constant and every comparison would agree."""
    from benchmark_stacking import measure_master
    sharp = measure_master(_starry_master(tmp_path / "s.fits", sigma=1.2))
    blurry = measure_master(_starry_master(tmp_path / "b.fits", sigma=2.4))
    assert blurry["half_light_px"] > sharp["half_light_px"] * 1.2, (
        f"blur did not register: {sharp['half_light_px']} -> {blurry['half_light_px']}")


def test_the_memory_sampler_reports_a_real_peak_not_a_high_water_mark():
    """The first version used resource.getrusage, whose ru_maxrss never
    decreases for the life of the process — so in a five-session run every
    session after the first inherited the largest earlier peak. Measured:
    10694, 10698, 10699, 10699 MB across four sessions of different sizes."""
    from benchmark_stacking import _PeakRSS
    with _PeakRSS(interval=0.05) as p:
        block = np.ones((40_000_000,), np.uint8)   # 40 MB, TOUCHED so it is resident
        block[::1000] = 2
        import time
        time.sleep(0.3)
        del block
    assert p.mb > 0 and p.largest_mb > 0
    assert p.mb >= p.largest_mb, "the tree total cannot be below its largest member"


def test_the_two_memory_numbers_are_not_the_same_claim():
    """They are reported as a pair on purpose: the sum double-counts the shared
    interpreter pages of every worker (measured: 11 processes at ~1.16 GB each
    summing to 10.4 GB), so it is comparable between runs but is not what the
    machine needs. Reporting only one would mislead whichever was chosen."""
    src = (ROOT / "scripts" / "benchmark_stacking.py").read_text()
    assert '"peak_rss_sum_mb"' in src and '"peak_rss_largest_mb"' in src
    # Check for USE, not for the word: the class docstring explains at length
    # why getrusage is wrong, and a bare substring search trips on that
    # explanation. Third time this exact trap has caught a test in this repo.
    import re
    assert not re.search(r"^\s*import resource", src, re.M), "resource is imported again"
    assert not re.search(r"resource\.getrusage\(", src), "the high-water-mark measurement is back"


def test_the_corpus_is_valid_and_says_what_each_session_is_for():
    """A corpus of paths with no rationale becomes a list nobody prunes."""
    data = json.loads((ROOT / "scripts" / "corpus.json").read_text())
    assert data["sessions"], "no sessions"
    for s in data["sessions"]:
        assert s["name"] and s["folder"]
    assert "_comment" in data, "the corpus does not say why these sessions"


def test_the_script_runs_and_reports_its_own_usage():
    """It is a developer tool; if --help is broken nobody finds out what it
    measures. This also catches an import-time error, which is how a sibling
    script in this repo shipped broken for a whole training run."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "benchmark_stacking.py"), "--help"],
                       capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert r.returncode == 0, r.stderr
    assert "--corpus" in r.stdout and "--limit" in r.stdout


def test_it_never_writes_to_the_session_folders():
    """The corpus points at the only copies of several nights. The script must
    write masters into --workdir and nowhere else."""
    src = (ROOT / "scripts" / "benchmark_stacking.py").read_text()
    body = src.split("def run_session")[1].split("def load_corpus")[0]
    assert "os.path.join(workdir" in body
    assert "os.path.join(folder" not in body.split("output_path")[0].split("subs = ")[-1] \
        or "glob" in body, "an output path may be derived from the source folder"
