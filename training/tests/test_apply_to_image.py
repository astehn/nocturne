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
