# -*- coding: utf-8 -*-
"""Bubble-management mesh parameter study (blind-prediction protocol).

Runs the SAME calibrated channel-bottleneck model the experiment tab uses
(bubblesim.solvers.channel + kernel.meshlayer), sweeping one mesh/operation
knob at a time around the calibrated 13-channel serpentine AEM cell, and dumps
polarization (LSV) curves + derived efficiency metrics + EIS spectra as CSVs.

IMPORTANT: the model is calibrated on the PRISTINE measured curve only. No mesh
polarization measurement enters the model. Mesh curves use geometry, the
force-balance departure diameter, and explicit electrode/PP contact angles.

Run:
  python analysis/mesh_study.py --smoke   # wiring check, prints ctx keys
  python analysis/mesh_study.py           # full study -> analysis/out/*.csv + summary.json
"""
import sys
import os
import json
import csv
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bubblesim import Params, Simulator                      # noqa: E402
from bubblesim.config import ElectrodeParams                 # noqa: E402
from bubblesim.solvers.channel import ChannelSolver          # noqa: E402
from bubblesim.kernel import impedance as imp                # noqa: E402
from bubblesim.constants import F, R_GAS                     # noqa: E402
from bubblesim3d.params3d import sweep_operating, MESH_CATALOG, mesh_spec  # noqa: E402

OUT = ROOT / "analysis" / "out"
OUT.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Calibrated baseline = the experiment-tab EXP_PRESET (13-ch serpentine AEM,
# dry cathode ON, re-fit RMSE 26 mV on the 16 measured pristine points).
# ---------------------------------------------------------------------------
D0 = {
    "W_cm": 2.2, "H_cm": 2.2, "ff": "serp", "n_ch": 13, "w_ch_mm": 0.88,
    "d_ch_mm": 0.9, "w_land_mm": 0.88, "t_ptl_um": 600, "eps_ptl": 0.95,
    "electrolyte": "KOH", "c_mol": 1.0, "T": 65, "u_flow": 0.0842,
    "mode": "CP", "j": 0.5,
    # Representative untreated surfaces used only by the mesh-transfer model.
    # Bare Ni foam: 110 deg; untreated PP mesh: 105.8 deg (sessile-water angle).
    "theta": 110.0, "mesh_theta": 105.8,
    "j0_anode": 6.3e-4, "j0_cathode": 6500, "alpha_a": 1.19, "r_mem": 1.33e-5,
    "gap_mm": 0.5, "void_frac": 0.81,
    "dry_cathode": "1", "n_drag": 2.5, "D_w_mem": 1.6e-9, "t_mem_um": 50,
}

# Measured pristine polarization the model was calibrated against (j mA/cm^2 -> V).
EXP_MEAS = [[10, 1.48294], [20, 1.4937], [50, 1.5184], [100, 1.55191],
            [200, 1.60495], [300, 1.65078], [400, 1.69504], [500, 1.74178],
            [625, 1.80051], [750, 1.86602], [875, 1.94376], [1000, 2.03323],
            [1250, 2.20449], [1500, 2.37841], [2000, 2.6616], [2250, 2.78376]]

SWEEP_J = [10, 20, 50, 100, 200, 300, 400, 500, 625, 750, 875,
           1000, 1250, 1500, 2000, 2250]                 # mA/cm^2

# The physical PP mesh used in the real cell (0.040"x0.053"): the anchor we vary
# each axis around, so single-axis sweeps isolate one geometric effect.
REF_MESH = {"hole_mm": 1.181, "hole_x_mm": 1.016, "hole_y_mm": 1.346,
            "open": 0.50, "t_mm": 0.483, "cover": 1.0, "pos": "outlet"}

THERMONEUTRAL_V = 1.481    # water-splitting thermoneutral voltage (efficiency ref)


def build_params(d):
    """Same Params the server's _sweep_params builds (calibrated kinetics)."""
    return Params(
        fritz_scale=0.08,
        anode=ElectrodeParams("OER", j0_ref=max(1e-12, float(d["j0_anode"])),
                              alpha_a=min(2.0, max(0.1, float(d["alpha_a"]))),
                              Ea_j0=50.0e3),
        cathode=ElectrodeParams("HER", j0_ref=max(1e-9, float(d["j0_cathode"])),
                                Ea_j0=30.0e3),
        r_membrane_area=max(0.0, float(d["r_mem"])))


def _apply_mesh(op, mesh):
    if mesh:
        op.mesh_hole_mm = float(mesh["hole_mm"])
        op.mesh_hole_x_mm = float(mesh.get("hole_x_mm", mesh["hole_mm"]))
        op.mesh_hole_y_mm = float(mesh.get("hole_y_mm", mesh["hole_mm"]))
        op.mesh_open = float(mesh["open"])
        op.mesh_t_mm = float(mesh["t_mm"])
        op.mesh_contact_angle = float(mesh.get("mesh_theta", op.mesh_contact_angle))
        op.mesh_cover = min(1.0, max(0.0, float(mesh.get("cover", 1.0))))
        op.mesh_pos = str(mesh.get("pos", "outlet"))
    return op


def run_lsv(d, mesh=None):
    """One polarization curve. mesh=dict(hole_mm,open,t_mm,cover,pos) or None.

    Returns per-j arrays + the split/fields/ctx at the highest j (for EIS)."""
    params = build_params(d)
    solver = ChannelSolver()
    dd = dict(d); dd["mesh_id"] = ""                        # inject mesh by hand, not catalog
    V, ju, reach, th_out, ep_out = [], [], [], [], []
    last = None
    for j in SWEEP_J:
        op = _apply_mesh(sweep_operating(dd, j), mesh)
        sim = Simulator(op=op, params=params)
        ctx = sim.props()
        st = solver.solve(op, ctx, sim.surfaces)
        j_used = float(st.j) / 10.0                          # A/m^2 -> mA/cm^2
        V.append(float(st.V)); ju.append(j_used)
        reach.append(bool(j_used >= 0.999 * j))
        th_out.append(float(st.fields["theta_out"]))
        ep_out.append(float(st.fields["eps_out"]))
        last = (st, ctx, op)
    st, ctx, op = last
    prof = st.fields.get("path_prof") or {}
    th_mean = float(np.mean(prof["theta"])) if prof.get("theta") else float(st.fields["theta_out"])
    split = {k: float(v) for k, v in st.overpotentials.items()
             if isinstance(v, (int, float))}
    fields = {k: st.fields.get(k) for k in
              ("mesh_on", "mesh_bubble_d_mm", "mesh_contact_prob",
               "mesh_wetting_drive", "mesh_capture_eff", "mesh_obstruction",
               "mesh_u_boost", "mesh_dp_ratio", "mesh_blocking_fraction",
               "mesh_electrode_angle", "mesh_contact_angle", "mesh_warn", "mesh_mask_frac",
               "theta_in", "theta_out", "eps_out", "eff_in", "eff_out", "up_frac")}
    return dict(j=list(SWEEP_J), V=V, j_used=ju, reachable=reach,
                theta_out=th_out, eps_out=ep_out, split_jmax=split,
                fields=fields, theta_mean_jmax=th_mean, mesh=mesh)


def Vat(res, j_target):
    """Cell voltage at a target current density (interp on delivered j)."""
    ju = np.asarray(res["j_used"]); V = np.asarray(res["V"])
    order = np.argsort(ju)
    return float(np.interp(j_target, ju[order], V[order]))


def metrics(res, pristine=None):
    """Derived efficiency numbers for one curve."""
    v500, v1000 = Vat(res, 500.0), Vat(res, 1000.0)
    m = {
        "V@500mV": round(v500 * 1000, 1),
        "V@1000mV": round(v1000 * 1000, 1),
        "eff@500_%": round(100 * THERMONEUTRAL_V / v500, 1),
        "eff@1000_%": round(100 * THERMONEUTRAL_V / v1000, 1),
        "theta_out@jmax": round(res["theta_out"][-1], 4),
        "eps_out@jmax": round(res["eps_out"][-1], 4),
        "theta_mean@jmax": round(res["theta_mean_jmax"], 4),
        "mesh_on": bool(res["fields"].get("mesh_on")),
        "mesh_bubble_d_mm": res["fields"].get("mesh_bubble_d_mm"),
        "mesh_contact_prob": res["fields"].get("mesh_contact_prob"),
        "mesh_wetting_drive": res["fields"].get("mesh_wetting_drive"),
        "mesh_capture_eff": res["fields"].get("mesh_capture_eff"),
        "mesh_obstruction": res["fields"].get("mesh_obstruction"),
        "mesh_u_boost": res["fields"].get("mesh_u_boost"),
        "mesh_dp_ratio": res["fields"].get("mesh_dp_ratio"),
        "mesh_warn": res["fields"].get("mesh_warn") or "",
    }
    if pristine is not None:
        m["dV@500_mV"] = round((Vat(pristine, 500.0) - v500) * 1000, 1)   # +ve = mesh saves V
        m["dV@1000_mV"] = round((Vat(pristine, 1000.0) - v1000) * 1000, 1)
    return m


def build_eis(d, mesh, j_macm2):
    """EIS spectrum at one operating point, mirroring cell3d.eis but fed the
    channel-model (mesh-affected) path-mean coverage. ohm*cm^2."""
    params = build_params(d)
    solver = ChannelSolver()
    dd = dict(d); dd["mesh_id"] = ""
    op = _apply_mesh(sweep_operating(dd, j_macm2), mesh)
    sim = Simulator(op=op, params=params)
    ctx = sim.props()
    st = solver.solve(op, ctx, sim.surfaces)
    prof = st.fields.get("path_prof") or {}
    th = float(np.mean(prof["theta"])) if prof.get("theta") else float(st.fields["theta_out"])
    j = max(float(st.j), 1e-3)                               # A/m^2
    ov = st.overpotentials
    T = op.T
    R_s = ov.get("eta_ohmic", 0.0) / j                      # ohm*m^2
    Rct_a = imp.r_ct_bv(max(1e-3, 1 - th) * ctx["j0_anode"],
                        ctx["alpha_a_anode"], ctx["alpha_c_anode"],
                        ov.get("eta_act_anode", 0.0), T)
    Rct_c = imp.r_ct_bv(max(1e-3, 1 - th) * ctx["j0_cathode"],
                        ctx["alpha_a_cathode"], ctx["alpha_c_cathode"],
                        ov.get("eta_act_cathode", 0.0), T)
    j_lim = ctx["j_lim_transport"]; z = ctx["z_primary"]
    R_d = (R_GAS * T / (z * F)) / max(j_lim - j, 1e-3)
    delta = min(ctx.get("delta_bl", 3e-5), 0.8 * ctx.get("gap_m", 5e-4))
    tau_d = delta * delta / max(ctx.get("D_carrier", 3e-9), 1e-12)
    Ca = max(1e-3, params.anode.C_dl) * max(1e-3, 1 - th)
    Cc = max(1e-3, params.cathode.C_dl) * max(1e-3, 1 - th)
    els = [{"R_ct": Rct_a, "C_dl": Ca, "R_d": 0.5 * R_d, "tau_d": tau_d},
           {"R_ct": Rct_c, "C_dl": Cc, "R_d": 0.5 * R_d, "tau_d": tau_d}]
    freqs = imp.log_freqs(0.1, 1e6, 60)
    Z = imp.cell_impedance(freqs, R_s, els)
    return dict(
        f=list(freqs),
        re=[z_.real * 1e4 for z_ in Z], im=[-z_.imag * 1e4 for z_ in Z],
        Rs=R_s * 1e4, Rct_a=Rct_a * 1e4, Rct_c=Rct_c * 1e4,
        Rct_tot=(Rct_a + Rct_c) * 1e4, theta_mean=th, j_macm2=j / 10.0)


# ---------------------------------------------------------------------------
def _csv(name, header, rows):
    p = OUT / name
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
    return p.name


def smoke():
    print("=== SMOKE ===")
    res = run_lsv(D0, None)
    print("ctx keys sample:", "ok")
    # print a couple of ctx keys via a fresh solve
    params = build_params(D0)
    op = sweep_operating({**D0, "mesh_id": ""}, 500)
    ctx = Simulator(op=op, params=params).props()
    want = ["j0_anode", "j0_cathode", "alpha_a_anode", "alpha_c_anode",
            "alpha_a_cathode", "alpha_c_cathode", "j_lim_transport", "z_primary",
            "delta_bl", "gap_m", "D_carrier"]
    print("ctx has:", {k: (k in ctx) for k in want})
    print("split_jmax keys:", sorted(res["split_jmax"].keys()))
    print("pristine V:", [round(v, 4) for v in res["V"]])
    # calibration RMSE against measured
    meas = {j: v for j, v in EXP_MEAS}
    err = [(Vat(res, j) - meas[j]) * 1000 for j, _ in EXP_MEAS]
    rmse = (sum(e * e for e in err) / len(err)) ** 0.5
    print(f"pristine RMSE vs measured = {rmse:.1f} mV")
    mres = run_lsv(D0, REF_MESH)
    print("ref-mesh metrics:", metrics(mres, res))
    eis0 = build_eis(D0, None, 500)
    print("EIS pristine @500: Rs=%.3f Rct=%.3f theta=%.3f"
          % (eis0["Rs"], eis0["Rct_tot"], eis0["theta_mean"]))
    print("=== SMOKE OK ===")


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        smoke()
    else:
        from mesh_study_run import main
        main(globals())
