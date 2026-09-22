from nocturne.core.diagnostics import summary_block
from nocturne.settings import Settings


def _probes(_path, argv, **kw):
    return {"-v": "GraXpert version: 3.0.2", "--version": "starnet2  version: 2.5.2"}.get(
        argv[0] if argv else "", "")


def test_it_opens_with_what_the_ticket_is_about(tmp_path):
    exe = tmp_path / "t"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    text = summary_block("0.39.1", "macOS 15.6 (arm64)", "2560x1440 @2x",
                         Settings(graxpert_path=str(exe), starnet_path=str(exe)),
                         failure="Star separation failed: lzw_decode",
                         steps=["Crop", "Deconvolution (BlurX)"],
                         version_probe=_probes)
    assert "0.39.1" in text and "macOS 15.6 (arm64)" in text
    assert "GraXpert version: 3.0.2" in text
    assert "lzw_decode" in text
    assert "Deconvolution (BlurX)" in text


def test_an_unprobeable_tool_still_appears(tmp_path):
    """Which tools are INSTALLED is itself the diagnostic. Alvaro's whole
    ticket turned on his NOT having RC-Astro."""
    exe = tmp_path / "t"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    text = summary_block("0.39.1", "macOS", "x", Settings(astap_path=str(exe)),
                         version_probe=lambda *a, **k: "")
    assert "ASTAP" in text and "version unknown" in text


def test_a_tool_that_is_not_set_says_so(tmp_path):
    text = summary_block("0.39.1", "macOS", "x", Settings(),
                         version_probe=lambda *a, **k: "")
    assert "RC-Astro" in text and "not set" in text


def test_a_tool_that_is_set_but_gone_is_not_reported_as_present(tmp_path):
    """"Set" and "runnable" are different facts and a ticket turns on which one
    it is: a path that no longer resolves is the user's bug, not Nocturne's."""
    text = summary_block("0.39.1", "macOS", "x",
                         Settings(graxpert_path=str(tmp_path / "moved away")),
                         version_probe=lambda *a, **k: "")
    assert "GraXpert SET BUT NOT RUNNABLE" in text


def test_no_failure_and_no_steps_still_produces_a_block():
    text = summary_block("0.39.1", "macOS", "x", Settings(),
                         version_probe=lambda *a, **k: "")
    assert "0.39.1" in text
    assert "Failed at" not in text, "do not invent a failure that was not reported"


def test_it_imports_without_qt():
    """core/ is Qt-free, and this pulls in settings and tools.probe, so the
    import has to be blocked rather than merely absent from this file: PySide6
    is installed here and a plain import would succeed either way."""
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-c",
                        "import sys; sys.modules['PySide6']=None; "
                        "import nocturne.core.diagnostics"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
