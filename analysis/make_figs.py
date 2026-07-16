# -*- coding: utf-8 -*-
"""Render publication-style SVG figures from the mesh-study CSV/JSON outputs.

English axis labels (avoids CJK font issues in matplotlib); Korean captions live
in the report HTML. Figures -> analysis/out/figs/*.svg
"""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("svg")
import matplotlib.pyplot as plt
from matplotlib import rcParams

rcParams.update({
    "svg.fonttype": "none", "font.size": 11, "axes.grid": True,
    "grid.color": "#e6e9ef", "grid.linewidth": 0.8, "axes.edgecolor": "#98a2b3",
    "axes.linewidth": 0.9, "axes.titlesize": 12, "axes.titleweight": "bold",
    "figure.dpi": 100, "savefig.bbox": "tight", "axes.axisbelow": True,
})

OUT = Path(__file__).resolve().parent / "out"
FIG = OUT / "figs"
FIG.mkdir(parents=True, exist_ok=True)
S = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
J = S["sweep_j"]

EXP_MEAS = [[10, 1.48294], [20, 1.4937], [50, 1.5184], [100, 1.55191],
            [200, 1.60495], [300, 1.65078], [400, 1.69504], [500, 1.74178],
            [625, 1.80051], [750, 1.86602], [875, 1.94376], [1000, 2.03323],
            [1250, 2.20449], [1500, 2.37841], [2000, 2.6616], [2250, 2.78376]]

ACC = "#1f6feb"; GRN = "#0f8a63"; GLD = "#c98a1a"; RED = "#c9333f"
MUT = "#8a94a6"; PUR = "#7a5af8"
CMESH = ["#1f6feb", "#0f8a63", "#c98a1a", "#c9333f", "#7a5af8", "#0891b2", "#db2777"]


def wide_csv(name):
    rows = list(csv.reader((OUT / name).read_text(encoding="utf-8-sig").splitlines()))
    head = rows[0]
    cols = {h: [] for h in head}
    for r in rows[1:]:
        for h, v in zip(head, r):
            cols[h].append(v)
    return head, cols


def save(fig, name):
    fig.savefig(FIG / name, format="svg", transparent=True)
    plt.close(fig)
    print("  ->", name)


# --- FIG 1: pristine calibration (measured pts vs model line) ---------------
def fig_calib():
    fig, ax = plt.subplots(figsize=(5.6, 3.9))
    ax.plot(J, S["pristine"]["V"], "-", color=ACC, lw=2, label="Model (calibrated)")
    ax.plot([m[0] for m in EXP_MEAS], [m[1] for m in EXP_MEAS], "o", color=RED,
            ms=5, mfc="white", mew=1.4, label="Measured (pristine)")
    ax.set_xlabel("current density  j  [mA/cm$^2$]")
    ax.set_ylabel("cell voltage  V  [V]")
    ax.set_title(f"Pristine calibration — RMSE {S['pristine']['calib_RMSE_mV']} mV")
    ax.legend(frameon=False, fontsize=10, loc="upper left")
    save(fig, "fig_calib.svg")


# --- FIG 2: catalog LSV overlay (fitting meshes) ----------------------------
def fig_catalog_lsv():
    head, cols = wide_csv("lsv_catalog.csv")
    fits = {r["id"]: r["fits"] for r in S["axes"]["catalog"]["table"]}
    fig, ax = plt.subplots(figsize=(5.9, 4.0))
    ax.plot(J, [float(x) / 1000 for x in cols["pristine"]], "--", color=MUT, lw=1.8, label="pristine")
    ci = 0
    for h in head[1:]:
        if h == "pristine":
            continue
        if not fits.get(h, False):
            continue
        ax.plot(J, [float(x) / 1000 for x in cols[h]], "-", color=CMESH[ci % len(CMESH)],
                lw=1.8, label=h)
        ci += 1
    ax.set_xlabel("current density  j  [mA/cm$^2$]")
    ax.set_ylabel("cell voltage  V  [V]")
    ax.set_title("Polarization — mountable PP meshes (t < 0.9 mm)")
    ax.legend(frameon=False, fontsize=8.5, loc="upper left", ncol=1)
    save(fig, "fig_catalog_lsv.svg")


# --- FIG 3: catalog dV@1000 bar (which mesh best) ---------------------------
def fig_catalog_bar():
    t = S["axes"]["catalog"]["table"]
    t2 = sorted(t, key=lambda r: (r["fits"], (r["dV@1000_mV"] or 0)))
    labels = [r["id"].replace("pp_", "") for r in t2]
    vals = [(r["dV@1000_mV"] or 0) for r in t2]
    colors = [GRN if r["fits"] else "#c7cdd8" for r in t2]
    fig, ax = plt.subplots(figsize=(6.2, 3.9))
    bars = ax.barh(labels, vals, color=colors, edgecolor="#5b6472", linewidth=0.6)
    for r, b in zip(t2, bars):
        tag = "" if r["fits"] else "  no-fit (t≥d_ch)"
        ax.text(b.get_width() + 1.5, b.get_y() + b.get_height() / 2,
                f"{int(r['dV@1000_mV'] or 0)}{tag}", va="center", fontsize=8.5,
                color="#5b6472")
    ax.set_xlabel("voltage saved vs pristine  ΔV @ 1000 mA/cm$^2$  [mV]  (higher = better)")
    ax.set_title("Mesh benefit ranking (green = mountable)")
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(vals) * 1.28 if max(vals) else 1)
    save(fig, "fig_catalog_bar.svg")


# --- FIG 4: coverage x position (THE key figure) ----------------------------
def fig_coverage():
    t = S["axes"]["coverage"]["table"]
    fig, ax = plt.subplots(figsize=(5.8, 4.0))
    styles = {"inlet": (RED, "o"), "middle": (GLD, "s"), "outlet": (GRN, "^")}
    for pos in ("inlet", "middle", "outlet"):
        rr = [r for r in t if r["pos"] == pos]
        rr = sorted(rr, key=lambda r: r["cover"])
        xs = [r["cover"] * 100 for r in rr]
        ys = [(r["dV@1000_mV"] or 0) for r in rr]
        c, mk = styles[pos]
        ax.plot(xs, ys, "-" + mk, color=c, lw=1.9, ms=6, mfc="white", mew=1.4, label=pos)
    ax.axhline(0, color=MUT, lw=0.8, ls=":")
    ax.set_xlabel("mesh-covered fraction of flow path  [%]")
    ax.set_ylabel("ΔV @ 1000 mA/cm$^2$  [mV]  (higher = better)")
    ax.set_title("Coverage × position — where to put the mesh")
    ax.legend(frameon=False, fontsize=10, title="anchor", title_fontsize=9)
    save(fig, "fig_coverage.svg")


# --- FIG 5: flow dependence -------------------------------------------------
def fig_flow():
    t = sorted(S["axes"]["flow"]["table"], key=lambda r: r["mL_min"])
    ml = [r["mL_min"] for r in t]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.2, 3.8))
    a1.plot(ml, [r["pris_V@1000"] for r in t], "-o", color=MUT, lw=1.9, ms=5, mfc="white", label="pristine")
    a1.plot(ml, [r["mesh_V@1000"] for r in t], "-o", color=ACC, lw=1.9, ms=5, mfc="white", label="+ mesh")
    a1.axvline(4.0, color=RED, lw=0.9, ls="--"); a1.text(4.2, a1.get_ylim()[1], " 4 mL/min\n (measured)", fontsize=8, va="top", color=RED)
    a1.set_xlabel("pump flow  [mL/min]"); a1.set_ylabel("V @ 1000 mA/cm$^2$  [mV]")
    a1.set_title("Cell voltage vs flow"); a1.legend(frameon=False, fontsize=9)
    a2.plot(ml, [(r["dV@1000_mV"] or 0) for r in t], "-o", color=GRN, lw=2, ms=5, mfc="white")
    a2.set_xlabel("pump flow  [mL/min]"); a2.set_ylabel("mesh benefit ΔV @1000  [mV]")
    a2.set_title("Mesh helps most in the choking regime")
    a2.axvline(4.0, color=RED, lw=0.9, ls="--")
    save(fig, "fig_flow.svg")


# --- FIG 6: thickness tradeoff (benefit vs pressure-drop proxy) -------------
def fig_thickness():
    t = sorted(S["axes"]["thickness"]["table"], key=lambda r: r["t_mm"])
    ts = [r["t_mm"] for r in t]
    fig, ax = plt.subplots(figsize=(5.9, 4.0))
    ax.plot(ts, [(r["dV@1000_mV"] or 0) for r in t], "-o", color=GRN, lw=2, ms=6, mfc="white", label="ΔV @1000 (benefit)")
    ax.set_xlabel("mesh thickness  t  [mm]  (channel depth = 0.9 mm)")
    ax.set_ylabel("ΔV @ 1000 mA/cm$^2$  [mV]", color=GRN)
    ax.tick_params(axis="y", labelcolor=GRN)
    ax2 = ax.twinx()
    ax2.plot(ts, [r["mesh_dp_ratio"] for r in t], "-s", color=RED, lw=1.8, ms=5, mfc="white", label="laminar ΔP ratio")
    ax2.set_ylabel("estimated laminar ΔP / ΔP₀", color=RED)
    ax2.tick_params(axis="y", labelcolor=RED); ax2.grid(False)
    ax.set_title("Thickness: voltage effect vs laminar pressure cost")
    save(fig, "fig_thickness.svg")


# --- FIG 7: open-area & pore (two panels) -----------------------------------
def fig_open_pore():
    to = sorted(S["axes"]["open_area"]["table"], key=lambda r: r["open_frac"])
    tp = sorted(S["axes"]["pore_size"]["table"], key=lambda r: r["hole_mm"])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.2, 3.8))
    a1.plot([r["open_frac"] * 100 for r in to], [(r["dV@1000_mV"] or 0) for r in to],
            "-o", color=PUR, lw=2, ms=6, mfc="white")
    a1.set_xlabel("open-area fraction φ  [%]  (lower = denser)")
    a1.set_ylabel("ΔV @1000  [mV]"); a1.set_title("Open area changes blockage")
    a2.plot([r["hole_mm"] for r in tp], [(r["dV@1000_mV"] or 0) for r in tp],
            "-o", color=GLD, lw=2, ms=6, mfc="white")
    a2.set_xlabel("opening size  [mm]"); a2.set_ylabel("ΔV @1000  [mV]")
    a2.set_title("Bubble contact changes continuously")
    save(fig, "fig_open_pore.svg")


# --- FIG 8: EIS Nyquist -----------------------------------------------------
def fig_eis():
    head, cols = wide_csv("eis_nyquist.csv")
    labels = [h.split("|")[0] for h in head[1:] if h.endswith("|Zre")]
    fig, ax = plt.subplots(figsize=(5.6, 4.0))
    colmap = [MUT, ACC, GRN]
    for i, lab in enumerate(labels):
        re = [float(x) for x in cols[f"{lab}|Zre"]]
        im = [float(x) for x in cols[f"{lab}|-Zim"]]
        ax.plot(re, im, "-", color=colmap[i % 3], lw=1.9, label=lab)
    ax.set_xlabel("Z' (real)  [Ω·cm$^2$]"); ax.set_ylabel("−Z'' (imag)  [Ω·cm$^2$]")
    ax.set_title("EIS @ 500 mA/cm$^2$ — coverage shrinks the R$_{ct}$ arc")
    ax.set_aspect("equal", adjustable="datalim")
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    save(fig, "fig_eis.svg")


import json as _json
DEC = _json.loads((OUT / "decomp.json").read_text(encoding="utf-8")) if (OUT / "decomp.json").exists() else None


# --- FIG 9: mechanism waterfall (WHY it improves) @1000 ---------------------
def fig_mechanism():
    if not DEC:
        return
    d = DEC["decomp"]["1000"]
    v0 = d["V_pristine"]
    st = d["steps_mV"]
    capture = st["접촉·젖음성 포획"]
    flow = st["유로 폐색에 따른 체류시간 감소"]
    block = st["촉매 접촉·압착 차단 (미모델링)"]
    labels = ["Pristine", "Transfer", "Flow residence", "Unmodelled contact", "+ Mesh"]
    deltas = [capture, flow, block]
    fig, ax = plt.subplots(figsize=(6.6, 4.1))
    running = v0
    ax.bar(0, v0, color="#c7cdd8", edgecolor="#5b6472", width=0.62)
    ax.text(0, v0 + 6, f"{v0:.0f}", ha="center", fontsize=9.5, fontweight="bold")
    for i, dv in enumerate(deltas, start=1):
        bottom = running - dv if dv > 0 else running
        color = GRN if dv > 0 else RED
        ax.bar(i, abs(dv), bottom=bottom, color=color, edgecolor="#5b6472", width=0.62)
        ax.plot([i - 1 + 0.31, i - 0.31], [running, running], color="#98a2b3", lw=0.8, ls=":")
        ax.text(i, bottom + abs(dv) + 6, f"{'−' if dv>0 else '+'}{abs(dv):.0f}",
                ha="center", fontsize=9.5, color=color, fontweight="bold")
        running -= dv
    ax.bar(4, running, color=ACC, edgecolor="#5b6472", width=0.62)
    ax.text(4, running + 6, f"{running:.0f}", ha="center", fontsize=9.5, fontweight="bold", color=ACC)
    ax.set_xticks(range(5)); ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("cell voltage  V @ 1000 mA/cm$^2$  [mV]")
    ax.set_ylim(v0 - max(deltas) * 4.5, v0 + 40)
    ax.set_title("Revised mesh model — voltage waterfall")
    ax.grid(axis="x", visible=False)
    save(fig, "fig_mechanism.svg")


# --- FIG 10: decomposition vs current (mix shifts) --------------------------
def fig_mechanism_j():
    if not DEC:
        return
    js = ["500", "1000", "2000"]
    cats = ["접촉·젖음성 포획", "유로 폐색에 따른 체류시간 감소", "촉매 접촉·압착 차단 (미모델링)"]
    names = ["Contact × wetting", "Flow residence", "Contact blocking (unmodelled)"]
    cols = [GRN, "#3aa981", RED]
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    import numpy as _np
    x = _np.arange(len(js)); w = 0.24
    for k, (cat, nm, c) in enumerate(zip(cats, names, cols)):
        vals = [DEC["decomp"][j]["steps_mV"][cat] for j in js]
        ax.bar(x + (k - 1) * w, vals, w, label=nm, color=c, edgecolor="#5b6472", linewidth=0.5)
    ax.axhline(0, color="#98a2b3", lw=0.8)
    ax.set_xticks(x); ax.set_xticklabels([f"{j} mA/cm$^2$" for j in js])
    ax.set_ylabel("contribution to ΔV  [mV]  (＋=saves)")
    ax.set_title("Each action's share grows with current")
    ax.legend(frameon=False, fontsize=8.5, ncol=2)
    save(fig, "fig_mechanism_j.svg")


# --- FIG 11: overpotential stack pristine vs mesh @1000 ---------------------
def fig_overpot():
    if not DEC:
        return
    d = DEC["decomp"]["1000"]
    tp, tm = d["overpot_pristine"], d["overpot_mesh"]
    order = ["E_rev", "eta_act_anode", "eta_act_cathode", "eta_ohmic", "eta_conc", "eta_water"]
    nice = ["E_rev (thermo)", "η_act anode (OER)", "η_act cathode (HER)\n+bubble cover",
            "η_ohmic\n+bubble void", "η_conc", "η_water (dry)"]
    cols = ["#c7cdd8", "#c67a1c", "#2f7fb8", GLD, "#9aa6ba", PUR]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    import numpy as _np
    for row, (label, terms) in enumerate([("+ Mesh", tm), ("Pristine", tp)]):
        left = 0
        for k, nm, c in zip(order, nice, cols):
            v = terms[k]
            ax.barh(row, v, left=left, color=c, edgecolor="white", linewidth=0.6)
            if v > 55:
                ax.text(left + v / 2, row, f"{v:.0f}", ha="center", va="center",
                        fontsize=8, color="#10233b" if c in ("#c7cdd8", GLD, "#c67a1c") else "white")
            left += v
        ax.text(left + 12, row, f"Σ {left:.0f} mV", va="center", fontsize=9, fontweight="bold")
    ax.set_yticks([0, 1]); ax.set_yticklabels(["+ Mesh", "Pristine"])
    ax.set_xlabel("cell voltage breakdown @ 1000 mA/cm$^2$  [mV]")
    ax.set_title("Where the voltage goes — mesh cuts the two bubble losses")
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for c in cols],
              labels=nice, frameon=False, fontsize=7.6, ncol=3, loc="upper center",
              bbox_to_anchor=(0.5, -0.28))
    ax.grid(axis="y", visible=False); ax.set_ylim(-0.6, 1.6)
    save(fig, "fig_overpot.svg")


# --- FIG 12: along-channel coverage profile (where relief happens) ----------
def fig_profile():
    if not DEC or not DEC.get("profiles_1000"):
        return
    p = DEC["profiles_1000"]
    pp, pm = p["pristine"], p["mesh"]
    if not pp or not pm:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.2, 3.7), sharex=True)
    a1.plot(pp["s"], pp["theta"], "-", color=MUT, lw=2, label="pristine")
    a1.plot(pm["s"], pm["theta"], "-", color=ACC, lw=2, label="+ mesh")
    a1.fill_between(pm["s"], pm["theta"], pp["theta"], color=GRN, alpha=0.12)
    a1.set_ylabel("coverage θ  (fraction of catalyst blanketed)")
    a1.set_xlabel("position along flow path  (0 inlet → 1 outlet)")
    a1.set_title("Coverage θ(s)"); a1.legend(frameon=False, fontsize=9)
    a2.plot(pp["s"], pp["eps"], "-", color=MUT, lw=2, label="pristine")
    a2.plot(pm["s"], pm["eps"], "-", color=ACC, lw=2, label="+ mesh")
    a2.fill_between(pm["s"], pm["eps"], pp["eps"], color=GRN, alpha=0.12)
    a2.set_ylabel("gas holdup ε  (bubble volume fraction)")
    a2.set_xlabel("position along flow path  (0 inlet → 1 outlet)")
    a2.set_title("Holdup ε(s)"); a2.legend(frameon=False, fontsize=9)
    save(fig, "fig_profile.svg")


M2D = _json.loads((OUT / "mesh_2d.json").read_text(encoding="utf-8")) if (OUT / "mesh_2d.json").exists() else None
LEXT = _json.loads((OUT / "lambda_ext.json").read_text(encoding="utf-8")) if (OUT / "lambda_ext.json").exists() else None


# --- FIG 13: blocking reverses only at low current ---------------------------
def fig_reversal():
    if not M2D:
        return
    js = M2D["js"]; cross = M2D["cross_j"]
    labs = {"기준(fine·얇음)": ("fine·thin (ref)", ACC, "o"),
            "coarse·촘촘·두꺼움": ("coarse·dense·thick", GLD, "s"),
            "극단 차단": ("extreme blocking", RED, "^")}
    fig, ax = plt.subplots(figsize=(6.4, 4.1))
    for tag, d in cross.items():
        nm, c, mk = labs.get(tag, (tag, MUT, "o"))
        ys = [d["dV_by_j"][str(j)] for j in js]
        ax.plot(js, ys, "-" + mk, color=c, lw=1.9, ms=5, mfc="white", label=nm)
    ax.axhline(0, color="#5b6472", lw=1.0)
    ax.axhspan(ax.get_ylim()[0], 0, color="#fdecec", alpha=0.5, zorder=0)
    ax.text(24, ax.get_ylim()[0] * 0.5 if ax.get_ylim()[0] < 0 else -2,
            "mesh HURTS", fontsize=9, color=RED)
    ax.set_xscale("log")
    ax.set_xlabel("current density  j  [mA/cm$^2$]  (log)")
    ax.set_ylabel("net ΔV  [mV]  (＋saves / −hurts)")
    ax.set_title("Blocking reverses the benefit only at LOW current")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    save(fig, "fig_reversal.svg")


# --- FIG 14: blocking cost grows (coarse+dense+thick) ------------------------
def fig_block_growth():
    if not M2D:
        return
    ex = M2D["extremes"]
    labels = [f"h{e['hole']:.0f}·φ{int(e['phi']*100)}·t{e['t']:.2f}" for e in ex]
    import numpy as _np
    x = _np.arange(len(ex)); w = 0.26
    fig, ax = plt.subplots(figsize=(6.8, 4.0))
    ax.bar(x - w, [e["peel"] for e in ex], w, label="Contact-angle transfer", color=GRN, edgecolor="#5b6472", linewidth=0.5)
    ax.bar(x, [e["push"] for e in ex], w, label="Residence reduction", color="#3aa981", edgecolor="#5b6472", linewidth=0.5)
    ax.bar(x + w, [e["block"] for e in ex], w, label="Contact blocking (unmodelled)", color=RED, edgecolor="#5b6472", linewidth=0.5)
    for i, e in enumerate(ex):
        ax.text(i + w, e["block"] - 3, f"{e['block']:.0f}", ha="center", va="top", fontsize=8, color=RED)
        ax.text(i, e["net"] + 4, f"net {e['net']:.0f}", ha="center", fontsize=8, color=ACC, fontweight="bold")
    ax.axhline(0, color="#5b6472", lw=0.9)
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("contribution @ 1000 mA/cm$^2$  [mV]")
    ax.set_title("Mesh effects at 1000 mA/cm$^2$ (contact blocking excluded)")
    ax.legend(frameon=False, fontsize=8.5, ncol=3, loc="lower left")
    save(fig, "fig_block_growth.svg")


# --- FIG 15: lambda(x) foam extension reproduces outlet-partial optimum ------
def fig_lambda():
    if not LEXT:
        return
    rows = LEXT["rows"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.4, 4.0))
    sty = {"inlet": (RED, "o"), "middle": (GLD, "s"), "outlet": (GRN, "^")}
    # left: base model (no foam) — monotone, 100% best
    for pos in ("inlet", "middle", "outlet"):
        rr = sorted([r for r in rows if r["pos"] == pos], key=lambda r: r["cover"])
        a1.plot([r["cover"] * 100 for r in rr], [r["base_dV"] for r in rr],
                "-" + sty[pos][1], color=sty[pos][0], lw=1.8, ms=5, mfc="white", label=pos)
    a1.set_title("Base model — 100% always best"); a1.set_ylim(-12, 125)
    a1.set_xlabel("mesh cover [%]"); a1.set_ylabel("ΔV @1000 [mV]")
    a1.legend(frameon=False, fontsize=8.5)
    # right: + foam lambda(x) — outlet peaks at partial cover
    for pos in ("inlet", "middle", "outlet"):
        rr = sorted([r for r in rows if r["pos"] == pos], key=lambda r: r["cover"])
        xs = [r["cover"] * 100 for r in rr]; ys = [r["total_dV"] for r in rr]
        a2.plot(xs, ys, "-" + sty[pos][1], color=sty[pos][0], lw=1.9, ms=5, mfc="white", label=pos)
        if pos == "outlet":
            k = max(range(len(ys)), key=lambda i: ys[i])
            a2.scatter([xs[k]], [ys[k]], s=140, facecolor="none", edgecolor=GRN, lw=2, zorder=5)
            a2.annotate(f"optimum {int(xs[k])}%", (xs[k], ys[k]), xytext=(xs[k] - 34, ys[k] + 6),
                        fontsize=9, color=GRN, fontweight="bold")
    a2.axhline(0, color="#98a2b3", lw=0.7, ls=":")
    a2.set_title("+ Ni-foam λ(x) — outlet-PARTIAL wins"); a2.set_ylim(-12, 125)
    a2.set_xlabel("mesh cover [%]"); a2.set_ylabel("ΔV @1000 [mV]")
    a2.legend(frameon=False, fontsize=8.5)
    save(fig, "fig_lambda.svg")


FOAM = _json.loads((OUT / "foam_model.json").read_text(encoding="utf-8")) if (OUT / "foam_model.json").exists() else None


# --- FIG 16: grounded foam model refutes the flip ---------------------------
def fig_foam():
    if not FOAM or not LEXT:
        return
    # §13 post-proc outlet totals (the fragile flip) vs grounded model
    lo = sorted([r for r in LEXT["rows"] if r["pos"] == "outlet" and r["cover"] > 0], key=lambda r: r["cover"])
    go = sorted([r for r in FOAM["ref_case"]["rows"] if r["pos"] == "outlet"], key=lambda r: r["cover"])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.4, 4.0))
    # left: outlet total dV vs cover — two models
    a1.plot([r["cover"] * 100 for r in lo], [r["total_dV"] for r in lo], "-o", color=GLD, lw=1.9, ms=6,
            mfc="white", label="§13 post-proc (assumed feed)")
    a1.plot([r["cover"] * 100 for r in go], [r["total_dV"] for r in go], "-^", color=ACC, lw=2, ms=7,
            mfc="white", label="grounded foam model")
    # mark the fragile flip peak
    kk = max(range(len(lo)), key=lambda i: lo[i]["total_dV"])
    a1.scatter([lo[kk]["cover"] * 100], [lo[kk]["total_dV"]], s=150, facecolor="none", edgecolor=GLD, lw=2, zorder=5)
    a1.annotate("fragile flip\n(assumption)", (lo[kk]["cover"] * 100, lo[kk]["total_dV"]),
                xytext=(38, lo[kk]["total_dV"] - 22), fontsize=8.5, color=GLD)
    a1.annotate("grounded → 100% wins", (100, go[-1]["total_dV"]), xytext=(40, go[-1]["total_dV"] + 4),
                fontsize=8.5, color=ACC, fontweight="bold")
    a1.set_xlabel("outlet mesh cover [%]"); a1.set_ylabel("ΔV @1000 [mV]")
    a1.set_title("Does outlet-partial beat full?"); a1.legend(frameon=False, fontsize=8.5, loc="lower right")
    # right: flip threshold — no flip at any entry-blocking
    qt = FOAM.get("q_threshold", [])
    a2.bar([f'{q["q_eff"]:.2f}' for q in qt], [q["outlet_best_cover"] * 100 for q in qt],
           color=[GRN if q["flip"] else "#c7cdd8" for q in qt], edgecolor="#5b6472", linewidth=0.6)
    a2.axvspan(-0.5, 1.5, color="#eef2f8", zorder=0)
    a2.text(0.5, 50, "geometric\nmax (≤0.5)", ha="center", fontsize=8, color=MUT)
    a2.set_ylim(0, 112); a2.axhline(100, color=MUT, lw=0.8, ls=":")
    a2.set_xlabel("foam water-entry blocking  q_eff"); a2.set_ylabel("optimal outlet cover [%]")
    a2.set_title("No flip at ANY blocking (even hydrophobic)")
    save(fig, "fig_foam.svg")


if __name__ == "__main__":
    print("rendering figures ...")
    fig_calib(); fig_catalog_lsv(); fig_catalog_bar(); fig_coverage()
    fig_flow(); fig_thickness(); fig_open_pore(); fig_eis()
    fig_mechanism(); fig_mechanism_j(); fig_overpot(); fig_profile()
    fig_reversal(); fig_block_growth(); fig_lambda(); fig_foam()
    print("figs ->", FIG)
