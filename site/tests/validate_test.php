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
