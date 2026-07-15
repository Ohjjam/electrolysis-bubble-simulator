# -*- coding: utf-8 -*-
"""WHY does the mesh help? Decompose the benefit into the model's three physical
actions by turning them on one at a time (a voltage waterfall).

The meshlayer maps geometry -> three factors that the channel solver applies on
the covered path:
  1) theta_factor   = 1 - 0.6*wick      : "떼어냄" — bubbles wicked OFF the
                                            catalyst wall, coverage amplitude cut
  2) retention_factor = (1-0.5*wick)/sqrt(u_boost) : "밀어냄" — local wall holdup
                                            swept out; two sub-parts:
                                            R_wick=(1-0.5*wick)  (strand drainage)
                                            R_sweep=1/sqrt(u_boost) (faster flow)
  3) theta_add      = 0.3*(1-phi)*(t/d) : "차단" — mesh blocks liquid access,
                                            adds a coverage FLOOR (the downside)

We monkeypatch mesh_factors to hand the solver a factor dict with only some
actions enabled, run the SAME LSV, and read V. The mV steps between cumulative
scenarios are each action's contribution. Order-dependent (cumulative
attribution) — stated as such in the report.
"""
import sys
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))

import mesh_study as ms
import bubblesim.solvers.channel as chan
from bubblesim.kernel.meshlayer import mesh_factors as real_mesh_factors

OUT = ROOT / "analysis" / "out"

REF = ms.REF_MESH                       # pp_040x053, full cover, outlet
D0 = ms.D0
C_RET = 0.5

# scenario override: a dict the patched mesh_factors returns (or None = real)
_OVERRIDE = {"mode": None}


def _patched(hole_mm, open_frac, t_mm, d_ch_mm):
    real = real_mesh_factors(hole_mm, open_frac, t_mm, d_ch_mm)
    mode = _OVERRIDE["mode"]
    if mode is None or not real["fits"]:
        return real
    wick = real["wick"]; u_boost = real["u_boost"]
    R_wick = 1.0 - C_RET * wick
    R_sweep = 1.0 / math.sqrt(u_boost)
    tf = real["theta_factor"]; ta = real["theta_add"]
    out = dict(real)
    if mode == "peel":                  # 1) 떼어냄 only
        out.update(theta_factor=tf, retention_factor=1.0, theta_add=0.0)
    elif mode == "peel_drain":          # + wicking drainage of holdup
        out.update(theta_factor=tf, retention_factor=R_wick, theta_add=0.0)
    elif mode == "peel_drain_sweep":    # + faster-flow sweep (encroachment)
        out.update(theta_factor=tf, retention_factor=R_wick * R_sweep, theta_add=0.0)
    elif mode == "full":                # + blocking floor = full mesh
        out.update(theta_factor=tf, retention_factor=R_wick * R_sweep, theta_add=ta)
    return out


chan.mesh_factors = _patched            # install


def V_at(j, mode):
    _OVERRIDE["mode"] = mode
    mesh = None if mode == "pristine" else REF
    res = ms.run_lsv(D0, mesh)
    _OVERRIDE["mode"] = None
    return ms.Vat(res, j) * 1000.0, res


# top-level additive terms (sum to V_cell); eta_bub_* are nested sub-components
_TOP = ("E_rev", "eta_act_anode", "eta_act_cathode", "eta_ohmic", "eta_conc", "eta_water")
_SUB = ("eta_bub_cov_anode", "eta_bub_cov_cathode", "eta_bub_void")


def overpot_at(j, mode):
    """Single-point solve at EXACTLY j -> overpotential terms (mV)."""
    from bubblesim import Simulator
    _OVERRIDE["mode"] = mode
    mesh = None if mode == "pristine" else REF
    params = ms.build_params(D0)
    dd = dict(D0); dd["mesh_id"] = ""
    op = ms._apply_mesh(ms.sweep_operating(dd, j), mesh)
    sim = Simulator(op=op, params=params)
    st = chan.ChannelSolver().solve(op, sim.props(), sim.surfaces)
    _OVERRIDE["mode"] = None
    s = st.overpotentials
    top = {k: round(float(s.get(k, 0.0)) * 1000, 1) for k in _TOP}
    sub = {k: round(float(s.get(k, 0.0)) * 1000, 1) for k in _SUB}
    return top, sub, round(float(st.V) * 1000, 1)


def decomp_at(j):
    v0, r0 = V_at(j, "pristine")
    v1, _ = V_at(j, "peel")
    v2, _ = V_at(j, "peel_drain")
    v3, _ = V_at(j, "peel_drain_sweep")
    v4, r4 = V_at(j, "full")
    # cumulative contributions (mV, +ve = saves voltage)
    steps = {
        "떼어냄 (촉매 피복 완화)": v0 - v1,
        "밀어냄 · 그물 배수": v1 - v2,
        "밀어냄 · 유속 부스트": v2 - v3,
        "차단 (액 접근 막힘, 손해)": v3 - v4,   # negative
    }
    top_p, sub_p, vp = overpot_at(j, "pristine")
    top_m, sub_m, vm = overpot_at(j, "full")
    return {
        "j": j, "V_pristine": round(v0, 1), "V_full": round(v4, 1),
        "net_mV": round(v0 - v4, 1),
        "steps_mV": {k: round(v, 1) for k, v in steps.items()},
        "theta_pristine": round(r0["theta_mean_jmax"], 3),
        "theta_mesh": round(r4["theta_mean_jmax"], 3),
        "eps_out_pristine": round(r0["eps_out"][-1], 3),
        "eps_out_mesh": round(r4["eps_out"][-1], 3),
        "overpot_pristine": top_p, "overpot_mesh": top_m,
        "overpot_sub_pristine": sub_p, "overpot_sub_mesh": sub_m,
        "V_check_pristine": vp, "V_check_mesh": vm,
    }


def profiles(j):
    """theta(s) & eps(s) along the flow path, pristine vs mesh, at current j."""
    def prof(mode):
        _OVERRIDE["mode"] = mode
        mesh = None if mode == "pristine" else REF
        params = ms.build_params(D0)
        dd = dict(D0); dd["mesh_id"] = ""
        op = ms._apply_mesh(ms.sweep_operating(dd, j), mesh)
        from bubblesim import Simulator
        sim = Simulator(op=op, params=params)
        st = chan.ChannelSolver().solve(op, sim.props(), sim.surfaces)
        _OVERRIDE["mode"] = None
        return st.fields.get("path_prof")
    return {"pristine": prof("pristine"), "mesh": prof("full")}


def main():
    # real mesh factors for the reference mesh (report the raw numbers too)
    d_ch = D0["d_ch_mm"]
    real = real_mesh_factors(REF["hole_mm"], REF["open"], REF["t_mm"], d_ch)
    factors = {
        "hole_mm": REF["hole_mm"], "open": REF["open"], "t_mm": REF["t_mm"], "d_ch_mm": d_ch,
        "wick": round(real["wick"], 3), "u_boost": round(real["u_boost"], 3),
        "theta_factor": round(real["theta_factor"], 3),
        "retention_factor": round(real["retention_factor"], 3),
        "theta_add": round(real["theta_add"], 3),
        "R_wick": round(1 - C_RET * real["wick"], 3),
        "R_sweep": round(1 / math.sqrt(real["u_boost"]), 3),
    }
    out = {"ref_mesh": REF, "factors": factors,
           "decomp": {str(j): decomp_at(j) for j in (500, 1000, 2000)},
           "profiles_1000": profiles(1000)}

    (OUT / "decomp.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV: waterfall at each j
    with open(OUT / "mech_decomposition.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["j_mAcm2", "작용", "기여_mV(+절감/-손해)"])
        for j, d in out["decomp"].items():
            for k, v in d["steps_mV"].items():
                w.writerow([j, k, v])
            w.writerow([j, "= 순이득", d["net_mV"]])

    # CSV: overpotential split pristine vs mesh at 1000 (top-level, additive)
    d1 = out["decomp"]["1000"]
    with open(OUT / "overpotential_split.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["항목", "pristine_mV", "mesh_mV", "차이_mV(+절감)"])
        for k in d1["overpot_pristine"]:
            a, b = d1["overpot_pristine"][k], d1["overpot_mesh"][k]
            w.writerow([k, a, b, round(a - b, 1)])
        w.writerow([])
        w.writerow(["# 하위성분(위 항목에 이미 포함)", "pristine", "mesh", ""])
        for k in d1["overpot_sub_pristine"]:
            w.writerow([k, d1["overpot_sub_pristine"][k], d1["overpot_sub_mesh"][k], ""])

    print("=== MECHANISM DECOMPOSITION (ref mesh pp_040x053, full cover) ===")
    print("factors:", json.dumps(factors, ensure_ascii=False))
    for j in (500, 1000, 2000):
        d = out["decomp"][str(j)]
        print(f"\nj={j} mA/cm2:  pristine {d['V_pristine']} -> mesh {d['V_full']} mV  (net {d['net_mV']} mV saved)")
        print(f"  theta {d['theta_pristine']} -> {d['theta_mesh']} | eps_out {d['eps_out_pristine']} -> {d['eps_out_mesh']}")
        for k, v in d["steps_mV"].items():
            print(f"    {k:22s} {v:+6.1f} mV")
    print("\nwrote decomp.json, mech_decomposition.csv, overpotential_split.csv")


if __name__ == "__main__":
    main()
