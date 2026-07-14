#!/usr/bin/env bash
# Vibe Survivors (4인 협동 서바이벌) 셋업 — 멱등. update.sh가 2분마다 호출하므로
# 이미 설치돼 있으면 마커 파일 보고 즉시 빠져나간다.
#
# 구조: Node 서버 하나가 정적 파일 + WebSocket 릴레이를 같은 포트(3011)에서 처리한다.
#   - 게임 로직은 서버에 0줄 (권위는 방장 브라우저). 밸런스를 고쳐도 서버 재시작만 하면 된다.
#   - Caddy `handle_path /survivors/*` 가 접두사를 떼고 넘기므로 WS도 같은 포트로 프록시된다.
set -euo pipefail

APP_DIR=/opt/bubblesim
GAME_DIR="$APP_DIR/games/survivors"
SERVICE=survivors
PORT=3011
MARKER=/opt/.survivors-setup-done1

# 코드가 바뀌면(= git pull로 커밋 해시가 달라지면) 서비스만 재시작하고 나머진 건너뛴다
CURRENT_REV="$(git -C "$APP_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
if [ -f "$MARKER" ] && [ "$(cat "$MARKER" 2>/dev/null)" = "$CURRENT_REV" ]; then
  exit 0
fi

echo "$(date -u '+%F %T')  survivors: 셋업/갱신 시작 ($CURRENT_REV)"

# ── Node 20+ (없으면 설치) ──
if ! command -v node >/dev/null 2>&1 || [ "$(node -v | sed 's/v\([0-9]*\).*/\1/')" -lt 18 ]; then
  echo "  · Node.js 설치"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null 2>&1
  apt-get install -y nodejs >/dev/null 2>&1
fi

# ── 의존성 (ws 하나뿐) ──
cd "$GAME_DIR"
if [ ! -d node_modules/ws ]; then
  echo "  · npm install (ws)"
  npm install --omit=dev --no-audit --no-fund >/dev/null 2>&1
fi

# ── systemd 서비스 ──
cat > /etc/systemd/system/${SERVICE}.service <<EOF
[Unit]
Description=Vibe Survivors (4인 협동 · 정적 파일 + WebSocket 릴레이)
After=network.target

[Service]
Type=simple
WorkingDirectory=${GAME_DIR}
Environment=PORT=${PORT}
Environment=HOST=127.0.0.1
Environment=STATIC_ROOT=${GAME_DIR}
ExecStart=/usr/bin/node survivors/server/index.js
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# ── Caddyfile 전면 재작성 ──
# ⚠ apex 블록에 '이 앱 + 기존 모든 앱 + 시뮬 catch-all'을 전부 다시 써야 한다.
#    하나라도 빠뜨리면 그 앱이 죽는다 (ADDING_APPS.md 3-3).
#    현재 앱: survivors(3011) + 버블 시뮬(8766, catch-all)
IP_HOST="$(cat "$APP_DIR/deploy/PUBLIC_HOST.txt" 2>/dev/null || echo '5-223-53-58.sslip.io')"
cat > /etc/caddy/Caddyfile <<EOF
${IP_HOST} {
    redir /survivors /survivors/
    handle_path /survivors/* {
        reverse_proxy 127.0.0.1:${PORT}
    }
    handle {
        reverse_proxy 127.0.0.1:8766
    }
}
EOF

systemctl daemon-reload
systemctl enable --now ${SERVICE} >/dev/null 2>&1
systemctl restart ${SERVICE}
systemctl reload caddy 2>/dev/null || systemctl restart caddy

echo "$CURRENT_REV" > "$MARKER"
echo "$(date -u '+%F %T')  survivors: 준비 완료 → https://${IP_HOST}/survivors/"
