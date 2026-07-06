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

### Sample nginx server block

```nginx
server {
    listen 443 ssl http2;
    server_name nocturne.stehn.com;

    # ssl_certificate / ssl_certificate_key managed by certbot
    root /var/www/nocturne;
    index index.html;

    gzip on;
    gzip_types text/css application/javascript image/svg+xml;

    location / { try_files $uri $uri/ =404; }

    # long cache for static assets
    location ~* \.(css|js|png|svg|zip)$ {
        expires 30d;
        add_header Cache-Control "public";
    }
}

server {
    listen 80;
    server_name nocturne.stehn.com;
    return 301 https://$host$request_uri;
}
```

Get TLS with your existing certbot: `sudo certbot --nginx -d nocturne.stehn.com`.

## Changing the download URL

The download link appears twice in `index.html`, each marked with `<!-- DOWNLOAD URL -->`.
It points to `https://nocturne.stehn.com/download/Nocturne.zip`. To serve from GitHub
Releases later, change both to the release asset URL.

## Screenshots

`#screenshots` shows a placeholder until you add real images. Drop e.g.
`img/screenshot-flow.png` into `site/img/`, then replace the `.shot.placeholder` block in
`index.html` with `<div class="shot"><img src="img/screenshot-flow.png" alt="Nocturne — the guided flow"></div>`.
