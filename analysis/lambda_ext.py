# -*- coding: utf-8 -*-
"""EXTENSION: nickel-foam reaction-zone depth lambda(x) — can it reproduce the
measured 'outlet-partial > full' optimum the base model cannot?

Physical hypothesis (the user's): the Ni-foam anode reacts in a WETTED zone of
depth lambda. Gas accumulation dries the foam pores (less liquid -> shallower
lambda -> less active area -> higher activation overpotential). A bubble-managing
mesh changes lambda two opposing ways:
  (+) it clears bubbles (lower wall holdup eps) -> foam stays wet deeper -> larger lambda
  (-) an exploratory liquid-entry penalty can starve the foam surface.

We DON'T touch the calibrated pristine baseline. We model only the DIFFERENTIAL:
how much the mesh changes lambda RELATIVE to pristine, and convert that active-
area change into an activation-voltage change. Constants are a-priori (blind);
we report whether the flip emerges and at what sensitivity — never fit to the
measured outlet-50% number.

    liquid saturation      s(x)      = 1 - eps(x)
    relative wetted depth  m(x)      = clip( s(x)^p_dry - k_block*b(x), lam_min, 1 )
    activation saving      dV_foam   = (RT/alpha_a F) * mean_x[ ln( m_mesh/m_pris ) ]

b(x) was a legacy exploratory blocking field.  Mesh model v2 does not infer
active-area or liquid-entry blockage from channel solid volume, so this module
is retained for historical sensitivity work only and is not used by the v2
report.
"""
import sys
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "analysis"))
import mesh_study as ms
from bubblesim import Simulator
from bubblesim.solvers.channel import ChannelSolver
from bubblesim.kernel.meshlayer import mesh_factors
from bubblesim.constants import F, R_GAS

OUT = ROOT / "analysis" / "out"
D0 = ms.D0
REF = ms.REF_MESH
J = 1000.0

# a-priori foam-wetting constants (NOT fitted to mesh data)
#   UPSTREAM-SUPPLY model (matches the user's hypothesis): liquid enters the
#   Ni-foam from the channel, preferentially where the surface is OPEN (mesh
#   absent). Covering a stretch throttles liquid ENTRY there by q, and that
#   shortfall propagates DOWNSTREAM (the foam is fed from upstream). So covering
#   the inlet starves the whole foam; covering only the outlet keeps the inlet
#   open (water enters) while clearing gas where it accumulates.
#     open(x)  = 1 - q * covered(x)                 # local entry openness
#     feed(x)  = mean_{x'<=x} open(x')              # cumulative upstream supply
#     wet(eps) = clip((1-eps - s_dry)/(s_crit - s_dry), 0, 1)   # local saturation
#     lam(x)   = clip( feed(x) * wet(eps(x)), lam_min, 1 )
#     dV_foam  = (RT/alpha_a F) * mean_x ln( lam_mesh / lam_pris )
PARAMS = dict(q=0.55, s_crit=0.50, s_dry=0.10, lam_min=0.30)


def profile(mesh):
    """Solve at j=J, return eps(s) profile, covered-mask, and cell V (mV)."""
    params = ms.build_params(D0)
    dd = dict(D0); dd["mesh_id"] = ""
    op = ms._apply_mesh(ms.sweep_operating(dd, J), mesh)
    sim = Simulator(op=op, params=params)
    ctx = sim.props()
    st = ChannelSolver().solve(op, ctx, sim.surfaces)
    pp = st.fields.get("path_prof") or {}
    eps = pp.get("eps") or [st.fields.get("eps_out", 0.0)]
    mask = pp.get("mesh") or [False] * len(eps)
    return eps, mask, float(st.V) * 1000.0, ctx


def _wet(eps, P):
    return min(1.0, max(0.0, ((1.0 - eps) - P["s_dry"]) / max(1e-6, P["s_crit"] - P["s_dry"])))


def dV_foam(mesh, pris_eps, ctx, P):
    """Upstream-supply foam re-wetting voltage saving (mV) vs pristine."""
    eps, mask, _, _ = profile(mesh)
    n = min(len(eps), len(pris_eps))
    if n == 0:
        return 0.0
    lo, q = P["lam_min"], P["q"]
    # cumulative upstream feed: covering upstream throttles supply downstream
    feed = []
    run = 0.0
    for i in range(n):
        run += 1.0 - q * (1.0 if (i < len(mask) and mask[i]) else 0.0)
        feed.append(run / (i + 1))
    acc = 0.0
    for i in range(n):
        lam_mesh = min(1.0, max(lo, feed[i] * _wet(eps[i], P)))
        lam_pris = min(1.0, max(lo, 1.0 * _wet(pris_eps[i], P)))   # pristine: full entry
        acc += math.log(max(1e-6, lam_mesh) / max(1e-6, lam_pris))
    alpha_a = ctx.get("alpha_a_anode", 1.19)
    rt_af = R_GAS * (D0["T"] + 273.15) / (alpha_a * F)
    return rt_af * (acc / n) * 1000.0        # V -> mV


def sweep(P):
    pris_eps, _, V0, ctx = profile(None)
    covers = [0.0, 0.25, 0.5, 0.75, 1.0]
    rows = []
    for pos in ("inlet", "middle", "outlet"):
        for c in covers:
            if c == 0.0:
                base_dV = 0.0; foam = 0.0
            else:
                mesh = {**REF, "cover": c, "pos": pos}
                _, _, Vm, _ = profile(mesh)
                base_dV = V0 - Vm
                foam = dV_foam(mesh, pris_eps, ctx, P)
            rows.append({"pos": pos, "cover": c,
                         "base_dV": round(base_dV, 1), "foam_dV": round(foam, 1),
                         "total_dV": round(base_dV + foam, 1)})
    return V0, rows


def summarize(rows):
    """For each position: base optimum vs total(with-foam) optimum cover."""
    out = {}
    for pos in ("inlet", "middle", "outlet"):
        rr = [r for r in rows if r["pos"] == pos and r["cover"] > 0]
        bopt = max(rr, key=lambda r: r["base_dV"])
        topt = max(rr, key=lambda r: r["total_dV"])
        out[pos] = {"base_best_cover": bopt["cover"], "base_best_dV": bopt["base_dV"],
                    "total_best_cover": topt["cover"], "total_best_dV": topt["total_dV"]}
    return out


def main():
    V0, rows = sweep(PARAMS)
    summ = summarize(rows)
    # sensitivity: vary q (mesh entry-throttling strength)
    sens = {}
    for q in (0.2, 0.4, 0.55, 0.7, 0.9):
        P = dict(PARAMS, q=q)
        _, rr = sweep(P)
        s = summarize(rr)
        outlet_rows = [r for r in rr if r["pos"] == "outlet" and r["cover"] > 0]
        sens[str(q)] = {"outlet_best_cover": s["outlet"]["total_best_cover"],
                        "outlet_total_dV": {str(r["cover"]): r["total_dV"] for r in outlet_rows}}

    out = {"params": PARAMS, "V0_1000": round(V0, 1), "rows": rows,
           "summary": summ, "sensitivity_kblock": sens,
           "note": "base_dV = 기존 채널 모델(피복 단조, 100% 최적). "
                   "total_dV = + 니켈폼 lambda(x) 재젖음 항. outlet에서 total 최적이 100% 미만이면 "
                   "실측의 부분피복 최적을 재현한 것."}
    (OUT / "lambda_ext.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(OUT / "lambda_extension.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["pos", "cover", "base_dV_mV", "foam_dV_mV", "total_dV_mV"])
        for r in rows:
            w.writerow([r["pos"], r["cover"], r["base_dV"], r["foam_dV"], r["total_dV"]])

    print(f"pristine V@1000={V0:.1f} mV; foam params {PARAMS}")
    print("\npos     cover  base_dV  foam_dV  total_dV")
    for r in rows:
        star = "  <-- outlet peak" if (r["pos"] == "outlet") else ""
        print(f"  {r['pos']:7s} {r['cover']:.2f}  {r['base_dV']:7.1f}  {r['foam_dV']:7.1f}  {r['total_dV']:7.1f}")
    print("\nOptimum cover (base model vs +lambda extension):")
    for pos, s in summ.items():
        flip = " ***FLIP***" if s["total_best_cover"] < 1.0 else ""
        print(f"  {pos:7s} base={s['base_best_cover']:.2f}(100%가 최적)  +foam={s['total_best_cover']:.2f}{flip}")
    print("\nsensitivity - best OUTLET cover vs q (entry-throttle):")
    for q, v in sens.items():
        print(f"  q={q}: best cover={v['outlet_best_cover']}  outlet total_dV={v['outlet_total_dV']}")
    print("wrote lambda_ext.json, lambda_extension.csv")


if __name__ == "__main__":
    main()
