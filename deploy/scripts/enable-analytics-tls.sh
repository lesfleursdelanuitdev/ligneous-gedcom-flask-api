#!/usr/bin/env bash
# Run on the server after phase-1 HTTP nginx is live and DNS points here.
# Issues a cert for analytics.gonsalvesfamily.com, installs the HTTPS nginx config, reloads nginx.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WEBROOT="${CERTBOT_WEBROOT:-/var/www/certbot}"
DOMAIN="${ANALYTICS_DOMAIN:-analytics.gonsalvesfamily.com}"
NGINX_SITE="/etc/nginx/sites-available/${DOMAIN}"

echo "==> Requesting certificate for ${DOMAIN} (webroot: ${WEBROOT})"
certbot certonly --webroot -w "${WEBROOT}" -d "${DOMAIN}" --non-interactive --agree-tos "$@"

echo "==> Installing HTTPS nginx config"
cp "${ROOT}/deploy/nginx/analytics.gonsalvesfamily.com.https.conf" "${NGINX_SITE}"

echo "==> Testing and reloading nginx"
nginx -t
systemctl reload nginx

echo "Done. Test: curl -sS https://${DOMAIN}/api/health"
