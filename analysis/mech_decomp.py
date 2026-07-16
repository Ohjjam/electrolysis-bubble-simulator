# -*- coding: utf-8 -*-
"""Voltage decomposition for the revised contact-angle mesh model.

The cumulative counterfactual order is:
  1) calculated bubble/opening contact × Young-equation wetting drive,
  2) gas residence reduction from the mesh solid-volume flow acceleration,
  3) catalyst-area blockage is reported as unmodelled, not inferred from solid
     channel volume.

No L_ref, wick, C_theta, C_ret, or C_block constants remain.
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))

import mesh_study as ms
import bubblesim.solvers.channel as chan
from bubblesim.kernel.meshlayer import operating_mesh_factors as real_operating_mesh_factors

OUT = ROOT / "analysis" / "out"
REF = ms.REF_MESH
D0 = ms.D0
_OVERRIDE = {"mode": None}


def _patched(op, props, j):
    real = real_operating_mesh_factors(op, props, j)
    mode = _OVERRIDE["mode"]
    if mode is None or not real["fits"]:
        return real
    out = dict(real)
    if mode == "capture":
        out.update(retention_factor=1.0, blocking_fraction=0.0)
    elif mode == "capture_flow":
        out.update(blocking_fraction=0.0)
    elif mode == "full":
        pass
    return out


chan.operating_mesh_factors = _patched


def solve_at(j, mode):
    from bubblesim import Simulator
    _OVERRIDE["mode"] = mode
    mesh = None if mode == "pristine" else REF
    dd = dict(D0)
    dd["mesh_id"] = ""
    op = ms._apply_mesh(ms.sweep_operating(dd, j), mesh)
    sim = Simulator(op=op, params=ms.build_params(D0))
    st = chan.ChannelSolver().solve(op, sim.props(), sim.surfaces)
    _OVERRIDE["mode"] = None
    return st


def V_at(j, mode):
    st = solve_at(j, mode)
    return float(st.V) * 1000.0, st


_TOP = ("E_rev", "eta_act_anode", "eta_act_cathode", "eta_ohmic", "eta_conc", "eta_water")
_SUB = ("eta_bub_cov_anode", "eta_bub_cov_cathode", "eta_bub_void")


def overpot(st):
    s = st.overpotentials
    top = {k: round(float(s.get(k, 0.0)) * 1000, 1) for k in _TOP}
    sub = {k: round(float(s.get(k, 0.0)) * 1000, 1) for k in _SUB}
    return top, sub


def _means(st):
    prof = st.fields.get("path_prof") or {}
    theta = float(np.mean(prof.get("theta") or [st.fields["theta_out"]]))
    eps = float(np.mean(prof.get("eps") or [st.fields["eps_out"]]))
    return theta, eps


def decomp_at(j):
    v0, s0 = V_at(j, "pristine")
    v1, _ = V_at(j, "capture")
    v2, _ = V_at(j, "capture_flow")
    v3, s3 = V_at(j, "full")
    steps = {
        "접촉·젖음성 포획": v0 - v1,
        "유로 폐색에 따른 체류시간 감소": v1 - v2,
        "촉매 접촉·압착 차단 (미모델링)": v2 - v3,
    }
    th0, ep0 = _means(s0)
    th3, ep3 = _means(s3)
    top_p, sub_p = overpot(s0)
    top_m, sub_m = overpot(s3)
    return {
        "j": j, "V_pristine": round(v0, 1), "V_full": round(v3, 1),
        "net_mV": round(v0 - v3, 1),
        "steps_mV": {k: round(v, 1) for k, v in steps.items()},
        "theta_pristine": round(th0, 4), "theta_mesh": round(th3, 4),
        "eps_mean_pristine": round(ep0, 4), "eps_mean_mesh": round(ep3, 4),
        "eps_out_pristine": round(float(s0.fields["eps_out"]), 4),
        "eps_out_mesh": round(float(s3.fields["eps_out"]), 4),
        "overpot_pristine": top_p, "overpot_mesh": top_m,
        "overpot_sub_pristine": sub_p, "overpot_sub_mesh": sub_m,
        "V_check_pristine": round(float(s0.V) * 1000, 1),
        "V_check_mesh": round(float(s3.V) * 1000, 1),
    }


def profiles(j):
    return {"pristine": solve_at(j, "pristine").fields.get("path_prof"),
            "mesh": solve_at(j, "full").fields.get("path_prof")}


def factors_at(j=1000):
    from bubblesim import Simulator
    dd = dict(D0)
    dd["mesh_id"] = ""
    op = ms._apply_mesh(ms.sweep_operating(dd, j), REF)
    sim = Simulator(op=op, params=ms.build_params(D0))
    f = real_operating_mesh_factors(op, sim.props(), op.j_set)
    keep = ("bubble_d_mm", "hole_x_mm", "hole_y_mm", "electrode_angle_deg",
            "mesh_angle_deg", "contact_prob", "wetting_drive", "capture_eff",
            "obstruction", "flow_open_frac", "u_boost", "dp_ratio",
            "theta_factor", "retention_factor", "blocking_fraction", "warn")
    out = {k: f[k] for k in keep}
    out.update(hole_mm=REF["hole_mm"], open=REF["open"], t_mm=REF["t_mm"],
               d_ch_mm=D0["d_ch_mm"])
    return out


def main():
    factors = factors_at(1000)
    out = {"model_version": "contact-angle-v2", "ref_mesh": REF,
           "factors": factors,
           "decomp": {str(j): decomp_at(j) for j in (500, 1000, 2000)},
           "profiles_1000": profiles(1000)}
    (OUT / "decomp.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    with open(OUT / "mech_decomposition.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["j_mAcm2", "작용", "기여_mV(+절감/-손해)"])
        for j, d in out["decomp"].items():
            for k, v in d["steps_mV"].items():
                w.writerow([j, k, v])
            w.writerow([j, "= 순이득", d["net_mV"]])

    d1 = out["decomp"]["1000"]
    with open(OUT / "overpotential_split.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["항목", "pristine_mV", "mesh_mV", "차이_mV(+절감)"])
        for k in d1["overpot_pristine"]:
            a, b = d1["overpot_pristine"][k], d1["overpot_mesh"][k]
            w.writerow([k, a, b, round(a - b, 1)])
        w.writerow([])
        w.writerow(["# 하위성분", "pristine", "mesh", ""])
        for k in d1["overpot_sub_pristine"]:
            w.writerow([k, d1["overpot_sub_pristine"][k], d1["overpot_sub_mesh"][k], ""])

    print("=== REVISED MESH DECOMPOSITION ===")
    print("factors:", json.dumps(factors, ensure_ascii=False))
    for j in (500, 1000, 2000):
        d = out["decomp"][str(j)]
        print(f"j={j}: {d['V_pristine']} -> {d['V_full']} mV; net {d['net_mV']:+.1f} mV")
        for k, v in d["steps_mV"].items():
            print(f"  {k}: {v:+.1f} mV")


if __name__ == "__main__":
    main()
