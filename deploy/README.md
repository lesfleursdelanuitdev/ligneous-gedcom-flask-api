# Deploying ligneous-python-api

Flask research/analytics service. Default upstream port **5001** (bind **loopback** only; terminate TLS on nginx).

Typical layout (all on one host, same as `the-gonsalves-family` / admin / Postgres):

1. **DNS** — `analytics.gonsalvesfamily.com` → this server’s public IP.
2. **Postgres** — `DATABASE_URL` in `ligneous-python-api/.env` matches the app that already talks to `ligneous_frontend` on this machine (for example copy from `the-gonsalves-family/.env.production` or your `ligneous-frontend` env). Use `localhost` / `127.0.0.1` when the DB is local.
3. **Research schema** — once per database (use the same `DATABASE_URL` value as in `.env`; exporting it in your shell is enough):

   ```bash
   cd /path/to/ligneous-python-api
   export DATABASE_URL="postgresql://…"   # same as sibling app / .env
   psql "$DATABASE_URL" -f migrations/001_research_schema.sql
   ```

4. **Python venv** — from this directory:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

5. **systemd** — copy `deploy/systemd/ligneous-python-api.service` to `/etc/systemd/system/`, edit `User`, `Group`, `WorkingDirectory`, `EnvironmentFile`, and `ExecStart` paths to match your install, then:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now ligneous-python-api
   sudo systemctl status ligneous-python-api
   ```

6. **nginx (`analytics.gonsalvesfamily.com`)** — two steps:

   **Phase 1 — HTTP only** (ACME webroot + proxy to Gunicorn; no TLS file required yet):

   ```bash
   sudo cp deploy/nginx/analytics.gonsalvesfamily.com.phase1-http.conf \
     /etc/nginx/sites-available/analytics.gonsalvesfamily.com
   sudo ln -sf /etc/nginx/sites-available/analytics.gonsalvesfamily.com /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```

   Smoke test from the server:  
   `curl -sS --resolve analytics.gonsalvesfamily.com:80:127.0.0.1 http://analytics.gonsalvesfamily.com/api/health`

   **Phase 2 — HTTPS** — after DNS works and port 80 is reachable from the internet, issue a cert and swap the site config:

   ```bash
   sudo bash deploy/scripts/enable-analytics-tls.sh
   ```

   If Let’s Encrypt returns a temporary error, retry later or check https://letsencrypt.status.io/ — the script is safe to re-run after fixing upstream issues.

   The older generic template `deploy/nginx/ligneous-python-api.conf.example` is still valid for other hostnames; for this domain use the `analytics.gonsalvesfamily.com.*.conf` files above.

7. **Next.js apps on the same host** — set **`PYTHON_API_URL=http://127.0.0.1:5001`** (no trailing slash) in each app’s production env so `/api/research/*` proxies hit Gunicorn over loopback. Restart PM2 / Node after changing env.

   Using `https://analytics.gonsalvesfamily.com` as `PYTHON_API_URL` also works but adds an extra hop through nginx; loopback is simpler on one machine.

8. **Smoke tests** (after TLS): `curl -sS https://analytics.gonsalvesfamily.com/api/health` and `/api/research/ping`. With HTTP-only phase 1, use `http://` in the same `curl` tests.

## Security notes

- Gunicorn should listen on **`127.0.0.1:5001`** only; only nginx should be public on **443**.
- Exposing this API on the internet without extra auth means any caller who knows a **tree UUID** can hit analytics routes. The public Next app mitigates that in its proxy; direct access to the subdomain does not. Add API keys, firewall rules, or nginx `allow` if you need tighter control.

## Optional: dedicated Unix user

If you use `User=ligneous` in the unit file, create a system user (once):

```bash
sudo useradd --system --home /nonexistent --shell /usr/sbin/nologin ligneous
sudo chown -R ligneous:ligneous /path/to/ligneous-python-api/.venv
# .env must be readable by that user; avoid world-readable permissions on secrets.
```
