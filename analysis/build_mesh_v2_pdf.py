# -*- coding: utf-8 -*-
"""Generate the Korean mesh-model v2 report with Figures 1-16.

The report is rebuilt from analysis/out/summary.json, decomp.json and the
latest CSV outputs.  It intentionally does not use the retired wick/L_ref/
C_theta heuristic.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "out"
FIG = OUT / "v2_figs"
PDF = OUT / "mesh_study_report_v2.pdf"
FONT_REG = Path(r"C:\Windows\Fonts\malgun.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\malgunbd.ttf")

BLUE = "#1769e0"
NAVY = "#14213d"
GREEN = "#0b8365"
RED = "#c83545"
GOLD = "#c98a1a"
PURPLE = "#7657d6"
MUTED = "#7b879b"
LIGHT = "#eef4ff"
GRID = "#e4eaf2"

MEASURED = np.array([
    [10, 1.48294], [20, 1.49370], [50, 1.51840], [100, 1.55191],
    [200, 1.60495], [300, 1.65078], [400, 1.69504], [500, 1.74178],
    [625, 1.80051], [750, 1.86602], [875, 1.94376], [1000, 2.03323],
    [1250, 2.20449], [1500, 2.37841], [2000, 2.66160], [2250, 2.78376],
])


def load_json(name: str):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


S = load_json("summary.json")
D = load_json("decomp.json")
J = np.asarray(S["sweep_j"], dtype=float)


def read_wide_csv(name: str):
    with (OUT / name).open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows


def setup_plot():
    from matplotlib import font_manager

    font_manager.fontManager.addfont(str(FONT_REG))
    family = font_manager.FontProperties(fname=str(FONT_REG)).get_name()
    plt.rcParams.update({
        "font.family": family,
        "font.size": 10.2,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.labelsize": 10,
        "axes.edgecolor": "#94a0b4",
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "axes.unicode_minus": False,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
    })


def save(fig, number: int):
    FIG.mkdir(parents=True, exist_ok=True)
    path = FIG / f"fig_{number:02d}.png"
    fig.savefig(path, dpi=220, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return path


def fig01_model_map():
    fig, ax = plt.subplots(figsize=(10.2, 5.2))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")
    box = dict(boxstyle="round,pad=0.55", linewidth=1.4)
    ax.text(1.5, 4.7, "폐기한 v1 경험식\n\nwick, Lref=2 mm\nCθ=0.6, Cret=0.5\nCblock=0.3",
            ha="center", va="center", color=RED,
            bbox={**box, "edgecolor": RED, "facecolor": "#fff0f2"})
    ax.text(4.9, 4.7, "직접 입력 또는 계산\n\n개구율 φ, 두께 tm\n구멍 Lx·Ly, 채널 깊이 dch\nθe, θm, 기포 직경 db",
            ha="center", va="center", color=NAVY,
            bbox={**box, "edgecolor": BLUE, "facecolor": LIGHT})
    ax.text(8.4, 4.7, "v2 전달 상한\n\nPcontact,UB\nPwet\nPtransfer,UB",
            ha="center", va="center", color=GREEN,
            bbox={**box, "edgecolor": GREEN, "facecolor": "#eefaf6"})
    ax.text(4.9, 1.5, "유동 폐색 경로\n\nχ=(1-φ)tm/dch\nu/u0=1/(1-χ)\nτ/τ0=1-χ",
            ha="center", va="center", color=NAVY,
            bbox={**box, "edgecolor": GOLD, "facecolor": "#fff8e8"})
    ax.text(8.4, 1.5, "보고 출력\n\n전압 변화 ΔV\n기포 피복률 θ(s), 홀드업 ε(s)\n압력강하 근사 ΔP/ΔP0",
            ha="center", va="center", color=NAVY,
            bbox={**box, "edgecolor": PURPLE, "facecolor": "#f5f1ff"})
    ax.annotate("", xy=(3.6, 4.7), xytext=(2.75, 4.7), arrowprops=dict(arrowstyle="-|>", color=MUTED, lw=1.7))
    ax.text(3.18, 5.02, "교체", ha="center", color=MUTED, fontsize=9)
    ax.annotate("", xy=(7.05, 4.7), xytext=(6.25, 4.7), arrowprops=dict(arrowstyle="-|>", color=BLUE, lw=1.7))
    ax.annotate("", xy=(4.9, 2.62), xytext=(4.9, 3.55), arrowprops=dict(arrowstyle="-|>", color=GOLD, lw=1.7))
    ax.annotate("", xy=(7.05, 1.5), xytext=(6.25, 1.5), arrowprops=dict(arrowstyle="-|>", color=PURPLE, lw=1.7))
    ax.annotate("", xy=(8.4, 2.62), xytext=(8.4, 3.55), arrowprops=dict(arrowstyle="-|>", color=GREEN, lw=1.7))
    ax.set_title("Mesh 모델 v2: 임의 기준 길이를 없애고 측정 가능한 양으로 분리", color=NAVY, pad=10)
    return save(fig, 1)


def fig02_geometry():
    f = D["factors"]
    lx, ly, db = f["hole_x_mm"], f["hole_y_mm"], f["bubble_d_mm"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.2, 4.7))
    a1.set_aspect("equal")
    a1.add_patch(Rectangle((0, 0), lx, ly, facecolor="#eef6ff", edgecolor=BLUE, lw=2))
    a1.add_patch(Circle((lx / 2, ly / 2), db / 2, facecolor="#b9ddff", edgecolor=BLUE, lw=1.5, alpha=0.9))
    a1.annotate("", xy=(0, -0.12), xytext=(lx, -0.12), arrowprops=dict(arrowstyle="<->", color=NAVY))
    a1.text(lx / 2, -0.23, f"Lx = {lx:.3f} mm", ha="center")
    a1.annotate("", xy=(lx + 0.12, 0), xytext=(lx + 0.12, ly), arrowprops=dict(arrowstyle="<->", color=NAVY))
    a1.text(lx + 0.23, ly / 2, f"Ly = {ly:.3f} mm", va="center", rotation=90)
    a1.text(lx / 2, ly / 2, f"db\n{db:.3f} mm", ha="center", va="center", color=NAVY, fontsize=9)
    a1.set_xlim(-0.18, lx + 0.36)
    a1.set_ylim(-0.32, ly + 0.12)
    a1.axis("off")
    a1.set_title("직사각형 개구와 기포의 투영")
    a2.axis("off")
    eq = (
        "Pcontact,UB = 1 - φ·max(1-db/Lx,0)·max(1-db/Ly,0)\n\n"
        "Pwet = max[0, (cosθe - cosθm)/(1 + cosθe)]\n\n"
        "Ptransfer,UB = Pcontact,UB × Pwet"
    )
    a2.text(0.03, 0.78, eq, transform=a2.transAxes, ha="left", va="top", fontsize=12,
            bbox=dict(boxstyle="round,pad=0.6", fc=LIGHT, ec=BLUE, lw=1.2))
    a2.text(0.03, 0.30,
            f"기준 PP 메시: Pcontact,UB={f['contact_prob']:.3f}\n"
            f"θe={f['electrode_angle_deg']:.1f}°, θm={f['mesh_angle_deg']:.1f}° → Pwet={f['wetting_drive']:.3f}\n"
            f"따라서 Ptransfer,UB={f['capture_eff']:.3f}",
            transform=a2.transAxes, ha="left", va="top", fontsize=11,
            bbox=dict(boxstyle="round,pad=0.55", fc="#eefaf6", ec=GREEN, lw=1.2))
    fig.suptitle("접촉 가능성과 젖음성 구동력을 분리한 v2 식", color=NAVY, fontsize=14, fontweight="bold")
    fig.tight_layout()
    return save(fig, 2)


def fig03_waterfall():
    d = D["decomp"]["1000"]
    transfer = d["steps_mV"]["접촉·젖음성 포획"]
    residence = d["steps_mV"]["유로 폐색에 따른 체류시간 감소"]
    block = d["steps_mV"]["촉매 접촉·압착 차단 (미모델링)"]
    v0 = d["V_pristine"]
    labels = ["Pristine", "접촉각 전달", "체류시간 감소", "촉매 차단\n미모델링", "+ Mesh"]
    contributions = [transfer, residence, block]
    fig, ax = plt.subplots(figsize=(9.3, 4.6))
    ax.bar(0, v0, width=0.62, color="#c8d0dc", edgecolor="#667085")
    running = v0
    for i, dv in enumerate(contributions, 1):
        bottom = running - dv if dv >= 0 else running
        color = GREEN if dv > 0 else (RED if dv < 0 else "#d5dae3")
        ax.bar(i, abs(dv) if abs(dv) > 0.8 else 0.8, bottom=bottom, width=0.62, color=color, edgecolor="#667085")
        ax.text(i, bottom + max(abs(dv), 0.8) + 5, f"-{dv:.1f}" if dv > 0 else f"{dv:.1f}", ha="center", color=color, fontweight="bold")
        ax.plot([i - 0.69, i - 0.31], [running, running], color=MUTED, ls=":", lw=1)
        running -= dv
    ax.bar(4, running, width=0.62, color=BLUE, edgecolor="#667085")
    ax.text(0, v0 + 7, f"{v0:.1f}", ha="center", fontweight="bold")
    ax.text(4, running + 7, f"{running:.1f}", ha="center", color=BLUE, fontweight="bold")
    ax.set_xticks(range(5), labels)
    ax.set_ylabel("셀 전압 [mV]")
    ax.set_ylim(1880, 2070)
    ax.set_title("1000 mA/cm² 전압 워터폴: 70.7 mV가 어디서 나왔나")
    ax.grid(axis="x", visible=False)
    return save(fig, 3)


def fig04_contribution_current():
    js = [500, 1000, 2000]
    keys = ["접촉·젖음성 포획", "유로 폐색에 따른 체류시간 감소", "촉매 접촉·압착 차단 (미모델링)"]
    labels = ["접촉각 전달", "체류시간 감소", "촉매 차단(미모델링)"]
    cols = [BLUE, GREEN, RED]
    x = np.arange(len(js))
    fig, ax = plt.subplots(figsize=(9.0, 4.6))
    for k, (key, label, color) in enumerate(zip(keys, labels, cols)):
        vals = [D["decomp"][str(j)]["steps_mV"][key] for j in js]
        ax.bar(x + (k - 1) * 0.24, vals, 0.24, label=label, color=color, edgecolor="#667085", linewidth=0.5)
        for xx, yy in zip(x + (k - 1) * 0.24, vals):
            if abs(yy) > 0.3:
                ax.text(xx, yy + 4, f"{yy:.1f}", ha="center", fontsize=8)
    ax.set_xticks(x, [f"{j}" for j in js])
    ax.set_xlabel("전류밀도 [mA/cm²]")
    ax.set_ylabel("전압 절감 기여 [mV]")
    ax.set_title("전류가 커질수록 유로 체류시간 항의 기여가 급증")
    ax.legend(frameon=False, ncol=3, loc="upper left")
    return save(fig, 4)


def fig05_overpotential():
    d = D["decomp"]["1000"]
    order = ["E_rev", "eta_act_anode", "eta_act_cathode", "eta_ohmic", "eta_conc", "eta_water"]
    names = ["가역전압", "양극 활성화", "음극 활성화\n+기포 피복", "옴 손실\n+기포 공극", "농도", "수분"]
    cols = ["#c7cfdb", GOLD, "#2f7fb8", "#e7a83e", "#9aa6ba", PURPLE]
    fig, ax = plt.subplots(figsize=(10.0, 4.0))
    for row, (label, terms) in enumerate([("+ Mesh", d["overpot_mesh"]), ("Pristine", d["overpot_pristine"]) ]):
        left = 0.0
        for key, color in zip(order, cols):
            value = terms[key]
            ax.barh(row, value, left=left, color=color, edgecolor="white", linewidth=0.7)
            if value > 45:
                ax.text(left + value / 2, row, f"{value:.0f}", ha="center", va="center", fontsize=8)
            left += value
        ax.text(left + 10, row, f"합계 {left:.1f} mV", va="center", fontweight="bold")
    ax.set_yticks([0, 1], ["+ Mesh", "Pristine"])
    ax.set_xlabel("셀 전압 구성 [mV], 1000 mA/cm²")
    ax.set_title("전압 절감은 음극 기포 피복과 기포 공극 저항 감소로 나타남")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in cols]
    ax.legend(handles, names, frameon=False, ncol=6, fontsize=7.6, loc="lower center", bbox_to_anchor=(0.5, -0.42))
    ax.grid(axis="y", visible=False)
    fig.subplots_adjust(bottom=0.28)
    return save(fig, 5)


def fig06_profiles():
    p = D["profiles_1000"]
    pp, pm = p["pristine"], p["mesh"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.2, 4.2), sharex=True)
    a1.plot(pp["s"], pp["theta"], color=MUTED, lw=2, label="Pristine")
    a1.plot(pm["s"], pm["theta"], color=BLUE, lw=2, label="+ Mesh")
    a1.fill_between(pm["s"], pm["theta"], pp["theta"], color=GREEN, alpha=0.14)
    a1.set_xlabel("유로 위치 (0=입구, 1=출구)")
    a1.set_ylabel("촉매 기포 피복률 θ")
    a1.set_title("촉매 피복률 θ(s)")
    a1.legend(frameon=False)
    a2.plot(pp["s"], pp["eps"], color=MUTED, lw=2, label="Pristine")
    a2.plot(pm["s"], pm["eps"], color=BLUE, lw=2, label="+ Mesh")
    a2.fill_between(pm["s"], pm["eps"], pp["eps"], color=GREEN, alpha=0.14)
    a2.set_xlabel("유로 위치 (0=입구, 1=출구)")
    a2.set_ylabel("기체 홀드업 ε")
    a2.set_title("기체 홀드업 ε(s)")
    a2.legend(frameon=False)
    fig.suptitle("1000 mA/cm²에서 유로를 따라 누적되는 기포", color=NAVY, fontweight="bold", fontsize=14)
    fig.tight_layout()
    return save(fig, 6)


def fig07_calibration():
    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    ax.plot(J, S["pristine"]["V"], color=BLUE, lw=2.2, label="Pristine 모델")
    ax.scatter(MEASURED[:, 0], MEASURED[:, 1], s=38, facecolor="white", edgecolor=RED, linewidth=1.4, label="Pristine 실측")
    ax.set_xlabel("전류밀도 [mA/cm²]")
    ax.set_ylabel("셀 전압 [V]")
    ax.set_title(f"Pristine 보정 곡선: RMSE {S['pristine']['calib_RMSE_mV']:.1f} mV")
    ax.legend(frameon=False)
    return save(fig, 7)


def fig08_catalog_lsv():
    rows = read_wide_csv("lsv_catalog.csv")
    fits = {r["id"]: r["fits"] for r in S["axes"]["catalog"]["table"]}
    fig, ax = plt.subplots(figsize=(9.0, 5.0))
    ax.plot([float(r["j_set_mAcm2"]) for r in rows], [float(r["pristine"]) / 1000 for r in rows], "--", color=MUTED, lw=2, label="Pristine")
    palette = [BLUE, GREEN, GOLD, RED, PURPLE]
    idx = 0
    for key in rows[0]:
        if key in ("j_set_mAcm2", "pristine") or not fits.get(key, False):
            continue
        ax.plot([float(r["j_set_mAcm2"]) for r in rows], [float(r[key]) / 1000 for r in rows], lw=1.8, color=palette[idx % len(palette)], label=key)
        idx += 1
    ax.set_xlabel("전류밀도 [mA/cm²]")
    ax.set_ylabel("셀 전압 [V]")
    ax.set_title("채널에 장착 가능한 PP 메시 후보의 모델 분극곡선")
    ax.legend(frameon=False, fontsize=8.5, ncol=2)
    return save(fig, 8)


def fig09_catalog_screen():
    rows = [r for r in S["axes"]["catalog"]["table"] if r["fits"]]
    rows = sorted(rows, key=lambda r: r["dV@1000_mV"])
    labels = [r["id"].replace("pp_", "") for r in rows]
    benefit = [r["dV@1000_mV"] for r in rows]
    dp = [r["mesh_dp_ratio"] for r in rows]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.3, 4.8))
    colors1 = [GREEN if r["id"] in ("pp_025x030", "pp_040x053") else BLUE for r in rows]
    a1.barh(labels, benefit, color=colors1, edgecolor="#667085", linewidth=0.5)
    for y, v in enumerate(benefit):
        a1.text(v + 1, y, f"{v:.1f}", va="center", fontsize=8.5)
    a1.set_xlabel("ΔV@1000 [mV]")
    a1.set_title("전압만 보면")
    a2.scatter(dp, benefit, s=[55 + 70 * r["t_mm"] for r in rows], c=colors1, edgecolor="#42526a")
    for r in rows:
        a2.annotate(r["id"].replace("pp_", ""), (r["mesh_dp_ratio"], r["dV@1000_mV"]), xytext=(4, 4), textcoords="offset points", fontsize=8)
    a2.axvspan(1, 3, color="#eaf8f3", alpha=0.9, label="ΔP 3배 이하")
    a2.set_xlabel("ΔP/ΔP0 층류 근사")
    a2.set_ylabel("ΔV@1000 [mV]")
    a2.set_xscale("log")
    a2.set_title("압력강하와 같이 보면")
    a2.legend(frameon=False, fontsize=8)
    fig.suptitle("메시 카탈로그: 전압 이득과 유압 비용의 동시 선별", color=NAVY, fontweight="bold", fontsize=14)
    fig.tight_layout()
    return save(fig, 9)


def fig10_thickness():
    rows = sorted(S["axes"]["thickness"]["table"], key=lambda r: r["t_mm"])
    x = [r["t_mm"] for r in rows]
    fig, ax = plt.subplots(figsize=(9.0, 4.8))
    ax.plot(x, [r["dV@1000_mV"] for r in rows], "-o", color=GREEN, lw=2, mfc="white", label="ΔV@1000")
    ax.set_xlabel("메시 두께 tm [mm] (채널 깊이 0.9 mm)")
    ax.set_ylabel("전압 절감 [mV]", color=GREEN)
    ax.tick_params(axis="y", labelcolor=GREEN)
    ax.axvline(0.9, color=RED, ls="--", lw=1, label="채널 깊이")
    ax2 = ax.twinx()
    ax2.plot(x, [r["mesh_dp_ratio"] for r in rows], "-s", color=RED, lw=1.9, mfc="white", label="ΔP/ΔP0")
    ax2.set_ylabel("압력강하 근사비", color=RED)
    ax2.tick_params(axis="y", labelcolor=RED)
    ax2.grid(False)
    ax.set_title("두꺼운 메시는 전압을 낮추지만 유압 비용이 더 빨리 증가")
    return save(fig, 10)


def fig11_open_area():
    rows = sorted(S["axes"]["open_area"]["table"], key=lambda r: r["open_frac"])
    x = np.array([r["open_frac"] * 100 for r in rows])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.2, 4.5))
    a1.plot(x, [r["dV@1000_mV"] for r in rows], "-o", color=PURPLE, lw=2, mfc="white")
    a1.set_xlabel("개구율 φ [%]")
    a1.set_ylabel("ΔV@1000 [mV]")
    a1.set_title("전압 이득")
    a2.plot(x, [r["mesh_dp_ratio"] for r in rows], "-s", color=RED, lw=2, mfc="white")
    a2.axhline(3, color=GREEN, ls="--", lw=1, label="선별 기준 3배")
    a2.set_xlabel("개구율 φ [%]")
    a2.set_ylabel("ΔP/ΔP0 근사")
    a2.set_title("유압 비용")
    a2.legend(frameon=False, fontsize=8)
    fig.suptitle("개구율을 낮추면 유속 효과도 커지지만 압력강하가 함께 증가", color=NAVY, fontweight="bold", fontsize=14)
    fig.tight_layout()
    return save(fig, 11)


def fig12_pore_size():
    base = sorted(S["axes"]["pore_size"]["table"], key=lambda r: r["hole_mm"])
    active = sorted(S["axes"]["pore_size_theta60"]["table"], key=lambda r: r["hole_mm"])
    x = np.array([r["hole_mm"] for r in base])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.3, 4.6))
    a1.plot(x, [r["dV@1000_mV"] for r in base], "-o", color=MUTED, lw=2, label="일반 Ni foam 110°")
    a1.plot(x, [r["dV@1000_mV"] for r in active], "-o", color=BLUE, lw=2, label="가정: 전극 60°")
    a1.set_xlabel("메시 구멍 크기 [mm]")
    a1.set_ylabel("ΔV@1000 [mV]")
    a1.set_title("전압 절감")
    a1.legend(frameon=False, fontsize=8.5)
    a2.plot(x, [r["mesh_contact_prob"] for r in base], "-s", color=GOLD, lw=2, label="Pcontact,UB (110°)")
    a2.plot(x, [r["mesh_capture_eff"] for r in active], "-^", color=GREEN, lw=2, label="Ptransfer,UB (60°)")
    a2.set_xlabel("메시 구멍 크기 [mm]")
    a2.set_ylabel("무차원 상한 지수")
    a2.set_ylim(0, 1.05)
    a2.set_title("기하 접촉과 젖음성 전달")
    a2.legend(frameon=False, fontsize=8.5)
    fig.suptitle("더 촘촘한 구멍은 전극이 충분히 친수성일 때만 전달 이득으로 연결", color=NAVY, fontweight="bold", fontsize=14)
    fig.tight_layout()
    return save(fig, 12)


def fig13_angle_heatmap():
    rows = S["axes"]["contact_angles"]["table"]
    e = sorted({r["electrode_angle_deg"] for r in rows})
    m = sorted({r["mesh_angle_deg"] for r in rows})
    z = np.full((len(e), len(m)), np.nan)
    for r in rows:
        z[e.index(r["electrode_angle_deg"]), m.index(r["mesh_angle_deg"])] = r["dV@1000_mV"]
    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    im = ax.imshow(z, cmap="YlGnBu", origin="lower", aspect="auto", vmin=np.nanmin(z), vmax=np.nanmax(z))
    for i in range(len(e)):
        for j in range(len(m)):
            ax.text(j, i, f"{z[i, j]:.1f}", ha="center", va="center", fontsize=8, color="white" if z[i, j] > 102 else NAVY)
    ax.set_xticks(range(len(m)), [f"{v:g}" for v in m])
    ax.set_yticks(range(len(e)), [f"{v:g}" for v in e])
    ax.set_xlabel("PP 메시 물 접촉각 θm [°]")
    ax.set_ylabel("전극 물 접촉각 θe [°]")
    ax.set_title("접촉각 조합별 ΔV@1000 [mV]")
    cbar = fig.colorbar(im, ax=ax, pad=0.02)
    cbar.set_label("전압 절감 [mV]")
    ax.grid(False)
    return save(fig, 13)


def fig14_coverage():
    rows = S["axes"]["coverage"]["table"]
    styles = {"inlet": (RED, "o", "입구부터"), "middle": (GOLD, "s", "중간부터"), "outlet": (GREEN, "^", "출구 쪽")}
    fig, ax = plt.subplots(figsize=(8.9, 4.8))
    for pos, (color, marker, label) in styles.items():
        rr = sorted([r for r in rows if r["pos"] == pos], key=lambda r: r["cover"])
        ax.plot([r["cover"] * 100 for r in rr], [r["dV@1000_mV"] for r in rr], "-" + marker, color=color, lw=2, mfc="white", label=label)
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_xlabel("메시가 덮는 유로 길이 [%]")
    ax.set_ylabel("ΔV@1000 [mV]")
    ax.set_title("같은 면적이면 기포가 누적된 출구 쪽 배치가 더 효율적")
    ax.legend(frameon=False)
    return save(fig, 14)


def fig15_flow():
    rows = sorted(S["axes"]["flow"]["table"], key=lambda r: r["mL_min"])
    x = [r["mL_min"] for r in rows]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.3, 4.5))
    a1.plot(x, [r["pris_V@1000"] for r in rows], "-o", color=MUTED, lw=2, mfc="white", label="Pristine")
    a1.plot(x, [r["mesh_V@1000"] for r in rows], "-o", color=BLUE, lw=2, mfc="white", label="+ Mesh")
    a1.axvline(4, color=RED, ls="--", lw=1)
    a1.set_xlabel("펌프 유량 [mL/min]")
    a1.set_ylabel("V@1000 [mV]")
    a1.set_title("셀 전압")
    a1.legend(frameon=False)
    a2.plot(x, [r["dV@500_mV"] for r in rows], "-s", color=GOLD, lw=2, mfc="white", label="500 mA/cm²")
    a2.plot(x, [r["dV@1000_mV"] for r in rows], "-o", color=GREEN, lw=2, mfc="white", label="1000 mA/cm²")
    a2.axvline(4, color=RED, ls="--", lw=1, label="기준 4 mL/min")
    a2.set_xlabel("펌프 유량 [mL/min]")
    a2.set_ylabel("전압 절감 [mV]")
    a2.set_title("메시 이득")
    a2.legend(frameon=False, fontsize=8.5)
    fig.suptitle("저유량일수록 기포 체류가 심해져 메시 효과가 크게 계산됨", color=NAVY, fontweight="bold", fontsize=14)
    fig.tight_layout()
    return save(fig, 15)


def fig16_decision_eis():
    cat = [r for r in S["axes"]["catalog"]["table"] if r["fits"]]
    eis = read_wide_csv("eis_nyquist.csv")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.5, 4.7))
    for r in cat:
        color = GREEN if r["id"] in ("pp_025x030", "pp_040x053") else BLUE
        marker = "*" if r["id"] in ("pp_025x030", "pp_040x053") else "o"
        a1.scatter(r["mesh_dp_ratio"], r["dV@1000_mV"], s=130 if marker == "*" else 65, marker=marker, color=color, edgecolor="#42526a", zorder=3)
        a1.annotate(r["id"].replace("pp_", ""), (r["mesh_dp_ratio"], r["dV@1000_mV"]), xytext=(4, 4), textcoords="offset points", fontsize=8)
    a1.axvline(3, color=GREEN, ls="--", lw=1)
    a1.axhline(65, color=MUTED, ls=":", lw=1)
    a1.set_xscale("log")
    a1.set_xlabel("ΔP/ΔP0 근사")
    a1.set_ylabel("ΔV@1000 [mV]")
    a1.set_title("실험 후보 선별")
    labels = ["pristine", "ref_mesh (pp_040x053)", "best (pp_015x015)"]
    cols = [MUTED, BLUE, RED]
    for label, color in zip(labels, cols):
        a2.plot([float(r[f"{label}|Zre"]) for r in eis], [float(r[f"{label}|-Zim"]) for r in eis], color=color, lw=2, label=label)
    a2.set_xlabel("Z' [Ω·cm²]")
    a2.set_ylabel("-Z'' [Ω·cm²]")
    a2.set_title("모델 유도 EIS 지표 (500 mA/cm²)")
    a2.legend(frameon=False, fontsize=7.8)
    a2.set_aspect("equal", adjustable="datalim")
    fig.suptitle("최종 의사결정: 전압·압력강하·임피던스를 함께 확인", color=NAVY, fontweight="bold", fontsize=14)
    fig.tight_layout()
    return save(fig, 16)


def build_figures():
    setup_plot()
    funcs = [fig01_model_map, fig02_geometry, fig03_waterfall, fig04_contribution_current,
             fig05_overpotential, fig06_profiles, fig07_calibration, fig08_catalog_lsv,
             fig09_catalog_screen, fig10_thickness, fig11_open_area, fig12_pore_size,
             fig13_angle_heatmap, fig14_coverage, fig15_flow, fig16_decision_eis]
    return [func() for func in funcs]


def register_fonts():
    pdfmetrics.registerFont(TTFont("Malgun", str(FONT_REG)))
    pdfmetrics.registerFont(TTFont("Malgun-Bold", str(FONT_BOLD)))
    pdfmetrics.registerFontFamily("Malgun", normal="Malgun", bold="Malgun-Bold")


def make_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Malgun-Bold", fontSize=25, leading=34, textColor=colors.HexColor(NAVY), alignment=TA_LEFT, spaceAfter=14),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontName="Malgun", fontSize=11.5, leading=18, textColor=colors.HexColor("#43516a"), spaceAfter=16),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName="Malgun-Bold", fontSize=17, leading=24, textColor=colors.HexColor(NAVY), spaceBefore=4, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Malgun-Bold", fontSize=13.5, leading=20, textColor=colors.HexColor(NAVY), spaceAfter=8),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="Malgun", fontSize=9.3, leading=15.2, textColor=colors.HexColor("#26344c"), spaceAfter=7),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="Malgun", fontSize=7.8, leading=12, textColor=colors.HexColor("#55637a")),
        "caption": ParagraphStyle("caption", parent=base["BodyText"], fontName="Malgun", fontSize=8.5, leading=13, textColor=colors.HexColor("#34435b"), spaceAfter=8),
        "figure": ParagraphStyle("figure", parent=base["Heading2"], fontName="Malgun-Bold", fontSize=15, leading=22, textColor=colors.HexColor(NAVY), spaceAfter=7),
        "center": ParagraphStyle("center", parent=base["BodyText"], fontName="Malgun", fontSize=9, leading=14, alignment=TA_CENTER, textColor=colors.HexColor("#34435b")),
        "callout": ParagraphStyle("callout", parent=base["BodyText"], fontName="Malgun", fontSize=9.3, leading=15.5, leftIndent=7, rightIndent=7, textColor=colors.HexColor(NAVY)),
    }


def para(text, style):
    return Paragraph(text, style)


FIGURE_TEXT = [
    ("Mesh 모델 v2의 계산 구조", "기존 wick 식은 임의 상수로 접촉각 효과를 전압에 직접 반영했다. v2는 기하 접촉 상한, 젖음성 구동력, 유로 폐색을 서로 독립된 경로로 계산한다.", "핵심: Lref=2 mm 같은 포화 기준은 더 이상 쓰지 않는다. 촉매 압착·차단은 데이터가 없어 0으로 숨기는 대신 미모델링 항으로 명시한다."),
    ("기포–메시 접촉과 전달 상한", "기포 중심이 개구 내부 어디에 있느냐를 면적 확률로 계산하고, 전극과 메시의 접촉각 차이는 별도의 젖음성 구동력으로 계산한다. 두 값을 곱한 것은 전달 효율이 아니라 zero-standoff 상한 지수다.", "기준값에서는 Pcontact,UB=0.781이지만 Pwet=0이므로 Ptransfer,UB=0이다. 즉 기포가 메시와 닿을 가능성과 메시로 옮겨갈 구동력은 같은 말이 아니다."),
    ("1000 mA/cm² 전압 워터폴", "Pristine 2033.3 mV에서 기준 메시 pp_040x053 적용값은 1962.7 mV다. 70.7 mV 절감 전부가 유로 폐색에 따른 국소 유속 증가와 기체 체류시간 감소 경로에서 나온다.", "접촉각 기반 전달 기여는 0 mV다. 이 결과를 떼어냄 효과가 48 mV라고 해석하면 안 된다."),
    ("전류밀도별 메커니즘 기여", "500, 1000, 2000 mA/cm²로 갈수록 기포 생성률이 증가해 체류시간 항의 전압 기여가 비선형적으로 커진다.", "고전류에서 큰 이득이 계산되는 것은 메시 재료 자체보다 기체 축적이 심해진 모델 상태의 결과다. 고전류 실험이 가장 강한 검증점이다."),
    ("1000 mA/cm² 전압 구성", "메시는 모델에서 음극 기포 피복에 연결된 활성화 손실과 기포 공극에 연결된 옴 손실을 낮춘다. 가역전압, 양극 활성화, 농도, 수분 항은 같은 조건에서 유지된다.", "전압 절감 70.7 mV는 구성항의 합으로도 닫힌다. 다만 이 분해는 독립 실험으로 검증된 EIS 피팅값이 아니라 모델 내부 분해다."),
    ("유로 방향 기포 피복과 홀드업", "Pristine은 입구에서 출구로 갈수록 θ와 ε가 누적된다. 메시가 있는 계산에서는 전 구간에서 기체 홀드업이 낮아지고, 그 결과 촉매 피복도 감소한다.", "출구 쪽 효과가 큰 이유를 공간적으로 보여준다. 실제 셀에서는 광학 관찰 또는 구간별 차압 측정으로 확인할 수 있다."),
    ("Pristine 모델 보정", "Pristine 분극 데이터 한 세트에 맞춘 결과이며 RMSE는 26.2 mV다. 메시 데이터에는 맞추지 않았기 때문에 메시 결과는 현재 블라인드 예측이다.", "모델이 Pristine을 설명한다고 해서 메시 메커니즘이 검증된 것은 아니다. 보고서의 모든 메시 mV는 설계 방향 탐색용으로 다룬다."),
    ("장착 가능한 메시 후보의 분극곡선", "채널 깊이 0.9 mm보다 얇은 후보만 비교했다. 고전류에서 후보 간 차이가 커지고 저전류에서는 곡선이 거의 겹친다.", "장착 가능 판정은 두께만 본 1차 필터다. 실제 조립 공차, 압착, 밀봉, 우회 유동은 포함하지 않는다."),
    ("카탈로그 전압–압력강하 선별", "pp_015x015는 전압 절감이 가장 크지만 ΔP/ΔP0 근사가 22.1배다. pp_025x030과 pp_040x053은 약 70 mV 이득과 2.4–2.6배 압력강하 사이의 균형이 낫다.", "전압 최대값을 그대로 최적 메시라고 부르지 않는다. 유압 비용과 조립 여유를 함께 본 실험 후보는 pp_025x030, pp_040x053이다."),
    ("메시 두께 민감도", "두께가 증가하면 고체 체적분율 χ가 커져 국소 유속은 증가하고 체류시간은 감소한다. 동시에 층류 압력강하 근사는 u³에 비례해 더 빠르게 증가한다.", "채널 깊이 0.9 mm에 가까운 메시를 단순히 더 좋다고 선택하면 안 된다. 실제 압착 두께와 투과도를 반드시 측정해야 한다."),
    ("개구율 민감도", "개구율 φ가 낮을수록 메시 고체 체적이 많아져 모델 전압은 낮아진다. 같은 이유로 압력강하도 크게 증가한다.", "이 축에서는 낮은 개구율의 이득이 위킹이나 접촉각 때문이 아니라 유로 폐색 때문임을 명확히 해야 한다."),
    ("구멍 크기와 접촉각 조건", "일반 Ni foam 110°와 PP 105.8° 조합에서는 Pwet=0이므로 구멍을 0.3 mm까지 줄여도 전압 절감은 70.7 mV로 평평하다. 전극을 60°로 가정하면 작은 구멍이 전달 상한을 높인다.", "따라서 더 촘촘하게 하면 무조건 좋아진다는 결론은 성립하지 않는다. 먼저 실제 운전 상태 접촉각이 전달 방향을 허용하는지 측정해야 한다."),
    ("전극–메시 접촉각 민감도", "메시가 전극보다 충분히 더 소수성일 때만 Pwet이 양수가 된다. θe≥θm인 조합 상당수에서는 전달 항이 0으로 clamp된다.", "이 그림은 정적 물 접촉각 민감도다. KOH 65 °C, 침지, 기포 하중에서의 advancing/receding 각과 히스테리시스는 별도 측정이 필요하다."),
    ("메시 피복 위치와 길이", "같은 피복률이면 기포가 이미 누적된 출구 쪽을 덮는 배치가 더 큰 전압 절감을 낸다. 전면 피복에서는 세 배치가 같은 70.7 mV에 수렴한다.", "부분 피복 실험은 메커니즘 판별력이 높다. 출구 25–50% 메시와 전면 메시를 비교하면 단순 면적 효과와 누적 기포 효과를 분리할 수 있다."),
    ("유량 민감도", "저유량일수록 Pristine의 기포 축적이 심해져 메시의 체류시간 감소 효과가 크게 계산된다. 기준 운전점은 4 mL/min이다.", "1, 4, 8 mL/min 정도의 유량 스윕에서 메시 이득이 감소하는지 보면 현재 유동 메커니즘을 직접 검증할 수 있다."),
    ("최종 실험 의사결정", "좌측은 전압 절감과 압력강하를 함께 본 후보 지도, 우측은 모델 파라미터로부터 유도한 EIS 지표다. 별표 후보가 pp_025x030과 pp_040x053이다.", "EIS 반원 축소는 예측이지 실측이 아니다. 최종 판단은 전압, 메시 전후 차압, EIS, 접촉각을 같은 시편에서 함께 측정해야 한다."),
]


def header_footer(canvas, doc):
    canvas.saveState()
    if doc.page > 1:
        canvas.setStrokeColor(colors.HexColor("#d8e0ec"))
        canvas.line(18 * mm, 18 * mm, 192 * mm, 18 * mm)
        canvas.setFont("Malgun", 7.5)
        canvas.setFillColor(colors.HexColor("#667085"))
        canvas.drawString(18 * mm, 11 * mm, "Mesh 모델 v2 재분석 · 그림 1–16")
        canvas.drawRightString(192 * mm, 11 * mm, str(doc.page))
    canvas.restoreState()


def callout_table(text, style, color=BLUE):
    t = Table([[para(text, style)]], colWidths=[169 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f8ff")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#cdd9ef")),
        ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(color)),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def figure_page(story, styles, number, path, title, caption, takeaway):
    story.append(PageBreak())
    story.append(para(f"그림 {number}. {title}", styles["figure"]))
    im = Image(str(path))
    max_w, max_h = 172 * mm, 115 * mm
    scale = min(max_w / im.imageWidth, max_h / im.imageHeight)
    im.drawWidth = im.imageWidth * scale
    im.drawHeight = im.imageHeight * scale
    story.append(im)
    story.append(Spacer(1, 3 * mm))
    story.append(para(f"<b>그림 설명.</b> {caption}", styles["caption"]))
    story.append(callout_table(f"<b>해석.</b> {takeaway}", styles["callout"], GREEN))


def make_pdf(figures):
    register_fonts()
    st = make_styles()
    doc = SimpleDocTemplate(str(PDF), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=22 * mm,
                            title="Mesh 모델 v2 재분석 보고서", author="Bubble simulator")
    story = []
    story.append(Spacer(1, 10 * mm))
    story.append(para("시뮬레이션 스터디 · 수정 모델 보고서", st["small"]))
    story.append(Spacer(1, 4 * mm))
    story.append(para("유로 삽입 PP 메시 인터레이어의<br/>기포 관리 효과", st["title"]))
    story.append(para("Mesh 모델 v2 재분석 — 접촉각 기반 전달 상한, 유로 폐색, 압력강하 guardrail을 분리하고 그림 1–16으로 정리", st["subtitle"]))
    meta = [
        ["셀", "2.2×2.2 cm · 13 채널", "유로", "0.88/0.90 mm (폭/깊이)"],
        ["전해질", "1.0 M KOH · 65 °C", "운전", "4 mL/min · dry-cathode AEM"],
        ["전극", "일반 bare Ni foam · θe=110°", "메시", "untreated PP · θm=105.8°"],
        ["모델", "channel + meshlayer v2", "보정", f"Pristine RMSE {S['pristine']['calib_RMSE_mV']:.1f} mV"],
    ]
    mt = Table(meta, colWidths=[20 * mm, 62 * mm, 20 * mm, 67 * mm])
    mt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Malgun"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#34435b")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#7b879b")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#7b879b")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#d8e0ec")),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(mt)
    story.append(Spacer(1, 8 * mm))
    d1000 = D["decomp"]["1000"]
    cards = [
        [para("기준 메시 ΔV@1000", st["small"]), para("접촉각 전달", st["small"]), para("압력강하 근사", st["small"])],
        [para(f"<b>{d1000['net_mV']:.1f} mV</b>", st["center"]), para(f"<b>{D['factors']['capture_eff']:.3f}</b>", st["center"]), para(f"<b>{D['factors']['dp_ratio']:.2f}×</b>", st["center"])],
    ]
    ct = Table(cards, colWidths=[56 * mm] * 3)
    ct.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(LIGHT)),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#cad7ee")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d8e0ec")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(ct)
    story.append(Spacer(1, 8 * mm))
    story.append(callout_table("<b>결론.</b> 일반 Ni foam 110°와 untreated PP 105.8° 조합에서는 접촉각 기반 기포 전달 구동력이 0이다. 기준 메시의 70.7 mV 절감은 전부 메시 고체 체적에 따른 국소 유속 증가와 기체 체류시간 감소에서 나온다. 따라서 기존 보고서의 wick, Lref, θfactor 해석은 사용하지 않는다.", st["callout"]))
    story.append(Spacer(1, 7 * mm))
    story.append(para("이 보고서의 상태", st["h2"]))
    story.append(para("Pristine 데이터 한 세트로만 보정한 블라인드 메시 예측이다. 메시 적용 전압, 접촉각 전달, 압력강하는 아직 외부 실험으로 보정하지 않았다. 결과는 실험 후보와 검증 순서를 정하는 데 사용하고, 절대 성능값으로 확정하지 않는다.", st["body"]))

    story.append(PageBreak())
    story.append(para("요약과 수정된 식", st["h1"]))
    story.append(para("1. <b>기하 접촉 상한</b>: P<sub>contact,UB</sub> = 1 - φ·max(1-d<sub>b</sub>/L<sub>x</sub>,0)·max(1-d<sub>b</sub>/L<sub>y</sub>,0). 메시와 기포가 붙어 있다고 가정한 zero-standoff 상한이다.", st["body"]))
    story.append(para("2. <b>젖음성 구동력</b>: P<sub>wet</sub> = max[0,(cosθ<sub>e</sub>-cosθ<sub>m</sub>)/(1+cosθ<sub>e</sub>)]. PP가 전극보다 더 소수성일 때만 양수가 된다.", st["body"]))
    story.append(para("3. <b>전달 상한 지수</b>: P<sub>transfer,UB</sub> = P<sub>contact,UB</sub>·P<sub>wet</sub>. 실제 전달 속도나 효율이 아니라 비교용 상한이다.", st["body"]))
    story.append(para("4. <b>유로 폐색</b>: χ=(1-φ)t<sub>m</sub>/d<sub>ch</sub>, u/u<sub>0</sub>=1/(1-χ), τ/τ<sub>0</sub>=1-χ, ΔP/ΔP<sub>0</sub>≈(u/u<sub>0</sub>)³. 마지막 식은 woven mesh 투과도 대신 쓴 1차 guardrail이다.", st["body"]))
    story.append(Spacer(1, 4 * mm))
    story.append(callout_table("<b>삭제된 값.</b> wick, Lref=2 mm, Cθ=0.6, Cret=0.5, Cblock=0.3은 v2 계산에 들어가지 않는다. 출력 JSON에 남은 theta_factor=1은 하위 호환 표시일 뿐, 더 이상 조절 계수가 아니다.", st["callout"], RED))
    story.append(Spacer(1, 7 * mm))
    story.append(para("그림 1–16 구성", st["h2"]))
    toc_rows = [[str(i), title] for i, (title, _, _) in enumerate(FIGURE_TEXT, 1)]
    toc = Table(toc_rows, colWidths=[12 * mm, 154 * mm])
    toc.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Malgun"), ("FONTSIZE", (0, 0), (-1, -1), 8.2),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor(BLUE)),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#e3e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(toc)

    for i, (path, texts) in enumerate(zip(figures, FIGURE_TEXT), 1):
        figure_page(story, st, i, path, *texts)

    story.append(PageBreak())
    story.append(para("실험 후보와 판정 기준", st["h1"]))
    cat = [r for r in S["axes"]["catalog"]["table"] if r["fits"]]
    order = {"pp_025x030": 0, "pp_040x053": 1}
    cat = sorted(cat, key=lambda r: (order.get(r["id"], 9), r["mesh_dp_ratio"]))
    rows = [["후보", "구멍\nmm", "개구율", "두께\nmm", "ΔV@1000\nmV", "ΔP/ΔP0", "채널 여유\nmm", "판정"]]
    for r in cat:
        clearance = 0.9 - r["t_mm"]
        if r["id"] == "pp_025x030": verdict = "1순위"
        elif r["id"] == "pp_040x053": verdict = "기준"
        elif r["mesh_dp_ratio"] > 3 or clearance < 0.1: verdict = "주의"
        else: verdict = "후보"
        rows.append([r["id"], f"{r['hole_mm']:.3f}", f"{r['open']:.0%}", f"{r['t_mm']:.3f}", f"{r['dV@1000_mV']:.1f}", f"{r['mesh_dp_ratio']:.2f}", f"{clearance:.3f}", verdict])
    tab = Table(rows, repeatRows=1, colWidths=[30 * mm, 17 * mm, 16 * mm, 17 * mm, 23 * mm, 20 * mm, 23 * mm, 20 * mm])
    tab.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Malgun"), ("FONTSIZE", (0, 0), (-1, -1), 7.3),
        ("FONTNAME", (0, 0), (-1, 0), "Malgun-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 1), (-1, 2), colors.HexColor("#edf9f5")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cfd8e6")),
        ("ALIGN", (1, 1), (-2, -1), "RIGHT"), ("ALIGN", (-1, 1), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tab)
    story.append(Spacer(1, 8 * mm))
    story.append(para("권장 실험", st["h2"]))
    story.append(para("pp_025x030과 pp_040x053을 같은 전극·가스켓·압착 조건에서 비교한다. 1, 4, 8 mL/min과 500, 1000, 2000 mA/cm²를 조합하고, 전압과 함께 메시 전후 차압 및 EIS를 기록한다. 가능하면 출구 25–50% 부분 피복 조건을 추가한다.", st["body"]))
    story.append(para("접촉각은 공기 중 sessile drop 한 값만 쓰지 말고, KOH 65 °C 침지 전후의 advancing/receding 값과 기포가 붙은 상태의 captive-bubble 각을 함께 측정한다. 이 데이터가 들어오면 현재 Ptransfer,UB를 실제 전달 시간상수로 교체할 수 있다.", st["body"]))

    story.append(PageBreak())
    story.append(para("한계와 참고 근거", st["h1"]))
    limitations = [
        "110°와 105.8°는 서로 다른 문헌의 정적 물 접촉각이다. 실제 KOH 65 °C 운전 중 표면 상태를 대표한다고 단정할 수 없다.",
        "Pcontact,UB는 메시와 기포 사이 간격이 0인 상한이다. 실제 standoff와 변형, 접촉선 pinning은 포함하지 않는다.",
        "ΔP/ΔP0는 평행 채널의 국소 유속에 기반한 근사다. woven mesh의 Darcy–Forchheimer 투과도와 우회 유동이 빠져 있다.",
        "촉매 압착·차단은 간격, 압착률, 접촉 면적 데이터가 없어 미모델링이다. 0이라는 뜻이 아니다.",
        "메시 전압 데이터로 재보정하지 않았으므로 후보 순위와 절대 mV 모두 실험 검증 전 예측이다.",
    ]
    for item in limitations:
        story.append(para("• " + item, st["body"]))
    story.append(Spacer(1, 5 * mm))
    story.append(para("문헌 입력", st["h2"]))
    story.append(para("• Bare Ni foam 물 접촉각 110°: <link href='https://www.sciencedirect.com/science/article/pii/S1002007122001083' color='#1769e0'>ScienceDirect 원문</link>", st["body"]))
    story.append(para("• Untreated PP mesh 물 접촉각 105.8°: <link href='https://pmc.ncbi.nlm.nih.gov/articles/PMC5393001/' color='#1769e0'>PMC 공개 원문</link>", st["body"]))
    story.append(para("• 정적 힘평형만으로 포착하기 어려운 기포 이탈·접촉선 영향: <link href='https://pubs.acs.org/doi/abs/10.1021/acs.langmuir.4c01963' color='#1769e0'>Langmuir 논문</link>", st["body"]))
    story.append(Spacer(1, 7 * mm))
    story.append(callout_table("<b>최종 결론.</b> 지금 단계에서 가장 안전한 해석은 ‘일반 Ni foam/PP 조합의 접촉각 떼어냄 효과는 0으로 계산되며, 기준 메시의 70.7 mV 이득은 유동 경로 가설이다’이다. 다음 실험은 더 촘촘한 메시 하나를 고르는 것이 아니라, pp_025x030과 pp_040x053을 차압·EIS·접촉각과 함께 비교해 그 가설을 검증하는 것이다.", st["callout"], GREEN))

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    return PDF


def main():
    figures = build_figures()
    pdf = make_pdf(figures)
    print(pdf)


if __name__ == "__main__":
    main()
