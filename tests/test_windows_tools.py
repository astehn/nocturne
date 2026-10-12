"""Finding the tools on Windows (2026-10-12)."""
import os
import sys

import pytest

from nocturne import settings as st

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows paths and PATHEXT")


@windows_only
def test_a_document_is_not_a_tool_on_windows(tmp_path):
    # Windows calls every existing file executable; the extension decides.
    doc = tmp_path / "GraXpert.md"; doc.write_text("not a program")
    exe = tmp_path / "GraXpert.exe"; exe.write_bytes(b"MZ")
    assert not st.is_tool(str(doc))
    assert st.is_tool(str(exe))


@windows_only
def test_a_per_user_install_is_found_through_localappdata(tmp_path, monkeypatch):
    exe = tmp_path / "Programs" / "GraXpert" / "GraXpert.exe"
    exe.parent.mkdir(parents=True); exe.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    found = st.detect_tool_paths(st.Settings(), candidates={
        "graxpert_path": [r"%LOCALAPPDATA%\Programs\GraXpert\GraXpert.exe"]})
    assert found == {"graxpert_path": str(exe)}


def test_an_unset_windows_variable_matches_nothing(monkeypatch):
    monkeypatch.delenv("NOCTURNE_NO_SUCH_DIR", raising=False)
    found = st.detect_tool_paths(st.Settings(), candidates={
        "graxpert_path": [r"%NOCTURNE_NO_SUCH_DIR%\GraXpert.exe"]})
    assert found == {}


def test_windows_gets_its_own_list():
    assert set(st._WINDOWS_CANDIDATES) == set(st._MAC_CANDIDATES) == set(st._LINUX_CANDIDATES)
    expected = (st._MAC_CANDIDATES if sys.platform == "darwin"
                else st._WINDOWS_CANDIDATES if sys.platform == "win32" else st._LINUX_CANDIDATES)
    assert st.TOOL_CANDIDATES is expected
