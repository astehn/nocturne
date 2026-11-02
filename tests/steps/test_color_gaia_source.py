"""The colour step says which catalogue source answered (2026-11-01).

With two sources, a log that only said "N stars matched" would leave nobody
able to tell whether our own copy is actually being used."""
from nocturne.core.color import ColorSettings
from nocturne.core.spcc import SpccResult
from nocturne.steps.color import ColorStep
from nocturne.tools.gaia import GaiaStar, GaiaStars

from tests.steps.test_color_dualband import _img
from tests.steps.test_color_step import _FakeAstap


def _run(monkeypatch, stars):
    monkeypatch.setattr("nocturne.core.spcc.photometric_gains",
                        lambda img, wcs, gaia, **k: SpccResult((2.0, 1.0, 0.5), 40))
    step = ColorStep(astap=_FakeAstap(), gaia_query=lambda *a, **k: stars)
    step.apply(_img("IRCUT"), ColorSettings(method="photometric"))
    return step.last_message


def _stars(source, failure=None):
    s = GaiaStars([GaiaStar(100.0, 0.0, 0.8, 10.0)])
    s.source, s.mirror_failure = source, failure
    return s


def test_the_log_names_the_source(monkeypatch):
    msg = _run(monkeypatch, _stars("nocturneastro.com"))
    assert msg.endswith("· from nocturneastro.com")
    assert "didn't answer" not in msg


def test_the_log_says_when_the_mirror_did_not_answer(monkeypatch):
    msg = _run(monkeypatch, _stars("VizieR", "TimeoutError: timed out"))
    assert "· from VizieR" in msg
    assert "(nocturneastro.com didn't answer: TimeoutError: timed out)" in msg


def test_a_plain_list_from_an_older_fake_still_works(monkeypatch):
    msg = _run(monkeypatch, [GaiaStar(100.0, 0.0, 0.8, 10.0)])
    assert "stars matched" in msg and "from" not in msg
