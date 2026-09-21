"""The Share dialog's "Send to the wall" button.

Spec §3.1–3.3. The dialog is where consent is asked for, where the plate is
left empty, and where a success must not be repeatable.
"""
import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.ui.share_dialog import ShareDialog          # noqa: E402
from nocturne.settings import Settings                     # noqa: E402


META = {"target": "NGC 7000", "source_label": "ngc7000.fits",
        "frames": 163, "livetime": 3260.0, "exposure": 20.0,
        "date": "2026-08-09T23:14:02", "creator": "ZWO Seestar S30 Pro"}


def _rgb(h=400, w=300):
    a = np.zeros((h, w, 3), np.uint8)
    a[:] = 180
    return a


def _dlg(qtbot, handle="me", **kw):
    d = ShareDialog(_rgb(), dict(META), Settings(handle=handle), **kw)
    qtbot.addWidget(d)
    return d


def test_the_button_is_off_until_consent_is_ticked(qtbot):
    d = _dlg(qtbot)
    assert d._submit_btn.isEnabled() is False
    d._consent.setChecked(True)
    assert d._submit_btn.isEnabled() is True
    d._consent.setChecked(False)
    assert d._submit_btn.isEnabled() is False


def test_no_handle_blocks_the_button_and_says_WHERE_to_set_one(qtbot):
    """§3.1. The handle is the only attribution there is, and it lives in
    Settings — so refusing without saying where is a dead end."""
    d = _dlg(qtbot, handle="")
    d._consent.setChecked(True)
    assert d._submit_btn.isEnabled() is False
    assert "settings" in d._submit_note.text().lower()


def test_the_image_is_composed_with_an_EMPTY_plate(qtbot, monkeypatch):
    """THE ONE THAT MATTERS. The wall renders its caption from the fields; a
    burned plate would print the same words twice and is unreadable at tile
    size anyway."""
    seen = {}
    real = __import__("nocturne.ui.share_dialog", fromlist=["compose_share"]).compose_share

    def spy(src, crop, caption, **kw):
        seen["caption"] = caption
        return real(src, crop, caption, **kw)

    monkeypatch.setattr("nocturne.ui.share_dialog.compose_share", spy)
    d = _dlg(qtbot)
    d._compose_for_submission()
    plate = seen["caption"]
    assert not plate.designation and not plate.common and not plate.credit, \
        f"the plate must be empty, got {plate}"


def test_the_preview_still_gets_its_REAL_plate(qtbot, monkeypatch):
    """The negative half. Without it, _compose_for_submission could be wired to
    blank every compose and the test above would still pass."""
    seen = []
    real = __import__("nocturne.ui.share_dialog", fromlist=["compose_share"]).compose_share

    def spy(src, crop, caption, **kw):
        seen.append(caption)
        return real(src, crop, caption, **kw)

    monkeypatch.setattr("nocturne.ui.share_dialog.compose_share", spy)
    d = _dlg(qtbot)
    d._compose_current()
    assert seen and (seen[-1].designation or seen[-1].credit), \
        "the ordinary preview must still carry the plate"


def test_a_successful_send_spends_the_button(qtbot):
    """§3.3: once a picture has gone, it must not go again — a second copy is
    work for Andreas and confusion for the sender."""
    d = _dlg(qtbot)
    d._consent.setChecked(True)
    d._on_submit_finished(True, "Sent. It will appear once it has been looked at.")
    assert d._submit_btn.isEnabled() is False
    assert d._consent.isEnabled() is False
    assert "looked at" in d._submit_note.text()


def test_a_FAILED_send_RE_ENABLES_the_button(qtbot):
    """The case that matters more: a network blip must not cost someone their
    submission.

    The button is disabled FIRST, as an in-flight send leaves it. The first
    version of this test called _on_submit_finished on an already-enabled
    button and asserted it was still enabled — which passes even if the
    failure path does nothing at all, and it did.
    """
    d = _dlg(qtbot)
    d._consent.setChecked(True)
    d._submit_btn.setEnabled(False)            # as _on_submit_clicked leaves it
    assert d._submit_btn.isEnabled() is False

    d._on_submit_finished(False, "Could not reach the gallery: timed out")
    assert d._submit_btn.isEnabled() is True, "a failed send must be retryable"
    assert d._consent.isEnabled() is True
    assert "could not reach" in d._submit_note.text().lower()


def test_a_failed_send_does_not_re_enable_without_consent(qtbot):
    """If the tick was cleared while the send was in flight, the button must
    stay off — the state on screen has to keep meaning what it says."""
    d = _dlg(qtbot)
    d._consent.setChecked(True)
    d._submit_btn.setEnabled(False)
    d._consent.setChecked(False)
    d._on_submit_finished(False, "timed out")
    assert d._submit_btn.isEnabled() is False


def test_the_button_is_disabled_WHILE_the_send_is_in_flight(qtbot, monkeypatch):
    """Two presses would queue the same picture twice."""
    started = {}
    monkeypatch.setattr("nocturne.ui.share_dialog.QThreadPool.globalInstance",
                        lambda: type("P", (), {"start": lambda s, j: started.setdefault("job", j)})())
    d = _dlg(qtbot)
    d._consent.setChecked(True)
    d._on_submit_clicked()
    assert d._submit_btn.isEnabled() is False
    assert "job" in started, "the work must be handed to a thread pool"


def test_the_send_runs_off_the_interface_thread(qtbot):
    """A 15 MB upload is seconds on a slow line. Inline, it freezes the dialog,
    and a frozen window reads as a crash."""
    from PySide6.QtCore import QRunnable
    from nocturne.ui import share_dialog
    assert issubclass(share_dialog._SubmitJob, QRunnable)


def test_the_worker_never_touches_widgets(qtbot):
    """Qt widgets are not thread-safe. The job carries data in and a signal
    out; if it held the dialog it could repaint from the wrong thread."""
    import ast
    import inspect
    from nocturne.ui import share_dialog

    # Strip docstrings and comments before looking. The first version of this
    # test matched the word "setText" inside the class's OWN docstring, which
    # explains why it must not call it — a test that reads the prose rather
    # than the code, and the same trap the support.js prefill test documents.
    tree = ast.parse(inspect.getsource(share_dialog._SubmitJob))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    code = ast.unparse(tree)

    for widget_ish in ("setEnabled", "setText", "_submit_btn", "_consent",
                       "_submit_note", "QMessageBox"):
        assert widget_ish not in code, f"{widget_ish} is touched from the worker"


def test_the_note_is_actually_ON_SCREEN(qtbot):
    """It was created and never added to a layout, so the message explaining
    why the button is grey was invisible — and a greyed button with no reason
    is the dead end the note exists to prevent.

    `parent()` is the check that matters: a QLabel with no parent has been
    built and forgotten, however correct its text is.
    """
    d = _dlg(qtbot, handle="")
    assert d._submit_note.parent() is not None, "the note is not in any layout"
    d.show()
    qtbot.waitExposed(d)
    assert d._submit_note.isVisible(), "the note is in a layout but not visible"
    assert "settings" in d._submit_note.text().lower()


def test_the_note_is_visible_in_the_ORDINARY_case_too(qtbot):
    """With a handle set the note is empty, but it must still be a real widget
    in the layout — otherwise the failure message after a send goes nowhere."""
    d = _dlg(qtbot, handle="@andreas")
    d.show()
    qtbot.waitExposed(d)
    d._on_submit_finished(False, "Could not reach the gallery: timed out")
    assert d._submit_note.isVisible()
    assert "could not reach" in d._submit_note.text().lower()


def test_the_share_help_explains_the_wall():
    """A feature nobody can find is not shipped, and `in-app-help-drift`
    records that help goes stale every cycle with nothing testing it."""
    from nocturne.ui import help_content
    body = help_content.TOPICS["share"].body.lower()
    assert "wall" in body
    assert "review" in body or "looked at" in body, \
        "it must say the picture is not published immediately"
    assert "settings" in body, "the handle comes from Settings — say where"
    assert "location" in body, "the privacy promise belongs where the button is"


@pytest.mark.parametrize("chosen", [1080, 2048, 4096, None])
def test_the_submission_size_IGNORES_the_export_size(qtbot, chosen):
    """Andreas: "some images can be very large right?"

    At "Full size" (None) on a drizzled master the submission encoded to
    30.9 MB against a 15 MB endpoint limit — an upload that fails after the
    wait. And every pixel above 2000 is discarded when the wall builds its
    derivative, so the large ones were waste even when they fitted.
    """
    from nocturne.core.submit import SUBMIT_EDGE
    # A source LARGER than SUBMIT_EDGE in both axes, or the cap is never
    # reached and the assertion holds whatever the code does. The first
    # version used the 400x300 fixture and passed with the cap removed.
    d = ShareDialog(_rgb(3000, 5000), dict(META), Settings(handle="me"))
    qtbot.addWidget(d)
    d._size = chosen
    img = d._compose_for_submission()
    assert max(img.width(), img.height()) <= SUBMIT_EDGE, \
        f"chose {chosen}, submitted {img.width()}x{img.height()}"
    # And it must actually BE the cap, not something smaller by accident.
    assert max(img.width(), img.height()) == SUBMIT_EDGE


def test_the_EXPORT_still_honours_the_chosen_size(qtbot):
    """The negative half. Capping the submission must not cap the export —
    someone choosing Full size for a print still gets full size."""
    # A source BIGGER than SUBMIT_EDGE, or there is no difference to observe:
    # the first version of this test used the 400x300 fixture, where both
    # sides come back 400x300 and the assertion is vacuous.
    d = ShareDialog(_rgb(2000, 3000), dict(META), Settings(handle="me"))
    qtbot.addWidget(d)
    d._size = None
    exported = d._compose_current()
    submitted = d._compose_for_submission()
    assert max(exported.width(), exported.height()) > \
        max(submitted.width(), submitted.height()), \
        "the export was capped too"


def test_a_small_image_is_not_UPSCALED_to_the_submission_size(qtbot):
    """compose_share downscales only. A 300px source must stay 300px rather
    than being inflated to 2400 — pixels without detail, and a bigger upload."""
    d = _dlg(qtbot)              # the fixture's source is 400x300
    d._size = None
    img = d._compose_for_submission()
    assert max(img.width(), img.height()) <= 400


def test_the_TITLE_PLATE_supplies_the_object_when_the_file_has_no_headers(qtbot):
    """Andreas's M 31: "instead of reprocessing the drizzled enourmous file i
    simply opened my saved tiff, cropped it and shared". A TIFF carries no FITS
    headers, so it reached the wall with no target, no frames and no caption —
    and opening a TIFF is a first-class way to use Nocturne.

    The object name is already on screen for such a file, because anyone
    plating a TIFF types it in. The thing you edited is the thing that is sent.
    """
    d = ShareDialog(_rgb(), {"source_label": "m31.tif"}, Settings(handle="@me"))
    qtbot.addWidget(d)
    assert not d._submission_metadata().get("target"), "nothing to start from"

    d._designation_edit.setText("M 31")
    assert d._submission_metadata()["target"] == "M 31"


def test_the_headers_WIN_over_the_plate(qtbot):
    """The plate is a fallback, not an override: a user may retitle a plate
    for effect, and a FITS header is the capture's own record."""
    d = _dlg(qtbot)                      # META carries target "NGC 7000"
    d._designation_edit.setText("Something Else")
    assert d._submission_metadata()["target"] == "NGC 7000"


def test_an_empty_plate_does_not_invent_a_target(qtbot):
    """A blank designation must leave the field absent, not send an empty
    string that renders as a dangling separator on the wall."""
    d = ShareDialog(_rgb(), {"source_label": "m31.tif"}, Settings(handle="@me"))
    qtbot.addWidget(d)
    d._designation_edit.setText("   ")
    assert "target" not in d._submission_metadata()
