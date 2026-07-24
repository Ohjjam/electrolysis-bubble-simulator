# 모델 검증 & 한계 (Model card)

이 문서는 "이게 진짜 전기화학 수전해 시뮬레이터로 납득 가능한가"에 대한 **정직한 근거**입니다.
핵심 원칙: **내부 정확성(수식이 맞음) ≠ 외부 타당성(실측을 재현함).** 둘 다 필요합니다.

## 무엇인가
HER/OER 수전해 셀의 다중 충실도(0D lumped → 2-전극 BV → 1D 갭 → 다공전극 Newman BVP →
유로 → 2D/3D flow) **축소차수(reduced-order) 시뮬레이터**. 전해질 선택지는
KOH/H₂SO₄/PB지만 정량 보정 경로는 KOH뿐이다. 3D 버블은 대표 Lagrangian parcel이며
계면·기체 상연속식을 풀지 않는다.

## 검증된 것 (자동 테스트로 락인 — `tests/test_validation.py`)
| 항목 | 모델 | 기준 | 출처 |
|---|---|---|---|
| 가역전압 E_rev(25°C) | 1.229 V | 1.229 V | 표준 |
| E_rev(80°C) | 1.180 V | ~1.18 V | 온도계수 −0.9 mV/K |
| 열중성전압 V_tn | 1.481 V | 1.481 V | ΔH_HHV/2F |
| KOH 전도도(6.9 M, 80°C) | 139 S/m | ~100–140 | Gilliam 2007 |
| **알칼리 분극 j@2.0V** | **0.785 A/cm²** | **0.785** | **AHEAD (Zhang, Sci.Adv. 2026)** |
| OER 병목 | η_OER 0.65 ≫ η_HER 0.12 | OER가 지배(정설) | — |

자동 외부 앵커는 **2.0 V 한 점 ±12%**, 1.6/1.8/2.0 V 단조성·넓은 현실 범위,
Tafel slope 범위다. 따라서 1.6–2.1 V 전 곡선을 수% 이내로 검증했다는 근거로 사용하면 안 된다.
기본 2-전극 파라미터는 AHEAD 계열 데이터에 **보정**된 apparent 값이다
(NiMo HER / NiFe OER, 30 wt% KOH, 80°C, zero-gap).

2026-07-22 1차 감사와 2026-07-23 재감사에서 확인된 코드 결함, 수정 확인 결과,
미해결 모델 한계는
[`docs/PRO_AUDIT_IMPLEMENTATION.md`](docs/PRO_AUDIT_IMPLEMENTATION.md)에 구분해 기록했다.

## 아직 검증 안 된 것 / 한계 (정직하게)
- **PEM/산성·중성**: 보정·검증은 알칼리 KOH만. 산성 셀은 미검증.
- **다른 온도·압력의 전체 곡선, EIS 스펙트럼, 가스발생률**: 직접 실측 대조 안 함(앵커만).
- **버블 동역학(이탈크기·피복·톱니파 주파수)**: 정성적으로만; 고속카메라 정량 대조 안 함.
- **j0_OER는 "겉보기 전셀 값"**(~1.3e-7 A/m², 본질 NiFe ~1e-4보다 낮음): AHEAD의 낮은 R_s
  때문에 전셀 비옴손실을 OER 가지에 흡수시킨 lumped 유효값. 본질 반응속도 상수 아님.
- **축소차수**: 패치 통계 버블·Bruggeman void·1D/2D 닫힘식 — 1차 공학모델이지 first-principles
  CFD/VOF 아님. 3D도 액체 비압축장 하나와 대표 parcel의 운동량 교환일 뿐
  `α_l=1−α_g` 상연속식이 없어 고 void 압력강하·holdup·choking의 정량 예측이 아니다.
- **격자**: 기본 `h=2 mm`는 미리보기 설정이다. 1 mm 채널/깊이는 정량 해상되지 않으며,
  요청·달성 형상과 depth cell 수를 진단에서 확인해야 한다. parcel의 구속·전단 계산은
  이제 달성 depth를 사용하지만, `n_ch`·전체 폭·pitch가 충돌하면 in-plane 폭 입력은
  절대 치수가 아니라 비율로만 반영된다.
- **고 void**: Euler coupling에 넣는 gas·계면적·운동량은 같은 국소 비율로 제한해 `d32`와
  항력이 서로 다른 체적을 보지 않게 했지만, 이는 기체 상연속식을 추가한 것이 아니다.
  제한된 체적은 진단에 따로 남으며 고 void 결과는 여전히 정량 two-phase 해가 아니다.
- **parcel multiplicity**: `mult`는 정수 실개수가 아니라 기대 기포수의 비음수 통계 가중치다.
  cohort 분할 뒤 1 미만도 허용한다. `Σmult`, 계면적 moment, 기체체적을 보존하는 대신 화면
  marker 수나 개별 `mult`를 실제 기포의 정수 계수로 해석하면 안 된다.
- **운전영역**: 총압이 물 활성도를 반영한 포화수증기압 이하인 입력은 UI/API에서 거부한다.
  KOH 고정밀 경로 밖 농도·온도와 Davies 활동도 범위 밖 입력은 계산값과 함께 invalid
  진단을 내며, 검증된 예측으로 취급하면 안 된다.
- **국소 전류맵**: 전체 전하 적분은 보존하도록 수정했지만 0D 평균전류를 coverage로 재분배한
  표시 진단이다. 국소 전위·농도 해가 아니며 Faraday source에 재입력되지 않는다.
- **자유 파라미터**: k_vogt·sh0·B_nuc·f_to_bubble·site_density 등 일부는 문헌 차수 추정이며
  특정 데이터에 미보정.

## 재검증·재보정 방법
- `py -3.14 -m pytest tests/test_validation.py tests/test_pro_audit_regressions.py -q`
  — 외부 앵커와 독립 감사 회귀시험.
- 비대칭 cathode transfer coefficient, CP infeasible sweep, EIS의 `dη_conc/dj`,
  live T/P 기체상태 변환, porous 내부 확산한계, 고 void coupling은
  `tests/test_pro_audit_regressions.py`의 독립 회귀식으로 확인한다.
- 새 데이터에 보정: `Params(anode/cathode ElectrodeParams j0_ref·alpha, r_membrane_area)`를
  측정 분극곡선에 맞추고 `test_validation`의 기대값을 갱신(같은 커밋에 사유 명기).

## 신뢰성 로드맵 (다음)
1. PEM/산성 셀 보정·검증(별도 데이터셋). 2. EIS Nyquist를 실측 스펙트럼과 대조.
3. 버블 동역학을 고속영상 통계(이탈경·속도분포)와 대조. 4. 다중 충실도 수렴 테스트
(lumped↔2-전극↔porous가 기준점에서 일치). 5. 런타임 보존 진단(전하→가스 Faraday,
에너지수지 closure). 6. 민감도/불확실도 정량(어떤 출력이 어떤 미보정 파라미터에 의존).
