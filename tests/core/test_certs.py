"""CA certificates must travel with the app.

Python resolves its default CA path at BUILD time, so a bundle built here points
at /opt/homebrew/etc/openssl@3/cert.pem — absent on a Mac without Homebrew, i.e.
every user's. Measured 2026-08-31 after a 0.18.0 build ran all day against a
0.20.0 release and never offered the update.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from nocturne.core.certs import ca_path_is_usable, configure_ssl

ROOT = Path(__file__).parents[2]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)


def test_it_points_at_a_bundle_that_actually_exists():
    """The whole failure was a path that resolved but did not exist, which looks
    identical to a working one until something opens a socket."""
    path = configure_ssl()
    assert path, "no CA bundle configured"
    assert os.path.exists(path), f"configured a path that does not exist: {path}"
    assert os.environ["SSL_CERT_FILE"] == path


def test_an_explicit_choice_is_left_alone(monkeypatch):
    """Someone who set SSL_CERT_FILE — a corporate CA, a debugging proxy — means
    it. Silently overriding that would be worse than the bug being fixed."""
    monkeypatch.setenv("SSL_CERT_FILE", "/somewhere/of/their/own.pem")
    assert configure_ssl() == "/somewhere/of/their/own.pem"
    assert os.environ["SSL_CERT_FILE"] == "/somewhere/of/their/own.pem"


def test_a_missing_certifi_is_survivable(monkeypatch):
    """Never take the app down over this. Startup calls it before the window
    exists, so an exception here would be a launch failure, not a warning."""
    import builtins
    real = builtins.__import__

    def no_certifi(name, *a, **k):
        if name == "certifi":
            raise ImportError("no certifi")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_certifi)
    assert configure_ssl() is None


def test_ca_path_is_usable_sees_a_missing_bundle(monkeypatch):
    """The check the packaged app could not do for itself: from source the build
    machine's path exists, so a bundle that only works here looks healthy."""
    assert ca_path_is_usable()          # this machine has Homebrew's store
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/cert.pem")
    monkeypatch.setenv("SSL_CERT_DIR", "/nonexistent/certs")
    import importlib
    import ssl
    importlib.reload(ssl)               # verify paths are read at import
    try:
        assert not ca_path_is_usable()
    finally:
        monkeypatch.undo()
        importlib.reload(ssl)


def test_https_works_on_a_machine_without_the_build_machines_certs():
    """The regression test, in a subprocess because OpenSSL reads SSL_CERT_FILE
    when a context is created — setting it in-process after ssl has been used
    proves nothing.

    Deliberately offline-safe: it asserts the SSL layer stops refusing, not that
    GitHub answered, so it does not fail on a train.
    """
    env = dict(os.environ)
    env["SSL_CERT_FILE"] = "/nonexistent/cert.pem"      # the broken bake-in
    env["SSL_CERT_DIR"] = "/nonexistent/certs"
    script = textwrap.dedent('''
        import os, sys, urllib.request
        sys.path.insert(0, %r)
        del os.environ["SSL_CERT_FILE"]        # a build artefact, not a user choice
        del os.environ["SSL_CERT_DIR"]
        from nocturne.core.certs import configure_ssl
        configure_ssl()
        try:
            urllib.request.urlopen("https://api.github.com/", timeout=15).close()
            print("OK")
        except Exception as e:
            print(f"{type(e).__name__}: {e}")
    ''' % str(ROOT))
    r = subprocess.run([sys.executable, "-c", script], capture_output=True,
                       text=True, env=env, timeout=120)
    out = (r.stdout + r.stderr).strip()
    assert "CERTIFICATE_VERIFY_FAILED" not in out, out
    # And it must have got far enough to TRY. Asserting only the absence of the
    # SSL error would pass on an ImportError, a typo in the path, or any other
    # crash before the request — the test would then be green for the wrong
    # reason, which is how a guard rots without anyone noticing.
    assert out == "OK" or "URLError" in out, (
        f"never reached the request: {out}")


def test_certifi_is_a_real_dependency_not_an_accident():
    """It arrives transitively today via other packages. That is not a promise —
    a dependency dropping it would silently reintroduce the bug in the next
    build, and nothing would notice until a user's app went quiet."""
    deps = (ROOT / "pyproject.toml").read_text()
    assert "certifi" in deps.split("[project.optional-dependencies]")[0], (
        "certifi is not a declared runtime dependency")


def test_the_bundle_collects_certifi():
    """The dependency alone is not enough — PyInstaller has to be told to carry
    cacert.pem, or the .app ships libssl with nothing to verify against."""
    spec = (ROOT / "packaging" / "nocturne.spec").read_text()
    assert "certifi" in spec, "the spec does not collect certifi"


def test_startup_configures_ssl_before_anything_can_connect():
    """Order matters and cannot be asserted at runtime: OpenSSL reads the
    variable when a context is built, so a call placed after the first request
    fixes nothing while looking correct."""
    src = (ROOT / "nocturne" / "__main__.py").read_text()
    assert "configure_ssl()" in src, "startup never configures SSL"
    body = src.split("def main()")[1]
    assert body.index("configure_ssl()") < body.index("QApplication(sys.argv)"), (
        "configure_ssl() must run before the app starts doing anything")
