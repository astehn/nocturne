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
