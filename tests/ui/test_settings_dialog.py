from PySide6.QtWidgets import QPushButton
import pytest

pytest.importorskip("PySide6")
from nocturne.settings import Settings  # noqa: E402
from nocturne.ui.settings_dialog import SettingsDialog  # noqa: E402


def test_graxpert_test_button_shows_version(qtbot):
    dlg = SettingsDialog(Settings(graxpert_path="/x/graxpert"))
    qtbot.addWidget(dlg)
    dlg._probe_runner = lambda argv: (0, "GraXpert 3.1.0", "")
    dlg._test_graxpert()
    assert "✓" in dlg._gx_result.text()
    assert "GraXpert" in dlg._gx_result.text()


def test_rcastro_test_button_shows_failure(qtbot):
    dlg = SettingsDialog(Settings(rcastro_path="/x/rc-astro"))
    qtbot.addWidget(dlg)
    dlg._probe_runner = lambda argv: (1, "", "license expired")
    dlg._test_rcastro()
    assert "✗" in dlg._rc_result.text()
    assert "license expired" in dlg._rc_result.text()


def test_empty_path_reports_not_set(qtbot):
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._test_graxpert()
    assert "✗" in dlg._gx_result.text()


def test_result_settings_roundtrip(qtbot):
    dlg = SettingsDialog(Settings(graxpert_path="/a", rcastro_path="/b"))
    qtbot.addWidget(dlg)
    s = dlg.result_settings()
    assert s.graxpert_path == "/a" and s.rcastro_path == "/b"


def test_settings_dialog_round_trips_base_dir(qtbot, tmp_path):
    d = SettingsDialog(Settings(base_dir=str(tmp_path)))
    qtbot.addWidget(d)
    assert d._dir.text() == str(tmp_path)          # prefilled from settings
    d._dir.setText("/tmp/newbase")
    assert d.result_settings().base_dir == "/tmp/newbase"


def test_dialog_round_trips_denoise_engine(qtbot):
    d = SettingsDialog(Settings(denoise_engine="graxpert"))
    qtbot.addWidget(d)
    assert d.denoise_box.currentText() == "GraXpert"
    assert d.result_settings().denoise_engine == "graxpert"


def test_settings_dialog_round_trips_astap_path(qtbot):
    from nocturne.ui.settings_dialog import SettingsDialog
    from nocturne.settings import Settings
    dlg = SettingsDialog(Settings(astap_path="/opt/astap/astap"))
    qtbot.addWidget(dlg)
    assert dlg.result_settings().astap_path == "/opt/astap/astap"


def test_settings_dialog_has_tool_download_links(qtbot):
    from nocturne.ui.settings_dialog import SettingsDialog, DOWNLOAD_URLS
    from nocturne.settings import Settings
    # StarNet2 joined on 2026-09-18 — a free star/starless split, which nine
    # features depend on and which was RC-Astro-only before.
    assert set(DOWNLOAD_URLS) == {"graxpert", "rcastro", "astap", "starnet"}
    assert all(u.startswith("https://") for u in DOWNLOAD_URLS.values())
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    labels = [w.text() for w in dlg.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)]
    assert any("astap.htm" in t for t in labels)          # ASTAP download link rendered


def test_browse_buttons_are_wired_and_do_not_raise(qtbot, monkeypatch):
    """Every Browse button in Settings was DEAD from 2026-08-15 (fd3a26b) to
    2026-08-20, shipped in v0.12.0 through v0.16.0.

    That commit gave `open_file`/`choose_folder` a required `caption`, updated
    every call site in the app, and missed the two here — which are lambdas, so
    nothing failed until a user clicked. The only way left to configure
    GraXpert, RC-Astro or ASTAP was to type an absolute path by hand, and on
    macOS that means finding the executable inside a .app bundle. It reached us
    as a real user's "setup is messy", which is the only reason we found it.

    Asserts the call SUCCEEDS with a caption, not merely that it is called:
    the defect was a TypeError raised inside a slot, where Qt prints to stderr
    and the button silently appears to do nothing.
    """
    from nocturne.ui import file_dialogs, settings_dialog
    from nocturne.settings import Settings

    seen = []
    monkeypatch.setattr(file_dialogs, "open_file",
                        lambda parent, caption, *a, **k: seen.append(("file", caption)) or "")
    monkeypatch.setattr(file_dialogs, "choose_folder",
                        lambda parent, caption, *a, **k: seen.append(("dir", caption)) or "")

    dlg = settings_dialog.SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    buttons = [b for b in dlg.findChildren(QPushButton) if b.text() == "Browse…"]
    assert len(buttons) >= 4, f"expected 3 tool paths + base folder, found {len(buttons)}"
    for b in buttons:
        b.click()                      # raised TypeError before the fix
    assert len(seen) == len(buttons)
    assert all(caption for _kind, caption in seen), "a Browse button passed an empty caption"


def test_rescan_button_fills_the_fields(qtbot, monkeypatch, tmp_path):
    """Andreas: "if the user messes autodetection up by fumbling around in the
    settings can we have a re-scan button, i think that would give some
    confidence to users".

    Drives the real button and reads the real line edits back, rather than
    calling the handler directly — a connected-but-broken handler is exactly
    what shipped in five releases (b4314fa).
    """
    from nocturne.settings import Settings
    from nocturne.ui import settings_dialog

    gx = tmp_path / "GraXpert.app" / "Contents" / "MacOS"
    gx.mkdir(parents=True)
    (gx / "GraXpert").write_text("#!/bin/sh\n")
    (gx / "GraXpert").chmod(0o755)   # a real tool is EXECUTABLE, not merely present
    monkeypatch.setattr(settings_dialog, "TOOL_CANDIDATES",
                        {"graxpert_path": [str(tmp_path / "GraXpert.app")],
                         "rcastro_path": [str(tmp_path / "absent")],
                         "astap_path": [str(tmp_path / "absent")]})

    dlg = settings_dialog.SettingsDialog(Settings(graxpert_path="/fumbled/by/hand"))
    qtbot.addWidget(dlg)
    dlg.rescan_btn.click()
    assert dlg._gx.text().endswith("GraXpert.app")      # the broken path was replaced
    assert "GraXpert" in dlg.rescan_result.text()


def test_ok_does_not_discard_settings_this_dialog_never_shows(qtbot):
    """Opening Settings and pressing OK used to reset every field not on the
    form — measured 2026-09-17: plate preset, saved plate looks, recent
    projects, help_expanded, annotation_density and share_band_opacity, all
    gone, from a dialog the user may have opened only to read a path.

    Written as assert-UNCHANGED over the whole dataclass rather than a list of
    fields: a check against known-bad values would pass while a NEW setting,
    added later and equally invisible here, was quietly reset. That is the
    weakness CLAUDE.md records getting through twice on one branch.
    """
    import dataclasses
    from nocturne.settings import Settings
    from nocturne.ui.settings_dialog import SettingsDialog

    before = Settings(
        graxpert_path="/gx", rcastro_path="/rc", astap_path="/astap",
        base_dir="/base", denoise_engine="graxpert", handle="@andreas",
        help_expanded=False, recent_projects=["/a.nocturne", "/b.nocturne"],
        last_project_dir="/projects", annotation_density="sparse",
        share_caption_size=0.031, share_band_opacity=0.42,
        plate_preset="Editorial", plate_style={"scrim": 0.3},
        plate_user_presets=[{"name": "mine"}],
    )
    snapshot = dataclasses.asdict(before)

    dlg = SettingsDialog(before)
    qtbot.addWidget(dlg)
    after = dataclasses.asdict(dlg.result_settings())

    # Everything the form actually shows. A field added to the dialog belongs
    # here; a field added to Settings and NOT to the dialog must keep surviving,
    # which is the whole point of the test.
    on_this_form = {"graxpert_path", "rcastro_path", "astap_path", "base_dir",
                    "denoise_engine", "handle", "check_updates", "telemetry"}
    for field, was in snapshot.items():
        if field in on_this_form:
            continue
        assert after[field] == was, f"{field} was reset by a dialog that never shows it"


def test_the_form_still_saves_what_it_does_show(qtbot):
    """The other half: `replace` must not have turned the dialog read-only."""
    from nocturne.settings import Settings
    from nocturne.ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(Settings(handle="@old", base_dir="/old"))
    qtbot.addWidget(dlg)
    dlg._handle.setText("@new")
    dlg._dir.setText("/new")
    out = dlg.result_settings()
    assert out.handle == "@new" and out.base_dir == "/new"


def test_the_update_check_can_be_turned_off_and_the_choice_survives(qtbot):
    """Until 2026-09-17 Nocturne asked GitHub for the latest release on every
    launch, with no disclosure and no way to decline — so every start sent the
    user's IP to github.com tagged as a Nocturne user."""
    from nocturne.settings import Settings
    from nocturne.ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    assert dlg.check_updates.isChecked(), "default stays on — a beta must be able to say a fix exists"
    dlg.check_updates.setChecked(False)
    assert dlg.result_settings().check_updates is False

    back = SettingsDialog(Settings(check_updates=False))
    qtbot.addWidget(back)
    assert not back.check_updates.isChecked(), "the dialog must show the saved answer"


def test_usage_counting_can_be_changed_after_the_first_run_question(qtbot):
    """The consent dialog says "you can change this any time in Settings", so
    this control is part of the promise rather than a convenience."""
    from nocturne.settings import Settings
    from nocturne.ui.settings_dialog import SettingsDialog

    on = SettingsDialog(Settings(telemetry="on"))
    qtbot.addWidget(on)
    assert on.telemetry.isChecked()
    on.telemetry.setChecked(False)
    assert on.result_settings().telemetry == "off"

    off = SettingsDialog(Settings(telemetry="off"))
    qtbot.addWidget(off)
    assert not off.telemetry.isChecked()
    off.telemetry.setChecked(True)
    assert off.result_settings().telemetry == "on"


def test_an_unanswered_question_shows_as_off_and_saves_as_a_real_answer(qtbot):
    """`unset` must never look like consent. Shown unticked; touching OK at all
    is the user answering, so it stores "off" rather than leaving it unset and
    re-asking on the next launch."""
    from nocturne.settings import Settings
    from nocturne.ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(Settings(telemetry="unset"))
    qtbot.addWidget(dlg)
    assert not dlg.telemetry.isChecked()
    assert dlg.result_settings().telemetry == "off"


# --- every tool with a path field needs a status on OPEN (2026-09-22) -------
#
# StarNet2 arrived 2026-09-18 and was never added to _refresh_status's tuple, so
# its row was BLANK while GraXpert and ASTAP said "✓ … found". Andreas hit
# exactly that and doubted StarNet2 was configured at all — then proved from the
# history log that it had been running the whole time.

def test_a_configured_starnet2_says_so_without_pressing_test(qtbot, tmp_path):
    exe = tmp_path / "starnet2"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    dlg = SettingsDialog(Settings(starnet_path=str(exe)))
    qtbot.addWidget(dlg)
    assert "✓" in dlg._starnet_result.text()
    assert "StarNet2" in dlg._starnet_result.text()


def test_an_unset_starnet2_says_optional_rather_than_nothing(qtbot):
    dlg = SettingsDialog(Settings(starnet_path=""))
    qtbot.addWidget(dlg)
    assert "optional" in dlg._starnet_result.text()


def test_every_tool_path_field_has_a_status_on_open(qtbot, tmp_path):
    """The structural guard. A sixth tool added to the dialog without a status
    row repeats this silently — the field looks configured and says nothing."""
    exe = tmp_path / "t"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    dlg = SettingsDialog(Settings(graxpert_path=str(exe), rcastro_path=str(exe),
                                  starnet_path=str(exe), astap_path=str(exe)))
    qtbot.addWidget(dlg)
    blank = [name for name, label in
             (("GraXpert", dlg._gx_result), ("RC-Astro", dlg._rc_result),
              ("StarNet2", dlg._starnet_result), ("ASTAP", dlg._astap_result))
             if not label.text().strip()]
    assert not blank, f"configured but silent on open: {blank}"


def test_typing_a_starnet2_path_updates_its_status_as_you_type(qtbot, tmp_path):
    """The SAME omission again, four lines below the one the commit fixed: the
    textChanged tuple also left StarNet2 out. So the row was right on open and
    then frozen — set the path, get no confirmation, which is the exact state
    the fix was supposed to end. Found by an adversarial review, not by me."""
    exe = tmp_path / "starnet2"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    assert "optional" in dlg._starnet_result.text()
    dlg._starnet.setText(str(exe))
    assert "✓" in dlg._starnet_result.text(), "typing a valid path said nothing"
    dlg._starnet.setText("/gone/missing")
    assert "✗" in dlg._starnet_result.text(), "a path that stopped working still said found"


def test_every_tool_field_is_wired_to_the_status_refresh(qtbot):
    """Structural, unlike the open-time test beside it: it reads the dialog's
    OWN list of path fields rather than repeating it, so a fifth tool that is
    never connected fails here without anyone remembering to add a case."""
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    fields = {"GraXpert": (dlg._gx, dlg._gx_result),
              "RC-Astro": (dlg._rc, dlg._rc_result),
              "StarNet2": (dlg._starnet, dlg._starnet_result),
              "ASTAP": (dlg._astap, dlg._astap_result)}
    unwired = []
    for name, (edit, label) in fields.items():
        before = label.text()
        edit.setText("/definitely/not/a/program")
        if label.text() == before:
            unwired.append(name)
    assert not unwired, f"path fields that never refresh their status: {unwired}"


# --- one table, or a fifth omission (2026-09-22) ---------------------------
#
# StarNet2 was added to the dialog on 2026-09-18 and left out of FOUR separate
# collections: _refresh_status's tuple, the textChanged tuple, _rescan's
# `fields` and _rescan's `names`. Each was found separately, by Andreas, using
# the app. The fix is not a fourth patch.

def test_rescan_handles_every_tool_the_detector_can_find(qtbot, tmp_path, monkeypatch):
    """Pressing Rescan raised `KeyError: 'starnet_path'` — the detector returns
    a field the dialog's own map did not contain, so the button crashed for
    anyone with StarNet2 installed in a usual place."""
    from nocturne.settings import TOOL_CANDIDATES
    from nocturne.ui import settings_dialog as sd

    exe = tmp_path / "found"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    # Every field the detector knows about, all found at once — the case the
    # dialog has to survive.
    monkeypatch.setattr(sd, "detect_tool_paths",
                        lambda *a, **k: {key: str(exe) for key in TOOL_CANDIDATES})
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._rescan()                       # must not raise
    assert "✓" in dlg.rescan_result.text()


def test_the_dialog_knows_every_tool_the_detector_knows(qtbot):
    """The invariant behind all four omissions, asserted once.

    `detect_tool_paths` returns keys from TOOL_CANDIDATES; the dialog must have
    a line edit for each. A fifth tool added to the detector and not the dialog
    fails here instead of raising KeyError under the user's cursor.
    """
    from nocturne.settings import TOOL_CANDIDATES
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    missing = sorted(set(TOOL_CANDIDATES) - set(dlg.tool_fields()))
    assert not missing, f"the detector can find these and the dialog cannot show them: {missing}"


def test_one_table_drives_the_dialog(qtbot):
    """Status on open, live refresh, rescan and the rescan summary all read the
    SAME table. Four hand-written collections is how one tool went missing from
    four of them."""
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    for key, (edit, label, name) in dlg.tool_fields().items():
        assert edit is not None and label is not None and name, key
    assert {"graxpert_path", "rcastro_path", "starnet_path", "astap_path"} \
        <= set(dlg.tool_fields())


# --- Tabs (screen-size piece 3, Andreas 2026-09-26: "go for your suggestion
# straight up"): General / External tools / Privacy, one fixed size.

_TABS = {
    "General": ("_dir", "_handle"),
    "External tools": ("_gx", "_rc", "_starnet", "_astap", "rescan_btn", "denoise_box"),
    "Privacy": ("check_updates", "telemetry"),
}


def test_every_setting_lives_on_its_tab(qtbot):
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    tabs = dlg.tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == list(_TABS)
    for i, (name, attrs) in enumerate(_TABS.items()):
        page = tabs.widget(i)
        for attr in attrs:
            assert page.isAncestorOf(getattr(dlg, attr)), f"{attr} is not on {name}"


def test_switching_tabs_never_resizes_the_window(qtbot):
    """Nothing moves (piece 1's rule): the window is sized for the tallest tab."""
    from nocturne.ui.theme import build_stylesheet
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    app.setStyleSheet(build_stylesheet())
    try:
        dlg = SettingsDialog(Settings())
        qtbot.addWidget(dlg)
        dlg.show(); qtbot.waitExposed(dlg)
        sizes = set()
        for i in range(dlg.tabs.count()):
            dlg.tabs.setCurrentIndex(i); qtbot.wait(20)
            sizes.add((dlg.width(), dlg.height()))
        assert len(sizes) == 1, sizes
    finally:
        app.setStyleSheet("")


def test_privacy_says_what_is_sent_on_the_page(qtbot):
    """The page you open to check exactly this: the explanation is visible
    text, not only a hover tooltip."""
    from PySide6.QtWidgets import QLabel
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    page = dlg.tabs.widget(list(_TABS).index("Privacy"))
    text = " ".join(l.text() for l in page.findChildren(QLabel))
    assert "github.com" in text.lower()
    assert "random number" in text.lower() and "no ip address" in text.lower()


def test_one_ok_covers_every_tab(qtbot):
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._handle.setText("@me")
    dlg.telemetry.setChecked(True)
    dlg._gx.setText("/g")
    s = dlg.result_settings()
    assert (s.handle, s.telemetry, s.graxpert_path) == ("@me", "on", "/g")
    from PySide6.QtWidgets import QDialogButtonBox
    boxes = dlg.findChildren(QDialogButtonBox)
    assert len(boxes) == 1 and not dlg.tabs.isAncestorOf(boxes[0])


def test_a_real_install_path_is_readable_whole(qtbot):
    """In tabs the dialog sized to its content and GraXpert's box showed
    'ert.app'. Every tool path box shows the longest default path whole."""
    from nocturne.ui.settings_dialog import _TYPICAL_PATH
    from nocturne.ui.theme import build_stylesheet
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    app.setStyleSheet(build_stylesheet())
    try:
        dlg = SettingsDialog(Settings())
        qtbot.addWidget(dlg)
        dlg.tabs.setCurrentIndex(1)
        dlg.show(); qtbot.waitExposed(dlg)
        for edit, _l, name in dlg.tool_fields().values():
            need = edit.fontMetrics().horizontalAdvance(_TYPICAL_PATH)
            assert edit.width() > need, f"{name}: {edit.width()} px for a {need} px path"
    finally:
        app.setStyleSheet("")


def test_download_links_use_the_accent_not_qt_blue(qtbot):
    from PySide6.QtWidgets import QLabel
    from nocturne.ui.theme import ACCENT
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    links = [l for l in dlg.findChildren(QLabel) if "Download" in l.text()]
    assert len(links) == 4 and all(ACCENT in l.text() for l in links)


def test_the_sizing_path_is_the_longest_place_nocturne_looks():
    """A hand-picked literal missed ~/Applications/RC-Astro/CLI/rc-astro, and
    the path-width test above measures against the constant — so the constant
    itself must cover every default location."""
    import os
    from nocturne.settings import TOOL_CANDIDATES
    from nocturne.ui.settings_dialog import _TYPICAL_PATH
    for paths in TOOL_CANDIDATES.values():
        for p in paths:
            if not p.startswith("which:"):
                assert len(_TYPICAL_PATH) >= len(os.path.expanduser(p)), p


# --- Version on General (Andreas, 2026-09-26 13:53): what is running, and
# what the update check found. The suite never goes online: results are fed in.

def _version_text(dlg) -> str:
    return dlg.version_status.text()


def test_general_shows_the_running_version(qtbot):
    from nocturne import app_title
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    page = dlg.tabs.widget(0)
    assert page.isAncestorOf(dlg.version_label) and page.isAncestorOf(dlg.check_now_btn)
    assert app_title() in dlg.version_label.text()


@pytest.mark.parametrize("result,expect", [
    (("v99.0.0", "startup"), "99.0.0 is available"),
    (("v0.0.1", "startup"), "latest version"),
    (("failed", "startup"), "couldn't reach github"),
    (("off", None), "update check is off"),
    (("pending", None), "checking"),
])
def test_each_update_state_reads_plainly(qtbot, result, expect):
    dlg = SettingsDialog(Settings(), update_result=result)
    qtbot.addWidget(dlg)
    assert expect in _version_text(dlg).lower(), _version_text(dlg)


def test_a_newer_release_links_to_the_download_page(qtbot):
    from nocturne.core.update_check import DOWNLOAD_URL
    dlg = SettingsDialog(Settings(), update_result=("v99.0.0", "startup"))
    qtbot.addWidget(dlg)
    assert DOWNLOAD_URL in _version_text(dlg) and dlg.version_status.openExternalLinks()


def test_check_now_asks_and_shows_the_answer(qtbot):
    asked = []
    dlg = SettingsDialog(Settings(check_updates=False), update_result=("off", None),
                         on_check_now=lambda done: asked.append(done))
    qtbot.addWidget(dlg)
    dlg.check_now_btn.click()
    assert len(asked) == 1
    assert "checking" in _version_text(dlg).lower() and not dlg.check_now_btn.isEnabled()
    asked[0](("v0.0.1", "now"))
    assert "latest version" in _version_text(dlg).lower() and dlg.check_now_btn.isEnabled()


def test_check_now_landing_after_the_dialog_closed_is_harmless(qtbot):
    import shiboken6
    asked = []
    dlg = SettingsDialog(Settings(), on_check_now=lambda done: asked.append(done))
    dlg.check_now_btn.click()
    shiboken6.delete(dlg)
    asked[0](("v0.0.1", "now"))          # must not raise
