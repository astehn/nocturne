import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.steps.local_contrast import LocalContrastStep


def test_local_contrast_step():
    img = AstroImage(np.random.default_rng(0).random((32, 32, 3)).astype(np.float32))
    out = LocalContrastStep().apply(img, "medium")
    assert out.data.shape == (32, 32, 3)
    assert not np.allclose(out.data, img.data)
