<?php
// Behind Apache Basic Auth (see site/README.md). Lists contributions.
$cfg = require __DIR__ . '/../config.php';
$pdo = new PDO($cfg['db_dsn'], $cfg['db_user'], $cfg['db_pass'], [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
$rows = $pdo->query('SELECT * FROM contributions ORDER BY created_at DESC')->fetchAll(PDO::FETCH_ASSOC);
function h($v) { return htmlspecialchars((string)$v, ENT_QUOTES); }
?><!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Nocturne — contributions</title>
<style>
body{font-family:system-ui,-apple-system,sans-serif;background:#0b1020;color:#e7ecf5;margin:24px}
h1{letter-spacing:-.02em}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid #24314f;padding:8px 10px;text-align:left;font-size:.9rem;vertical-align:top}
th{background:#12203f}
a{color:#2dd4bf}
</style></head><body>
<h1>Contributions (<?= count($rows) ?>)</h1>
<table>
<tr><th>When</th><th>Name</th><th>Email</th><th>Target</th><th>Integration</th><th>Size</th><th>Notes</th><th>File</th></tr>
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
</table>
</body></html>
