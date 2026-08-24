import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apply_to_image import output_path


def test_the_output_name_records_both_the_run_and_the_strength():
    """Comparing 0.5 against 1.0 is how you judge a denoiser. A fixed output
    name would overwrite the first answer while you were producing the second."""
    a = output_path("/x/M8.fits", "/runs/n2n_v1", 0.75)
    b = output_path("/x/M8.fits", "/runs/n2n_v1", 1.0)
    c = output_path("/x/M8.fits", "/runs/ladder_v1", 0.75)
    assert a.name == "M8_denoised_n2n_v1_s0.75.fits"
    assert len({a, b, c}) == 3, "two different runs or strengths collide on one filename"


def test_the_result_lands_beside_the_image_not_in_the_cwd():
    """You run this from the repo; your masters live on an external volume."""
    assert output_path("/Volumes/Work2/M8.fits", "/runs/n2n_v1", 0.75).parent.as_posix() == "/Volumes/Work2"


def test_an_explicit_out_wins():
    assert output_path("/x/M8.fits", "/runs/n2n_v1", 0.75, "/tmp/mine.fits").as_posix() == "/tmp/mine.fits"


def test_a_missing_image_fails_loudly_rather_than_writing_nothing():
    from apply_to_image import main
    assert main(["--image", "/nope/missing.fits"]) == 2


def test_the_capture_metadata_survives_denoising(tmp_path):
    """Without this the result opens in Nocturne with no frame count and no
    integration time — the Import panel loses "1h 07m (405 x 10s), Frames 405"
    and the provenance report has nothing to record. Caught by Andreas noticing
    the missing line in the app, not by any test."""
    import numpy as np
    from astropy.io import fits

    src = tmp_path / "master.fits"
    hdu = fits.PrimaryHDU(np.zeros((3, 8, 8), np.float32))
    for k, v in (("STACKCNT", 405), ("EXPTIME", 4050.0), ("OBJECT", "M 8"),
                 ("FILTER", "LP"), ("INSTRUME", "ZWO Seestar S30 Pro")):
        hdu.header[k] = v
    hdu.writeto(src)

    from nocturne.core.export import save_fits
    from nocturne.core.image import AstroImage
    with fits.open(src) as hdul:
        h = hdul[0].header
        keep = {k: h[k] for k in h
                if k not in {"SIMPLE", "BITPIX", "EXTEND", "COMMENT", "HISTORY", ""}
                and not k.startswith("NAXIS")}
    dest = tmp_path / "out.fits"
    save_fits(AstroImage(np.zeros((8, 8, 3), np.float32), is_linear=True), str(dest),
              header=keep)

    got = fits.getheader(dest)
    assert got["STACKCNT"] == 405, "frame count lost"
    assert got["EXPTIME"] == 4050.0, "integration time lost"
    assert got["OBJECT"] == "M 8"
    assert got["NAXIS1"] == 8, "structural keys must describe the NEW array"


def test_a_run_can_be_named_instead_of_pathed(tmp_path, monkeypatch):
    """Typing a full /Volumes path to compare two models is friction, and
    comparing models on a real master is the only check that has ever caught a
    bad one. `--run n2n_v2` must work."""
    import apply_to_image as A

    root = tmp_path / "runs"
    (root / "n2n_v2").mkdir(parents=True)
    (root / "n2n_v2" / "best.pt").write_bytes(b"x")
    monkeypatch.setattr(A, "_RUN_ROOT", root)

    assert A.resolve_run("n2n_v2") == root / "n2n_v2"
    assert A.resolve_run(str(root / "n2n_v2")) == root / "n2n_v2"
    assert A.resolve_run("nope") is None


def test_an_unknown_run_lists_what_exists(tmp_path, monkeypatch, capsys):
    import apply_to_image as A
    root = tmp_path / "runs"
    (root / "ladder_v1").mkdir(parents=True)
    (root / "ladder_v1" / "best.pt").write_bytes(b"x")
    monkeypatch.setattr(A, "_RUN_ROOT", root)
    img = tmp_path / "i.fits"; img.write_bytes(b"x")
    assert A.main(["--image", str(img), "--run", "typo"]) == 2
    assert "ladder_v1" in capsys.readouterr().err
