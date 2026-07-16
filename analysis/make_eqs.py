# -*- coding: utf-8 -*-
"""Render the governing equations to standalone SVG (LaTeX-style, self-contained)
so the report can show WHY each figure's numbers come out as they do.
Equations -> analysis/out/figs/eq_*.svg
"""
from pathlib import Path
import matplotlib
matplotlib.use("svg")
import matplotlib.pyplot as plt
from matplotlib import rcParams

rcParams["mathtext.fontset"] = "cm"       # Computer-Modern (LaTeX look)
rcParams["svg.fonttype"] = "path"         # glyphs as paths (renders anywhere)

FIG = Path(__file__).resolve().parent / "out" / "figs"
FIG.mkdir(parents=True, exist_ok=True)
INK = "#1b2740"

EQS = {
    # --- cell-voltage backbone (all figures) ---
    "vcell": r"$V_{cell}=E_{rev}+\eta_{act,a}+\eta_{act,c}+\eta_{ohm}+\eta_{conc}+\eta_{water}$",
    "bv":    r"$j=(1-\theta)\,j_0\left[e^{\,\alpha_a f\eta}-e^{-\alpha_c f\eta}\right],\quad f=\dfrac{F}{RT}$",
    "etacov": r"$\eta_{cov}=\dfrac{RT}{\alpha F}\,\ln\dfrac{1}{1-\theta}$",
    # --- channel gas accumulation (figs 4,5,7,11) ---
    "accum": r"$\dfrac{V_{gas}}{Q}=\dfrac{RT/P}{z F\,u\,d_{ch}}\int_0^{s}\! j\,ds'$",
    "eps":   r"$\varepsilon(s)=\dfrac{V_{gas}/Q}{1+V_{gas}/Q}$",
    "theta": r"$\theta=\theta_{max}(1-P_{cap})(1-e^{-k\varepsilon})$",
    # --- mesh three actions (figs 1,2,3,8,9) ---
    "wick":  r"$P_{contact,UB}=1-\phi\,\max(1-d_b/L_x,0)\,\max(1-d_b/L_y,0)$",
    "peel":  r"$P_{wet}=\max\!\left[0,\dfrac{\cos\theta_e-\cos\theta_m}{1+\cos\theta_e}\right],\quad P_{cap}=P_{contact}P_{wet}$",
    "sweep": r"$\chi=(1-\varphi)\dfrac{t_m}{d_{ch}},\quad u_{boost}=\dfrac{1}{1-\chi},\quad retention=1-\chi$",
    "block": r"$\dfrac{\Delta P}{\Delta P_0}\simeq u_{boost}^{3}\quad(\mathrm{laminar\ fixed\ flow})$",
    # --- why-decomposition (fig 1) ---
    "decomp": r"$\Delta V_{net}=\Delta V_{transfer}+\Delta V_{residence},\quad \Delta V_k=V_{before}-V_{after}$",
    # --- EIS (fig 12) ---
    "rct":   r"$R_{ct}=\left[(1-\theta)j_0\,\dfrac{F}{RT}\left(\alpha_a e^{\alpha_a f\eta}+\alpha_c e^{-\alpha_c f\eta}\right)\right]^{-1}$",
    "zcell": r"$Z(\omega)=R_s+\sum_e\dfrac{R_{ct,e}+Z_{W,e}}{1+(R_{ct,e}+Z_{W,e})\,i\omega C_{dl,e}}$",
    # --- dry-cathode water limit ---
    "water": r"$j_{lim,w}=\dfrac{F\,k_w}{1+n_{drag}},\ \ k_w=\dfrac{D_w c_w}{t_{mem}},\ \ \eta_{water}=-\dfrac{RT}{F}\ln\!\left(1-\dfrac{j}{j_{lim,w}}\right)$",
    # --- Ni-foam lambda(x) extension (figs 13,16) ---
    "foamW": r"$\dfrac{dW}{dx}=k_s(1-\varepsilon)(1-q\,c)-k_d\,\varepsilon$",
    "zwet":  r"$z_{wet}(x)=L_{foam}\,W(x)^{m}$",
    "foamdV": r"$\Delta V_{foam}=\dfrac{RT}{\alpha_a F}\left\langle\ln\dfrac{z_{wet}^{mesh}}{z_{wet}^{pris}}\right\rangle_x$",
}


def render(key, tex, fs=20):
    fig = plt.figure(figsize=(0.1, 0.1))
    fig.text(0.0, 0.0, tex, fontsize=fs, color=INK)
    fig.savefig(FIG / f"eq_{key}.svg", bbox_inches="tight", pad_inches=0.06, transparent=True)
    plt.close(fig)
    print("  ->", f"eq_{key}.svg")


if __name__ == "__main__":
    print("rendering equations ...")
    ok = 0
    for k, tex in EQS.items():
        try:
            render(k, tex); ok += 1
        except Exception as e:
            print(f"  !! {k}: {e}")
    print(f"{ok}/{len(EQS)} equations -> {FIG}")
