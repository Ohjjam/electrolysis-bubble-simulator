# 구버전 보관함

코드 어디서도 참조하지 않는 옛 파일들을 (git에 커밋된 적이 없어 지우면 복구 불가라)
삭제 대신 여기로 옮겨둔 곳. **이 폴더는 통째로 삭제해도 아무 영향 없음.**

## web3d 프로토타입/ — 2026-06-18~19 제작, 07-10 이동

3세대 Python 3D 엔진(`bubblesim3d/` + `web3d/app3d.html`)으로 대체된,
JS 자체엔진 시절의 프로토타입들:

| 파일 | 정체 |
|---|---|
| `sim3d.js` | JS 3D 물리엔진 (Stam 유체 + 가스 파슬) — `bubblesim3d/`가 대체 |
| `gl3d.html` | WebGL(three.js) 렌더 버전 |
| `panels.html` | "3D 계산 → 2D 패널 표시" 버전 |
| `index.html` | 지오메트리 우선 셀 도면 + 버블 확대 프로토타입 |

참고: `bubblesim3d/params3d.py` 주석에 "디자이너 기본값은 web3d/index.html의
CTRL[]에서 왔다"는 출처 표기가 있음 — 코드가 이 파일을 읽는 건 아니고 역사 기록일 뿐.
