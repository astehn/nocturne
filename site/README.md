# Nocturne website (`nocturne.stehn.com`)

A self-contained static site — `index.html` + `styles.css` + `main.js` + `img/`. No build
step, no framework, no external network calls. Deploy by copying this folder to the web root.

## Deploy

```bash
# on the VPS
sudo mkdir -p /var/www/nocturne
sudo rsync -av --delete site/ /var/www/nocturne/
```

Put the packaged app at `/var/www/nocturne/download/Nocturne.zip` so the Download button
resolves:

```bash
sudo mkdir -p /var/www/nocturne/download
sudo cp Nocturne.zip /var/www/nocturne/download/Nocturne.zip   # zip of dist/Nocturne.app
```

### Apache virtual host

Enable the modules used below (once): `sudo a2enmod deflate expires headers`.

Create `/etc/apache2/sites-available/nocturne.conf`:

```apache
<VirtualHost *:80>
    ServerName nocturne.stehn.com
    DocumentRoot /var/www/nocturne

    <Directory /var/www/nocturne>
        Require all granted
        Options -Indexes
        AllowOverride None
    </Directory>

    # gzip
    AddOutputFilterByType DEFLATE text/html text/css application/javascript image/svg+xml

    # long cache for static assets
    <FilesMatch "\.(css|js|png|svg|zip)$">
        Header set Cache-Control "public, max-age=2592000"
    </FilesMatch>
</VirtualHost>
```

Enable it and reload:

```bash
sudo a2ensite nocturne.conf
sudo systemctl reload apache2
```

Then get TLS with certbot's **Apache** plugin — it edits Apache (not nginx) and
automatically creates the HTTPS (`*:443`) vhost **and** the HTTP→HTTPS redirect for you, so
the `*:80` vhost above is all you need to write by hand:

```bash
sudo certbot --apache -d nocturne.stehn.com
```

(Certbot also installs a renewal timer; `sudo certbot renew --dry-run` verifies it.)

## Contribution uploads (`#contribute` → `upload.php`)

Lets visitors upload a stacked FITS master (≤ 512 MB). Files are stored **outside** the web
root and recorded in MariaDB; review them at `/admin/`.

**1. Database**
```sql
CREATE DATABASE nocturne CHARACTER SET utf8mb4;
CREATE USER 'nocturne'@'localhost' IDENTIFIED BY 'a-strong-password';
GRANT ALL PRIVILEGES ON nocturne.* TO 'nocturne'@'localhost';
FLUSH PRIVILEGES;
```
```bash
mysql nocturne < /var/www/nocturne/db/schema.sql
```

**2. Config** (git-ignored — never committed)
```bash
cd /var/www/nocturne
cp config.example.php config.php     # then edit db_pass, upload_dir, etc.
```
`config.php` returns a PHP array, so even if it were requested over the web it prints
nothing — but keep it out of any world-readable listing anyway.

**3. Upload directory** (outside the web root, writable by the PHP/Apache user)
```bash
sudo mkdir -p /srv/nocturne-uploads
sudo chown www-data:www-data /srv/nocturne-uploads      # user Apache/PHP runs as
sudo chmod 750 /srv/nocturne-uploads
```

**4. Raise the size limits** — a 512 MB upload needs both PHP and Apache bumped.
In `php.ini` (the one your Apache PHP uses):
```ini
upload_max_filesize = 512M
post_max_size = 520M
max_execution_time = 600
memory_limit = 256M
```
In the Apache vhost (inside the `<VirtualHost>`): `LimitRequestBody 536870912`   # 512 MB
Then `sudo systemctl reload apache2`.

**5. Protect the admin area** with HTTP Basic Auth:
```bash
sudo htpasswd -c /etc/apache2/.htpasswd-nocturne admin      # sets the admin password
```
Add to the `*:443` vhost (the one certbot created):
```apache
<Directory /var/www/nocturne/admin>
    AuthType Basic
    AuthName "Nocturne admin"
    AuthUserFile /etc/apache2/.htpasswd-nocturne
    Require valid-user
</Directory>
```
`sudo systemctl reload apache2`. Now `nocturne.stehn.com/admin/` prompts for the password;
`admin.php` lists contributions and each links to `download.php?id=…` (streams the file).

### Manual test checklist (on the VPS)

- Upload a real stacked master → the progress bar advances → "Thank you" → a new row shows in
  `/admin/`, and its download link returns a byte-identical file.
- A `.txt` renamed to `.fits` is rejected ("doesn't look like a FITS file").
- A file over 512 MB is rejected.
- `/admin/` and `/admin/download.php` both prompt for the password (never public).

## Changing the download URL

The download link appears twice in `index.html`, each marked with `<!-- DOWNLOAD URL -->`.
It points to `https://nocturne.stehn.com/download/Nocturne.zip`. To serve from GitHub
Releases later, change both to the release asset URL.

## Screenshots

The `#screenshots` gallery uses `img/shot-flow.jpg`, `img/shot-result.jpg`,
`img/shot-stacking.jpg`, `img/shot-haoiii.jpg`, `img/shot-batch.jpg`. Any web format works
(JPG/PNG); keep them reasonably sized — the two large full-app shots were downscaled to
1600 px wide (~120 KB each) so the page stays fast. To swap one, replace the file (same
name) or update the `<img src>` in the `#screenshots` section of `index.html`.
