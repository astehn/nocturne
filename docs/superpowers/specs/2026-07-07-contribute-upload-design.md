# Contribute Upload ("share your stack") — Design

**Date:** 2026-07-07
**Project:** Nocturne website — self-hosted stack upload on `nocturne.stehn.com`
**Status:** Approved — building under standing authorization.

## Motivation

Nocturne needs community test data (stacked dualband/LP FITS masters). Rather than send
people to Dropbox, host the upload on the site itself so everything lives in one place. The
VPS runs Apache + PHP + MariaDB with ample disk, which makes a small self-hosted upload
straightforward.

## Decisions (from discussion)

- **Scope:** accept a single **stacked FITS master**, up to **512 MB**. Raw subs (GB) are out
  of scope.
- **Stack:** PHP endpoint + MariaDB record + files stored **outside the web root**.
- **No email** notification — each upload is a row in the `contributions` table.
- **Admin:** a small `admin/` area (`admin.php` list + `download.php` passthrough) protected
  by **Apache Basic Auth** (`.htpasswd`) — one folder to secure, no login code.
- **UX:** a progress bar during upload (XHR), degrading to a plain form POST without JS.
- **Deferred (YAGNI):** resumable/chunked uploads, virus scanning, email, contributor
  accounts, public Photon-Donor list generation (the About page already lists donors from
  its own data).

## Architecture / files

```
site/
  index.html              # #contribute becomes a real <form> (progressive enhancement)
  contribute.js           # XHR upload with progress bar (loaded on the page)
  upload.php              # PUBLIC endpoint: validate → store → record → respond
  config.example.php      # template (committed); real config.php is git-ignored (creds)
  db/schema.sql           # CREATE TABLE contributions
  admin/                  # Apache Basic Auth protects this whole folder
    admin.php             # list contributions + download links
    download.php          # authenticated file passthrough (files live outside web root)
```

`site/config.php` (real credentials) is added to `.gitignore`.

### `db/schema.sql`

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

### `config.example.php`

```php
<?php
// Copy to config.php (git-ignored) and fill in. Used by upload.php + admin/*.php.
return [
    'db_dsn'        => 'mysql:host=127.0.0.1;dbname=nocturne;charset=utf8mb4',
    'db_user'       => 'nocturne',
    'db_pass'       => 'CHANGE_ME',
    'upload_dir'    => '/srv/nocturne-uploads',   // OUTSIDE the web root
    'max_bytes'     => 512 * 1024 * 1024,          // 512 MB
    'rate_per_hour' => 5,                          // max uploads per IP per hour
];
```

### `upload.php`

Public endpoint. **Validation is a pure function** so it's unit-testable without a DB:

```php
// Returns a list of human error strings; empty list = valid.
function nocturne_validate_upload(array $file, array $post, int $max_bytes): array
```

Rules (all server-side):
- **Honeypot**: a hidden `website` field must be empty (bots fill it) → reject.
- **Consent**: `consent` checkbox must be present → else "Please tick the consent box."
- **File present** and `$file['error'] === UPLOAD_ERR_OK` (map PHP upload errors to messages;
  `UPLOAD_ERR_INI_SIZE`/`FORM_SIZE` → "File is larger than the 512 MB limit.").
- **Size** `<= max_bytes`.
- **Extension** in {`fit`,`fits`,`fts`} (case-insensitive).
- **FITS content check**: first 6 bytes of the file are `SIMPLE` (real FITS header) → else
  "That doesn't look like a FITS file."

Main flow (after validation passes):
1. Load config; open **PDO** (MySQL) with `ERRMODE_EXCEPTION`.
2. **Rate limit**: `SELECT COUNT(*) ... WHERE ip = ? AND created_at > (NOW() - INTERVAL 1 HOUR)`;
   if `>= rate_per_hour` → reject "Too many uploads from your connection — try again later."
3. Generate a safe unique stored name: `date('Ymd-His') . '-' . bin2hex(random_bytes(6)) . '.fits'`
   (no user input in the filename); `move_uploaded_file()` into `upload_dir`.
4. **INSERT** via a prepared statement (name/email/target/integration/notes truncated to
   column limits; original filename kept only in the DB; `ip` from `REMOTE_ADDR`).
5. **Respond**: if the request is AJAX (`$_POST['ajax'] === '1'`) → `header('Content-Type: application/json')`
   and echo `{"ok":true}` / `{"ok":false,"errors":[...]}`; otherwise render a minimal HTML
   thank-you (or error) page.

Text fields are stored raw (parametrised) and **escaped on output** (admin) with
`htmlspecialchars` — never echoed unescaped.

### `admin/admin.php`

Requires `../config.php`; `SELECT * FROM contributions ORDER BY created_at DESC`; renders an
HTML table (created · name · email · target · integration · size · notes · **Download**),
every field `htmlspecialchars`-escaped. Download link → `download.php?id=<id>`. Protected by
the folder's Apache Basic Auth (no auth code in the PHP itself).

### `admin/download.php`

Requires `../config.php`; `$id = (int)($_GET['id'] ?? 0)`; prepared `SELECT stored_filename,
orig_filename FROM contributions WHERE id = ?`; if found and the file exists in `upload_dir`,
stream it with `Content-Type: application/octet-stream`, `Content-Disposition: attachment;
filename="<orig>"`, `Content-Length`, and `readfile()`. No path input from the user — the
stored name comes from the DB, joined to the configured dir with `basename()` for safety.
Also behind the `admin/` Basic Auth.

### `site/index.html` — the form

Replace the static `#contribute` copy with a `<form method="post" action="upload.php"
enctype="multipart/form-data">`:
- `<input type="file" name="stack" accept=".fit,.fits,.fts" required>`
- text inputs: `name`, `email` (type=email), `target`, `integration`; `<textarea name="notes">`
- required `consent` checkbox; hidden honeypot `website` (visually hidden, `tabindex=-1`,
  `autocomplete=off`)
- hidden `ajax` field the JS sets to `1`
- a progress-bar element (hidden until upload starts) + a status area
- submit button

Keeps the existing reassurance copy (credit as Photon Donor; used only to improve Nocturne).

### `site/contribute.js`

Progressive enhancement: on submit, if `FormData`/XHR available, `preventDefault`, set
`ajax=1`, POST via `XMLHttpRequest`; `xhr.upload.onprogress` updates the bar; on load show
the JSON result (thank-you or the error list). Without JS the form posts normally to
`upload.php`, which returns an HTML thank-you page.

## Data flow

Contributor fills the form → (JS) XHR upload with a progress bar → `upload.php` validates
(honeypot, consent, size, extension, FITS magic), rate-limits by IP, stores the file outside
the web root, inserts a `contributions` row → thank-you. The owner reviews at
`nocturne.stehn.com/admin/` (Basic Auth) and downloads via the authenticated passthrough.

## Security

- Public endpoint: hard size cap (+ matching PHP/Apache limits), extension whitelist **and**
  FITS-magic content check, honeypot, per-IP hourly rate limit.
- Files stored **outside** the web root, never served/executed; generated (non-user)
  filenames; `basename()` on lookup — no path traversal.
- **PDO prepared statements** for every query (no SQL injection); `htmlspecialchars` on all
  admin output (no stored XSS).
- `admin/` (both scripts) behind Apache Basic Auth; `download.php` only accepts an integer id
  and resolves the path from the DB.
- `config.php` (creds) git-ignored; only `config.example.php` committed.

## Deploy additions (documented in `site/README.md`)

1. Create DB + user; load `db/schema.sql`.
2. `cp config.example.php config.php` and fill DB creds; set perms so PHP can read it.
3. `sudo mkdir -p /srv/nocturne-uploads && sudo chown www-data:www-data /srv/nocturne-uploads`
   (writable by the PHP user; outside the web root).
4. Raise limits: PHP `upload_max_filesize = 512M`, `post_max_size = 520M`,
   `max_execution_time = 600`, `memory_limit >= 128M`; Apache `LimitRequestBody 536870912`.
5. Protect `admin/`: `htpasswd -c /etc/apache2/.htpasswd-nocturne admin` + a
   `<Directory .../admin>` `AuthType Basic` block (sample provided).

## Testing

- **Python** (`tests/test_contribute_page.py`): `site/index.html` contains the upload form
  posting to `upload.php` with the required fields (`stack`, `consent`, honeypot `website`,
  `ajax`); `site/config.example.php`, `site/db/schema.sql`, `site/upload.php`,
  `site/admin/admin.php`, `site/admin/download.php`, `site/contribute.js` all exist;
  `site/config.php` is **not** committed and is in `.gitignore`.
- **PHP** (if `php` is available in the build env — attempt install; else document as
  VPS-verified): `php -l` lints every `.php`; a small `site/tests/validate_test.php` exercises
  `nocturne_validate_upload()` for the pass case and each failure (no file, too big, wrong
  extension, non-FITS magic, missing consent, honeypot filled).
- **Manual (VPS) checklist** in `site/README.md`: upload a real master → progress bar → row
  appears in `admin.php` → download returns the identical file; a `.txt` renamed to `.fits`
  is rejected; the 512 MB limit rejects an oversized file; `admin/` prompts for a password.
- Full Python suite stays green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`).

## Verification (by eye)

Open the site's Contribute section: a clean form (file + name/email/target/integration/notes
+ consent), a progress bar while uploading, and a thank-you on success. A renamed non-FITS
or oversized file is refused with a clear message. `nocturne.stehn.com/admin/` asks for a
password, then lists contributions with working download links; downloaded files match the
originals byte-for-byte.
