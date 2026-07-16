# -*- coding: utf-8 -*-
"""Full mesh parameter study driver. Called by mesh_study.py's main().

Produces (in analysis/out/):
  lsv_*.csv       wide polarization curves (j_set + V per variant)  -> plot-ready
  metrics_*.csv   one row per variant (V@500, V@1000, eff, theta, dV vs pristine)
  eis_*.csv       wide Nyquist (freq + Zre/Zim per variant)
  eis_metrics.csv Rs / Rct / theta per variant
  summary.json    everything, structured, for the report writer
"""
import json


def _flow_mlmin(d, u):
    # serpentine = one continuous channel: Q = u * (w_ch * d_ch)
    A = (d["w_ch_mm"] * 1e-3) * (d["d_ch_mm"] * 1e-3)
    return u * A * 60e6


def main(g):
    D0 = g["D0"]; run_lsv = g["run_lsv"]; metrics = g["metrics"]
    build_eis = g["build_eis"]; Vat = g["Vat"]; _csv = g["_csv"]
    MESH_CATALOG = g["MESH_CATALOG"]; REF_MESH = g["REF_MESH"]
    SWEEP_J = g["SWEEP_J"]; EXP_MEAS = g["EXP_MEAS"]; OUT = g["OUT"]

    summary = {"baseline": dict(D0), "sweep_j": list(SWEEP_J),
               "thermoneutral_V": g["THERMONEUTRAL_V"], "axes": {}}

    # -- pristine reference (no mesh) --------------------------------------
    print("[1/8] pristine baseline ...")
    pris = run_lsv(D0, None)
    meas = {j: v for j, v in EXP_MEAS}
    err = [(Vat(pris, j) - meas[j]) * 1000 for j, _ in EXP_MEAS]
    rmse = (sum(e * e for e in err) / len(err)) ** 0.5
    summary["pristine"] = {"V": pris["V"], "metrics": metrics(pris),
                           "calib_RMSE_mV": round(rmse, 1)}
    print(f"      pristine RMSE vs measured = {rmse:.1f} mV")

    def lsv_wide(name, variants):
        """variants: list of (label, res). Writes j_set + one V col per label."""
        header = ["j_set_mAcm2"] + [lab for lab, _ in variants]
        rows = []
        for i, j in enumerate(SWEEP_J):
            rows.append([j] + [round(res["V"][i] * 1000, 1) for _, res in variants])  # mV
        return _csv(name, header, rows)

    def metrics_table(name, variants, extra_cols=None):
        extra_cols = extra_cols or []
        keys = ["V@500mV", "V@1000mV", "eff@500_%", "eff@1000_%",
                "theta_out@jmax", "theta_mean@jmax", "eps_out@jmax",
                "dV@500_mV", "dV@1000_mV", "mesh_bubble_d_mm",
                "mesh_contact_prob", "mesh_wetting_drive", "mesh_capture_eff",
                "mesh_obstruction", "mesh_u_boost", "mesh_dp_ratio", "mesh_warn"]
        header = ["variant"] + [c[0] for c in extra_cols] + keys
        rows = []
        table = []
        for lab, res in variants:
            m = metrics(res, pris)
            rows.append([lab] + [c[1](res) for c in extra_cols]
                        + [m.get(k, "") for k in keys])
            table.append({"variant": lab, **{c[0]: c[1](res) for c in extra_cols}, **m})
        _csv(name, header, rows)
        return table

    # -- AXIS 1: mesh THICKNESS (t_m) --------------------------------------
    print("[2/8] thickness sweep ...")
    T_VALS = [0.20, 0.30, 0.40, 0.48, 0.60, 0.75, 0.85]     # mm (d_ch = 0.9)
    thk = [(f"t={t:.2f}mm", run_lsv(D0, {**REF_MESH, "t_mm": t})) for t in T_VALS]
    thk_all = [("pristine", pris)] + thk
    lsv_wide("lsv_thickness.csv", thk_all)
    summary["axes"]["thickness"] = {
        "held": {"hole_mm": REF_MESH["hole_mm"], "open": REF_MESH["open"],
                 "cover": 1.0, "pos": "outlet", "d_ch_mm": D0["d_ch_mm"]},
        "table": metrics_table("metrics_thickness.csv", thk,
                               [("t_mm", lambda r: r["mesh"]["t_mm"])])}

    # -- AXIS 2: OPEN-AREA fraction (phi ~ wire spacing/density) -----------
    print("[3/8] open-area sweep ...")
    O_VALS = [0.15, 0.24, 0.35, 0.50, 0.65, 0.80]
    opn = [(f"phi={o:.2f}", run_lsv(D0, {**REF_MESH, "open": o})) for o in O_VALS]
    lsv_wide("lsv_open.csv", [("pristine", pris)] + opn)
    summary["axes"]["open_area"] = {
        "held": {"hole_mm": REF_MESH["hole_mm"], "t_mm": REF_MESH["t_mm"],
                 "cover": 1.0, "pos": "outlet"},
        "table": metrics_table("metrics_open.csv", opn,
                               [("open_frac", lambda r: r["mesh"]["open"])])}

    # -- AXIS 3: opening / PORE size (hole_mm) -----------------------------
    print("[4/8] pore-size sweep ...")
    H_VALS = [0.30, 0.46, 0.70, 1.00, 1.181, 2.00, 3.00]    # mm
    hol = [(f"hole={h:.2f}mm", run_lsv(
        D0, {**REF_MESH, "hole_mm": h, "hole_x_mm": h, "hole_y_mm": h})) for h in H_VALS]
    lsv_wide("lsv_pore.csv", [("pristine", pris)] + hol)
    summary["axes"]["pore_size"] = {
        "held": {"open": REF_MESH["open"], "t_mm": REF_MESH["t_mm"],
                 "cover": 1.0, "pos": "outlet",
                 "electrode_angle_deg": D0["theta"], "mesh_angle_deg": D0["mesh_theta"]},
        "table": metrics_table("metrics_pore.csv", hol,
                               [("hole_mm", lambda r: r["mesh"]["hole_mm"])])}

    # Same pore sweep for an activated/hydrophilic electrode scenario.  This is
    # where opening size can matter because PP now has a positive wetting drive.
    d_active = {**D0, "theta": 60.0}
    pris_active = run_lsv(d_active, None)
    hol_active = [(f"hole={h:.2f}mm", run_lsv(
        d_active, {**REF_MESH, "hole_mm": h, "hole_x_mm": h,
                   "hole_y_mm": h, "mesh_theta": D0["mesh_theta"]})) for h in H_VALS]
    active_rows = []
    for lab, res in hol_active:
        m = metrics(res, pris_active)
        active_rows.append({"variant": lab, "hole_mm": res["mesh"]["hole_mm"], **m})
    _csv("metrics_pore_theta60.csv",
         ["variant", "hole_mm", "V@1000mV", "dV@1000_mV", "mesh_bubble_d_mm",
          "mesh_contact_prob", "mesh_wetting_drive", "mesh_capture_eff"],
         [[r.get(k, "") for k in ("variant", "hole_mm", "V@1000mV", "dV@1000_mV",
                                   "mesh_bubble_d_mm", "mesh_contact_prob",
                                   "mesh_wetting_drive", "mesh_capture_eff")]
          for r in active_rows])
    summary["axes"]["pore_size_theta60"] = {
        "held": {"electrode_angle_deg": 60.0, "mesh_angle_deg": D0["mesh_theta"],
                 "open": REF_MESH["open"], "t_mm": REF_MESH["t_mm"]},
        "table": active_rows}

    # -- AXIS 4: COVERED fraction x POSITION (the "가린 면적" question) ------
    print("[5/8] coverage x position sweep ...")
    C_VALS = [0.0, 0.25, 0.50, 0.75, 1.0]
    POS = ["inlet", "middle", "outlet"]
    cov_variants = []
    cov_table = []
    for pos in POS:
        for c in C_VALS:
            if c == 0.0:
                res = pris; lab = "cover=0 (none)"
            else:
                res = run_lsv(D0, {**REF_MESH, "cover": c, "pos": pos})
                lab = f"{pos} {int(c*100)}%"
            cov_variants.append((lab, res))
            m = metrics(res, pris)
            cov_table.append({"pos": pos, "cover": c, "variant": lab,
                              "V@500mV": m["V@500mV"], "V@1000mV": m["V@1000mV"],
                              "dV@500_mV": m.get("dV@500_mV"), "dV@1000_mV": m.get("dV@1000_mV"),
                              "theta_out@jmax": m["theta_out@jmax"],
                              "theta_mean@jmax": m["theta_mean@jmax"]})
    # de-dup the cover=0 columns for the wide LSV (keep one 'none')
    seen0 = False
    wide_cov = []
    for lab, res in cov_variants:
        if lab == "cover=0 (none)":
            if seen0:
                continue
            seen0 = True
        wide_cov.append((lab, res))
    lsv_wide("lsv_coverage.csv", wide_cov)
    _csv("metrics_coverage.csv",
         ["pos", "cover", "V@500mV", "V@1000mV", "dV@500_mV", "dV@1000_mV",
          "theta_out@jmax", "theta_mean@jmax"],
         [[r["pos"], r["cover"], r["V@500mV"], r["V@1000mV"], r["dV@500_mV"],
           r["dV@1000_mV"], r["theta_out@jmax"], r["theta_mean@jmax"]] for r in cov_table])
    summary["axes"]["coverage"] = {"held": dict(REF_MESH), "table": cov_table}

    # -- AXIS 5: FLOW (u_flow) : pristine vs ref-mesh ----------------------
    print("[6/8] flow sweep ...")
    U_VALS = [0.021, 0.042, 0.0842, 0.168, 0.336, 0.63]     # m/s
    flow_table = []
    flow_lsv_pris, flow_lsv_mesh = [], []
    for u in U_VALS:
        d_u = {**D0, "u_flow": u}
        rp = run_lsv(d_u, None)
        rm = run_lsv(d_u, REF_MESH)
        ml = _flow_mlmin(D0, u)
        flow_lsv_pris.append((f"{ml:.1f}mL/min", rp))
        flow_lsv_mesh.append((f"{ml:.1f}mL/min", rm))
        mp, mm = metrics(rp), metrics(rm, rp)
        flow_table.append({"u_flow_ms": u, "mL_min": round(ml, 2),
                           "pris_V@500": mp["V@500mV"], "pris_V@1000": mp["V@1000mV"],
                           "mesh_V@500": mm["V@500mV"], "mesh_V@1000": mm["V@1000mV"],
                           "dV@500_mV": mm.get("dV@500_mV"), "dV@1000_mV": mm.get("dV@1000_mV"),
                           "pris_theta_out": mp["theta_out@jmax"],
                           "mesh_theta_out": mm["theta_out@jmax"]})
    lsv_wide("lsv_flow_pristine.csv", flow_lsv_pris)
    lsv_wide("lsv_flow_mesh.csv", flow_lsv_mesh)
    _csv("metrics_flow.csv",
         ["u_flow_ms", "mL_min", "pris_V@500", "pris_V@1000", "mesh_V@500",
          "mesh_V@1000", "dV@500_mV", "dV@1000_mV", "pris_theta_out", "mesh_theta_out"],
         [[r["u_flow_ms"], r["mL_min"], r["pris_V@500"], r["pris_V@1000"],
           r["mesh_V@500"], r["mesh_V@1000"], r["dV@500_mV"], r["dV@1000_mV"],
           r["pris_theta_out"], r["mesh_theta_out"]] for r in flow_table])
    summary["axes"]["flow"] = {"table": flow_table}

    # -- AXIS 6: real CATALOG comparison (which product is best) -----------
    print("[7/8] catalog comparison ...")
    d_ch = D0["d_ch_mm"]
    cat_variants = []
    cat_table = []
    for ms in MESH_CATALOG:
        fits = ms["t_mm"] < d_ch
        mesh = {"hole_mm": ms["hole_mm"],
                "hole_x_mm": ms.get("hole_x_mm", ms["hole_mm"]),
                "hole_y_mm": ms.get("hole_y_mm", ms["hole_mm"]),
                "open": ms["open"], "t_mm": ms["t_mm"],
                "cover": 1.0, "pos": "outlet"}
        res = run_lsv(D0, mesh)
        m = metrics(res, pris)
        cat_variants.append((ms["id"], res))
        cat_table.append({"id": ms["id"], "name": ms["name"], "fits": bool(fits),
                          "hole_mm": ms["hole_mm"], "open": ms["open"], "t_mm": ms["t_mm"],
                          "V@500mV": m["V@500mV"], "V@1000mV": m["V@1000mV"],
                          "dV@500_mV": m.get("dV@500_mV"), "dV@1000_mV": m.get("dV@1000_mV"),
                          "theta_out@jmax": m["theta_out@jmax"], "mesh_warn": m["mesh_warn"],
                          "mesh_bubble_d_mm": m["mesh_bubble_d_mm"],
                          "mesh_contact_prob": m["mesh_contact_prob"],
                          "mesh_wetting_drive": m["mesh_wetting_drive"],
                          "mesh_capture_eff": m["mesh_capture_eff"],
                          "mesh_obstruction": m["mesh_obstruction"],
                          "mesh_u_boost": m["mesh_u_boost"], "mesh_dp_ratio": m["mesh_dp_ratio"]})
    lsv_wide("lsv_catalog.csv", [("pristine", pris)] + cat_variants)
    _csv("metrics_catalog.csv",
         ["id", "name", "fits", "hole_mm", "open", "t_mm", "V@500mV", "V@1000mV",
          "dV@500_mV", "dV@1000_mV", "theta_out@jmax", "mesh_bubble_d_mm",
          "mesh_contact_prob", "mesh_wetting_drive", "mesh_capture_eff",
          "mesh_obstruction", "mesh_u_boost", "mesh_dp_ratio", "mesh_warn"],
         [[r["id"], r["name"], r["fits"], r["hole_mm"], r["open"], r["t_mm"],
           r["V@500mV"], r["V@1000mV"], r["dV@500_mV"], r["dV@1000_mV"],
           r["theta_out@jmax"], r["mesh_bubble_d_mm"], r["mesh_contact_prob"],
           r["mesh_wetting_drive"], r["mesh_capture_eff"], r["mesh_obstruction"],
           r["mesh_u_boost"], r["mesh_dp_ratio"], r["mesh_warn"]]
          for r in cat_table])
    summary["axes"]["catalog"] = {"d_ch_mm": d_ch, "table": cat_table}

    cat_active = []
    for ms in MESH_CATALOG:
        if ms["t_mm"] >= d_ch:
            continue
        mesh = {"hole_mm": ms["hole_mm"],
                "hole_x_mm": ms.get("hole_x_mm", ms["hole_mm"]),
                "hole_y_mm": ms.get("hole_y_mm", ms["hole_mm"]),
                "open": ms["open"], "t_mm": ms["t_mm"], "cover": 1.0,
                "pos": "outlet", "mesh_theta": D0["mesh_theta"]}
        m = metrics(run_lsv(d_active, mesh), pris_active)
        cat_active.append({"id": ms["id"], "hole_mm": ms["hole_mm"],
                           "open": ms["open"], "t_mm": ms["t_mm"], **m})
    _csv("metrics_catalog_theta60.csv",
         ["id", "hole_mm", "open", "t_mm", "V@1000mV", "dV@1000_mV",
          "mesh_contact_prob", "mesh_capture_eff", "mesh_dp_ratio"],
         [[r.get(k, "") for k in ("id", "hole_mm", "open", "t_mm", "V@1000mV",
                                   "dV@1000_mV", "mesh_contact_prob",
                                   "mesh_capture_eff", "mesh_dp_ratio")]
          for r in cat_active])
    summary["axes"]["catalog_theta60"] = {"table": cat_active}

    # -- contact-angle sensitivity: the dominant unmeasured surface state --
    print("[8/9] electrode × PP contact-angle sensitivity ...")
    angle_table = []
    for te in (40.0, 60.0, 80.0, 100.0, 110.0, 120.0):
        for tm in (90.0, 105.8, 120.0, 140.0):
            da = {**D0, "theta": te, "mesh_theta": tm}
            ra = run_lsv(da, {**REF_MESH, "mesh_theta": tm})
            ma = metrics(ra, pris)
            angle_table.append({"electrode_angle_deg": te, "mesh_angle_deg": tm,
                                "V@1000mV": ma["V@1000mV"],
                                "dV@1000_mV": ma.get("dV@1000_mV"),
                                "bubble_d_mm": ma["mesh_bubble_d_mm"],
                                "contact_prob": ma["mesh_contact_prob"],
                                "wetting_drive": ma["mesh_wetting_drive"],
                                "capture_eff": ma["mesh_capture_eff"]})
    _csv("metrics_contact_angles.csv",
         ["electrode_angle_deg", "mesh_angle_deg", "V@1000mV", "dV@1000_mV",
          "bubble_d_mm", "contact_prob", "wetting_drive", "capture_eff"],
         [[r[k] for k in ("electrode_angle_deg", "mesh_angle_deg", "V@1000mV",
                          "dV@1000_mV", "bubble_d_mm", "contact_prob",
                          "wetting_drive", "capture_eff")] for r in angle_table])
    summary["axes"]["contact_angles"] = {"table": angle_table}

    # -- AXIS 7: EIS comparison --------------------------------------------
    print("[9/9] EIS comparison ...")
    fitting = [r for r in cat_table if r["fits"]]
    best = min(fitting, key=lambda r: r["V@1000mV"]) if fitting else None
    worst = max(fitting, key=lambda r: r["V@1000mV"]) if fitting else None
    eis_cases = [("pristine", None)]
    eis_cases.append(("ref_mesh (pp_040x053)", REF_MESH))
    if best:
        bm = next(m for m in MESH_CATALOG if m["id"] == best["id"])
        eis_cases.append((f"best ({best['id']})",
                          {"hole_mm": bm["hole_mm"],
                           "hole_x_mm": bm.get("hole_x_mm", bm["hole_mm"]),
                           "hole_y_mm": bm.get("hole_y_mm", bm["hole_mm"]),
                           "open": bm["open"], "t_mm": bm["t_mm"],
                           "cover": 1.0, "pos": "outlet"}))
    eis_specs = []
    for lab, mesh in eis_cases:
        eis_specs.append((lab, build_eis(D0, mesh, 500.0)))
    # wide Nyquist csv
    header = ["freq_Hz"]
    for lab, _ in eis_specs:
        header += [f"{lab}|Zre", f"{lab}|-Zim"]
    n = len(eis_specs[0][1]["f"])
    rows = []
    for i in range(n):
        row = [round(eis_specs[0][1]["f"][i], 4)]
        for _, s in eis_specs:
            row += [round(s["re"][i], 5), round(s["im"][i], 5)]
        rows.append(row)
    _csv("eis_nyquist.csv", header, rows)
    _csv("eis_metrics.csv",
         ["variant", "Rs_ohmcm2", "Rct_a_ohmcm2", "Rct_c_ohmcm2", "Rct_tot_ohmcm2", "theta_mean"],
         [[lab, round(s["Rs"], 4), round(s["Rct_a"], 4), round(s["Rct_c"], 4),
           round(s["Rct_tot"], 4), round(s["theta_mean"], 4)] for lab, s in eis_specs])
    summary["axes"]["eis"] = {
        "operating_j_mAcm2": 500.0,
        "note": "coverage-driven: mesh lowers path-mean theta -> (1-theta) raises "
                "effective j0 -> lower Rct. Rs unchanged (same membrane/electrolyte).",
        "table": [{"variant": lab, "Rs": round(s["Rs"], 4),
                   "Rct_tot": round(s["Rct_tot"], 4), "theta_mean": round(s["theta_mean"], 4)}
                  for lab, s in eis_specs]}
    summary["best_worst"] = {"best_fitting": best, "worst_fitting": worst}

    with open(OUT / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("done ->", OUT)
    # console recap
    print("\nCATALOG (fits) ranked by V@1000:")
    for r in sorted(fitting, key=lambda r: r["V@1000mV"]):
        print(f"  {r['id']:14s} t={r['t_mm']:.2f} phi={r['open']:.2f} hole={r['hole_mm']:.2f}"
              f"  V@500={r['V@500mV']} V@1000={r['V@1000mV']} dV@1000={r['dV@1000_mV']}")
    print("\nCOVERAGE best per position (dV@1000, +ve=saves):")
    for pos in POS:
        rr = [r for r in cov_table if r["pos"] == pos and r["cover"] > 0]
        b = max(rr, key=lambda r: (r["dV@1000_mV"] or -1e9))
        print(f"  {pos:7s} best = {b['variant']}  dV@1000={b['dV@1000_mV']}  dV@500={b['dV@500_mV']}")
    return summary
