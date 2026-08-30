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


# -------------------------------------------------------------------- stage

def _models_dir_digest():
    """A digest of the models directory the APP loads from, as it stands now."""
    import hashlib
    from pathlib import Path

    models = Path(__file__).resolve().parents[2] / "nocturne" / "assets" / "models"
    h = hashlib.sha256()
    for f in sorted(models.iterdir()) if models.is_dir() else []:
        h.update(f.name.encode())
        h.update(str(f.stat().st_size).encode())
        h.update(hashlib.sha256(f.read_bytes()).digest() if f.stat().st_size < 20_000_000
                 else str(f.stat().st_mtime_ns).encode())
    return h.hexdigest()


def test_a_passing_run_leaves_the_shipped_model_untouched(tmp_path):
    """The 2026-08-23 run passed its gate and promoted a model that still
    damaged the M8 master. The gate got stronger, but 'passed' still is not
    'safe' -- the proxy is blind to everything that is not chroma-shaped. So
    the runner loses the ability to ship anything.

    Asserted as UNCHANGED bytes of the REAL nocturne/assets/models directory,
    not as 'different from the new model': `!= new` would pass while the runner
    wrote some third wrong thing, and a monkeypatched destination would miss a
    hard-coded path entirely.
    """
    import nightly

    before = _models_dir_digest()

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "model.onnx").write_bytes(b"a freshly trained model")
    (run_dir / "model.json").write_text('{"sigma_scale": 0.0015}')

    assert nightly.stage(str(run_dir), gate_passed=True, sensor="s30")

    assert _models_dir_digest() == before
    assert (run_dir / "staged" / "denoise_s30_v1.onnx").read_bytes() == b"a freshly trained model"
    assert (run_dir / "staged" / "denoise_s30_v1.json").read_text() == '{"sigma_scale": 0.0015}'
    assert not [p for p in (run_dir / "staged").iterdir() if p.name.startswith(".")]


def test_a_failing_gate_stages_nothing(tmp_path):
    import nightly

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "model.onnx").write_bytes(b"x")
    assert not nightly.stage(str(run_dir), gate_passed=False, sensor="s30")
    assert not (run_dir / "staged").exists()


def test_stage_returns_false_when_no_exported_model_exists(tmp_path):
    """Gate passed but export never ran (e.g. it was skipped) -- nothing to stage."""
    import nightly

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert nightly.stage(str(run_dir), gate_passed=True) is False
    assert not (run_dir / "staged").exists()


def test_stage_leaves_no_partial_file_if_the_copy_is_interrupted(tmp_path, monkeypatch):
    """Prove the guard has teeth: break the copy mid-flight and confirm the
    staging directory is left clean, not half-written."""
    import nightly

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "model.onnx").write_bytes(b"x" * 1000)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(nightly.shutil, "copyfile", boom)
    with pytest.raises(OSError):
        nightly.stage(str(run_dir), gate_passed=True)
    assert not list((run_dir / "staged").rglob("*"))


def test_nightly_no_longer_exposes_promote():
    """A leftover promote() would be an easy accident to reintroduce."""
    import nightly
    assert not hasattr(nightly, "promote")


def test_nightly_does_not_know_where_the_app_loads_models_from():
    """The whole point of the change: the runner has no destination to ship to.
    Pinned on the source, so a future edit that reintroduces the path is caught
    even if no test happens to exercise that code path."""
    import inspect
    import nightly

    assert not hasattr(nightly, "_NOCTURNE_MODELS_DIR")
    src = inspect.getsource(nightly)
    assert "assets" not in src, "nightly.py names the app's model directory again"


def test_promote_ships_only_what_was_staged_and_only_when_told(tmp_path, monkeypatch):
    """The human step. --yes is the explicit consent; without it, an aborted
    prompt must leave the shipped model byte-identical."""
    import hashlib
    import promote as promote_mod

    models = tmp_path / "models"
    models.mkdir()
    shipped = models / "denoise_s30_v1.onnx"
    shipped.write_bytes(b"old model")
    before = hashlib.sha256(shipped.read_bytes()).hexdigest()
    monkeypatch.setattr(promote_mod, "_MODELS", models)

    run_dir = tmp_path / "run"
    staged = run_dir / "staged"
    staged.mkdir(parents=True)
    (staged / "denoise_s30_v1.onnx").write_bytes(b"new model")
    (staged / "denoise_s30_v1.json").write_text('{"sigma_scale": 0.002}')

    monkeypatch.setattr("builtins.input", lambda *a: "n")
    assert promote_mod.main(["--run", str(run_dir)]) == 1
    assert hashlib.sha256(shipped.read_bytes()).hexdigest() == before

    assert promote_mod.main(["--run", str(run_dir), "--yes"]) == 0
    assert shipped.read_bytes() == b"new model"
    assert (models / "denoise_s30_v1.json").read_text() == '{"sigma_scale": 0.002}'
    assert not [p for p in models.iterdir() if p.name.startswith(".")]


def test_promote_refuses_a_run_with_nothing_staged(tmp_path, monkeypatch, capsys):
    import promote as promote_mod

    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setattr(promote_mod, "_MODELS", models)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert promote_mod.main(["--run", str(run_dir)]) == 2
    assert not list(models.iterdir())


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
        ExperimentResult(name="a", status="ok", gate_passed=True, staged=True, duration_s=61.0),
        ExperimentResult(name="b", status="error", error="boom", duration_s=3.0),
    ]
    out = write_queue_summary(results, tmp_path / "summary.md")
    text = open(out).read()
    assert "a" in text and "b" in text and "boom" in text
    assert "1/2 configs completed" in text
    assert "1 staged" in text


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


# ------------------------------------------------------- the deep-end proxy

def test_the_deep_end_proxy_returns_nothing_when_the_master_is_absent(monkeypatch):
    """The deep-end proxy is the ONLY check that can reach the depths the user
    actually works at -- a truth-based gate never can, because the deepest
    stack IS the truth. So its absence must be distinguishable from its
    approval: it returns None, and run_one turns that into an empty result set,
    which check_no_harm already refuses to pass."""
    import nightly
    from gate import DepthResult, check_no_harm

    monkeypatch.setattr(nightly, "_M8_MASTER", "/nonexistent/master.fits")
    assert nightly._deep_end_result(object(), object(), 0.75) is None
    # an EMPTY list of deep-end results means the same thing and is refused
    # the same way -- "nothing to report" must never read as approval
    assert nightly._with_deep_end([DepthResult("NGC6888", 8, 1e-4, 5e-5)], []) == []
    # and an empty result set is what run_one hands the gate in that case
    assert not check_no_harm([], tolerance=0.0).passed


def test_an_unverified_deep_end_leaves_the_gate_nothing_to_pass_on():
    """A held-out set that passes on its own must NOT carry the run when the
    deep end could not be measured. Asserted on the exact list the gate is
    handed, because "passed" is what authorises staging a model."""
    import nightly
    from gate import DepthResult, check_no_harm

    healthy = [DepthResult("NGC6888", 8, 1.0e-4, 0.5e-4),
               DepthResult("NGC6888", 32, 1.3e-4, 0.7e-4)]
    assert check_no_harm(healthy).passed          # they would pass alone

    lines = []
    assert nightly._with_deep_end(healthy, None, on_line=lines.append) == []
    assert not check_no_harm(nightly._with_deep_end(healthy, None, on_line=lines.append)).passed
    assert any("deep-end" in line for line in lines)


def test_a_harmful_deep_end_fails_a_run_whose_held_out_pairs_all_pass():
    """The 2026-08-23 shape of the incident: every held-out depth improved and
    the deep master was still damaged."""
    import nightly
    from gate import DepthResult, check_no_harm

    healthy = [DepthResult("NGC6888", 8, 1.0e-4, 0.5e-4)]
    # both deep-end checks are handed over together; only one of them objects
    chroma = DepthResult("M8-deep-chroma", 405, 0.0407, 0.0410, 0.15)
    detail = DepthResult("M8-deep-detail", 405, 1.0 / 1.10, 1.0 / 0.98)
    combined = nightly._with_deep_end(healthy, [chroma, detail])
    assert combined == healthy + [chroma, detail]
    g = check_no_harm(combined)
    assert not g.passed
    assert any("M8-deep-detail" in f for f in g.failures)


def test_the_deep_end_proxy_measures_both_sides_over_the_same_sky_pixels(tmp_path, monkeypatch):
    """Input and output must be compared over ONE set of pixels, chosen from
    the input. A mask recomputed on the model's own output would let a model
    that darkens the nebula move the goalposts under itself and score its own
    damage as background."""
    import numpy as np
    import gate
    import nightly
    from astropy.io import fits

    rng = np.random.default_rng(7)
    img = (0.02 + 0.4 * np.linspace(0, 1, 128, dtype=np.float32)[None, :, None]
           + rng.normal(0, 0.002, (128, 128, 3))).astype(np.float32)
    master = tmp_path / "master.fits"
    fits.writeto(master, np.transpose(img, (2, 0, 1)).astype(np.float32))
    monkeypatch.setattr(nightly, "_M8_MASTER", str(master))

    import evaluate
    # A model that crushes the bright end. It has to REORDER pixels by
    # luminance, not merely rescale them: sky_mask is a percentile, so any
    # monotonic output (x*0.2+0.4, say) yields the identical mask and the
    # assertions below could not tell the two apart. Clamping makes 70% of the
    # frame tie at the top, which moves the 60th percentile onto the clamp.
    monkeypatch.setattr(evaluate, "apply_model",
                        lambda x, *a, **k: np.minimum(np.asarray(x, np.float32),
                                                      np.percentile(x, 30)))

    seen = []
    real_bias = gate.patch_chroma_bias
    monkeypatch.setattr(gate, "patch_chroma_bias",
                        lambda img_hwc, mask, **kw: seen.append(mask.copy()) or real_bias(img_hwc, mask, **kw))

    results = nightly._deep_end_result(object(), object(), 0.75)
    assert results is not None
    assert [r.target for r in results] == ["M8-deep-chroma", "M8-deep-detail"]
    assert all(r.depth == nightly._M8_DEPTH for r in results)
    assert len(seen) == 2
    assert np.array_equal(seen[0], seen[1]), "input and output were masked differently"
    assert np.array_equal(seen[0], gate.sky_mask(img)), "the mask did not come from the input"


def test_train_command_widens_the_material_without_renaming_the_model():
    """`sensor` and `sensors` are two different things and the config has to
    keep them apart: the model Nocturne ships is still denoise_s30_v1 (the S30
    Pro is the camera the app targets), while the material it learns from now
    includes the S50 groups -- which are the deep ones."""
    from nightly import _train_command
    cmd = _train_command({"name": "n2n_v2", "sensor": "s30",
                          "sensors": ["s30", "s50"]},
                         dataset_dir="/d", run_dir="/r", smoke=False)
    assert "--sensors" in cmd
    assert cmd[cmd.index("--sensors") + 1] == "s30,s50"
    assert cmd[cmd.index("--sensor") + 1] == "s30"


def test_split_sensors_fall_back_to_the_single_sensor_key():
    """An old config with only `sensor` must keep meaning exactly what it did."""
    from nightly import _split_sensors
    assert _split_sensors({"sensor": "s30"}) == ("s30",)
    assert _split_sensors({"sensor": "s30", "sensors": ["s30", "s50"]}) == ("s30", "s50")
    assert _split_sensors({}) == ("s30",)


def test_the_deep_end_is_judged_at_the_apps_strength_not_the_configs():
    """Measured 2026-08-24: s30_v2 — the checkpoint that broke a real M8 master —
    FAILS the detail check at strength 0.75 (0.979 on M8, 0.942 on M45) and
    PASSES it at 1.0 (1.249 / 1.258). At 1.0 it strips 91% of the noise, so its
    noise-matched control is a much blurrier blur and beating it is trivial.

    Every config in this repo sets strength 1.0. A deep-end check that read the
    config would therefore have missed the exact regression it exists to catch,
    so the strength is pinned to what the app itself applies.
    """
    import ast
    from pathlib import Path

    import nightly

    assert nightly.DEEP_END_STRENGTH == 0.75

    src = Path(nightly.__file__).read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_deep_end_result")
    kwargs = [kw for call in ast.walk(fn) if isinstance(call, ast.Call)
              for kw in call.keywords if kw.arg == "strength"]
    assert kwargs, "_deep_end_result never passes a strength"
    for kw in kwargs:
        assert not (isinstance(kw.value, ast.Name) and kw.value.id == "strength"), (
            "the deep end is using the config's strength — at 1.0 that lets the "
            "known-bad checkpoint through")


# ------------------------------------------------------------- injection

def test_an_injection_config_selects_the_injection_dataset():
    """The gate must keep judging on REAL held-out pairs even when training is
    manufactured. Manufactured data judging a model trained on manufactured
    data would be a closed loop that cannot detect its own premise being wrong.
    """
    from pathlib import Path

    cfg = json.loads(Path(_TRAINING, "configs", "inject_v1.json").read_text())
    assert cfg.get("dataset") == "injection"
    assert cfg["sensor"] == "s30"          # the model's identity, not its material
    # WAS {"s30","s50"}: the S50 groups were the deep ones and a clean target
    # had to come from somewhere deep. All three died with Work2 on 2026-08-25
    # (M42 2361 frames, SH2-142 1357, NGC7023 821) and none is recoverable, so
    # the archive is entirely S30 Pro now. Still a list, so re-adding borrowed
    # data later stays a config change.
    assert set(cfg["sensors"]) == {"s30"}
    # The plan's draft asserted the held-out names were absent from a
    # `train_targets` key. There is no such key -- the split is code, not
    # config -- so that assertion passed on an empty list and proved nothing.
    # What the file can honestly promise is that it RECORDS the holdout; the
    # enforcement is tested against the split itself in test_data.py.
    recorded = json.dumps(cfg.get("_comment_held_out", ""))
    # NGC7000 replaced NGC281 on 2026-08-30 so NGC281's 1514 frames could train;
    # it keeps the light-polluted holdout the split needs. M8 and M45 are not
    # negotiable — they are Andreas' own masters.
    for held in ("M8", "M45", "NGC6888", "NGC7000"):
        assert held in recorded


def test_the_gate_dataset_and_the_injection_tiles_are_different_places():
    """One config, two datasets: real pairs for the gate, manufactured tiles
    for training. If they were the same directory the gate could end up
    scoring the model on the very material it was trained on."""
    import build_injection
    import nightly

    cfg = {"name": "inject_v1", "dataset": "injection"}
    gate_dir = nightly.gate_dataset_dir(cfg)
    inject_dir = build_injection.injection_root(cfg)
    assert gate_dir != inject_dir
    assert str(inject_dir).startswith(str(gate_dir))   # kept together, not mixed


def test_manufactured_tiles_can_never_be_read_as_held_out_pairs(tmp_path):
    """scan_tiles is what feeds the gate its held-out pairs. Injection tiles
    live under the same dataset directory, so this is the actual guarantee:
    they are invisible to it."""
    import data as D

    inj = tmp_path / "injection" / "s30_M16_2026-08-09_LP_10s"
    inj.mkdir(parents=True)
    (inj / "tile_000000.npz").write_bytes(b"")

    # Positive control, so this cannot pass merely because scan_tiles found
    # nothing anywhere: a real pair in the layout it DOES read is picked up.
    pair = tmp_path / "s30_NGC6888_2026-08-09_LP_10s" / "pair_0000_in16_target128"
    (pair / "tiles").mkdir(parents=True)
    (pair / "manifest.json").write_text(json.dumps(
        {"pair": {"input_count": 16, "target_count": 128, "disjoint": True,
                  "kind": "truth"}}))
    (pair / "tiles" / "tile_000000.npz").write_bytes(b"")

    found = D.scan_tiles(str(tmp_path))
    # Canonical since 2026-08-30: the target is normalised at scan time, because
    # the archive writes "NGC 6888_sub" where every split list says "NGC6888".
    assert [t.target for t in found] == ["ngc6888"]


def test_the_train_command_selects_the_injection_dataset():
    """train.py defaults to the ladder tiles, so an injection run that did not
    say so would train on real pairs and report success -- the same trap
    --pairs already had."""
    import build_injection
    from nightly import _train_command

    cfg = {"name": "inject_v1", "sensor": "s30", "dataset": "injection"}
    cmd = _train_command(cfg, dataset_dir="/d", run_dir="/r", smoke=False)
    assert cmd[cmd.index("--dataset") + 1] == "injection"
    assert cmd[cmd.index("--injection-tiles") + 1] == str(
        build_injection.injection_root(cfg))


def test_a_ladder_config_still_gets_the_tile_dataset():
    """Every existing config omits `dataset`; none of them may change meaning."""
    from nightly import _train_command

    cmd = _train_command({"name": "n2n_v2", "sensor": "s30"},
                         dataset_dir="/d", run_dir="/r", smoke=False)
    assert cmd[cmd.index("--dataset") + 1] == "tiles"
    assert "--injection-tiles" not in cmd


def _fake_injection_tiles(root, groups=(("s30_M16_x_LP_10s", 3), ("s30_M27_x_LP_10s", 2))):
    """Injection tiles in build_injection.py's layout: a target carrying its
    own residual noise and four half-stack fields (sqrt(2) noisier)."""
    import numpy as np

    rng = np.random.default_rng(0)
    for slug, n in groups:
        d = root / slug
        d.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            level = 0.05 + np.linspace(0, 0.03, 128, dtype=np.float32)[None, :, None]
            target = (level + rng.normal(0, 0.0006, (128, 128, 3))).astype(np.float32)
            fields = rng.normal(0, 0.00085, (4, 128, 128, 3)).astype(np.float32)
            np.savez(d / f"tile_{i:06d}.npz", target=target, fields=fields,
                     coverage=np.ones((128, 128), np.float32), depth=np.int32(800))
    return root


def test_train_py_really_trains_on_the_injection_tiles(tmp_path):
    """The wiring, end to end and for real: train.py must read the injection
    root, split it, and drive InjectionDataset through a DataLoader. Everything
    else in this section checks the COMMAND; a command that is right while the
    script ignores the flag would train on the ladder and report success --
    exactly the trap --pairs already had."""
    import subprocess
    import sys as _sys

    _fake_injection_tiles(tmp_path / "ds" / "injection")
    out = tmp_path / "run"
    proc = subprocess.run(
        [_sys.executable, os.path.join(_TRAINING, "train.py"),
         "--pairs", str(tmp_path / "ds"), "--dataset", "injection",
         "--out", str(out), "--smoke", "--batch", "2", "--crop", "64",
         "--base", "8", "--workers", "0", "--sample-every", "0"],
        capture_output=True, text=True, cwd=tmp_path)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    log = (out / "train.log").read_text()
    assert "dataset       : injection" in log
    assert "m16" in log and "m27" in log
    assert (out / "best.pt").is_file()
    cfg = json.load(open(out / "config.json"))
    assert cfg["dataset"] == "injection"
    assert cfg["split"] == {"train": ["m16"], "val": ["m27"], "test": []}
