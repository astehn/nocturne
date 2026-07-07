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

## Changing the download URL

The download link appears twice in `index.html`, each marked with `<!-- DOWNLOAD URL -->`.
It points to `https://nocturne.stehn.com/download/Nocturne.zip`. To serve from GitHub
Releases later, change both to the release asset URL.

## Screenshots

`#screenshots` shows a placeholder until you add real images. Drop e.g.
`img/screenshot-flow.png` into `site/img/`, then replace the `.shot.placeholder` block in
`index.html` with `<div class="shot"><img src="img/screenshot-flow.png" alt="Nocturne — the guided flow"></div>`.
