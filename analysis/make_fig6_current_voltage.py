# -*- coding: utf-8 -*-
"""Plot along-path current redistribution and a local voltage diagnostic.

Panel A is the actual j(s) returned by the common-potential channel solve.
Panel B is not a second local cell voltage: it is the voltage that each path
point would require if that point alone were forced to carry 1000 mA/cm2 at
its local theta/epsilon state.  Horizontal lines show the actual common cell
voltage for each case.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "out"
FIG = OUT / "v2_figs" / "fig_06_current_voltage.png"
CSV = OUT / "fig_06_current_voltage.csv"
META = OUT / "fig_06_current_voltage.json"
FONT = Path(r"C:\Windows\Fonts\malgun.ttf")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))

import mesh_study as ms
from bubblesim import Simulator
from bubblesim.solvers.channel import EPS_FILM, _Stub
from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver


def local_required_voltage(op, context, theta, eps):
    """Hypothetical V needed for local j=1000 mA/cm2 at local gas state."""
    solver = ZeroDTwoElectrodeSolver(n_outer=60, n_inner=60)
    values = []
    for th, ep in zip(theta, eps):
        # This mirrors channel.py's threshold-excess void mapping, but applies
        # it pointwise for the diagnostic instead of using the path mean.
        ep_ohm = op.void_ohmic_frac * np.clip(
            (ep - EPS_FILM) / (1.0 - EPS_FILM), 0.0, 1.0
        )
        state = solver.solve(op, context, [_Stub(float(th), float(ep_ohm))])
        values.append(float(state.V) * 1000.0)
    return np.asarray(values)


def calculate():
    decomp = json.loads((OUT / "decomp.json").read_text(encoding="utf-8"))
    profiles = decomp["profiles_1000"]
    d1000 = decomp["decomp"]["1000"]

    raw = dict(ms.D0)
    raw["mesh_id"] = ""
    op = ms._apply_mesh(ms.sweep_operating(raw, 1000), ms.REF_MESH)
    sim = Simulator(op=op, params=ms.build_params(ms.D0))
    context = sim.props()

    s = np.asarray(profiles["pristine"]["s"], dtype=float)
    theta_p = np.asarray(profiles["pristine"]["theta"], dtype=float)
    eps_p = np.asarray(profiles["pristine"]["eps"], dtype=float)
    j_p = np.asarray(profiles["pristine"]["j"], dtype=float) / 10.0

    theta_m = np.asarray(profiles["mesh"]["theta"], dtype=float)
    eps_m = np.asarray(profiles["mesh"]["eps"], dtype=float)
    j_m = np.asarray(profiles["mesh"]["j"], dtype=float) / 10.0

    vreq_p = local_required_voltage(op, context, theta_p, eps_p)
    vreq_m = local_required_voltage(op, context, theta_m, eps_m)
    vcommon_p = float(d1000["V_pristine"])
    vcommon_m = float(d1000["V_full"])

    with CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "s_0inlet_1outlet",
            "theta_pristine", "eps_pristine", "j_pristine_mAcm2",
            "Vreq_pristine_at1000_mV", "Vcommon_pristine_mV",
            "theta_mesh", "eps_mesh", "j_mesh_mAcm2",
            "Vreq_mesh_at1000_mV", "Vcommon_mesh_mV",
        ])
        for i in range(len(s)):
            writer.writerow([
                f"{s[i]:.4f}", f"{theta_p[i]:.4f}", f"{eps_p[i]:.4f}",
                f"{j_p[i]:.2f}", f"{vreq_p[i]:.2f}", f"{vcommon_p:.2f}",
                f"{theta_m[i]:.4f}", f"{eps_m[i]:.4f}", f"{j_m[i]:.2f}",
                f"{vreq_m[i]:.2f}", f"{vcommon_m:.2f}",
            ])

    summary = {
        "operating_mean_current_mA_cm2": 1000.0,
        "common_cell_voltage_mV": {"pristine": vcommon_p, "mesh": vcommon_m},
        "local_current_mA_cm2": {
            "pristine": {"inlet": float(j_p[0]), "outlet": float(j_p[-1]),
                           "min": float(j_p.min()), "max": float(j_p.max())},
            "mesh": {"inlet": float(j_m[0]), "outlet": float(j_m[-1]),
                      "min": float(j_m.min()), "max": float(j_m.max())},
        },
        "hypothetical_Vreq_at_local_1000_mV": {
            "pristine": {"inlet": float(vreq_p[0]), "outlet": float(vreq_p[-1]),
                           "min": float(vreq_p.min()), "max": float(vreq_p.max())},
            "mesh": {"inlet": float(vreq_m[0]), "outlet": float(vreq_m[-1]),
                      "min": float(vreq_m.min()), "max": float(vreq_m.max())},
        },
        "note": "Vreq is a diagnostic at forced local 1000 mA/cm2, not a physical local cell-voltage measurement.",
    }
    META.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return s, j_p, j_m, vreq_p, vreq_m, vcommon_p, vcommon_m, summary


def render(data):
    s, j_p, j_m, vreq_p, vreq_m, vcommon_p, vcommon_m, summary = data
    font_manager.fontManager.addfont(str(FONT))
    family = font_manager.FontProperties(fname=str(FONT)).get_name()
    plt.rcParams.update({
        "font.family": family,
        "font.size": 10.5,
        "axes.titlesize": 12.5,
        "axes.titleweight": "bold",
        "axes.edgecolor": "#94a0b4",
        "axes.grid": True,
        "grid.color": "#e4eaf2",
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "axes.unicode_minus": False,
    })

    grey = "#7b879b"
    blue = "#1769e0"
    green = "#0b8365"
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.2, 4.8))

    a1.plot(s, j_p, color=grey, lw=2.3, label="Pristine 실제 j(s)")
    a1.plot(s, j_m, color=blue, lw=2.3, label="+ Mesh 실제 j(s)")
    a1.axhline(1000, color=green, ls="--", lw=1.4, label="설정·평균 1000")
    a1.scatter([s[0], s[-1]], [j_p[0], j_p[-1]], color=grey, s=26, zorder=3)
    a1.scatter([s[0], s[-1]], [j_m[0], j_m[-1]], color=blue, s=26, zorder=3)
    a1.annotate(f"{j_p[0]:.0f}", (s[0], j_p[0]), xytext=(7, -4), textcoords="offset points", color=grey)
    a1.annotate(f"{j_p[-1]:.0f}", (s[-1], j_p[-1]), xytext=(-34, -17), textcoords="offset points", color=grey)
    a1.annotate(f"{j_m[0]:.0f}", (s[0], j_m[0]), xytext=(7, -16), textcoords="offset points", color=blue)
    a1.annotate(f"{j_m[-1]:.0f}", (s[-1], j_m[-1]), xytext=(-34, 7), textcoords="offset points", color=blue)
    a1.set_xlabel("유로 위치 s (0=입구, 1=출구)")
    a1.set_ylabel("국소 전류밀도 j(s) [mA/cm²]")
    a1.set_title("같은 셀 전압에서 실제로 분배되는 전류")
    a1.legend(frameon=False, fontsize=8.5)

    a2.plot(s, vreq_p, color=grey, lw=2.3, label="Pristine: 국소 1000 요구전압")
    a2.plot(s, vreq_m, color=blue, lw=2.3, label="+ Mesh: 국소 1000 요구전압")
    a2.axhline(vcommon_p, color=grey, ls=":", lw=1.6,
               label=f"Pristine 공통전압 {vcommon_p:.1f} mV")
    a2.axhline(vcommon_m, color=blue, ls=":", lw=1.6,
               label=f"Mesh 공통전압 {vcommon_m:.1f} mV")
    a2.set_xlabel("유로 위치 s (0=입구, 1=출구)")
    a2.set_ylabel("1000 mA/cm² 요구전압 [mV]")
    a2.set_title("각 구간에 1000을 강제로 흘릴 때 필요한 전압")
    a2.legend(frameon=False, fontsize=7.8, loc="upper left")

    fig.suptitle(
        "1000 mA/cm² 운전점의 유로별 전류 분포와 국소 전압 진단",
        fontsize=15, fontweight="bold", color="#14213d",
    )
    fig.text(
        0.5, -0.01,
        "주의: 실제 셀 전압은 위치별로 달라지지 않고 하나다. 오른쪽 곡선은 각 위치를 단독으로 1000 mA/cm²에 고정했을 때의 진단값이다.",
        ha="center", fontsize=8.8, color="#59677d",
    )
    fig.tight_layout(rect=[0, 0.04, 1, 0.93])
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG, dpi=220, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)


def main():
    data = calculate()
    render(data)
    print(json.dumps(data[-1], ensure_ascii=False, indent=2))
    print(FIG)


if __name__ == "__main__":
    main()
