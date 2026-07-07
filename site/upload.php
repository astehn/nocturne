<?php
// Public endpoint: validate an uploaded FITS master, store it outside the web
// root, and record it in MariaDB. No credentials here — see config.php.

/**
 * Pure validation (no DB / filesystem writes) so it is unit-testable.
 * @return string[] human-readable errors; empty array means valid.
 */
function nocturne_validate_upload(array $file, array $post, int $max_bytes): array
{
    if (!empty($post['website'] ?? '')) {          // honeypot: bots fill this
        return ['Spam detected.'];
    }
    $errors = [];
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
    $ext = strtolower(pathinfo((string)($file['name'] ?? ''), PATHINFO_EXTENSION));
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

// ---- main flow (skipped when included by the unit test / CLI) ----
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
