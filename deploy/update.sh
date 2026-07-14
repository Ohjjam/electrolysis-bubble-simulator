#!/usr/bin/env bash
# Pull the latest code and restart the service ONLY when origin/main moved.
# Run every 2 minutes by /etc/cron.d/bubblesim-update (installed by setup.sh),
# so on your PC you just `git push` (or double-click the deploy .bat) and the
# live server catches up within ~2 min. Nothing to do on the server.
set -euo pipefail
APP_DIR=/opt/bubblesim
SERVICE=bubblesim3d
cd "$APP_DIR"
git fetch --quiet origin main || exit 0
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse origin/main)"
if [ "$LOCAL" != "$REMOTE" ]; then
  git reset --hard origin/main
  systemctl restart "$SERVICE"
  echo "$(date -u '+%Y-%m-%d %H:%M:%S')  updated ${LOCAL:0:7} -> ${REMOTE:0:7}"
fi

# also make sure any extra apps (games) are installed (idempotent, fast no-op once done)
if [ -f "$APP_DIR/deploy/setup-maple.sh" ]; then
  /bin/bash "$APP_DIR/deploy/setup-maple.sh" || true
fi
