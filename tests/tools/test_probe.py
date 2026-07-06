from nocturne.tools.probe import probe_binary


def test_probe_success():
    ok, msg = probe_binary("/x", ["-v"], runner=lambda a: (0, "GraXpert 3.1.0\n", ""))
    assert ok and "GraXpert" in msg


def test_probe_uses_stderr_when_stdout_empty():
    ok, msg = probe_binary("/x", ["-v"], runner=lambda a: (0, "", "RC-Astro 0.9.3"))
    assert ok and "RC-Astro" in msg


def test_probe_failure():
    ok, msg = probe_binary("/x", ["-v"], runner=lambda a: (1, "", "boom"))
    assert not ok and "boom" in msg


def test_probe_missing_binary():
    ok, msg = probe_binary("/nope/definitely-not-here", ["-v"])
    assert ok is False and msg
