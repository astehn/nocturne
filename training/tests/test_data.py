import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PAIRS_ROOT = "/Volumes/Work2/Images/Astro/TrainingPairs"


def test_dataset_reports_the_sigma_of_the_tile_it_returns():
    """Measured on the tile actually handed to the model, not the whole pair --
    a crop from a bright core and a crop from empty sky have different noise."""
    import data as D
    tiles = D.scan_tiles(PAIRS_ROOT)
    ds = D.TileDataset(tiles[:4], D.DataConfig(), train=False)
    noisy, clean, mask, sigma = ds[0]
    from noise import estimate_sigma
    assert abs(float(sigma) - estimate_sigma(noisy.permute(1, 2, 0).numpy())) < 1e-6
    assert float(sigma) > 0
