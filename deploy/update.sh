#!/usr/bin/env bash
# Pull the latest code and restart the service ONLY when origin/main moved.
# Run every 2 minutes by /etc/cron.d/bubblesim-update (installed by setup.sh),
# so on your PC you just `git push` (or double-click the deploy .bat) and the
# live server catches up within ~2 min. Nothing to do on the server.
set -euo pipefail
APP_DIR=/opt/bubblesim
SERVICE=bubblesim3d
cd "$APP_DIR"
# Robust fetch: a depth-1 shallow clone can silently fail to fetch after a large
# history change (that once wedged auto-update). Deepen it, and LOG real failures
# instead of vanishing quietly.
git fetch --depth=100 origin main 2>/dev/null \
  || git fetch origin main 2>/dev/null \
  || { echo "$(date -u '+%F %T')  fetch FAILED (network/repo?)"; exit 0; }
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse origin/main)"
if [ "$LOCAL" != "$REMOTE" ]; then
  git reset --hard origin/main
  systemctl restart "$SERVICE"
  echo "$(date -u '+%Y-%m-%d %H:%M:%S')  updated ${LOCAL:0:7} -> ${REMOTE:0:7}"
fi

# reconcile the maple game: set up if present in the repo, tear down if removed
if [ -f "$APP_DIR/deploy/setup-maple.sh" ] && [ -d "$APP_DIR/games/maplestory" ]; then
  /bin/bash "$APP_DIR/deploy/setup-maple.sh" || true
elif [ -f /etc/systemd/system/maplestory.service ]; then
  echo "$(date -u '+%F %T')  maple removed from repo -> tearing down"
  systemctl disable --now maplestory 2>/dev/null || true
  rm -f /etc/systemd/system/maplestory.service /opt/.maplestory-setup-done2 /opt/.maplestory-setup-done
  systemctl daemon-reload
  IP_HOST="$(cat "$APP_DIR/deploy/PUBLIC_HOST.txt" 2>/dev/null || true)"
  if [ -n "$IP_HOST" ]; then
    printf '%s {\n    reverse_proxy 127.0.0.1:8766\n}\n' "$IP_HOST" > /etc/caddy/Caddyfile
    systemctl reload caddy 2>/dev/null || true
  fi
fi

# reconcile survivors (4인 협동 서바이벌, 포트 3011): repo에 있으면 셋업, 사라지면 철거
if [ -f "$APP_DIR/deploy/setup-survivors.sh" ] && [ -d "$APP_DIR/games/survivors" ]; then
  /bin/bash "$APP_DIR/deploy/setup-survivors.sh" || true
elif [ -f /etc/systemd/system/survivors.service ]; then
  echo "$(date -u '+%F %T')  survivors removed from repo -> tearing down"
  systemctl disable --now survivors 2>/dev/null || true
  rm -f /etc/systemd/system/survivors.service /opt/.survivors-setup-done1 /opt/.survivors-setup-done2
  systemctl daemon-reload
  IP_HOST="$(cat "$APP_DIR/deploy/PUBLIC_HOST.txt" 2>/dev/null || true)"
  if [ -n "$IP_HOST" ]; then
    printf '%s {\n    reverse_proxy 127.0.0.1:8766\n}\n' "$IP_HOST" > /etc/caddy/Caddyfile
    systemctl reload caddy 2>/dev/null || true
  fi
fi
