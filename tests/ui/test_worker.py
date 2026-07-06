import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QThreadPool  # noqa: E402
from nocturne.ui.worker import run_async  # noqa: E402


def test_run_async_delivers_result(qtbot):
    got = []
    run_async(QThreadPool.globalInstance(), lambda: 21 * 2, got.append)
    qtbot.waitUntil(lambda: got == [42], timeout=2000)


def test_run_async_reports_error(qtbot):
    errs = []

    def boom():
        raise ValueError("nope")

    run_async(QThreadPool.globalInstance(), boom, lambda r: None, errs.append)
    qtbot.waitUntil(lambda: len(errs) == 1, timeout=2000)
    assert isinstance(errs[0], ValueError)


