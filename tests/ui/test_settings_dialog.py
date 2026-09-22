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
