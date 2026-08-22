import json
import os
import sys

import pytest

_TRAINING = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_TRAINING)
sys.path.insert(0, _TRAINING)
sys.path.insert(0, _REPO_ROOT)


# --------------------------------------------------------------------- queue

def test_queue_continues_after_one_config_fails():
    """A crashed experiment at 01:00 must not cost the whole night -- the
    brief's own acceptance test."""
    from nightly import run_queue, ExperimentResult

    good_cfg = {"name": "good1"}
    broken_cfg = {"name": "broken"}
    good_cfg2 = {"name": "good2"}

    def fake_runner(cfg):
        if cfg["name"] == "broken":
            raise RuntimeError("simulated training crash")
        return ExperimentResult(name=cfg["name"], status="ok")

    results = run_queue([good_cfg, broken_cfg, good_cfg2], runner=fake_runner)
    assert [r.status for r in results] == ["ok", "error", "ok"]
    assert results[1].error and "simulated training crash" in results[1].error
    assert results[2].name == "good2"  # the queue reached the config AFTER the crash


def test_run_queue_defaults_to_run_one(monkeypatch):
    """No runner given -> run_queue calls the real run_one, not a no-op."""
    import nightly

    calls = []
    monkeypatch.setattr(nightly, "run_one", lambda cfg: calls.append(cfg) or nightly.ExperimentResult(
        name=cfg["name"], status="ok"))
    results = nightly.run_queue([{"name": "x"}])
    assert calls == [{"name": "x"}]
    assert results[0].status == "ok"


# ------------------------------------------------------------------ promote

def test_a_failed_gate_does_not_promote_the_model(tmp_path):
    """The brief's own acceptance test."""
    from nightly import promote

    run_dir = tmp_path / "run"
    dest = tmp_path / "dest"
    assert promote(run_dir, gate_passed=False, dest=dest) is False
    assert not list(dest.glob("*.onnx"))


def test_promote_copies_the_model_when_the_gate_passes(tmp_path):
    from nightly import promote

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "model.onnx").write_bytes(b"onnx-bytes")
    (run_dir / "model.json").write_text('{"a": 1}')
    dest = tmp_path / "dest"

    assert promote(run_dir, gate_passed=True, dest=dest, sensor="s30") is True
    assert (dest / "denoise_s30_v1.onnx").read_bytes() == b"onnx-bytes"
    assert (dest / "denoise_s30_v1.json").read_text() == '{"a": 1}'
    assert not [p for p in dest.iterdir() if p.name.startswith(".")]  # no temp debris


def test_promote_returns_false_when_no_exported_model_exists(tmp_path):
    """Gate passed but export never ran (e.g. it was skipped) -- nothing to promote."""
    from nightly import promote

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dest = tmp_path / "dest"

    assert promote(run_dir, gate_passed=True, dest=dest) is False
    assert not list(dest.glob("*.onnx"))


def test_promote_leaves_no_partial_file_if_the_copy_is_interrupted(tmp_path, monkeypatch):
    """Prove the guard has teeth: break the copy mid-flight and confirm the
    destination is left clean, not half-written."""
    import nightly

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "model.onnx").write_bytes(b"x" * 1000)
    dest = tmp_path / "dest"

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(nightly.shutil, "copyfile", boom)
    with pytest.raises(OSError):
        nightly.promote(run_dir, gate_passed=True, dest=dest)
    assert not list(dest.rglob("*"))


# -------------------------------------------------------------- run history

def test_saved_metrics_use_only_the_qualified_key_form(tmp_path):
    """report._previous_key() falls back to a plain-depth key when the
    qualified one is absent; if nightly.py ever wrote both forms for the same
    depth, that fallback could match the wrong prior entry. Assert the file
    nightly.py writes never contains the ambiguous plain form at all."""
    from nightly import _save_metrics, _load_previous_metrics

    run_dir = tmp_path / "run"
    metrics = [
        {"target": "NGC281", "depth": 8, "input_err": 1e-4, "model_err": 5e-5},
        {"target": "M45", "depth": 8, "input_err": 2e-4, "model_err": 9e-5},
    ]
    _save_metrics(run_dir, metrics)
    saved = _load_previous_metrics(run_dir)
    assert set(saved.keys()) == {"NGC281:8", "M45:8"}
    assert "8" not in saved


def test_load_previous_metrics_is_none_for_a_first_run(tmp_path):
    from nightly import _load_previous_metrics

    assert _load_previous_metrics(tmp_path / "never_run") is None


# ------------------------------------------------------------ pair identity

def test_pair_identity_parses_target_and_depth_from_the_directory_layout():
    from nightly import _pair_identity

    target, depth = _pair_identity(
        "/Volumes/Work2/Images/Astro/denoise/datasets/ladder_v1/"
        "s30_NGC6888_2026-08-11_LP_10s/pair_0000_in8_target128"
    )
    assert target == "NGC6888"
    assert depth == 8


def test_pair_identity_rejects_a_directory_it_cannot_parse():
    from nightly import _pair_identity

    with pytest.raises(ValueError):
        _pair_identity("/some/random/path/not_a_pair_dir")


# --------------------------------------------------------- the --pairs trap

def test_train_command_always_sets_pairs_explicitly():
    """The exact trap the brief calls out: train.py's own --pairs default
    points at the OLD, superseded dataset. The command nightly.py builds must
    never rely on that default."""
    from nightly import _train_command

    cfg = {"name": "ladder_v1", "sensor": "s30", "epochs": 40}
    cmd = _train_command(cfg, dataset_dir="/Volumes/Work2/Images/Astro/denoise/datasets/ladder_v1",
                          run_dir="/tmp/some_run", smoke=False)
    assert "--pairs" in cmd
    pairs_value = cmd[cmd.index("--pairs") + 1]
    assert pairs_value == "/Volumes/Work2/Images/Astro/denoise/datasets/ladder_v1"
    # the known-old default this must never silently fall back to
    assert pairs_value != "/Volumes/Work2/Images/Astro/TrainingPairs"


def test_train_command_smoke_sets_the_smoke_flag_not_resume():
    from nightly import _train_command

    cmd = _train_command({"name": "x"}, dataset_dir="/d", run_dir="/r", smoke=True)
    assert "--smoke" in cmd
    assert "--resume" not in cmd


def test_train_command_passes_through_optional_hyperparams():
    from nightly import _train_command

    cfg = {"name": "x", "batch": 4, "crop": 128, "lr": 1e-3, "base": 16, "workers": 2}
    cmd = _train_command(cfg, dataset_dir="/d", run_dir="/r", smoke=False)
    for flag, value in (("--batch", "4"), ("--crop", "128"), ("--lr", "0.001"),
                        ("--base", "16"), ("--workers", "2")):
        assert flag in cmd
        assert cmd[cmd.index(flag) + 1] == value


# ------------------------------------------------------------------ run_one

def test_smoke_requires_a_prebuilt_dataset(tmp_path, monkeypatch):
    """Real registration/stacking cannot finish in "under a minute" -- smoke
    mode must refuse to silently kick off the slow build step, and must fail
    with a clear message rather than a confusing downstream crash."""
    import nightly

    monkeypatch.setattr(nightly.build_dataset, "_DEFAULT_DATASET_ROOT", tmp_path / "datasets")
    cfg = {"name": "missing_ds", "smoke": True}
    with pytest.raises(RuntimeError, match="already-built dataset"):
        nightly.run_one(cfg)


# ---------------------------------------------------------------- CLI glue

def test_write_queue_summary_lists_every_config(tmp_path):
    from nightly import write_queue_summary, ExperimentResult

    results = [
        ExperimentResult(name="a", status="ok", gate_passed=True, promoted=True, duration_s=61.0),
        ExperimentResult(name="b", status="error", error="boom", duration_s=3.0),
    ]
    out = write_queue_summary(results, tmp_path / "summary.md")
    text = open(out).read()
    assert "a" in text and "b" in text and "boom" in text
    assert "1/2 configs completed" in text
    assert "1 promoted" in text


def test_cli_config_mode_reports_a_failing_single_config(tmp_path, monkeypatch, capsys):
    import nightly

    monkeypatch.setattr(nightly.build_dataset, "_DEFAULT_DATASET_ROOT", tmp_path / "datasets")
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({"name": "nope", "smoke": True}))

    rc = nightly.main(["--config", str(cfg_path), "--summary-out", str(tmp_path / "summary.md")])

    assert rc == 1
    out = capsys.readouterr().out
    assert "nope" in out
    assert "nope" in (tmp_path / "summary.md").read_text()


def test_cli_queue_mode_sorts_and_runs_every_config_in_the_directory(tmp_path, monkeypatch):
    import nightly

    monkeypatch.setattr(nightly.build_dataset, "_DEFAULT_DATASET_ROOT", tmp_path / "datasets")
    qdir = tmp_path / "configs"
    qdir.mkdir()
    (qdir / "b.json").write_text(json.dumps({"name": "b", "smoke": True}))
    (qdir / "a.json").write_text(json.dumps({"name": "a", "smoke": True}))

    rc = nightly.main(["--queue", str(qdir), "--summary-out", str(tmp_path / "summary.md")])

    assert rc == 1  # neither config has a prebuilt dataset -> both error, queue still finishes
    text = (tmp_path / "summary.md").read_text()
    assert "a" in text and "b" in text


def test_cli_queue_mode_reports_missing_directory(tmp_path, capsys):
    import nightly

    rc = nightly.main(["--queue", str(tmp_path / "empty"), "--summary-out", str(tmp_path / "summary.md")])
    assert rc == 1
    assert "no configs found" in capsys.readouterr().out


# ------------------------------------------------------- what the gate sees

def _fake_pair_dirs():
    dirs = []
    for tgt, rungs in (("NGC281", [1, 2, 4, 8, 16]), ("NGC6888", [1, 2, 4, 8, 16, 32])):
        for p in (0, 1):
            for d in rungs:
                dirs.append(f"/ds/s30_{tgt}_2026-01-01_LP_10s/pair_{p:04d}_in{d}_target128")
    return dirs


def test_a_real_run_gates_on_every_held_out_pair():
    """The design's gate is "every held-out target at every depth". A real
    (non-smoke) run must therefore not silently sample a subset -- the gate is
    the only thing standing between an unattended run and overwriting the
    model the app ships."""
    from nightly import select_gate_pairs

    dirs = _fake_pair_dirs()
    chosen = select_gate_pairs(dirs, None)
    assert set(chosen) == set(dirs)          # every one, none invented
    assert len(chosen) == len(dirs) == 22


def test_pairs_are_ordered_by_target_then_numeric_depth():
    """Plain string sort puts in16 BEFORE in1 ('6' < '_'), so a truncated run
    picked an arbitrary depth spread. Order by parsed depth instead."""
    from nightly import select_gate_pairs

    order = [d.rsplit("/", 1)[-1] for d in select_gate_pairs(_fake_pair_dirs(), None)
             if "NGC281" in d and "pair_0000" in d]
    assert order == [f"pair_0000_in{d}_target128" for d in (1, 2, 4, 8, 16)]


def test_a_truncated_run_still_touches_every_held_out_target():
    """If a config does cap the count, the cap must not hand every slot to
    whichever target sorts first -- the previous behaviour gave all three to
    NGC281 and never evaluated NGC6888 at all."""
    from nightly import select_gate_pairs, _pair_identity

    chosen = select_gate_pairs(_fake_pair_dirs(), 3)
    assert len(chosen) == 3
    assert {_pair_identity(d)[0] for d in chosen} == {"NGC281", "NGC6888"}


def test_truncation_prefers_the_deepest_rungs():
    """A cap should spend its budget where harm actually showed up: the deep
    end is what the shipped model damaged, not the 1-frame rung."""
    from nightly import select_gate_pairs, _pair_identity

    chosen = select_gate_pairs(_fake_pair_dirs(), 2)
    assert sorted(_pair_identity(d)[1] for d in chosen) == [16, 32]


def test_select_gate_pairs_handles_a_cap_larger_than_the_dataset():
    from nightly import select_gate_pairs

    dirs = _fake_pair_dirs()
    assert len(select_gate_pairs(dirs, 500)) == len(dirs)
