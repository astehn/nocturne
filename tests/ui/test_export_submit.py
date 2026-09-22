"""Sending a finished picture to the wall, from the Export step.

Spec §2.4 and §3.0. It lives here rather than in the Share dialog because Share
reframes for a destination and strips the plate — so what was sent differed
from what was shown, in the one dialog built around them being identical.

The panel RECEIVES the facts and a callback; it cannot reach the image. That is
this file's existing shape (see on_export) and it is what makes these tests
possible without a main window.
"""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QLabel  # noqa: E402
from nocturne.ui.pipeline import path_stages  # noqa: E402
from nocturne.ui.step_panels import build_panel  # noqa: E402


FACTS = {"handle": "@andreasstehn", "target": "NGC 7000", "frames": "163",
         "sub_s": "20.00", "integration_s": "3260",
         "instrument": "ZWO Seestar S30 Pro", "captured_on": "2026-08-09"}


def _stage():
    return next(s for s in path_stages() if s.id == "export")


def _panel(qtbot, fields=None, handle="@andreasstehn", sent=None):
    w = build_panel(_stage(),
                    wall_fields=dict(FACTS if fields is None else fields),
                    wall_handle=handle,
                    on_wall_submit=(sent.append if sent is not None else None))
    qtbot.addWidget(w)
    return w


def _labels(w):
    return " ".join(l.text() for l in w.findChildren(QLabel))


def test_the_export_panel_offers_the_wall(qtbot):
    w = _panel(qtbot)
    assert w.wall_consent is not None and w.wall_btn is not None


def test_the_button_is_off_until_consent_is_ticked(qtbot):
    w = _panel(qtbot)
    assert w.wall_btn.isEnabled() is False
    w.wall_consent.setChecked(True)
    assert w.wall_btn.isEnabled() is True
    w.wall_consent.setChecked(False)
    assert w.wall_btn.isEnabled() is False


def test_no_handle_blocks_it_and_names_SETTINGS(qtbot):
    """The handle is the only attribution there is, and it lives in Settings —
    so refusing without saying where is a dead end."""
    w = _panel(qtbot, handle="")
    w.wall_consent.setChecked(True)
    assert w.wall_btn.isEnabled() is False
    assert "settings" in w.wall_note.text().lower()


def test_the_note_is_ON_SCREEN_not_merely_correct(qtbot):
    """The Share version was built and never added to a layout, so the message
    explaining the disabled button rendered nowhere and Andreas met a grey
    button with no reason given."""
    w = _panel(qtbot, handle="")
    assert w.wall_note.parent() is not None


def test_it_SHOWS_the_facts_it_will_send(qtbot):
    """§3.0: someone publishing to a public wall should be able to read what it
    will say about them before pressing the button. The summary is built from
    the same dict that is posted, so the panel cannot claim one thing and send
    another — which is the failure this whole move exists to fix."""
    text = _labels(_panel(qtbot))
    assert "NGC 7000" in text
    assert "163" in text and "20" in text
    assert "Seestar S30 Pro" in text
    assert "@andreasstehn" in text


def test_the_object_is_EDITABLE_when_the_file_has_none(qtbot):
    """A TIFF carries no FITS headers, and finishing one is a first-class use.
    Andreas's M 31 reached the wall as a byline and nothing else."""
    w = _panel(qtbot, fields={"handle": "@a"})
    assert w.wall_target is not None
    assert w.wall_target.isEnabled()


def test_the_object_field_is_ABSENT_when_the_file_supplied_one(qtbot):
    """One field, and only when there is nothing to show. A form at the end of
    the pipeline is a reason not to finish."""
    w = _panel(qtbot)
    assert w.wall_target is None, "a target came from the file; do not ask again"


def test_the_typed_object_reaches_the_callback(qtbot):
    sent = []
    w = _panel(qtbot, fields={"handle": "@a"}, sent=sent)
    w.wall_target.setText("M 31")
    w.wall_consent.setChecked(True)
    w.wall_btn.click()
    assert sent and sent[0] == "M 31"


def test_a_blank_typed_object_is_not_sent_as_empty(qtbot):
    """An empty string renders as a dangling separator on the wall; absent does
    not, and the renderer already handles absent."""
    sent = []
    w = _panel(qtbot, fields={"handle": "@a"}, sent=sent)
    w.wall_target.setText("   ")
    w.wall_consent.setChecked(True)
    w.wall_btn.click()
    assert sent and sent[0] == ""


def test_a_success_spends_the_button(qtbot):
    """Once a picture has gone it must not go again — a second copy is work for
    Andreas and confusion for the sender."""
    w = _panel(qtbot)
    w.wall_consent.setChecked(True)
    w.wall_finished(True, "Sent. It will appear once it has been looked at.")
    assert w.wall_btn.isEnabled() is False
    assert w.wall_consent.isEnabled() is False
    assert "looked at" in w.wall_note.text()


def test_a_FAILED_send_RE_ENABLES_the_button(qtbot):
    """The case that matters more: a network blip must not cost someone their
    submission. Disabled FIRST, as an in-flight send leaves it."""
    w = _panel(qtbot)
    w.wall_consent.setChecked(True)
    w.wall_btn.setEnabled(False)
    w.wall_finished(False, "Could not reach the gallery: timed out")
    assert w.wall_btn.isEnabled() is True
    assert "could not reach" in w.wall_note.text().lower()


def test_the_button_goes_dead_while_in_flight(qtbot):
    """Two presses would queue the same picture twice."""
    w = _panel(qtbot, sent=[])
    w.wall_consent.setChecked(True)
    w.wall_btn.click()
    assert w.wall_btn.isEnabled() is False


def test_the_panel_never_reaches_for_the_IMAGE(qtbot):
    """It receives facts and a callback. A panel that composed its own image
    would be a second compose path — the exact fault being moved away from."""
    import inspect
    from nocturne.ui import step_panels
    src = inspect.getsource(step_panels.build_panel)
    export = src.split('stage.kind == "export"', 1)[1].split("else:  #", 1)[0]
    # NOT a bare "submit(" — that matches the on_wall_submit CALLBACK, which is
    # precisely the right thing for the panel to do. What must be absent is the
    # panel doing the work: composing, posting, or threading.
    for reach in ("compose_share", "core.submit", "QThreadPool",
                  "QRunnable", "imagescale", "urlopen"):
        assert reach not in export, f"the panel is doing {reach} itself"
    assert "on_wall_submit(" in export, "it must hand the work upward"


# --- the wiring, against a real window --------------------------------------
#
# The tests above build the panel with a fake dict, so they never exercise where
# the dict comes from. That gap let `self.metadata` — an attribute MainWindow
# does not have — reach the full suite, where it surfaced as two unrelated
# step-commit tests failing rather than as anything naming the cause.

def _win(qtbot, tmp_path):
    import numpy as np
    from nocturne.core.image import AstroImage
    from tests.ui.test_main_window import _window
    win = _window(qtbot, tmp_path)
    win.open_image(AstroImage(np.full((32, 32, 3), 0.25, np.float32),
                              is_linear=False,
                              metadata={"target": "NGC 7000", "frames": 163,
                                        "livetime": 3260.0, "exposure": 20.0,
                                        "creator": "ZWO Seestar S30 Pro"}),
                   "test")
    return win


def test_the_window_can_build_the_facts_for_a_real_image(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    stage = next(s for s in path_stages() if s.id == "export")
    fields = win._wall_fields(stage)
    assert fields is not None
    assert fields["target"] == "NGC 7000"
    assert fields["frames"] == "163"
    assert fields["instrument"] == "ZWO Seestar S30 Pro"


def test_the_offer_appears_ONLY_on_the_export_stage(qtbot, tmp_path):
    """The block shows only when it is given fields, so the offer cannot turn
    up halfway through the pipeline where there is nothing finished to send."""
    win = _win(qtbot, tmp_path)
    for stage in path_stages():
        fields = win._wall_fields(stage)
        if stage.kind == "export":
            assert fields is not None, "export must offer it"
        else:
            assert fields is None, f"{stage.id} must not"


def test_no_project_means_no_offer(qtbot, tmp_path):
    from tests.ui.test_main_window import _window
    win = _window(qtbot, tmp_path)          # nothing opened
    stage = next(s for s in path_stages() if s.id == "export")
    assert win._wall_fields(stage) is None


def test_the_help_points_at_EXPORT_not_share():
    """`in-app-help-drift`: help goes stale every cycle and nothing tests it.
    A topic describing a button that moved is worse than one that is silent."""
    from nocturne.ui import help_content
    export = help_content.TOPICS["export"].body.lower()
    assert "gallery" in export
    assert "looked at" in export or "review" in export
    assert "settings" in export, "the handle comes from Settings — say where"
    assert "location is never" in export, "the privacy promise travels with it"
    share = help_content.TOPICS["share"].body.lower()
    assert "send to the wall" not in share and "send to the gallery" not in share


def test_the_submit_goes_through_run_async_not_a_hand_rolled_runnable():
    """It segfaulted on the first real press.

    A hand-rolled QRunnable auto-deletes itself in C++ the moment run()
    returns, so the queued signal reached the main thread pointing at a
    destroyed QObject — PySide::getWrapperForQObject on freed memory.
    worker.py exists for exactly this and its own comment says so; every other
    background call in this window already uses it.
    """
    import inspect
    from nocturne.ui import main_window
    src = inspect.getsource(main_window.MainWindow._submit_to_wall)
    assert "run_async(" in src, "use the house pattern"
    # Comments stripped before looking: this method's own comment explains the
    # crash and names QRunnable several times, and a test that reads the prose
    # rather than the code is a trap this session has already fallen into twice.
    code = "\n".join(l.split("#", 1)[0] for l in src.split("\n"))
    assert "QRunnable" not in code, "a hand-rolled runnable is back"
    assert "class _Job" not in code and "Signal(" not in code


def test_the_send_actually_completes_end_to_end(qtbot, tmp_path, monkeypatch):
    """The one that would have caught the crash.

    Everything before this stubbed the POST or tested the panel alone, so
    nothing ever ran the thread hop that failed. This drives the real path with
    the network replaced, and waits for the answer to arrive on the main
    thread — which is where the segfault happened.
    """
    win = _win(qtbot, tmp_path)
    monkeypatch.setattr("nocturne.core.submit.submit",
                        lambda *a, **k: (True, "Sent. It will appear once looked at."))
    # Navigate to Export for real — the first version of this test skipped when
    # the panel was not the export one, which meant it never ran the path that
    # crashed. A test that skips is not a test.
    idx = next(i for i, s in enumerate(win._stages) if s.id == "export")
    win._go_to(idx)
    panel = win._panel
    assert hasattr(panel, "wall_finished"), "the export panel should be current"
    win._submit_to_wall("")
    qtbot.waitUntil(lambda: "looked at" in panel.wall_note.text(), timeout=4000)
    assert panel.wall_btn.isEnabled() is False, "a success must spend the button"


def test_the_USER_FACING_words_say_gallery_and_name_the_site(qtbot):
    """Andreas, seeing it for the first time: "What wall? What gallery?" — and
    "we should stick with one nomenclature, today we refer to it as the gallery
    sometimes and the wall other times."

    The page is called Gallery: that is its nav label, its <h1> and every link
    on the site. "The wall" was internal vocabulary out of the spec that leaked
    into the interface. Internal names (wall_fields, wall.php, the submissions
    table) keep it; nothing a user reads does.

    It must also say WHERE. A button offering to publish somewhere unnamed is
    asking for consent to something the user cannot picture.
    """
    from PySide6.QtWidgets import QCheckBox, QPushButton
    w = _panel(qtbot)
    words = " ".join(
        [l.text() for l in w.findChildren(QLabel)]
        + [b.text() for b in w.findChildren(QPushButton)]
        + [c.text() for c in w.findChildren(QCheckBox)])
    assert "wall" not in words.lower(), f"'wall' reached the interface: {words}"
    assert "gallery" in words.lower()
    assert "nocturneastro.com" in words, "say where it is being published"


def test_the_help_says_gallery_and_where():
    from nocturne.ui import help_content
    body = help_content.TOPICS["export"].body
    assert "wall" not in body.lower()
    assert "gallery" in body.lower()
    assert "nocturneastro.com" in body, "a new user does not know where it goes"
