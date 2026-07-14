#!/usr/bin/env bash
# Vibe Survivors (4인 협동 서바이벌) 셋업 — 멱등. update.sh가 2분마다 호출한다.
#
# 구조: Node 서버 하나가 정적 파일 + WebSocket 릴레이를 같은 포트(3011)에서 처리한다.
#   - 게임 로직은 서버에 0줄 (권위는 방장 브라우저)
#   - Caddy `handle_path /survivors/*` 가 접두사를 떼고 넘기므로 WS도 같은 포트로 프록시된다
#
# 설계 원칙 — 셋업에서 네트워크에 기대지 않는다:
#   ws(195KB)는 games/survivors/node_modules에 동봉되어 있어 npm install이 필요 없다.
#   1차 배포가 조용히 실패했던 원인이 이 부류(외부 의존)로 의심되어, 필요한 것을 node 하나로 줄였다.
#   그리고 모든 단계를 /var/log/survivors-setup.log에 남긴다 — 실패해도 이유를 볼 수 있게.
set -uo pipefail   # ⚠ set -e 없음: 한 단계가 실패해도 이유를 로그에 남기고 계속 진단한다

APP_DIR=/opt/bubblesim
GAME_DIR="$APP_DIR/games/survivors"
SERVICE=survivors
PORT=3011
MARKER=/opt/.survivors-setup-done2
LOG=/var/log/survivors-setup.log

log() { echo "$(date -u '+%F %T')  $*" | tee -a "$LOG"; }

CURRENT_REV="$(git -C "$APP_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
if [ -f "$MARKER" ] && [ "$(cat "$MARKER" 2>/dev/null)" = "$CURRENT_REV" ]; then
  exit 0   # 이미 이 커밋으로 셋업됨 — 조용히 종료 (2분마다 호출되므로)
fi

log "─── survivors 셋업 시작 (rev ${CURRENT_REV:0:7}) ───"

# ── 1. 페이로드 확인 ──
if [ ! -f "$GAME_DIR/survivors/server/index.js" ]; then
  log "✗ 서버 파일 없음: $GAME_DIR/survivors/server/index.js — git pull이 안 됐거나 페이로드가 불완전"
  exit 1
fi
if [ ! -d "$GAME_DIR/node_modules/ws" ]; then
  log "✗ ws 동봉본 없음: $GAME_DIR/node_modules/ws"
  exit 1
fi
log "✓ 페이로드 확인 ($(du -sh "$GAME_DIR" | cut -f1))"

# ── 2. Node (없으면 설치) ──
NODE_BIN="$(command -v node || true)"
if [ -z "$NODE_BIN" ]; then
  log "· node 없음 → NodeSource 20.x 설치 시도"
  curl -fsSL https://deb.nodesource.com/setup_20.x 2>>"$LOG" | bash - >>"$LOG" 2>&1
  apt-get install -y nodejs >>"$LOG" 2>&1
  NODE_BIN="$(command -v node || true)"
fi
if [ -z "$NODE_BIN" ]; then
  log "· NodeSource 실패 → 배포판 기본 패키지 시도"
  apt-get update >>"$LOG" 2>&1
  apt-get install -y nodejs >>"$LOG" 2>&1
  NODE_BIN="$(command -v node || true)"
fi
if [ -z "$NODE_BIN" ]; then
  log "✗ node 설치 실패 — 수동 설치 필요. 로그: $LOG"
  exit 1
fi
log "✓ node: $NODE_BIN ($($NODE_BIN -v))"

# ── 3. systemd 서비스 ──
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
ExecStart=${NODE_BIN} survivors/server/index.js
Restart=always
RestartSec=3
StandardOutput=append:/var/log/survivors.log
StandardError=append:/var/log/survivors.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload >>"$LOG" 2>&1
systemctl enable ${SERVICE} >>"$LOG" 2>&1
systemctl restart ${SERVICE} >>"$LOG" 2>&1
sleep 2

if ! systemctl is-active --quiet ${SERVICE}; then
  log "✗ 서비스 기동 실패:"
  systemctl status ${SERVICE} --no-pager -l 2>&1 | tail -15 | tee -a "$LOG"
  exit 1
fi
log "✓ 서비스 기동 (포트 ${PORT})"

# 로컬에서 실제로 응답하는지 확인한 뒤에만 Caddy를 건드린다 —
# 죽은 백엔드로 라우팅을 돌리면 기존 앱까지 같이 망가진 것처럼 보인다
if ! curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
  log "✗ /healthz 무응답 — Caddy 라우팅은 건드리지 않고 중단"
  tail -20 /var/log/survivors.log 2>/dev/null | tee -a "$LOG"
  exit 1
fi
log "✓ /healthz 응답 확인"

# ── 4. Caddyfile 전면 재작성 ──
# ⚠ apex 블록에 '이 앱 + 기존 모든 앱 + 시뮬 catch-all'을 전부 다시 써야 한다.
#    하나라도 빠뜨리면 그 앱이 죽는다 (ADDING_APPS.md §3-3).
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

if ! caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >>"$LOG" 2>&1; then
  log "✗ Caddyfile 검증 실패 — 되돌리고 중단 (기존 앱 보호)"
  printf '%s {\n    reverse_proxy 127.0.0.1:8766\n}\n' "$IP_HOST" > /etc/caddy/Caddyfile
  systemctl reload caddy >>"$LOG" 2>&1
  exit 1
fi

systemctl reload caddy >>"$LOG" 2>&1 || systemctl restart caddy >>"$LOG" 2>&1
log "✓ Caddy 라우팅: /survivors/* → 127.0.0.1:${PORT}, / → 8766 (시뮬)"

echo "$CURRENT_REV" > "$MARKER"
log "─── 완료 → https://${IP_HOST}/survivors/ ───"
