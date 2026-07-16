# -*- coding: utf-8 -*-
"""Build the canonical Data Analytics report artifact for mesh model v2.

Reads the latest simulator outputs and writes one bounded report manifest.  The
artifact is the report source used by the ChatGPT Desktop reader; it is not a
second independent calculation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "out"
ARTIFACT = OUT / "mesh_model_v2_artifact.json"
TITLE = "Mesh 실험 모델 v2 — 접촉각 기반 재해석과 설계 판단"


def _load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def _f(value, digits=4):
    return round(float(value), digits)


def build():
    summary = _load("summary.json")
    decomp = _load("decomp.json")
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")

    cat = [r for r in summary["axes"]["catalog"]["table"] if r.get("fits")]
    cat = sorted(cat, key=lambda r: r["dV@1000_mV"], reverse=True)
    ref = next(r for r in cat if r["id"] == "pp_040x053")
    robust = next(r for r in cat if r["id"] == "pp_025x030")
    factors = decomp["factors"]
    d1000 = decomp["decomp"]["1000"]
    rmse = summary["pristine"]["calib_RMSE_mV"]

    catalog_rows = []
    for rank, r in enumerate(cat, 1):
        clearance = 0.9 - r["t_mm"]
        catalog_rows.append({
            "rank_voltage": rank,
            "mesh_id": r["id"],
            "mesh_label": r["id"].replace("pp_", "PP "),
            "hole_mm": _f(r["hole_mm"], 3),
            "open_fraction": _f(r["open"], 3),
            "thickness_mm": _f(r["t_mm"], 3),
            "clearance_mm": _f(clearance, 3),
            "V_1000_mV": _f(r["V@1000mV"], 1),
            "dV_1000_mV": _f(r["dV@1000_mV"], 1),
            "contact_probability_upper": _f(r["mesh_contact_prob"], 4),
            "wetting_drive": _f(r["mesh_wetting_drive"], 4),
            "transfer_index_upper": _f(r["mesh_capture_eff"], 4),
            "solid_volume_fraction": _f(r["mesh_obstruction"], 4),
            "flow_speed_ratio": _f(r["mesh_u_boost"], 2),
            "pressure_drop_ratio_est": _f(r["mesh_dp_ratio"], 2),
            "hydraulic_guardrail": "통과" if r["mesh_dp_ratio"] <= 3 else "주의",
            "assembly_guardrail": "통과" if clearance >= 0.1 else "주의",
        })

    base_pore = {r["hole_mm"]: r for r in summary["axes"]["pore_size"]["table"]}
    active_pore = {r["hole_mm"]: r for r in summary["axes"]["pore_size_theta60"]["table"]}
    pore_rows = []
    for hole in sorted(base_pore):
        for case, angle, row in (
            ("일반 Ni foam 110°", 110.0, base_pore[hole]),
            ("젖음성 개선 전극 60°", 60.0, active_pore[hole]),
        ):
            pore_rows.append({
                "hole_label": f"{hole:.2f}",
                "hole_mm": _f(hole, 3),
                "electrode_case": case,
                "electrode_angle_deg": angle,
                "mesh_angle_deg": 105.8,
                "V_1000_mV": _f(row["V@1000mV"], 1),
                "dV_1000_mV": _f(row["dV@1000_mV"], 1),
                "bubble_d_mm": _f(row["mesh_bubble_d_mm"], 4),
                "contact_probability_upper": _f(row["mesh_contact_prob"], 4),
                "wetting_drive": _f(row["mesh_wetting_drive"], 4),
                "transfer_index_upper": _f(row["mesh_capture_eff"], 4),
                "pressure_drop_ratio_est": _f(row["mesh_dp_ratio"], 2),
            })

    angle_rows = []
    for r in summary["axes"]["contact_angles"]["table"]:
        angle_rows.append({
            "electrode_angle_deg": _f(r["electrode_angle_deg"], 1),
            "mesh_angle_deg": _f(r["mesh_angle_deg"], 1),
            "V_1000_mV": _f(r["V@1000mV"], 1),
            "dV_1000_mV": _f(r["dV@1000_mV"], 1),
            "bubble_d_mm": _f(r["bubble_d_mm"], 4),
            "contact_probability_upper": _f(r["contact_prob"], 4),
            "wetting_drive": _f(r["wetting_drive"], 4),
            "transfer_index_upper": _f(r["capture_eff"], 4),
        })

    headline = [{
        "ref_dV_1000_mV": _f(d1000["net_mV"], 1),
        "ref_transfer_index": _f(factors["capture_eff"], 4),
        "ref_pressure_drop_ratio": _f(factors["dp_ratio"], 2),
        "pristine_RMSE_mV": _f(rmse, 1),
    }]

    sources = [
        {
            "id": "summary_source",
            "label": "재실행한 mesh parameter study",
            "path": "analysis/out/summary.json",
            "query": {
                "engine": "DuckDB",
                "language": "sql",
                "sql": "SELECT * FROM read_json_auto('analysis/out/summary.json')",
                "description": "현재 mesh model v2로 재실행한 전체 스윕 JSON을 읽는다.",
                "executed_at": generated,
                "tables_used": ["analysis/out/summary.json"],
                "filters": ["65 °C", "4 mL/min", "electrode angle 110°", "PP angle 105.8°"],
                "metric_definitions": ["ΔV@1000 = pristine voltage - mesh voltage at 1000 mA/cm²"],
            },
        },
        {
            "id": "decomp_source",
            "label": "메커니즘 반사실 분해",
            "path": "analysis/out/decomp.json",
            "query": {
                "engine": "DuckDB",
                "language": "sql",
                "sql": "SELECT * FROM read_json_auto('analysis/out/decomp.json')",
                "description": "접촉각 전달과 체류시간 감소를 순차적으로 켠 반사실 분해 JSON을 읽는다.",
                "executed_at": generated,
                "tables_used": ["analysis/out/decomp.json"],
                "metric_definitions": ["각 기여 mV = 직전 단계 cell voltage - 다음 단계 cell voltage"],
            },
        },
        {
            "id": "ni_angle_source",
            "label": "Bare Ni foam water contact angle 110°",
            "href": "https://www.sciencedirect.com/science/article/pii/S1002007122001083",
        },
        {
            "id": "pp_angle_source",
            "label": "Untreated PP mesh water contact angle 105.8°",
            "href": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5393001/",
        },
        {
            "id": "detachment_limit_source",
            "label": "Bubble detachment beyond static Fritz scaling",
            "href": "https://pubs.acs.org/doi/abs/10.1021/acs.langmuir.4c01963",
        },
    ]

    cards = [
        {"id": "card_dv", "dataset": "headline", "sourceId": "decomp_source",
         "description": "pp_040x053, 1000 mA/cm²에서 pristine 대비 모델 전압 절감",
         "metrics": [{"label": "기준 메시 ΔV@1000 (mV)", "field": "ref_dV_1000_mV", "format": "number", "signed": True}]},
        {"id": "card_transfer", "dataset": "headline", "sourceId": "decomp_source",
         "description": "110° Ni foam과 105.8° PP 사이의 접촉각 기반 상한 전달 지수",
         "metrics": [{"label": "접촉각 전달 지수 상한", "field": "ref_transfer_index", "format": "percent"}]},
        {"id": "card_dp", "dataset": "headline", "sourceId": "decomp_source",
         "description": "woven mesh CFD가 아닌 평행 간극 근사 압력강하 비",
         "metrics": [{"label": "ΔP/ΔP₀ 추정", "field": "ref_pressure_drop_ratio", "format": "number"}]},
        {"id": "card_rmse", "dataset": "headline", "sourceId": "summary_source",
         "description": "mesh 데이터가 아니라 pristine 보정점에 대한 모델 오차",
         "metrics": [{"label": "Pristine RMSE (mV)", "field": "pristine_RMSE_mV", "format": "number"}]},
    ]

    charts = [
        {
            "id": "catalog_chart",
            "title": "장착 가능한 PP mesh별 전압 절감",
            "subtitle": "전압만 보면 촘촘한 메시가 커 보이지만, ΔP 추정과 조립 여유를 함께 봐야 한다.",
            "intent": "comparison",
            "type": "bar",
            "dataset": "catalog",
            "sourceId": "summary_source",
            "encodings": {
                "x": {"field": "mesh_label", "type": "nominal", "label": "PP mesh", "aggregate": "none"},
                "y": {"field": "dV_1000_mV", "type": "quantitative", "label": "ΔV@1000", "unit": "mV", "aggregate": "none"},
                "tooltip": [
                    {"field": "pressure_drop_ratio_est", "type": "quantitative", "label": "ΔP/ΔP₀ 추정"},
                    {"field": "clearance_mm", "type": "quantitative", "label": "채널 여유", "unit": "mm"},
                    {"field": "transfer_index_upper", "type": "quantitative", "label": "전달 지수 상한", "format": "percent"},
                ],
            },
            "layout": "full",
            "valueFormat": "number",
            "unit": "mV",
            "settings": {"orientation": "horizontal", "sort": "descending", "showValues": True},
            "palette": {"kind": "sequential", "name": "blue"},
        },
        {
            "id": "pore_chart",
            "title": "구멍 크기별 전압 절감과 전극 접촉각 가정",
            "subtitle": "일반 Ni foam 110°에서는 구멍 크기 효과가 사라지고, 전극이 더 친수성일 때만 작은 구멍의 전달 상한이 커진다.",
            "intent": "comparison",
            "type": "bar",
            "dataset": "pore_cases",
            "sourceId": "summary_source",
            "encodings": {
                "x": {"field": "hole_label", "type": "ordinal", "label": "구멍 크기", "unit": "mm", "aggregate": "none"},
                "y": {"field": "dV_1000_mV", "type": "quantitative", "label": "ΔV@1000", "unit": "mV", "aggregate": "none"},
                "color": {"field": "electrode_case", "type": "nominal", "label": "전극 가정", "aggregate": "none"},
                "tooltip": [
                    {"field": "contact_probability_upper", "type": "quantitative", "label": "접촉 확률 상한", "format": "percent"},
                    {"field": "wetting_drive", "type": "quantitative", "label": "젖음성 구동력", "format": "percent"},
                    {"field": "transfer_index_upper", "type": "quantitative", "label": "전달 지수 상한", "format": "percent"},
                ],
            },
            "layout": "full",
            "valueFormat": "number",
            "unit": "mV",
            "settings": {"groupMode": "grouped", "orientation": "vertical", "showValues": False},
            "legend": {"position": "bottom", "title": "전극 접촉각"},
            "palette": {"kind": "categorical", "name": "default"},
        },
    ]

    tables = [
        {
            "id": "catalog_table",
            "title": "PP mesh 후보: 성능과 물리 guardrail",
            "subtitle": "ΔP/ΔP₀≤3, 채널 여유≥0.10 mm를 보고서의 보수적 선별 기준으로 표시했다.",
            "dataset": "catalog",
            "sourceId": "summary_source",
            "defaultSort": {"field": "dV_1000_mV", "direction": "desc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "mesh_id", "label": "mesh", "type": "text"},
                {"field": "hole_mm", "label": "구멍 mm", "format": "number"},
                {"field": "open_fraction", "label": "개구율", "format": "percent"},
                {"field": "thickness_mm", "label": "두께 mm", "format": "number"},
                {"field": "clearance_mm", "label": "채널 여유 mm", "format": "number"},
                {"field": "dV_1000_mV", "label": "ΔV@1000 mV", "format": "number", "movement": True},
                {"field": "pressure_drop_ratio_est", "label": "ΔP/ΔP₀ 추정", "format": "number"},
                {"field": "hydraulic_guardrail", "label": "유압", "type": "text"},
                {"field": "assembly_guardrail", "label": "조립", "type": "text"},
            ],
        },
        {
            "id": "angle_table",
            "title": "전극 × PP 접촉각 민감도",
            "subtitle": "정적 물 접촉각을 이용한 상한 민감도이며, 실제 운전 중 동적 접촉각·히스테리시스는 포함하지 않는다.",
            "dataset": "contact_angles",
            "sourceId": "summary_source",
            "defaultSort": {"field": "electrode_angle_deg", "direction": "asc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "electrode_angle_deg", "label": "전극 θe (°)", "format": "number"},
                {"field": "mesh_angle_deg", "label": "mesh θm (°)", "format": "number"},
                {"field": "contact_probability_upper", "label": "접촉확률 상한", "format": "percent"},
                {"field": "wetting_drive", "label": "젖음성 구동력", "format": "percent"},
                {"field": "transfer_index_upper", "label": "전달 지수 상한", "format": "percent"},
                {"field": "dV_1000_mV", "label": "ΔV@1000 mV", "format": "number", "movement": True},
            ],
        },
    ]

    blocks = [
        {"id": "title", "type": "markdown", "layout": "full", "body": f"# {TITLE}"},
        {"id": "summary", "type": "markdown", "layout": "full", "body": (
            "## 결론\n\n"
            f"기본값은 **bare Ni foam 물 접촉각 110°**, **untreated PP mesh 105.8°**로 바꿨다. "
            "이 조합에서는 PP가 전극보다 더 소수성이 아니므로 Young 식 기반 기포 전달 구동력이 **0**이다. "
            f"따라서 기준 pp_040x053의 **{d1000['net_mV']:.1f} mV 절감**은 접촉각 포획이 아니라 "
            "메시 고체 체적에 따른 국소 유속 증가·기체 체류시간 감소에서 나온 모델 결과다. "
            "이 결과는 mesh 분극 데이터로 검증된 값이 아니므로 **제한부 사용 가능(share with caveats)** 상태다."
        )},
        {"id": "metrics", "type": "metric-strip", "layout": "full", "cardIds": ["card_dv", "card_transfer", "card_dp", "card_rmse"]},
        {"id": "evidence", "type": "markdown", "layout": "full", "body": (
            "## 무엇을 근거로 바꿨나\n\n"
            "- 문헌 입력: bare Ni foam의 정적 물 접촉각 **110°**, untreated PP mesh의 정적 물 접촉각 **105.8°**.\n"
            "- 모델 직접 계산: 이 두 값에서는 `cos(θe)−cos(θm)<0`이므로 접촉각 전달 구동력은 0.\n"
            "- 해석: 일반 Ni foam 기준에서는 ‘PP가 기포를 끌어당겨 떼어낸다’고 단정할 수 없다.\n"
            "- 남은 효과: 유로 내 고체 체적비로부터 얻은 체류시간 변화. 단, 실제 woven mesh 압력손실은 permeability/CFD가 필요하다.\n\n"
            "문헌: [Ni foam 110°](https://www.sciencedirect.com/science/article/pii/S1002007122001083), "
            "[PP mesh 105.8°](https://pmc.ncbi.nlm.nih.gov/articles/PMC5393001/)."
        )},
        {"id": "catalog_heading", "type": "markdown", "layout": "full", "body": (
            "## 후보 mesh 비교\n\n"
            f"전압만 보면 가장 촘촘한 pp_015x015가 {cat[0]['dV@1000_mV']:.1f} mV로 가장 크지만, "
            f"ΔP 추정이 {cat[0]['mesh_dp_ratio']:.1f}배여서 설계 후보로 쓰기 어렵다. "
            f"**{robust['id']}**는 ΔP {robust['mesh_dp_ratio']:.2f}배, 채널 여유 {0.9-robust['t_mm']:.3f} mm이고 "
            "작은 구멍 덕분에 전극 접촉각이 달라지는 경우에도 비교적 강건한 1차 실험 후보로 본다."
        )},
        {"id": "catalog_chart_block", "type": "chart", "layout": "full", "chartId": "catalog_chart"},
        {"id": "catalog_table_block", "type": "table", "layout": "full", "tableId": "catalog_table"},
        {"id": "angle_heading", "type": "markdown", "layout": "full", "body": (
            "## 접촉각과 구멍 크기의 관계\n\n"
            "`L_ref=2 mm` 같은 문턱은 삭제했다. 기포 직경과 직사각형 개구의 실제 치수로 접촉 가능 영역을 계산한다. "
            "다만 이는 mesh가 전극에 거의 붙어 있다는 **zero-standoff 상한**이다. 일반 Ni foam 110°에서는 젖음성 구동력이 0이라 "
            "구멍을 더 작게 해도 전압 이득이 늘지 않는다. 전극이 60°처럼 더 친수성일 때에만 작은 구멍의 기하 접촉 상한이 전압에 반영된다."
        )},
        {"id": "pore_chart_block", "type": "chart", "layout": "full", "chartId": "pore_chart"},
        {"id": "angle_table_block", "type": "table", "layout": "full", "tableId": "angle_table"},
        {"id": "method", "type": "markdown", "layout": "full", "body": (
            "## 수정한 식\n\n"
            "1. 기포 직경 `d_b`: 기존 bubble force-balance의 이탈 직경을 운전 전류와 벽면 유속으로 계산.\n"
            "2. 접촉확률 상한 `P_contact,UB = 1 − φ·max(1−d_b/Lx,0)·max(1−d_b/Ly,0)`.\n"
            "3. 젖음성 구동력 `P_wet = max[0,(cosθe−cosθm)/(1+cosθe)]`.\n"
            "4. 전달 지수 상한 `P_transfer,UB = P_contact,UB·P_wet`; 피복 진폭은 상한 민감도에서 `1−P_transfer,UB`를 곱함.\n"
            "5. 고체 체적비 `χ=(1−φ)t_m/d_ch`; `u/u₀=1/(1−χ)`, `τ/τ₀=1−χ`, 평행 간극 근사 `ΔP/ΔP₀≈[1/(1−χ)]³`.\n"
            "6. 촉매 차단 손실: χ에서 추정하지 않음. 간격·압착·측면 액 접근이 없으므로 전압식에 0으로 두고 미모델링 위험으로 남김.\n\n"
            "삭제한 항: `wick`, `L_ref=2 mm`, `C_theta=0.6`, `C_ret=0.5`, `C_block=0.3`."
        )},
        {"id": "limitations", "type": "markdown", "layout": "full", "body": (
            "## 한계와 검증 상태\n\n"
            "- 110°와 105.8°는 서로 다른 논문의 정적 물 접촉각이며, 실제 KOH·65 °C·전위 인가 상태의 동적 값이 아니다.\n"
            "- 거친 다공성 표면에서는 sessile-drop 각도와 수중 bubble contact angle이 다를 수 있다.\n"
            "- 접촉각 히스테리시스와 contact-line pinning은 bubble departure를 크게 바꿀 수 있으므로 정적 Fritz 계열 계산만으로 완전하지 않다. "
            "[관련 검토](https://pubs.acs.org/doi/abs/10.1021/acs.langmuir.4c01963).\n"
            "- `P_transfer,UB`는 kinetics가 검증된 효율이 아니라 thermodynamic/geometric 상한 지수다.\n"
            "- 압력강하 비는 woven-mesh Darcy–Forchheimer 모델이 아니라 평행 간극 추정이다.\n"
            "- mesh 실측 분극곡선으로 보정하거나 외부 검증하지 않았으므로 절대 mV는 설계 방향 탐색용이다."
        )},
        {"id": "next", "type": "markdown", "layout": "full", "body": (
            "## 다음 실험\n\n"
            f"1차 후보는 **{robust['id']}**와 기준 **{ref['id']}** 두 개로 좁힌다. 같은 셀에서 "
            "(a) KOH·65 °C 상태의 전극/PP 수중 advancing–receding contact angle, "
            "(b) mesh 전후 압력강하, (c) 500/1000/2000 mA cm⁻² 전압을 함께 측정한다. "
            "그 세 데이터가 들어오면 현재 상한 지수와 hydraulic estimate를 실제 transfer time constant와 permeability로 교체할 수 있다."
        )},
    ]

    manifest = {
        "version": 1,
        "surface": "report",
        "title": TITLE,
        "description": "Nickel foam/PP mesh contact-angle model correction, rerun results, engineering guardrails and validation plan.",
        "generatedAt": generated,
        "cards": cards,
        "charts": charts,
        "tables": tables,
        "sources": sources,
        "blocks": blocks,
    }
    snapshot = {
        "version": 1,
        "generatedAt": generated,
        "status": "ready",
        "datasets": {
            "headline": headline,
            "catalog": catalog_rows,
            "pore_cases": pore_rows,
            "contact_angles": angle_rows,
        },
    }
    return {"surface": "report", "manifest": manifest, "snapshot": snapshot, "sources": sources}


def main():
    artifact = build()
    ARTIFACT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(ARTIFACT)


if __name__ == "__main__":
    main()
