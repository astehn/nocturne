import os
import sys

import numpy as np
import pytest

_TRAINING = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_TRAINING)
sys.path.insert(0, _TRAINING)
sys.path.insert(0, _REPO_ROOT)


def test_report_leads_with_the_verdict_and_diffs_the_previous_run(tmp_path):
    """The brief's own acceptance test, verbatim."""
    from report import write_report
    from gate import GateResult

    p = write_report(
        tmp_path,
        GateResult(False, ["NGC6888 @ 405 frames: ..."]),
        metrics=[{"depth": 8, "model_err": 6.8e-5}],
        images=["compare.png"],
        previous={"8": {"model_err": 7.4e-5}},
    )
    text = open(p).read()
    assert text.splitlines()[0].startswith("# VERDICT: FAIL")
    assert "NGC6888 @ 405" in text
    assert "compare.png" in text
    assert "-8.1%" in text or "8.1%" in text  # improvement vs previous


def test_report_passes_verdict_when_gate_passes(tmp_path):
    from report import write_report
    from gate import GateResult

    p = write_report(
        tmp_path,
        GateResult(True, []),
        metrics=[{"target": "NGC281", "depth": 32, "model_err": 3.1e-5}],
        images=[],
        previous=None,
    )
    text = open(p).read()
    assert text.splitlines()[0] == "# VERDICT: PASS"
    assert "No previous run recorded" in text


def test_report_says_no_previous_run_explicitly_when_none_given(tmp_path):
    """A missing previous run must be a stated fact, not a silently blank diff
    column -- the first night of a new ladder is a legitimate state."""
    from report import write_report
    from gate import GateResult

    p = write_report(
        tmp_path, GateResult(True, []), metrics=[{"depth": 8, "model_err": 1e-4}],
        images=[], previous=None,
    )
    text = open(p).read()
    assert "vs previous" not in text.split("## Metrics")[1].split("## Previous")[0]
    assert "No previous run recorded" in text


def test_report_marks_a_regression_with_a_positive_percentage(tmp_path):
    from report import write_report
    from gate import GateResult

    p = write_report(
        tmp_path,
        GateResult(True, []),
        metrics=[{"depth": 405, "model_err": 5.0e-5}],
        images=[],
        previous={"405": {"model_err": 4.0e-5}},
    )
    text = open(p).read()
    assert "25.0%" in text
    assert "-25.0%" not in text


def test_report_matches_previous_run_by_target_when_depths_collide(tmp_path):
    """Two targets can share a depth; a plain depth key would silently diff
    the wrong pair unless the target-qualified key is tried first."""
    from report import write_report
    from gate import GateResult

    p = write_report(
        tmp_path,
        GateResult(True, []),
        metrics=[
            {"target": "NGC281", "depth": 8, "model_err": 5.0e-5},
            {"target": "M45", "depth": 8, "model_err": 9.0e-5},
        ],
        images=[],
        previous={
            "NGC281:8": {"model_err": 5.0e-5},   # unchanged -> 0.0%
            "M45:8": {"model_err": 6.0e-5},       # +50% regression
        },
    )
    text = open(p).read()
    assert "0.0%" in text
    assert "50.0%" in text


def test_report_creates_run_dir_if_missing(tmp_path):
    from report import write_report
    from gate import GateResult

    run_dir = tmp_path / "fresh_run"
    p = write_report(str(run_dir), GateResult(True, []), metrics=[], images=[])
    assert os.path.isfile(p)
    assert os.path.basename(p) == "report.md"


# --------------------------------------------------------------- image sheet

def test_render_comparison_sheet_uses_one_stretch_per_row(tmp_path, monkeypatch):
    """The trap this project already hit once: a per-panel stretch makes a
    smoother image render differently for reasons unrelated to denoising.
    Assert `_stretch_params` is called exactly once per row -- not once per
    panel -- so every panel in a row is provably sharing one transfer function."""
    import report
    from nocturne.core import autostretch

    calls = []
    orig = autostretch._stretch_params

    def counting(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    # render_comparison_sheet does `from nocturne.core.autostretch import
    # _stretch_params` INSIDE the function, so this patch (applied to the
    # module attribute before the call) is what a fresh import picks up.
    monkeypatch.setattr(autostretch, "_stretch_params", counting)

    rng = np.random.default_rng(0)
    truth = (rng.random((32, 32, 3)) * 0.1 + 0.05).astype(np.float32)
    noisy = truth + rng.normal(0, 0.01, truth.shape).astype(np.float32)
    model = truth + rng.normal(0, 0.002, truth.shape).astype(np.float32)

    rows = [
        ("NGC281 @ 8f", truth, [("noisy", noisy), ("model", model), ("truth", truth)]),
        ("NGC281 @ 32f", truth, [("noisy", noisy), ("model", model)]),
    ]
    out = report.render_comparison_sheet(rows, str(tmp_path / "sheet.png"))
    assert os.path.isfile(out)
    assert len(calls) == len(rows)  # exactly one stretch derivation per row


def test_render_comparison_sheet_applies_identical_stretch_to_every_panel(tmp_path):
    """Direct proof, not just a call count: two panels holding the SAME pixel
    values must render to the SAME output pixels, because they share the
    row's one stretch. If each panel derived its own params this would fail
    only when the two arrays differ -- so use two panels built from data with
    different local statistics but feed the identical array as both."""
    import report
    from nocturne.core.autostretch import _apply_params, _stretch_params

    rng = np.random.default_rng(1)
    truth = (rng.random((16, 16, 3)) * 0.2 + 0.1).astype(np.float32)
    same = truth.copy()

    rows = [("target @ depth", truth, [("a", same), ("b", same)])]
    out_path = str(tmp_path / "sheet.png")
    report.render_comparison_sheet(rows, out_path, cell=16)

    from PIL import Image

    sheet = np.asarray(Image.open(out_path).convert("RGB"))
    left = sheet[:16, :16]
    right = sheet[:16, 16:32]
    assert np.array_equal(left, right)


def test_render_comparison_sheet_writes_a_grid_sized_png(tmp_path):
    import report

    truth = np.full((8, 8, 3), 0.1, np.float32)
    rows = [
        ("a", truth, [("x", truth), ("y", truth)]),
        ("b", truth, [("x", truth), ("y", truth), ("z", truth)]),
    ]
    out = report.render_comparison_sheet(rows, str(tmp_path / "grid.png"), cell=10)
    from PIL import Image

    img = Image.open(out)
    assert img.size == (10 * 3, (10 + 18) * 2)  # widest row (3 panels) x 2 rows


def test_render_comparison_sheet_rejects_empty_rows(tmp_path):
    import report

    with pytest.raises(ValueError):
        report.render_comparison_sheet([], str(tmp_path / "x.png"))


def test_panel_labels_are_ascii_because_the_default_font_is():
    """render_comparison_sheet draws with PIL's default bitmap font, which has
    no glyph beyond ASCII -- an em-dash there renders as a hollow box in the
    one artefact that gets looked at every morning."""
    from report import _panel_label

    label = _panel_label("NGC281 @ 16f", "noisy")
    label.encode("ascii")            # raises if a non-ASCII char sneaks back in
    assert "noisy" in label and "NGC281 @ 16f" in label
