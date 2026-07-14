#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One-shot server setup for the gen-3 Bubble Simulator (Track A live / :8766).
# Target: a fresh Hetzner Cloud VPS running Ubuntu 24.04.
# Idempotent - safe to re-run.  Invoked automatically by cloud-init on first
# boot (see deploy/cloud-init.yaml), or by hand:
#     sudo bash /opt/bubblesim/deploy/setup.sh
# ---------------------------------------------------------------------------
set -euo pipefail

APP_DIR=/opt/bubblesim
VENV=/opt/bubblesim-venv
PORT=8766
SERVICE=bubblesim3d

echo "== [1/7] system packages =="
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git curl gnupg ufw \
                   debian-keyring debian-archive-keyring apt-transport-https

echo "== [2/7] python venv + numpy (the only dependency) =="
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install numpy

echo "== [3/7] public IP -> free sslip.io hostname =="
IP="$(curl -4 -s https://ipv4.icanhazip.com || curl -4 -s https://ifconfig.co)"
IP="$(echo "$IP" | tr -d '[:space:]')"
HOST="${IP//./-}.sslip.io"
echo "$HOST" > "$APP_DIR/deploy/PUBLIC_HOST.txt"
echo "   -> https://$HOST"

echo "== [4/7] systemd service (keeps the app running + restarts on crash/reboot) =="
cat > /etc/systemd/system/${SERVICE}.service <<EOF
[Unit]
Description=Bubble Simulator (gen-3 3D live)
After=network.target

[Service]
WorkingDirectory=$APP_DIR
ExecStart=$VENV/bin/python $APP_DIR/server3d_app.py --port $PORT --host 127.0.0.1 --no-browser
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
EOF

echo "== [5/7] Caddy (automatic HTTPS reverse proxy) =="
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  apt-get install -y caddy
fi
cat > /etc/caddy/Caddyfile <<EOF
$HOST {
    reverse_proxy 127.0.0.1:$PORT
}
EOF

echo "== [6/7] firewall + 2-min auto-update cron =="
ufw allow 22/tcp  || true
ufw allow 80/tcp  || true
ufw allow 443/tcp || true
ufw --force enable || true

chmod +x "$APP_DIR/deploy/"*.sh || true
cat > /etc/cron.d/bubblesim-update <<EOF
# pull latest code every 2 min; restart the service only if origin/main moved
*/2 * * * * root /bin/bash $APP_DIR/deploy/update.sh >> /var/log/bubblesim-update.log 2>&1
EOF
chmod 0644 /etc/cron.d/bubblesim-update

echo "== [7/7] enable + start =="
systemctl daemon-reload
systemctl enable --now ${SERVICE}
systemctl restart caddy

echo ""
echo "======================================================"
echo "  DONE.   Open:  https://$HOST"
echo "  (the first visit takes ~10-30 s while the TLS cert is issued)"
echo "======================================================"
