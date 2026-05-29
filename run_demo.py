"""Demo + research-grade figures for bubblesim.

Runs the coupled model and writes four figures to outputs/:
  1. current(t) sawtooth + coverage at a fixed operating point
  2. polarization curve: with bubbles vs ideal (bubble-free) baseline
  3. wettability sweep: current & coverage vs contact angle
  4. control-lever comparison: flow, B-field, E-field vs current

Usage:  python run_demo.py
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from bubblesim import Simulator, Operating, Params
from bubblesim.sweeps import polarization, sweep

OUT = os.path.join(os.path.dirname(__file__), "outputs")
os.makedirs(OUT, exist_ok=True)


def fig_transient():
    sim = Simulator(Operating(V_cell=2.0, contact_angle=70, u_flow=0.0), seed=3)
    h = sim.run(t_end=3.0, dt=2e-4)
    fig, ax1 = plt.subplots(figsize=(9, 4.5))
    ax1.plot(h["t"], h["j"], color="#1f77b4", lw=1.0, label="current density j")
    ax1.set_xlabel("time [s]")
    ax1.set_ylabel("j  [A/cm$^2$]", color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")
    ax2 = ax1.twinx()
    ax2.plot(h["t"], h["theta"], color="#d62728", lw=1.0, alpha=0.8, label="coverage")
    ax2.set_ylabel(r"bubble coverage $\theta$", color="#d62728")
    ax2.tick_params(axis="y", labelcolor="#d62728")
    ax1.set_title("Current sawtooth: bubbles grow (j drops) then detach (j jumps)\n"
                  "V = 2.0 V, contact angle 70 deg, no flow")
    fig.tight_layout()
    p = os.path.join(OUT, "1_transient_sawtooth.png")
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def fig_polarization():
    V = [1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2, 2.4, 2.6]
    real = polarization(V, base_op=Operating(contact_angle=70), t_end=1.2, dt=2e-4)
    ideal = polarization(V, base_op=Operating(contact_angle=70),
                         params=Params(site_density=0.0), t_end=1.2, dt=2e-4)
    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.plot(ideal["j"], ideal["V"], "k--", marker="o", ms=4,
            label="ideal (no bubbles)")
    ax.plot(real["j"], real["V"], color="#1f77b4", marker="s", ms=4,
            label="with bubble coverage + void")
    ax.set_xlabel("mean current density  [A/cm$^2$]")
    ax.set_ylabel("cell voltage  [V]")
    ax.set_title("Polarization curve: bubbles add overpotential\n"
                 "(same current needs more voltage)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p = os.path.join(OUT, "2_polarization.png")
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def fig_wettability():
    angles = [15, 30, 45, 60, 75, 90, 110, 130, 150]
    s = sweep("contact_angle", angles, base_op=Operating(V_cell=2.0),
              t_end=1.2, dt=2e-4)
    fig, ax1 = plt.subplots(figsize=(8, 5))
    ax1.plot(s["contact_angle"], s["j"], color="#1f77b4", marker="o",
             label="current density")
    ax1.set_xlabel("contact angle  [deg]   (hydrophilic -> hydrophobic)")
    ax1.set_ylabel("j  [A/cm$^2$]", color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")
    ax2 = ax1.twinx()
    ax2.plot(s["contact_angle"], s["theta"], color="#d62728", marker="s",
             label="coverage")
    ax2.plot(s["contact_angle"], s["eps"], color="#ff7f0e", marker="^",
             ls="--", label="void fraction")
    ax2.set_ylabel(r"$\theta$, $\varepsilon$", color="#d62728")
    ax2.tick_params(axis="y", labelcolor="#d62728")
    ax1.set_title("Wettability controls bubbles:\n"
                  "wetting (low angle) = small bubbles, low coverage, high current")
    fig.legend(loc="upper right", bbox_to_anchor=(0.88, 0.88))
    fig.tight_layout()
    p = os.path.join(OUT, "3_wettability.png")
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def fig_levers():
    flow = sweep("u_flow", [0, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5],
                 base_op=Operating(V_cell=2.0), t_end=1.0, dt=2.5e-4)
    bfield = sweep("B_field", [0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0],
                   base_op=Operating(V_cell=2.0), t_end=1.0, dt=2.5e-4)
    efield = sweep("E_ext", [0, 1e5, 3e5, 5e5, 1e6, 2e6, 3e6],
                   base_op=Operating(V_cell=2.0), t_end=1.0, dt=2.5e-4)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    axes[0].plot(flow["u_flow"], flow["j"], "o-", color="#1f77b4")
    axes[0].set_xlabel("cross-flow velocity [m/s]")
    axes[0].set_title("Forced flow")
    axes[1].plot(bfield["B_field"], bfield["j"], "s-", color="#2ca02c")
    axes[1].set_xlabel("magnetic field [T]")
    axes[1].set_title("Magnetic field (MHD)")
    axes[2].plot([e / 1e6 for e in efield["E_ext"]], efield["j"], "^-",
                 color="#9467bd")
    axes[2].set_xlabel("near-surface field [MV/m]")
    axes[2].set_title("Electric field (DEP)")
    for ax in axes:
        ax.set_ylabel("mean j [A/cm$^2$]")
        ax.grid(alpha=0.3)
    fig.suptitle("Each lever clears bubbles -> raises current (V = 2.0 V fixed)",
                 y=1.02)
    fig.tight_layout()
    p = os.path.join(OUT, "4_control_levers.png")
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


if __name__ == "__main__":
    print("running bubblesim demo (this takes ~30-60 s) ...")
    for fn in (fig_transient, fig_polarization, fig_wettability, fig_levers):
        path = fn()
        print("  wrote", os.path.relpath(path))
    print("done. open the outputs/ folder.")
