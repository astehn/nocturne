# Contribute Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A self-hosted "share your stack" upload on `nocturne.stehn.com` — a hardened PHP endpoint storing FITS masters outside the web root, recorded in MariaDB, with a progress-bar form and a Basic-Auth-protected admin area.

**Architecture:** `upload.php` validates (pure function) → stores the file outside the web root → inserts a `contributions` row via PDO. The `#contribute` form uses `contribute.js` for an XHR progress bar (degrades to a plain POST). `admin/admin.php` lists rows; `admin/download.php` streams a file after auth. Config/creds live in a git-ignored `config.php`.

**Tech Stack:** PHP (PDO/MySQL), MariaDB, Apache (Basic Auth); vanilla JS; Python/pytest for static checks.

## Global Constraints

- Files under `site/`. Max upload **512 MB** (`max_bytes = 512*1024*1024`); per-IP rate limit **5/hour**.
- Accept extensions `fit`/`fits`/`fts` **and** verify the file starts with the FITS magic `SIMPLE`.
- Files stored in `upload_dir` **outside the web root** (`/srv/nocturne-uploads`), never served; stored filenames are generated (no user input); originals kept only in the DB.
- Every DB query uses **PDO prepared statements**; all admin output is `htmlspecialchars`-escaped.
- Real credentials live in `site/config.php` — **git-ignored**; only `site/config.example.php` is committed.
- `admin/` (both scripts) is protected by Apache Basic Auth (documented; not app code).
- Python tests run with `.venv/bin/pytest` (system python3 is 3.9). Suite: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`.
- If `php` is available in the build env, `php -l` every `.php` and run the PHP unit test; otherwise note it as VPS-verified.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Backend — schema, config, `upload.php`, PHP validation test

**Files:**
- Create: `site/db/schema.sql`, `site/config.example.php`, `site/upload.php`, `site/tests/validate_test.php`
- Modify: `.gitignore` (ignore `site/config.php`)

**Interfaces:**
- Produces: `nocturne_validate_upload(array $file, array $post, int $max_bytes): array` (returns list of error strings; empty = valid) — defined in `upload.php`, exercised by `validate_test.php`.

- [ ] **Step 1: Ignore real config; add schema + config template**

Append to `.gitignore`: `site/config.php`

`site/db/schema.sql`:
```sql
CREATE TABLE IF NOT EXISTS contributions (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  name            VARCHAR(120)  DEFAULT NULL,
  email           VARCHAR(190)  DEFAULT NULL,
  target          VARCHAR(190)  DEFAULT NULL,
  integration     VARCHAR(80)   DEFAULT NULL,
  notes           TEXT          DEFAULT NULL,
  orig_filename   VARCHAR(255)  NOT NULL,
  stored_filename VARCHAR(120)  NOT NULL,
  size_bytes      BIGINT        NOT NULL,
  ip              VARCHAR(45)   DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

`site/config.example.php`:
```php
<?php
// Copy to config.php (git-ignored) and fill in. Used by upload.php + admin/*.php.
return [
    'db_dsn'        => 'mysql:host=127.0.0.1;dbname=nocturne;charset=utf8mb4',
    'db_user'       => 'nocturne',
    'db_pass'       => 'CHANGE_ME',
    'upload_dir'    => '/srv/nocturne-uploads',   // OUTSIDE the web root
    'max_bytes'     => 512 * 1024 * 1024,          // 512 MB
    'rate_per_hour' => 5,
];
```

- [ ] **Step 2: Write `site/upload.php`**

```php
<?php
// Public endpoint: validate an uploaded FITS master, store it outside the web
// root, and record it in MariaDB. No credentials here — see config.php.

/**
 * Pure validation (no DB / filesystem) so it is unit-testable.
 * @return string[] human-readable errors; empty array means valid.
 */
function nocturne_validate_upload(array $file, array $post, int $max_bytes): array
{
    $errors = [];
    if (!empty($post['website'] ?? '')) {          // honeypot: bots fill this
        return ['Spam detected.'];
    }
    if (empty($post['consent'] ?? '')) {
        $errors[] = 'Please tick the consent box.';
    }
    $err = $file['error'] ?? UPLOAD_ERR_NO_FILE;
    if ($err === UPLOAD_ERR_NO_FILE) {
        $errors[] = 'Please choose a FITS file to upload.';
        return $errors;
    }
    if ($err === UPLOAD_ERR_INI_SIZE || $err === UPLOAD_ERR_FORM_SIZE) {
        $errors[] = 'That file is larger than the 512 MB limit.';
        return $errors;
    }
    if ($err !== UPLOAD_ERR_OK) {
        $errors[] = 'Upload failed — please try again.';
        return $errors;
    }
    if (($file['size'] ?? 0) > $max_bytes) {
        $errors[] = 'That file is larger than the 512 MB limit.';
    }
    $name = strtolower($file['name'] ?? '');
    $ext = pathinfo($name, PATHINFO_EXTENSION);
    if (!in_array($ext, ['fit', 'fits', 'fts'], true)) {
        $errors[] = 'Please upload a FITS file (.fit, .fits, or .fts).';
    }
    $tmp = $file['tmp_name'] ?? '';
    if ($tmp && is_readable($tmp)) {
        $head = (string)file_get_contents($tmp, false, null, 0, 6);
        if (strncmp($head, 'SIMPLE', 6) !== 0) {
            $errors[] = "That doesn't look like a FITS file.";
        }
    }
    return $errors;
}

// ---- main flow (skipped when included by the unit test) ----
if (php_sapi_name() !== 'cli' && ($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
    $cfg = require __DIR__ . '/config.php';
    $isAjax = (($_POST['ajax'] ?? '') === '1');

    $respond = function (bool $ok, array $errors = []) use ($isAjax) {
        if ($isAjax) {
            header('Content-Type: application/json');
            echo json_encode(['ok' => $ok, 'errors' => $errors]);
        } else {
            header('Content-Type: text/html; charset=utf-8');
            if ($ok) {
                echo '<h1>Thank you!</h1><p>Your stack was uploaded — you may be credited as a Photon Donor. <a href="/">Back to nocturne.stehn.com</a></p>';
            } else {
                echo '<h1>Upload problem</h1><ul>';
                foreach ($errors as $e) { echo '<li>' . htmlspecialchars($e) . '</li>'; }
                echo '</ul><p><a href="/#contribute">Try again</a></p>';
            }
        }
        exit;
    };

    $file = $_FILES['stack'] ?? [];
    $errors = nocturne_validate_upload($file, $_POST, (int)$cfg['max_bytes']);
    if ($errors) { $respond(false, $errors); }

    try {
        $pdo = new PDO($cfg['db_dsn'], $cfg['db_user'], $cfg['db_pass'], [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        ]);
        $ip = $_SERVER['REMOTE_ADDR'] ?? '';
        $rl = $pdo->prepare('SELECT COUNT(*) FROM contributions WHERE ip = ? AND created_at > (NOW() - INTERVAL 1 HOUR)');
        $rl->execute([$ip]);
        if ((int)$rl->fetchColumn() >= (int)$cfg['rate_per_hour']) {
            $respond(false, ['Too many uploads from your connection — please try again later.']);
        }

        $stored = date('Ymd-His') . '-' . bin2hex(random_bytes(6)) . '.fits';
        $dest = rtrim($cfg['upload_dir'], '/') . '/' . $stored;
        if (!move_uploaded_file($file['tmp_name'], $dest)) {
            $respond(false, ['Could not save the file — please try again.']);
        }

        $ins = $pdo->prepare(
            'INSERT INTO contributions (name,email,target,integration,notes,orig_filename,stored_filename,size_bytes,ip)
             VALUES (?,?,?,?,?,?,?,?,?)');
        $ins->execute([
            mb_substr(trim($_POST['name'] ?? ''), 0, 120) ?: null,
            mb_substr(trim($_POST['email'] ?? ''), 0, 190) ?: null,
            mb_substr(trim($_POST['target'] ?? ''), 0, 190) ?: null,
            mb_substr(trim($_POST['integration'] ?? ''), 0, 80) ?: null,
            mb_substr(trim($_POST['notes'] ?? ''), 0, 2000) ?: null,
            mb_substr((string)($file['name'] ?? ''), 0, 255),
            $stored,
            (int)($file['size'] ?? 0),
            $ip,
        ]);
        $respond(true);
    } catch (Throwable $e) {
        error_log('nocturne upload: ' . $e->getMessage());
        $respond(false, ['A server error occurred — please try again later.']);
    }
}
```

- [ ] **Step 3: Write the PHP unit test `site/tests/validate_test.php`**

```php
<?php
require __DIR__ . '/../upload.php';

$MAX = 512 * 1024 * 1024;
$fails = 0;
function check($cond, $label) { global $fails; if (!$cond) { $fails++; echo "FAIL: $label\n"; } else { echo "ok: $label\n"; } }

// a valid FITS-looking temp file
$tmp = tempnam(sys_get_temp_dir(), 'fit');
file_put_contents($tmp, 'SIMPLE  =                    T');
$okFile = ['name' => 'm.fits', 'error' => UPLOAD_ERR_OK, 'size' => 1000, 'tmp_name' => $tmp];
$okPost = ['consent' => 'on', 'website' => ''];

check(nocturne_validate_upload($okFile, $okPost, $MAX) === [], 'valid passes');
check(nocturne_validate_upload($okFile, ['consent' => '', 'website' => ''], $MAX) !== [], 'missing consent fails');
check(nocturne_validate_upload($okFile, ['consent' => 'on', 'website' => 'bot'], $MAX) !== [], 'honeypot fails');
check(nocturne_validate_upload(['error' => UPLOAD_ERR_NO_FILE], $okPost, $MAX) !== [], 'no file fails');
$big = $okFile; $big['size'] = $MAX + 1;
check(nocturne_validate_upload($big, $okPost, $MAX) !== [], 'oversize fails');
$badext = $okFile; $badext['name'] = 'm.txt';
check(nocturne_validate_upload($badext, $okPost, $MAX) !== [], 'wrong extension fails');
$notfits = tempnam(sys_get_temp_dir(), 'txt'); file_put_contents($notfits, 'hello there');
$badmagic = ['name' => 'm.fits', 'error' => UPLOAD_ERR_OK, 'size' => 11, 'tmp_name' => $notfits];
check(nocturne_validate_upload($badmagic, $okPost, $MAX) !== [], 'non-FITS magic fails');

unlink($tmp); unlink($notfits);
echo $fails ? "\n$fails FAILED\n" : "\nALL PASSED\n";
exit($fails ? 1 : 0);
```

- [ ] **Step 4: Lint + run the PHP test if `php` is available**

```bash
if command -v php >/dev/null; then
  php -l site/upload.php && php site/tests/validate_test.php
else
  echo "php not installed locally — validation verified on the VPS (see site/README.md)"
fi
```
Expected: `ALL PASSED` (or the skip note). `php -l` prints "No syntax errors".

- [ ] **Step 5: Commit**

```bash
git add .gitignore site/db/schema.sql site/config.example.php site/upload.php site/tests/validate_test.php
git commit -m "feat: contribute upload backend (upload.php + schema + config)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Front-end — the form, progress JS, and styles

**Files:**
- Modify: `site/index.html` (`#contribute` section), `site/styles.css` (form styles)
- Create: `site/contribute.js`
- Test: `tests/test_contribute_page.py`

**Interfaces:**
- Consumes: `site/upload.php` (Task 1) as the form `action`.
- Produces: an upload form with fields `stack`, `name`, `email`, `target`, `integration`, `notes`, `consent`, hidden `website` (honeypot) + `ajax`.

- [ ] **Step 1: Write the failing Python test**

Create `tests/test_contribute_page.py`:
```python
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
    for f in ("upload.php", "config.example.php", "contribute.js",
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_contribute_page.py -q`
Expected: FAIL (form fields absent; `contribute.js` / `admin/*` not created yet).

- [ ] **Step 3: Replace the `#contribute` section in `site/index.html`**

Replace the current `<section id="contribute">…</section>` body with the intro copy plus this form (keep the reassurance lines):
```html
      <form id="contribute-form" action="upload.php" method="post" enctype="multipart/form-data" class="contribute-form">
        <input type="file" name="stack" accept=".fit,.fits,.fts" required>
        <div class="field-row">
          <input type="text" name="name" placeholder="Your name (for the credit — optional)" maxlength="120">
          <input type="email" name="email" placeholder="Email (optional, private)" maxlength="190">
        </div>
        <div class="field-row">
          <input type="text" name="target" placeholder="Target (e.g. NGC 7000)" maxlength="190">
          <input type="text" name="integration" placeholder="Total integration (e.g. 48 min)" maxlength="80">
        </div>
        <textarea name="notes" placeholder="Notes (optional)" maxlength="2000" rows="2"></textarea>
        <label class="consent"><input type="checkbox" name="consent" required> I'm happy for this to be used to test &amp; improve Nocturne.</label>
        <input type="text" name="website" class="hp" tabindex="-1" autocomplete="off" aria-hidden="true">
        <input type="hidden" name="ajax" value="0">
        <button type="submit" class="btn btn-primary">Upload my stack</button>
        <div class="progress" hidden><div class="progress-bar"></div></div>
        <p class="form-status" role="status" aria-live="polite"></p>
      </form>
```
Add `<script src="contribute.js"></script>` before `</body>` (after `main.js`).

- [ ] **Step 4: Add form styles to `site/styles.css`**

```css
.contribute-form { max-width: 620px; margin-top: 26px; display: grid; gap: 12px; }
.contribute-form input[type=text], .contribute-form input[type=email], .contribute-form textarea, .contribute-form input[type=file] {
  width: 100%; padding: 12px 14px; border-radius: 10px; border: 1px solid var(--border);
  background: var(--surface); color: var(--text); font: inherit;
}
.contribute-form input:focus, .contribute-form textarea:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
.field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.consent { display: flex; align-items: flex-start; gap: 10px; color: var(--muted); font-size: .92rem; }
.hp { position: absolute; left: -9999px; width: 1px; height: 1px; }
.progress { height: 8px; background: var(--surface-2); border-radius: 999px; overflow: hidden; }
.progress-bar { height: 100%; width: 0; background: var(--accent); transition: width .1s linear; }
.form-status { color: var(--muted); font-size: .92rem; min-height: 1.2em; }
.form-status.error { color: #ff6b6b; }
.form-status.ok { color: var(--accent); }
@media (max-width: 640px) { .field-row { grid-template-columns: 1fr; } }
```

- [ ] **Step 5: Write `site/contribute.js`**

```javascript
// Progressive enhancement: XHR upload with a progress bar. Falls back to a
// plain form POST if anything is unsupported.
(function () {
  var form = document.getElementById("contribute-form");
  if (!form || !window.FormData || !window.XMLHttpRequest) return;

  var bar = form.querySelector(".progress");
  var fill = form.querySelector(".progress-bar");
  var status = form.querySelector(".form-status");
  var button = form.querySelector('button[type="submit"]');

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var data = new FormData(form);
    data.set("ajax", "1");
    var xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    button.disabled = true;
    status.className = "form-status";
    status.textContent = "Uploading…";
    if (bar) bar.hidden = false;

    xhr.upload.addEventListener("progress", function (ev) {
      if (ev.lengthComputable && fill) fill.style.width = Math.round((ev.loaded / ev.total) * 100) + "%";
    });
    xhr.addEventListener("load", function () {
      button.disabled = false;
      if (bar) bar.hidden = true;
      var res = {};
      try { res = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status === 200 && res.ok) {
        status.className = "form-status ok";
        status.textContent = "Thank you! Your stack was uploaded 🌌";
        form.reset();
      } else {
        status.className = "form-status error";
        status.textContent = (res.errors && res.errors.join(" ")) || "Upload failed — please try again.";
      }
    });
    xhr.addEventListener("error", function () {
      button.disabled = false;
      if (bar) bar.hidden = true;
      status.className = "form-status error";
      status.textContent = "Upload failed — please check your connection and try again.";
    });
    xhr.send(data);
  });
})();
```

- [ ] **Step 6: Run tests + verify by eye**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_contribute_page.py tests/test_site_links.py -q`
Expected: PASS (the form/fields present; `admin/*` will exist once Task 3 lands — if running Task 2 before Task 3, `test_backend_and_admin_files_exist` fails on the admin files; land Task 3 before final green, or create empty admin stubs. Recommended: run Tasks 2 and 3, then this test.)

- [ ] **Step 7: Commit**

```bash
git add site/index.html site/styles.css site/contribute.js tests/test_contribute_page.py
git commit -m "feat: contribute upload form + progress bar

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Admin area + deploy docs

**Files:**
- Create: `site/admin/admin.php`, `site/admin/download.php`
- Modify: `site/README.md` (deploy: DB, config, upload dir, PHP/Apache limits, `.htpasswd`, manual test checklist)

**Interfaces:**
- Consumes: `site/config.php` (from `config.example.php`), the `contributions` table (Task 1).

- [ ] **Step 1: Write `site/admin/admin.php`**

```php
<?php
// Behind Apache Basic Auth (see site/README.md). Lists contributions.
$cfg = require __DIR__ . '/../config.php';
$pdo = new PDO($cfg['db_dsn'], $cfg['db_user'], $cfg['db_pass'], [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
$rows = $pdo->query('SELECT * FROM contributions ORDER BY created_at DESC')->fetchAll(PDO::FETCH_ASSOC);
function h($v) { return htmlspecialchars((string)$v, ENT_QUOTES); }
?><!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Nocturne — contributions</title>
<style>body{font-family:system-ui,sans-serif;background:#0b1020;color:#e7ecf5;margin:24px}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #24314f;padding:8px 10px;text-align:left;font-size:.9rem}
th{background:#12203f}a{color:#2dd4bf}</style></head><body>
<h1>Contributions (<?= count($rows) ?>)</h1>
<table><tr><th>When</th><th>Name</th><th>Email</th><th>Target</th><th>Integration</th><th>Size</th><th>Notes</th><th>File</th></tr>
<?php foreach ($rows as $r): ?>
<tr>
  <td><?= h($r['created_at']) ?></td>
  <td><?= h($r['name']) ?></td>
  <td><?= h($r['email']) ?></td>
  <td><?= h($r['target']) ?></td>
  <td><?= h($r['integration']) ?></td>
  <td><?= round(((int)$r['size_bytes']) / 1048576, 1) ?> MB</td>
  <td><?= h($r['notes']) ?></td>
  <td><a href="download.php?id=<?= (int)$r['id'] ?>"><?= h($r['orig_filename']) ?></a></td>
</tr>
<?php endforeach; ?>
</table></body></html>
```

- [ ] **Step 2: Write `site/admin/download.php`**

```php
<?php
// Behind Apache Basic Auth. Streams a stored file by DB id (no path input).
$cfg = require __DIR__ . '/../config.php';
$id = (int)($_GET['id'] ?? 0);
$pdo = new PDO($cfg['db_dsn'], $cfg['db_user'], $cfg['db_pass'], [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
$stmt = $pdo->prepare('SELECT stored_filename, orig_filename FROM contributions WHERE id = ?');
$stmt->execute([$id]);
$row = $stmt->fetch(PDO::FETCH_ASSOC);
if (!$row) { http_response_code(404); echo 'Not found'; exit; }

$path = rtrim($cfg['upload_dir'], '/') . '/' . basename($row['stored_filename']);
if (!is_file($path)) { http_response_code(410); echo 'File missing'; exit; }

$dl = preg_replace('/[^A-Za-z0-9._-]/', '_', $row['orig_filename']) ?: 'stack.fits';
header('Content-Type: application/octet-stream');
header('Content-Disposition: attachment; filename="' . $dl . '"');
header('Content-Length: ' . filesize($path));
readfile($path);
```

- [ ] **Step 3: Lint the admin PHP if available**

```bash
command -v php >/dev/null && php -l site/admin/admin.php && php -l site/admin/download.php || echo "php not local — VPS-verified"
```
Expected: "No syntax errors" (or skip note).

- [ ] **Step 4: Add deploy + manual-test docs to `site/README.md`**

Add a "## Contribution uploads" section covering: create the DB + user and load
`db/schema.sql`; `cp config.example.php config.php` and fill creds (+ file perms so PHP can
read it but it's not web-served — it returns an array, so even if fetched it prints nothing);
`sudo mkdir -p /srv/nocturne-uploads && sudo chown www-data:www-data /srv/nocturne-uploads`;
PHP limits (`upload_max_filesize 512M`, `post_max_size 520M`, `max_execution_time 600`,
`memory_limit 256M`); Apache `LimitRequestBody 536870912`; protect `admin/` with
`sudo htpasswd -c /etc/apache2/.htpasswd-nocturne admin` and a `<Directory /var/www/nocturne/admin>`
`AuthType Basic` / `AuthUserFile` / `Require valid-user` block; and a **manual test checklist**
(upload a real master → progress → row in `admin/` → download matches; renamed `.txt` rejected;
oversize rejected; `admin/` prompts for a password).

- [ ] **Step 5: Full suite + commit**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: PASS (all green, including `tests/test_contribute_page.py`).

```bash
git add site/admin/admin.php site/admin/download.php site/README.md
git commit -m "feat: contribute admin area (list + authed download) + deploy docs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- PHP endpoint, store outside web root, MariaDB record → Task 1 (`upload.php`, schema, config). ✅
- Pure validation (size, extension, FITS magic, honeypot, consent) + rate limit + prepared statements → Task 1. ✅
- Form with all fields + progress bar (XHR, degrades) → Task 2. ✅
- Admin list + authenticated download passthrough (files outside web root) → Task 3. ✅
- No email → nothing sends mail. ✅
- config.php git-ignored, only example committed → Task 1 Step 1 + Task 2 test `test_real_config_not_committed`. ✅
- Deploy (DB, dir, PHP/Apache limits, `.htpasswd`) + manual checklist → Task 3 Step 4. ✅
- Security (whitelist+magic, generated names, basename, escaping, honeypot, rate limit) → Tasks 1 & 3. ✅
- Testing (Python static, PHP lint + unit test if available, VPS manual) → Tasks 1–3. ✅

**Placeholder scan:** Every code file shown complete; the only prose-authored step is the README deploy section (Task 3 Step 4), itemised precisely. No vague steps. ✅

**Type consistency:** `nocturne_validate_upload(array,array,int):array` identical in Task 1 impl + test. Field names (`stack`,`name`,`email`,`target`,`integration`,`notes`,`consent`,`website`,`ajax`) consistent across the form (Task 2), `upload.php` (Task 1), and `test_contribute_page.py`. DB columns match the INSERT and `admin.php` reads. `stored_filename`/`orig_filename`/`upload_dir` consistent across `upload.php`, `download.php`, config. ✅

**Note on task ordering:** `test_contribute_page.py::test_backend_and_admin_files_exist` references `admin/*` (Task 3), so the full page test only goes green after Task 3. Land Tasks 1→2→3 in order; run the full suite at the end of Task 3.
