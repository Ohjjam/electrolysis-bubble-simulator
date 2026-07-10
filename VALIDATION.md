# 모델 검증 & 한계 (Model card)

이 문서는 "이게 진짜 전기화학 수전해 시뮬레이터로 납득 가능한가"에 대한 **정직한 근거**입니다.
핵심 원칙: **내부 정확성(수식이 맞음) ≠ 외부 타당성(실측을 재현함).** 둘 다 필요합니다.

## 무엇인가
HER/OER 수전해 셀의 다중 충실도(0D lumped → 2-전극 BV → 1D 갭 → 다공전극 Newman BVP →
유로 → 2D flow) **축소차수(reduced-order) 시뮬레이터**. 전해질 KOH/H₂SO₄/PB.
버블은 대표 패치 위의 Lagrangian 입자(계면 미해상, sub-grid). 단일 PC 실시간.

## 검증된 것 (자동 테스트로 락인 — `tests/test_validation.py`)
| 항목 | 모델 | 기준 | 출처 |
|---|---|---|---|
| 가역전압 E_rev(25°C) | 1.229 V | 1.229 V | 표준 |
| E_rev(80°C) | 1.180 V | ~1.18 V | 온도계수 −0.9 mV/K |
| 열중성전압 V_tn | 1.481 V | 1.481 V | ΔH_HHV/2F |
| KOH 전도도(6.9 M, 80°C) | 139 S/m | ~100–140 | Gilliam 2007 |
| **알칼리 분극 j@2.0V** | **0.785 A/cm²** | **0.785** | **AHEAD (Zhang, Sci.Adv. 2026)** |
| j@2.05V | 1.08 A/cm² | ~1.0 | AHEAD serpentine |
| OER 병목 | η_OER 0.65 ≫ η_HER 0.12 | OER가 지배(정설) | — |

분극은 **단일점이 아니라 1.6–2.1 V 곡선 전체**가 AHEAD serpentine과 일치(수% 이내).
기본 2-전극 파라미터는 이 실측에 **보정**됨(NiMo HER / NiFe OER, 30 wt% KOH, 80°C, zero-gap).
내부 정확성(BV·Tafel·Faraday·Nernst·EIS·Newman BVP·Fritz)은 별도 13-도메인 감사 + 적대적
검토로 검증(`tests/test_audit_fixes.py` 21 가드).

## 아직 검증 안 된 것 / 한계 (정직하게)
- **PEM/산성·중성**: 보정·검증은 알칼리 KOH만. 산성 셀은 미검증.
- **다른 온도·압력의 전체 곡선, EIS 스펙트럼, 가스발생률**: 직접 실측 대조 안 함(앵커만).
- **버블 동역학(이탈크기·피복·톱니파 주파수)**: 정성적으로만; 고속카메라 정량 대조 안 함.
- **j0_OER는 "겉보기 전셀 값"**(~1.3e-7 A/m², 본질 NiFe ~1e-4보다 낮음): AHEAD의 낮은 R_s
  때문에 전셀 비옴손실을 OER 가지에 흡수시킨 lumped 유효값. 본질 반응속도 상수 아님.
- **축소차수**: 패치 통계 버블·Bruggeman void·1D/2D 닫힘식 — 1차 공학모델이지 first-principles
  CFD/VOF 아님. flow2d 속도장은 정성적(예시), 정량 예측 아님.
- **자유 파라미터**: k_vogt·sh0·B_nuc·f_to_bubble·site_density 등 일부는 문헌 차수 추정이며
  특정 데이터에 미보정.

## 재검증·재보정 방법
- `python tests/test_validation.py` — 앵커 + AHEAD 분극 대조.
- 새 데이터에 보정: `Params(anode/cathode ElectrodeParams j0_ref·alpha, r_membrane_area)`를
  측정 분극곡선에 맞추고 `test_validation`의 기대값을 갱신(같은 커밋에 사유 명기).

## 신뢰성 로드맵 (다음)
1. PEM/산성 셀 보정·검증(별도 데이터셋). 2. EIS Nyquist를 실측 스펙트럼과 대조.
3. 버블 동역학을 고속영상 통계(이탈경·속도분포)와 대조. 4. 다중 충실도 수렴 테스트
(lumped↔2-전극↔porous가 기준점에서 일치). 5. 런타임 보존 진단(전하→가스 Faraday,
에너지수지 closure). 6. 민감도/불확실도 정량(어떤 출력이 어떤 미보정 파라미터에 의존).
