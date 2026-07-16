# -*- coding: utf-8 -*-
"""Render Figure 3 with an explicit catalyst-blocking assumption.

Scenario:
  * reference mesh pp_040x053, full-path coverage;
  * zero standoff / full strand contact;
  * catalyst active-area blocking B = 1 - mesh open fraction;
  * the surviving bubble-free active fraction is multiplied by (1 - B);
  * the extra cathode activation voltage is evaluated with the simulator's
    Butler-Volmer inversion at 1000 mA/cm2.

This is a conservative scenario figure, not a calibrated prediction.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "out"
FIG = OUT / "v2_figs" / "fig_03_blocking50.png"
DATA = OUT / "fig_03_blocking50.json"
FONT = Path(r"C:\Windows\Fonts\malgun.ttf")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))

import mesh_study as ms
from bubblesim import Simulator
from bubblesim.solvers.zerod import _invert_bv


def calculate():
    decomp = json.loads((OUT / "decomp.json").read_text(encoding="utf-8"))
    d = decomp["decomp"]["1000"]

    raw = dict(ms.D0)
    raw["mesh_id"] = ""
    op = ms._apply_mesh(ms.sweep_operating(raw, 1000), ms.REF_MESH)
    sim = Simulator(op=op, params=ms.build_params(ms.D0))
    context = sim.props()

    block_fraction = 1.0 - float(ms.REF_MESH["open"])
    theta_mesh = float(d["theta_mesh"])
    active_before = 1.0 - theta_mesh
    active_after = active_before * (1.0 - block_fraction)
    theta_effective = 1.0 - active_after

    j = float(op.j_set)
    j0 = float(context["j0_cathode"])
    alpha_a = float(context["alpha_a_cathode"])
    alpha_c = float(context["alpha_c_cathode"])
    temperature = float(op.T)

    eta_before = _invert_bv(
        j / active_before, j0, alpha_c, alpha_a, temperature, n=80
    )
    eta_after = _invert_bv(
        j / active_after, j0, alpha_c, alpha_a, temperature, n=80
    )
    blocking_penalty = (eta_after - eta_before) * 1000.0

    pristine = float(d["V_pristine"])
    contact_saving = float(d["steps_mV"]["접촉·젖음성 포획"])
    residence_saving = float(d["steps_mV"]["유로 폐색에 따른 체류시간 감소"])
    mesh_no_block = float(d["V_full"])
    mesh_with_block = mesh_no_block + blocking_penalty
    net_saving = pristine - mesh_with_block

    result = {
        "scenario": "zero-standoff full-strand contact",
        "mesh_id": "pp_040x053",
        "current_density_mA_cm2": 1000,
        "blocking_fraction": block_fraction,
        "theta_mesh_bubble_only": theta_mesh,
        "active_fraction_before_blocking": active_before,
        "active_fraction_after_blocking": active_after,
        "effective_total_coverage": theta_effective,
        "contact_angle_saving_mV": contact_saving,
        "residence_saving_mV": residence_saving,
        "blocking_penalty_mV": blocking_penalty,
        "pristine_voltage_mV": pristine,
        "mesh_no_block_voltage_mV": mesh_no_block,
        "mesh_with_block_voltage_mV": mesh_with_block,
        "net_saving_mV": net_saving,
    }
    DATA.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def render(r):
    font_manager.fontManager.addfont(str(FONT))
    family = font_manager.FontProperties(fname=str(FONT)).get_name()
    plt.rcParams.update({
        "font.family": family,
        "font.size": 10.5,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.edgecolor": "#94a0b4",
        "axes.grid": True,
        "grid.color": "#e4eaf2",
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "axes.unicode_minus": False,
    })

    pristine = r["pristine_voltage_mV"]
    contact = r["contact_angle_saving_mV"]
    residence = r["residence_saving_mV"]
    penalty = r["blocking_penalty_mV"]
    after_contact = pristine - contact
    after_residence = r["mesh_no_block_voltage_mV"]
    final = r["mesh_with_block_voltage_mV"]

    labels = [
        "Pristine",
        "접촉각 전달",
        "체류시간 감소",
        "촉매 차단\n50% 가정",
        "+ Mesh\n(차단 포함)",
    ]
    fig, ax = plt.subplots(figsize=(10.2, 5.4))

    ax.bar(0, pristine, width=0.62, color="#c5ceda", edgecolor="#667085")
    ax.text(0, pristine + 6, f"{pristine:.1f}", ha="center", fontweight="bold")

    ax.bar(1, 0.8, bottom=after_contact - 0.4, width=0.62,
           color="#d9dee7", edgecolor="#667085")
    ax.text(1, after_contact + 6, f"{-contact:.1f}", ha="center",
            color="#b8c1d0", fontweight="bold")

    ax.bar(2, after_contact - after_residence, bottom=after_residence, width=0.62,
           color="#118765", edgecolor="#667085")
    ax.text(2, after_contact + 6, f"-{residence:.1f}", ha="center",
            color="#07805e", fontweight="bold")

    ax.bar(3, penalty, bottom=after_residence, width=0.62,
           color="#d94b55", edgecolor="#667085")
    ax.text(3, final + 6, f"+{penalty:.1f}", ha="center",
            color="#c83545", fontweight="bold")

    ax.bar(4, final, width=0.62, color="#246cda", edgecolor="#667085")
    ax.text(4, final + 6, f"{final:.1f}", ha="center",
            color="#1769e0", fontweight="bold")

    levels = [pristine, after_contact, after_residence, final]
    for i, level in enumerate(levels):
        ax.plot([i + 0.31, i + 0.69], [level, level],
                color="#7b879b", linestyle=":", linewidth=1.1)

    ax.set_xticks(range(5), labels)
    ax.set_ylabel("셀 전압 [mV]")
    ax.set_ylim(1880, 2075)
    ax.set_title("1000 mA/cm² 전압 워터폴: 촉매 활성면적 50% 차단 가정")
    ax.grid(axis="x", visible=False)

    assumption = (
        "보수적 가정: 메시가 전극에 완전히 밀착하고, "
        "고체 면적분율 1-φ=0.50만큼 활성면적을 차단"
    )
    result = (
        f"유동 이득 {residence:.1f} mV - 차단 손실 {penalty:.1f} mV "
        f"= 순절감 {r['net_saving_mV']:.1f} mV"
    )
    ax.text(
        0.01, 0.97, assumption + "\n" + result,
        transform=ax.transAxes, ha="left", va="top", fontsize=9.2,
        bbox=dict(boxstyle="round,pad=0.45", facecolor="#fff7e8",
                  edgecolor="#d7a338", linewidth=1.0),
    )
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG, dpi=220, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)


def main():
    result = calculate()
    render(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(FIG)


if __name__ == "__main__":
    main()
