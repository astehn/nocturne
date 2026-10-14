import pytest


@pytest.fixture(scope="session", autouse=True)
def _gc_on_the_gui_thread(qapp):
    """As the app does (nocturne/__main__.py): cyclic garbage is collected on
    the GUI thread only, never inside a pool job (ui/gc_guard.py)."""
    from nocturne.ui import gc_guard
    gc_guard.install(qapp)
    yield
    gc_guard.uninstall(qapp)


@pytest.fixture(autouse=True)
def _no_worker_outlives_its_test():
    """Waits for every global-pool job to finish, then delivers what they
    posted — their done/error signals and any deferred deletes — before the
    next test starts. A job's done left queued landed in the NEXT test's event
    loop, on a window pytest-qt had already deleted: the class of crash behind
    the one full-suite segfault on the no-freezes branch (2026-10-06). Live
    previews made pool jobs routine."""
    yield
    try:
        from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
    except ImportError:
        return
    QThreadPool.globalInstance().waitForDone(30000)
    if QCoreApplication.instance() is not None:
        QCoreApplication.sendPostedEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def _no_real_file_dialogs(monkeypatch):
    """A real file dialog in the suite blocks forever with nothing to click.

    That happened once already: migrating the app off the static
    QFileDialog.getXxx helpers left old monkeypatches pointing at a class the
    code no longer calls, so tests opened genuine modal panels and the run hung
    instead of failing. A hang tells you nothing; this raises with the caption,
    which names the test and the dialog in one line.
    """
    from nocturne.ui import file_dialogs

    def refuse(parent, caption, directory, filters):
        raise AssertionError(
            f"a real file dialog was opened in a test: {caption!r}. Patch "
            f"nocturne.ui.file_dialogs.choose_folder / open_file / save_file.")

    monkeypatch.setattr(file_dialogs, "_prepare", refuse)
