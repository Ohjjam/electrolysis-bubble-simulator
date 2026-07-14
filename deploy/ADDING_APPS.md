# 이 서버에 새 앱(게임 등) 추가하기 — AI/사람용 가이드

이 문서만 따라 하면 새 앱을 배포할 수 있습니다. **서버에 SSH로 들어갈 필요 없이 이 저장소에 push만** 하면 됩니다.

## 1. 서버 구조 (배경)
- Hetzner VPS. 서버 IP `5.223.53.58` → base URL **https://5-223-53-58.sslip.io**
- 앞단에 **Caddy**(자동 HTTPS 리버스 프록시). 각 앱은 localhost의 포트에서 돌고, Caddy가 URL로 갈라 보냅니다.
- 배포는 **GitHub 자동갱신**: 서버가 이 저장소(`Ohjjam/electrolysis-bubble-simulator`, branch `main`)를 **2분마다 `git pull`** 해서(`deploy/update.sh`, cron) 반영합니다. → **"배포" = 이 repo의 `ohjam` remote에 push.**
- 현재 앱: **버블 시뮬**(Python, 루트의 `server3d_app.py`, 포트 **8766**) — apex `/`.
- 현재 어떤 앱들이 있고 각 포트가 뭔지는 이 저장소의 **`games/` 폴더**와 **`deploy/setup-*.sh`** 를 보면 됩니다(포트/경로 충돌 방지용으로 먼저 확인).

## 2. 핵심 규칙: 서브도메인 말고 **하위경로(subpath)**
- `*.sslip.io` 서브도메인은 Let's Encrypt 인증서 발급이 불안정(rate limit) → **쓰지 말 것.**
- 새 앱은 apex의 **하위경로**로 서빙: `https://5-223-53-58.sslip.io/<name>/`
- Caddy 라우팅: `handle_path /<name>/* { reverse_proxy 127.0.0.1:<port> }`, 그리고 맨 끝에 시뮬 catch-all `handle { reverse_proxy 127.0.0.1:8766 }`.

## 3. 앱 추가 절차
1. 앱 파일을 **`games/<name>/`** 에 넣는다.
2. **포트**를 하나 정한다(8766=시뮬 사용 중; `3001`, `3002` … 기존과 안 겹치게 — `deploy/setup-*.sh`에서 기존 포트 확인).
3. **`deploy/setup-<name>.sh`** 작성(멱등: 마커 파일로 1회만 실제 작업):
   - 런타임 설치(필요시): Node면 `apt-get install -y nodejs`, Python이면 venv+pip. **정적 HTML만이면 런타임 불필요** (Caddy `file_server`로 직접 서빙 가능).
   - **systemd 서비스** 생성해 앱을 그 포트에 띄움(`Restart=always`, `WorkingDirectory=/opt/bubblesim/games/<name>`).
   - **`/etc/caddy/Caddyfile` 재작성** — apex 블록에 **이 앱 + 기존 모든 앱 + 시뮬 catch-all** 을 전부 포함(아래 예시). ⚠️ 기존 앱 블록을 빠뜨리면 그 앱이 죽으니 항상 전체를 다시 쓸 것.
   - `systemctl daemon-reload; systemctl enable --now <svc>; systemctl reload caddy`
   - `PUBLIC_HOST.txt`(= `5-223-53-58.sslip.io`)는 `deploy/PUBLIC_HOST.txt`에서 읽는다.
4. **`deploy/update.sh`** 에 연결: 앱이 repo에 있으면 setup 호출, 사라지면 teardown(서비스 내리고 Caddy 복구). 과거 maple 처리 패턴을 git 이력(`deploy/update.sh` history)에서 참고.
5. **WebSocket** 쓰는 앱이면: 클라이언트가 `wss:// + location.host` 로만 연결하면 subpath에서 깨짐 → `+ location.pathname`(현재 경로) 붙여 `wss://host/<name>/` 로 연결되게 패치. (Caddy `handle_path`가 WS 업그레이드도 프록시함.)
6. **커밋 + push** (remote = `ohjam`):
   - 저장된 git 자격이 읽기전용일 수 있음 → `git -c credential.helper='!gh auth git-credential' push ohjam main` (활성 gh 계정이 **Ohjjam**이어야 함). 또는 GitHub Desktop.
   - 새 컴퓨터라 push 권한이 없으면: `gh auth login`으로 Ohjjam 로그인하거나 GitHub Desktop으로 로그인 후 push.
7. **~2-4분 뒤 서버 자동 반영.** 검증:
   - `curl https://5-223-53-58.sslip.io/<name>/` → 200 + 앱 내용
   - WS면 WS 업그레이드가 `101 Switching Protocols` 인지 확인.

## 4. Caddyfile 예시 (앱 2개일 때)
```
5-223-53-58.sslip.io {
    redir /game1 /game1/
    handle_path /game1/* { reverse_proxy 127.0.0.1:3001 }
    redir /game2 /game2/
    handle_path /game2/* { reverse_proxy 127.0.0.1:3002 }
    handle { reverse_proxy 127.0.0.1:8766 }
}
```

## 5. 주의사항 (실제로 겪은 것들)
- **shallow clone**: 서버 clone이 `--depth 1`이라 대규모 히스토리 변화 후 fetch가 조용히 멈춘 적 있음 → `update.sh`가 `git fetch --depth=100`로 견고화됨(수정 완료).
- **줄바꿈**: `deploy/*.sh`는 반드시 LF(리눅스). `deploy/.gitattributes`가 `* text eol=lf`로 강제(설정됨). CRLF면 shebang 깨짐. 검증은 `python -c "print(open(f,'rb').read().count(b'\r'))"`.
- **서버 직접 접근은 사용자만**: AI는 repo push로만 배포. 막히면 사용자에게 `ssh root@5.223.53.58`(root 비번은 서버 생성 시 이메일로 옴)로 진단/복구 명령을 대신 실행하도록 요청. 진단 예: `git -C /opt/bubblesim log --oneline -1`, `systemctl status <svc>`, `cat /etc/caddy/Caddyfile`, `journalctl -u caddy -n 30`.
- **멱등성**: setup 스크립트는 매 2분 호출되므로 이미 설치됐으면 빠르게 early-exit(마커 파일)해야 함.
