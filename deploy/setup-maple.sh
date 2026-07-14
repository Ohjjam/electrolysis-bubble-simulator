#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Deploy the maplestory clone as a SECOND app, served under the apex domain at
#   https://<server-ip>.sslip.io/maple/   ->  127.0.0.1:3000
# We use a SUB-PATH (not a maple.* subdomain) on purpose: a separate sslip.io
# subdomain cert is unreliable (Let's Encrypt rate limits on the shared
# sslip.io domain), whereas the apex cert already works — so /maple/ reuses it.
# Idempotent: called every 2 min by update.sh; real work runs once.
#   game: games/maplestory/maplestory-server.js  (zero npm deps, pure Node)
# ---------------------------------------------------------------------------
set -euo pipefail

APP_DIR=/opt/bubblesim
GAME_DIR="$APP_DIR/games/maplestory"
SVC=maplestory
PORT=3000
MARKER=/opt/.maplestory-setup-done2          # bumped: re-run with sub-path config

[ -d "$GAME_DIR" ] || exit 0
if [ -f "$MARKER" ] && systemctl is-active --quiet "$SVC"; then exit 0; fi

echo "[maple] setting up (sub-path /maple)..."

# Node.js — the game has ZERO npm dependencies, so the distro package is enough
if ! command -v node >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y nodejs
fi
NODE="$(command -v node)"

# systemd service (game on localhost:3000)
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

# Caddy: one apex site, /maple/* -> game (prefix stripped), everything else -> sim.
# Rewriting the whole Caddyfile keeps it idempotent and drops the old (failed)
# maple.* subdomain block if it was there.
IP_HOST="$(cat "$APP_DIR/deploy/PUBLIC_HOST.txt" 2>/dev/null || true)"
if [ -n "$IP_HOST" ]; then
  cat > /etc/caddy/Caddyfile <<EOF
${IP_HOST} {
    redir /maple /maple/
    handle_path /maple/* {
        reverse_proxy 127.0.0.1:${PORT}
    }
    handle {
        reverse_proxy 127.0.0.1:8766
    }
}
EOF
  systemctl reload caddy 2>/dev/null || systemctl restart caddy || true
fi

systemctl daemon-reload
systemctl enable --now "$SVC"
touch "$MARKER"
echo "[maple] up at https://${IP_HOST}/maple/"
