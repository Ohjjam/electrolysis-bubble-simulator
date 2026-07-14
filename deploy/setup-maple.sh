#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Deploy the maplestory clone as a SECOND app on the same server.
# Idempotent: called every 2 min by update.sh, but does the real work only once
# (fast early-exit afterwards). No SSH needed — install happens via auto-pull.
#   game:   games/maplestory/maplestory-server.js  (zero npm deps, pure Node)
#   url:    https://maple.<server-ip>.sslip.io   ->  127.0.0.1:3000
# ---------------------------------------------------------------------------
set -euo pipefail

APP_DIR=/opt/bubblesim
GAME_DIR="$APP_DIR/games/maplestory"
SVC=maplestory
PORT=3000
MARKER=/opt/.maplestory-setup-done

[ -d "$GAME_DIR" ] || exit 0                                    # game not present yet
if [ -f "$MARKER" ] && systemctl is-active --quiet "$SVC"; then exit 0; fi   # already up

echo "[maple] setting up..."

# Node.js — the game has ZERO npm dependencies, so the distro package is enough
if ! command -v node >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y nodejs
fi
NODE="$(command -v node)"

# systemd service (keeps the game running + restarts on crash/reboot)
cat > /etc/systemd/system/${SVC}.service <<EOF
[Unit]
Description=Maplestory clone (multiplayer)
After=network.target

[Service]
WorkingDirectory=$GAME_DIR
ExecStart=$NODE $GAME_DIR/maplestory-server.js $PORT
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
EOF

# Caddy: add a route for  maple.<server-ip>.sslip.io  (idempotent)
IP_HOST="$(cat "$APP_DIR/deploy/PUBLIC_HOST.txt" 2>/dev/null || true)"   # e.g. 5-223-53-58.sslip.io
GAME_HOST="maple.${IP_HOST}"
if [ -n "$IP_HOST" ] && ! grep -q "$GAME_HOST" /etc/caddy/Caddyfile 2>/dev/null; then
  cat >> /etc/caddy/Caddyfile <<EOF

${GAME_HOST} {
    reverse_proxy 127.0.0.1:${PORT}
}
EOF
  systemctl reload caddy 2>/dev/null || systemctl restart caddy || true
fi

systemctl daemon-reload
systemctl enable --now "$SVC"
touch "$MARKER"
echo "[maple] up at https://${GAME_HOST}"
