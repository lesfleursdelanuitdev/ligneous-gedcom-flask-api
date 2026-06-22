#!/bin/bash
# Deploy the Flask analytics / research API (Python) — rootless Podman Quadlet container.
#
# Production runs as the `ligneous-flask-api` container under user `svc-ligneous`
# (image localhost/flask-api:prod, published on 127.0.0.1:5001; nginx does NOT
# expose it). The legacy native-systemd unit flask-analytics.service is DISABLED.
#
# This script (run as momolig): builds the prod image from this repo root, loads
# it into svc-ligneous's rootless image store, and restarts the Quadlet unit.
# DATABASE_URL is injected at runtime via the Podman secret `ligneous-db-url`
# (not at build time). See /srv/apps/deploy/quadlet/README.md and
# /home/momolig/containerization-status.md.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
IMAGE="flask-api:prod"
UNIT="ligneous-flask-api.service"
RUN_USER="svc-ligneous"

if [[ "$(id -un)" != "momolig" ]]; then
  echo "Run as momolig (builds images; uses sudo for $RUN_USER)." >&2
  exit 1
fi

echo "==> Building localhost/$IMAGE from $REPO_ROOT ..."
cd "$REPO_ROOT"
podman build -t "$IMAGE" .

echo "==> Loading localhost/$IMAGE into ${RUN_USER}'s rootless store ..."
podman save "localhost/$IMAGE" | sudo -u "$RUN_USER" podman load

echo "==> Restarting $UNIT ..."
sudo systemctl --user -M "${RUN_USER}@" restart "$UNIT"
sudo systemctl --user -M "${RUN_USER}@" --no-pager --lines=0 status "$UNIT" || true

echo "==> Smoke check (http://127.0.0.1:5001/api/ready) ..."
if ! curl -fsS -o /dev/null -w 'flask /api/ready -> %{http_code}\n' --max-time 15 http://127.0.0.1:5001/api/ready; then
  echo "WARN: smoke check failed. Logs: journalctl --user -M ${RUN_USER}@ -u $UNIT -e" >&2
fi

echo "Deploy complete. Flask API live on 127.0.0.1:5001 (loopback only)."
