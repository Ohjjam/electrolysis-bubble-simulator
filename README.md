# 수전해 버블 다이내믹스 시뮬레이터 (HER / OER)

전기화학 수전해에서 **전압 → 전류 → 기포 핵생성·성장·이탈**이 서로 되먹임하는 과정을
최대한 현실 물리/화학에 맞게 모사하고, **어떤 변수를 바꾸면 버블을 제어할 수 있는지**
탐구하기 위한 시뮬레이터입니다.

구성:

| | 무엇 | 용도 |
|---|---|---|
| **`bubblesim/`** | 순수 Python 물리 코어 (정답지) | 검증·파라미터 스윕·분극곡선·재현성. numpy 불필요(표준 라이브러리만) |
| **`2세대 라이브앱/`** (app.html + server_app.py) | 코어를 그대로 브라우저에 띄우는 라이브 서버 앱 (:8765) | **메인 인터랙티브 앱.** `2세대 라이브앱\서버 켜기.bat`으로 실행. 멀티피직스 전 모델(2전극·다공·채널·2D CFD·EIS) 반영 |
| **`1세대 단일HTML/`** (index.html) | 물리를 JS로 포팅한 단일 HTML (1세대) | 설치 0 간이판. 더블클릭 실행. lumped 0D만, 동결 |

웹은 코어의 "거울"입니다 — 같은 방정식/상수를 씁니다.

> **3D 시뮬레이터 (신설, `bubblesim3d/`)**: 위 평면 모델과 별개로, 현실의 **3D 구조**
> (3D 전극·유로·다공 스캐폴드)를 다루는 시뮬레이터가 추가되었습니다. 같은 `bubblesim.kernel`
> 물리를 재사용하며 `bubblesim/`은 무수정. `run3d.bat`(또는 `py -3.14 server3d_app.py`)로 실행
> → http://localhost:8766/. 셀 스케일 라이브(Track A) + 포어 스케일 배치·재생(Track B).
> 자세한 내용: [`docs/3D_SIMULATOR.md`](docs/3D_SIMULATOR.md).

> **파일이 많아 헷갈리면** → [`프로젝트 지도.md`](<프로젝트 지도.md>) —
> 세대(1·2·3D) 구분, 실행 .bat 전체 목록, 폴더 지도, 타임라인 한눈 정리.

---

## 빠른 시작

**웹 (탐구용):**
```
서버 켜기.bat          → http://localhost:8765   (메인 앱, Python 커널 라이브)
index.html 더블클릭                              (1세대 간이판, 설치 0)
```
전압·접촉각·농도·유속·자기장·전기장·온도·압력 슬라이더를 움직이면
버블 거동과 전류 톱니파가 실시간으로 바뀝니다.

**Python (검증·그림):**
```bash
pip install -r requirements.txt      # matplotlib만 (코어는 불필요)
python "1세대 단일HTML/run_demo.py"   # 1세대 단일HTML/outputs/ 에 그림 4장 생성
python tests/test_physics.py         # 물리 sanity 테스트
```

**Python (직접 사용):**
```python
from bubblesim import Simulator, Operating
sim = Simulator(Operating(V_cell=2.0, contact_angle=40, u_flow=0.1))
h = sim.run(t_end=2.0, dt=2e-4)
print(h["j"][-1], h["theta"][-1])     # 전류밀도[A/cm²], coverage
```

---

## 멀티-피델리티 · 멀티피직스 (v2)

물리 코어가 **차원 무관 공유 커널 + 갈아끼우는 솔버** 구조로 재편되었습니다. 같은 `Operating` 레버가
모든 fidelity에 동일하게 들어가고, `Operating.model`로 정밀도를 고릅니다.

| `model` | 전기화학 | 풀이하는 식 |
|---|---|---|
| `"lumped"` (기본) | 유효 Tafel 1개 + 옴 저항 (기존 0D, 거동 그대로) | `j=(1−θ)·j0·10^[(V−E_rev−jR)/b]` |
| `"two_electrode"` | 양극·음극 분리 + 완전 Butler–Volmer | `V=E+η_a(j)+η_c(j)+η_conc(j)+j·R` |

`two_electrode`에 들어간 이론 (전부 `bubblesim/kernel/`, 순수 Python):
- **반응속도** `kinetics.py` — Butler–Volmer `j=j0[exp(α_a Fη/RT)−exp(−α_c Fη/RT)]`, j0(T,c) Arrhenius (촉매 활성·열활성화)
- **물질전달** `transport.py` — 경계층 `Sh=f(Re,Sc)`, 유속 의존 `j_lim`, 농도과전압 `η_conc=−(RT/zF)ln(1−j/j_lim)`, Henry 과포화
- **전해질화학** `chemistry.py` — 이온세기→Davies 활동도, `pKw(T)`, **전극 표면 국소 pH**(HER쪽↑·OER쪽↓를 관측량으로 보고)
- **저항** — 막저항 `r_membrane_area` + 전극/접촉(전자전도) 저항 `r_contact_area` 직렬항
- **에너지수지** `energy.py` (`thermal=True`) — `C·dT/dt = j(V−V_tn)·A − hA(T−T_amb)` → T가 상태변수 (전류↑→발열↑→T↑→κ↑ 되먹임)

```python
from bubblesim import Simulator, Operating
# 이론 기반: 2-전극 Butler–Volmer + 열수지
sim = Simulator(Operating(V_cell=2.0, model="two_electrode", thermal=True))
h = sim.run(t_end=1.0, dt=2e-4)
print(h["j"][-1], h["T"][-1])
```

> **웹(`index.html`)은 현재 lumped 0D만 반영(동결).** 신규 멀티피직스는 Python 코어 전용 —
> 1D 솔버 착지 시 헤드리스 커널 + 프론트엔드(standalone)로 통합 예정. (`solvers/`에 fidelity 추가)

---

## 물리 모델 (핵심, lumped 기준)

### 반응
- **HER (cathode):** 2 H₂O + 2 e⁻ → H₂ + 2 OH⁻  (z = 2)
- **OER (anode):** 4 OH⁻ → O₂ + 2 H₂O + 4 e⁻  (z = 4)
- 같은 전하량당 **H₂는 O₂의 2배 부피** 기체 발생.

### 1. 전기화학 (V → I), `electrochem.py`
고정 셀 전압에서 기하학적 전류밀도 `j_geo`를 음함수로 풀이:

```
j_geo = (1 − θ) · j0 · 10^[ (V_cell − E_rev − j_geo·R_area) / b ]
```

- `E_rev(T)` : 가역 전압 (1.229 V, −0.9 mV/K)
- `b` : Tafel 기울기 [V/dec], `j0` : 교환전류밀도
- **버블 커플링이 들어가는 두 자리:**
  - **Coverage θ** → 활성면적 차단: `j_geo = (1−θ)·j_local`
  - **Void fraction ε** → 전해질 저항 증가 (Bruggeman): `κ_eff = κ·(1−ε)^1.5`,  `R_area = gap/κ_eff`

### 2. 기포 한살이, `surface.py`
대표 패치(6 × 5 mm) 위에서 개별 버블을 추적:

- **핵생성:** 활성 site 수 ∝ site 밀도 × 면적, 핵생성률 ∝ 전류밀도. (접촉각↑ → site↑, 기체가 소수성 표면을 선호)
- **성장:** Faraday로 계산한 기체 부피율 `Q = (I/zF)·RT/P` 중 `f_to_bubble`만큼을 부착 버블들에 면적(∝r²) 비례 분배.
- **합체(coalescence):** 겹치면 합쳐짐. 단, **전해질 농도가 임계치 이상이면 합체 억제**(salting-out).
- **이탈:** 아래 힘균형으로 departure 반경 `r_d` 계산 → `r ≥ r_d`인 버블 분리. (표면 불균질성으로 버블마다 ±30% 분산)
- **상승:** 분리된 버블은 Stokes 종단속도로 부력 상승 + 유속 drift.

### 3. 이탈 힘균형, `forces.py`
버블에 작용하는 분리력 vs 표면장력 고정력:

```
부력   F_b(r) = (4/3)π·Δρ·g·r³                       ~ r³
유동 drag F_d(r) = ½·Cd·ρ_l·u_eff²·π·r²                ~ r²
음의 DEP  F_E(r) = 2π·ε0·ε_l·|K|·E²·r²  (전극에서 밀어냄)  ~ r²
```
고정력은 무유동·무전기장에서 **Fritz 직경**으로 떨어지도록 보정:
```
F_adh = F_b(r_d0),   r_d0 = fritz_scale · ½ · 0.0208·β[deg]·√(σ/(g·Δρ))
```
이탈 반경 `r_d`는 `F_b(r) + F_d(r) + F_E(r) = F_adh` 의 해. 분리력이 클수록 `r_d`↓ → 더 자주 이탈.
MHD는 `u_eff = u_flow + k_mhd·j·B` 로 유효 유속에 가산(Lorentz j×B 대류).

### 4. 커플링 루프 (네가 말한 그 현상), `simulator.py`
매 스텝:
```
버블상태 → θ, ε  →  j 풀이  →  기체 Q  →  성장/핵생성/합체/이탈/상승  →  다시 θ, ε ...
```
버블이 자라며 θ↑ → 전류 흘러내림 → 이탈로 θ 급감 → 전류 급등 = **톱니파**.

---

## 조작 변수가 들어가는 자리

| 변수 | 모델 진입점 | 정성적 효과 |
|---|---|---|
| **전압 V** | η → j → 기체율 | ↑ → 전류·핵생성·성장 전부 ↑ |
| **Wettability (접촉각 β)** | Fritz `r_d0` ∝ β, footprint = r·sinβ, site 밀도 | 친수(작은 β) → 작은 버블·낮은 θ·고전류 |
| **농도 (KOH)** | 전도도 κ(c) (≈6 M 최대), coalescence 억제, σ | 6 M 부근에서 옴손실 최소 |
| **유속 u** | drag 이탈, sweep, `j_lim` 상승 | ↑ → θ↓, 전류↑ |
| **자기장 B** | `u_eff += k_mhd·j·B` (MHD) | ↑ → 이탈 촉진, 전류↑ |
| **전기장 E** | 음의 DEP `F_E ∝ E²` | ↑ → 강제 이탈, 전류↑ |
| **온도 T** | E_rev↓, κ↑, σ↓, μ↓ | ↑ → 전류↑ |
| **압력 P** | 기체 밀도 ρ_g, 부피율 Q | ↑ → 같은 전하당 부피↓ |

---

## 산출물 / 관측량
- 전극 표면 버블 실시간 애니메이션 (HER=파랑 H₂, OER=빨강 O₂)
- `j(t)` 톱니파, 평균 전류, **V–j 분극곡선**(누적 산점)
- coverage θ, void ε, 이탈 직경 `d_d`, 이탈 빈도, 버블 수, 기체 발생률[mL/min/cm²]
- 과전압 분해 (E_rev / η_act+η_ohm)
- (Python) `outputs/`의 그림 4장: 톱니파 / 분극곡선(버블 유무 비교) / wettability 스윕 / flow·B·E 스윕

---

## ⚠️ 가정과 한계 (v1, 정성/차수 수준)
이 버전은 **물리적 경향과 차수**를 맞추는 데 목표를 둡니다. 정량 검증 전 단계입니다.

- **Lumped이 기본**: `model="lumped"`는 HER+OER를 유효 Tafel 1개로 축약(기존 거동, golden 테스트로 고정). 두 전극 분리·멤브레인/전극 iR·농도과전압·국소 pH·열수지는 `model="two_electrode"`(+`thermal=True`)에서 제공.
- **상관식이 근사**: KOH 전도도/σ/μ, Fritz 직경, Bruggeman, DEP/MHD 계수, j0/α/Ea, Sherwood·Davies·pKw 계수 모두 단순 근사. (각 함수에 가정 주석) 특정 촉매/논문엔 `Params.anode/cathode` 등으로 캘리브레이션.
- **대표 패치 모델**: 실제 수백만 핵생성 site를 통계적 대표 패치(수십~수백 버블)로 축약.
- **물질전달**: 경계층(Sh/Re/Sc)·`η_conc`·Henry 과포화는 `two_electrode`에 반영. 표면 국소 pH는 *관측량*으로만 보고(전압수지엔 `η_conc`로 1회 계산, 이중계산 회피). 아직 0D — gap 방향 프로파일은 1D 솔버(예정).
- **2D 전자기장/유동장 없음**: B는 유효 유속으로, E는 균일 ∇E²로 근사.
- Fritz는 전해 버블에 대해 과대평가 경향 → `fritz_scale`로 보정.

---

## 정량화(캘리브레이션) 가이드
특정 논문/실험에 맞추려면 `bubblesim/config.py`의 `Params`와 `properties.py`를 조정:
1. **분극곡선 피팅**: 측정 I–V로 `j0`, `tafel_b`, `gap_mm` 보정 (먼저 `site_density=0`로 버블 없는 기준선 맞춤).
2. **버블 크기**: 고속카메라 departure 직경으로 `fritz_scale`, `detach_spread` 보정.
3. **물성**: `conductivity_KOH`, `surface_tension` 등을 실제 전해질 상관식(예: Gilliam 2007)으로 교체.
4. **이탈 빈도**: 측정 빈도로 `k_nuc`, `f_to_bubble` 보정.

---

## 로드맵 (현실성 단계적 강화)
- [x] **두 전극 분리 + Butler–Volmer + 멤브레인/전극 iR + 농도 과전압(boundary layer)** → `model="two_electrode"`
- [x] **전해질 화학(국소 pH·활동도) + 에너지수지(T 상태변수)** → `chemistry.py`, `thermal=True`
- [ ] Population balance(크기분포) 옵션 (대표 패치 대안)
- [ ] **1D gap 솔버**(전위·농도·void 프로파일) → 2D(y,z) 전류분포 `j(y)` (`solvers/`에 추가)
- [ ] 헤드리스 커널 + 프론트엔드(standalone) 통합 → 웹에 멀티피직스 반영
- [ ] 실험 데이터 로더 + 자동 캘리브레이션(분극/빈도 피팅)
- [ ] VOF/Euler-Euler CFD 특정 케이스 검증 연동

---

## 파일 맵
```
bubblesim/              물리 코어 (커널=순수 Python; numpy는 향후 1D/2D 솔버에서만)
  constants.py          기본 상수
  properties.py         물성 상관식 (E_rev, κ, σ, ρ, μ, D, j0 Arrhenius)
  config.py             Operating(levers; model·thermal·track_both) + Params(+ElectrodeParams)
  simulator.py          커플링 시간적분 (솔버에 위임) + 트레이스 (T 포함)
  sweeps.py             분극곡선 / 단일변수 민감도
  kernel/               ── 차원 무관 공유 물리 (~70%) ──
    context.py          build_context: 물성·계수 번들 (고정 인터페이스, "추가만")
    kinetics.py         Tafel + Butler–Volmer
    transport.py        경계층 Sh/Re/Sc, j_lim, η_conc, Henry 과포화
    chemistry.py        이온세기·Davies 활동도·pKw(T)·국소 pH
    energy.py           발열 j(V−V_tn)·Newton 냉각·T 적분 (V_tn=1.48 V)
    sources.py          Faraday 기체 발생률
    _solve.py           공용 이분법
    bubbles/            bubble.py · forces.py(이탈) · population.py(개체군 θ,ε)
  solvers/              ── 공간 솔버 (~30%, fidelity별) ──
    base.py             Solver 프로토콜 + ElectroState(j, j_field, overpotentials, fields)
    zerod.py            ZeroDSolver(lumped) · ZeroDTwoElectrodeSolver(Butler–Volmer)
  electrochem·forces·bubble·surface.py   구경로 shim (하위호환)
1세대 단일HTML/          [1세대] index.html(더블클릭, lumped 0D 동결) · run_demo.py(그림 4장→outputs/) · demo_multiphysics.py(텍스트 데모)
2세대 라이브앱/          [2세대] app.html+server_app.py (:8765) — 서버 켜기.bat · build_web.py가 docs/ 웹판 빌드 · 터널/배포 도구
bubblesim3d/ + web3d/   [3세대] 3D 셀 시뮬레이터 (:8766) — run3d.bat · docs/3D_SIMULATOR.md
tests/                  전체 테스트 — py -3.14 -m pytest tests/ -q
※ 실행 .bat/.url 전체 목록과 상세 지도 → 프로젝트 지도.md
```
