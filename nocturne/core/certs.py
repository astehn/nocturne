"""Point OpenSSL at a CA bundle that exists on the machine actually running us.

Python resolves its default CA path at BUILD time. On the machine Nocturne is
built on that is Homebrew's:

    cafile   /opt/homebrew/etc/openssl@3/cert.pem

which is baked into the bundle and does not exist on a Mac without Homebrew —
that is, on every user's Mac. The .app ships libssl and _ssl but no certificate
bundle of its own, so every HTTPS call fails with

    [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate

Measured 2026-08-31, after Andreas had a 0.18.0 build open all day against a
0.20.0 release with no notification. Two user-facing features were affected and
both hid it, because both catch broadly and fail quiet by design:

  * the update check (core/update_check.py) returns None on any error, so the
    toolbar item simply never appeared — on any Mac, ever;
  * SPCC's Gaia/VizieR lookup (tools/gaia.py), which is why "Couldn't reach
    Gaia" is worth re-testing now rather than assuming it is a timeout.

certifi ships the bundle Mozilla publishes, so the fix is to say where it is.
"""
from __future__ import annotations

import os


def configure_ssl() -> str | None:
    """Set SSL_CERT_FILE to a CA bundle, and return the path used (or None).

    Called once at startup, BEFORE anything opens a connection: OpenSSL reads
    this environment variable when a context is created, so setting it later
    leaves already-built contexts pointing at the missing path.

    An SSL_CERT_FILE already in the environment is left alone. Someone who set
    it — a corporate CA, a debugging proxy — means it, and silently overriding
    that would be worse than the bug this fixes.
    """
    existing = os.environ.get("SSL_CERT_FILE")
    if existing:
        return existing
    try:
        import certifi
    except ImportError:               # not installed: leave OpenSSL's default
        return None
    path = certifi.where()
    if not os.path.exists(path):      # bundled wrong, or trimmed by the packager
        return None
    os.environ["SSL_CERT_FILE"] = path
    return path


def ca_path_is_usable() -> bool:
    """Whether the CA path OpenSSL will actually use exists.

    The check the packaged app could not do for itself: a build that resolves to
    a path only present on the build machine looks perfectly healthy from source.
    """
    import ssl

    paths = ssl.get_default_verify_paths()
    for p in (paths.cafile, paths.capath):
        if p and os.path.exists(p):
            return True
    return False
