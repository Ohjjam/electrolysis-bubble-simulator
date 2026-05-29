# 수전해 버블 다이내믹스 시뮬레이터 (HER / OER)

전기화학 수전해에서 **전압 → 전류 → 기포 핵생성·성장·이탈**이 서로 되먹임하는 과정을
최대한 현실 물리/화학에 맞게 모사하고, **어떤 변수를 바꾸면 버블을 제어할 수 있는지**
탐구하기 위한 시뮬레이터입니다.

구성은 두 개:

| | 무엇 | 용도 |
|---|---|---|
| **`bubblesim/`** | 순수 Python 물리 코어 (정답지) | 검증·파라미터 스윕·분극곡선·재현성. numpy 불필요(표준 라이브러리만) |
| **`index.html`** | 동일 물리를 포팅한 단일 HTML | 실시간 애니메이션 + 슬라이더로 직관 탐구. 더블클릭으로 실행, 설치 0 |

웹은 코어의 "거울"입니다 — 같은 방정식/상수를 씁니다.

---

## 빠른 시작

**웹 (탐구용):**
```
index.html 을 브라우저로 더블클릭   (또는 호스팅된 링크 접속)
```
전압·접촉각·농도·유속·자기장·전기장·온도·압력 슬라이더를 움직이면
버블 거동과 전류 톱니파가 실시간으로 바뀝니다.

**Python (검증·그림):**
```bash
pip install -r requirements.txt      # matplotlib만 (코어는 불필요)
python run_demo.py                   # outputs/ 에 그림 4장 생성
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

## 물리 모델 (핵심)

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

- **Lumped 전기화학**: HER+OER를 하나의 유효 Tafel+옴 저항으로 축약. 두 전극·멤브레인 분리 안 됨.
- **상관식이 근사**: KOH 전도도/σ/μ, Fritz 직경, Bruggeman, DEP/MHD 계수 모두 단순 근사. (각 함수에 가정 주석 표기)
- **대표 패치 모델**: 실제 수백만 핵생성 site를 통계적 대표 패치(수십~수백 버블)로 축약.
- **확산 과포화·물질전달 경계층** 명시 모델 없음 (`j_lim`과 `f_to_bubble`로 흡수).
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
- [ ] 두 전극 분리 + 멤브레인/iR + 농도 과전압(boundary layer) 모델
- [ ] Population balance(크기분포) 옵션 (대표 패치 대안)
- [ ] 1D/2D 전위·전류장, 자기장 MHD 유동장 풀이
- [ ] 실험 데이터 로더 + 자동 캘리브레이션(분극/빈도 피팅)
- [ ] VOF/Euler-Euler CFD 특정 케이스 검증 연동

---

## 파일 맵
```
bubblesim/            물리 코어 (순수 Python)
  constants.py        기본 상수
  properties.py       물성 상관식 (E_rev, κ, σ, ρ, μ, 확산)
  config.py           Operating(levers) + Params(모델계수)
  electrochem.py      V→j 음함수 풀이, 과전압 분해
  forces.py           이탈 힘균형 → departure 반경 (Fritz + flow/DEP/MHD)
  bubble.py           단일 버블
  surface.py          버블 개체군 (핵생성/성장/합체/이탈/상승, θ, ε)
  simulator.py        커플링 시간적분 + 트레이스 기록
  sweeps.py           분극곡선 / 단일변수 민감도
index.html            실시간 인터랙티브 앱 (동일 물리 JS 포팅, GitHub Pages 진입점)
run_demo.py           그림 4장 생성
tests/test_physics.py 물리 sanity 테스트
outputs/              생성 그림
```
