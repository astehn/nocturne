from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
HTML = (SITE / "index.html").read_text(encoding="utf-8")


def test_upload_form_present():
    assert 'action="upload.php"' in HTML
    assert 'enctype="multipart/form-data"' in HTML
    for field in ('name="stack"', 'name="consent"', 'name="website"', 'name="ajax"',
                  'name="target"', 'name="integration"'):
        assert field in HTML, field


def test_backend_and_admin_files_exist():
    for f in ("upload.php", "config.example.php", "contribute.js", "get.php",
              "db/schema.sql", "admin/admin.php", "admin/download.php"):
        assert (SITE / f).exists(), f


def test_real_config_not_committed():
    import subprocess
    tracked = subprocess.run(["git", "ls-files", "site/config.php"],
                             capture_output=True, text=True,
                             cwd=SITE.parent).stdout.strip()
    assert tracked == "", "site/config.php must NOT be committed"
    gi = (SITE.parent / ".gitignore").read_text()
    assert "site/config.php" in gi
