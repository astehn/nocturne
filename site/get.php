<?php
// Public: record one app download (best-effort), then redirect to the file.
// Apache serves the big zip directly — this only logs the click. A DB error
// must never block the download.
$cfg = require __DIR__ . '/config.php';
try {
    $ua = mb_substr($_SERVER['HTTP_USER_AGENT'] ?? '', 0, 255);
    // skip obvious bots/crawlers/prefetchers so the count reflects real people
    if ($ua !== '' && !preg_match('/bot|crawl|spider|slurp|curl|wget|python|headless|monitor|preview|fetch/i', $ua)) {
        $pdo = new PDO($cfg['db_dsn'], $cfg['db_user'], $cfg['db_pass'], [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
        $pdo->prepare('INSERT INTO downloads (ip, user_agent) VALUES (?, ?)')
            ->execute([$_SERVER['REMOTE_ADDR'] ?? '', $ua]);
    }
} catch (Throwable $e) {
    error_log('nocturne download count: ' . $e->getMessage());
}
header('Location: /download/Nocturne.zip', true, 302);
