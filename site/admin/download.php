<?php
// Behind Apache Basic Auth. Streams a stored file by DB id (no path input from
// the user — the stored name comes from the DB and is basename()'d).
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
