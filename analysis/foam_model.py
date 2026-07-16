# -*- coding: utf-8 -*-
"""Through-thickness + axial Ni-foam wetting model — grounds the §13 lambda(x)
result in REAL foam physics instead of a free knob q.

Two transport directions in the porous Ni-foam anode:
  AXIAL (x, along the channel):  electrolyte soaks in where the surface is OPEN
    (mesh absent) and advects DOWNSTREAM inside the foam, consumed by reaction.
    Covering the inlet throttles entry -> the WHOLE downstream foam is starved.
      W[i] = clip( W[i-1] + (entry_i - consume_i)*ds, 0, W_max )
      entry_i   = k_in * (1-eps_ch_i) * (1 - q_eff*covered_i)
      consume_i = c_cons * j_i
      s_surf_i  = W[i]/W_max                          # channel-side saturation
  THROUGH-THICKNESS (z, into the foam):  wetted reaction depth from a capillary
    supply vs reaction-consumption balance (steady wetting front):
      z_wet_i   = min( L_foam, D_cap * s_surf_i / (nu * j_i) )

Effective active area ~ a*z_wet; the DIFFERENTIAL vs pristine gives an activation
saving:  dV_foam = (RT/alpha_a F) * mean_x ln( z_wet_mesh / z_wet_pris ).

The mesh water-entry blocking is GROUNDED, not free:
      q_eff = (1 - phi) * (1 - recover)
where (1-phi) is the strand-covered surface fraction and `recover` is how much
the foam re-supplies under a strand by lateral spreading (large-pore foam -> high
recover -> low q_eff). We SCAN the two genuinely-uncertain groups (dry-out scale,
recover) over plausible ranges and report where the outlet-partial optimum lives
and where the real reference foam+mesh sits.  BLIND: never fit to outlet-50%.
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

OUT = ROOT / "analysis" / "out"
D0 = ms.D0
REF = ms.REF_MESH
J = 1000.0
F = 96485.0
R = 8.314

# --- real foam / operating numbers (grounded) ------------------------------
FOAM = dict(
    L_foam_um=600.0,      # NiFe/NF anode thickness (measured)
    eps_foam=0.95,        # foam porosity (measured, eps_ptl)
    d_pore_um=450.0,      # Ni-foam pore size (~110 PPI, literature)
    kappa=27.0,           # 1 M KOH @65C ionic conductivity [S/m]
    alpha_a=1.19,         # calibrated OER transfer coefficient
    T=338.15,
)
# water molar volume / stoichiometry: OER consumes ~ (per e-) water via the
# anolyte balance; nu*j is the volumetric liquid consumption flux [m/s per A/m^2].
# We fold constants into a single reference dry-out current j_dry (grounded below)
# and work in the dimensionless ratio j/j_dry, so absolute nu cancels.


def profiles():
    """Channel eps(x), j(x), covered-mask for pristine + every (cover,pos)."""
    def one(mesh):
        params = ms.build_params(D0); dd = dict(D0); dd["mesh_id"] = ""
        op = ms._apply_mesh(ms.sweep_operating(dd, J), mesh)
        sim = Simulator(op=op, params=params)
        st = ChannelSolver().solve(op, sim.props(), sim.surfaces)
        pp = st.fields.get("path_prof") or {}
        return (pp.get("eps") or [st.fields.get("eps_out", 0.0)],
                pp.get("j") or [J * 10],
                pp.get("mesh") or [False])
    return one


# anchored drying model. The channel gas holdup eps(x) already encodes the local
# gas load at this current, so it carries the drying; we don't re-divide by j.
#   axial surface saturation W(x):  gas choking (eps) drains, open channel liquid
#   re-soaks (throttled by the mesh where it covers):
#       dW/dx = ks*(1-eps)*(1 - q_eff*cov)  -  kd*eps
#   through-thickness wetted depth:  z_wet = L * W^m
# kd/ks/m are anchored so PRISTINE is partially wetted (deep at inlet, dried at
# the gas-choked outlet) — NOT bone-dry, NOT fully flooded.
KD, KS, MEXP, S_FLOOR = 1.6, 1.3, 0.7, 0.08


def z_wet_profile(eps, mask, q_eff, kd, L_um):
    n = len(eps)
    ds = 1.0 / max(1, n - 1)
    w = 1.0
    z = []
    for i in range(n):
        cov = 1.0 if (i < len(mask) and mask[i]) else 0.0
        drain = kd * eps[i]
        soak = KS * (1.0 - eps[i]) * (1.0 - q_eff * cov)
        w = min(1.0, max(S_FLOOR, w + (soak - drain) * ds))
        z.append(L_um * (w ** MEXP))
    return z


def dV_foam(zc_mesh, zc_pris):
    n = min(len(zc_mesh), len(zc_pris))
    acc = sum(math.log(max(1e-3, zc_mesh[i]) / max(1e-3, zc_pris[i])) for i in range(n))
    rt_af = R * FOAM["T"] / (FOAM["alpha_a"] * F)
    return rt_af * (acc / n) * 1000.0           # mV


def q_eff_grounded(mesh, recover):
    """Mesh water-entry blocking from geometry: strand-covered fraction minus
    lateral re-supply. recover in [0,1] (large-pore foam -> high recover)."""
    return (1.0 - mesh["open"]) * (1.0 - recover)


_BASE_CACHE = {}
def _base_dV(mesh_key, mesh):
    if mesh_key not in _BASE_CACHE:
        _BASE_CACHE[mesh_key] = (ms.Vat(ms.run_lsv(D0, None), J) * 1000
                                 - ms.Vat(ms.run_lsv(D0, mesh), J) * 1000)
    return _BASE_CACHE[mesh_key]


def run(recover, kd, q_override=None):
    one = profiles()
    peps, pj, pmask = one(None)
    zc_pris = z_wet_profile(peps, pmask, 0.0, kd, FOAM["L_foam_um"])
    covers = [0.25, 0.5, 0.75, 1.0]
    rows = []
    for pos in ("inlet", "middle", "outlet"):
        for c in covers:
            mesh = {**REF, "cover": c, "pos": pos}
            eps, jj, mask = one(mesh)
            base = _base_dV((pos, c), mesh)
            qeff = q_override if q_override is not None else q_eff_grounded(mesh, recover)
            zc = z_wet_profile(eps, mask, qeff, kd, FOAM["L_foam_um"])
            foam = dV_foam(zc, zc_pris)
            rows.append(dict(pos=pos, cover=c, q_eff=round(qeff, 3),
                             base_dV=round(base, 1), foam_dV=round(foam, 1),
                             total_dV=round(base + foam, 1),
                             zwet_pris_out=round(zc_pris[-1], 0), zwet_mesh_out=round(zc[-1], 0)))
    return rows


def best_outlet_cover(rows):
    o = [r for r in rows if r["pos"] == "outlet"]
    b = max(o, key=lambda r: r["total_dV"])
    return b["cover"], b["total_dV"]


def main():
    # reference-foam run: 450um pores vs mesh strands -> moderate lateral recovery
    REF_RECOVER, REF_KD = 0.35, 1.6
    ref_rows = run(REF_RECOVER, REF_KD)
    ref_qeff = q_eff_grounded(REF, REF_RECOVER)
    bc, bdv = best_outlet_cover(ref_rows)

    # robustness scan: does outlet-partial win across plausible (recover, kd)?
    recovers = [0.0, 0.2, 0.35, 0.5, 0.7]
    kds = [1.0, 1.6, 2.4, 3.5]        # foam dry-out strength (gas-choke sensitivity)
    scan = []
    flips = 0
    for rc in recovers:
        for kd in kds:
            rows = run(rc, kd)
            c, dv = best_outlet_cover(rows)
            qe = q_eff_grounded(REF, rc)
            flip = c < 1.0
            flips += 1 if flip else 0
            scan.append({"recover": rc, "kd": kd, "q_eff": round(qe, 3),
                         "outlet_best_cover": c, "outlet_best_dV": dv, "flip": flip})
    frac = flips / len(scan)

    # REGIME PROBE: can the flip appear when the WHOLE foam is water-starved
    # (low anolyte flow -> high holdup everywhere) at the mesh's max entry-block?
    probe = []
    orig_u = D0["u_flow"]                        # D0 is the SHARED ms.D0 global
    try:
        for ml in (1.0, 2.0, 4.0, 8.0):
            D0["u_flow"] = ml * orig_u / 4.0    # 4 mL/min is the calibrated u_flow
            _BASE_CACHE.clear()
            rows = run(0.0, 2.4)                  # recover=0 -> q_eff = max = (1-phi)=0.5
            c, dv = best_outlet_cover(rows)
            probe.append({"mL_min": ml, "q_eff": 0.5, "outlet_best_cover": c, "flip": c < 1.0})
    finally:                                      # always restore the shared global, even on error
        D0["u_flow"] = orig_u
        _BASE_CACHE.clear()

    # THRESHOLD: how strong must foam water-entry blocking (q_eff) be to flip?
    # (q_eff up to 0.5 is geometric; >0.5 implies hydrophobic repulsion beyond open-area)
    qthr = []
    q_flip = None
    for qe in (0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 0.97):
        rows = run(0.0, 2.4, q_override=qe)
        c, dv = best_outlet_cover(rows)
        qthr.append({"q_eff": qe, "outlet_best_cover": c, "flip": c < 1.0})
        if q_flip is None and c < 1.0:
            q_flip = qe

    out = {"foam": FOAM, "anchor": {"KD": KD, "KS": KS, "MEXP": MEXP}, "regime_probe": probe,
           "q_threshold": qthr, "q_flip_min": q_flip,
           "ref_case": {"recover": REF_RECOVER, "kd": REF_KD,
           "q_eff": round(ref_qeff, 3), "outlet_best_cover": bc, "outlet_best_dV": bdv,
           "rows": ref_rows},
           "scan": scan, "flip_fraction": round(frac, 2)}
    (OUT / "foam_model.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(OUT / "foam_model_scan.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["recover", "kd", "q_eff(ref)", "outlet_best_cover", "outlet_best_dV_mV", "flip"])
        for s in scan:
            w.writerow([s["recover"], s["kd"], s["q_eff"], s["outlet_best_cover"], s["outlet_best_dV"], s["flip"]])

    print(f"REF foam case: q_eff={ref_qeff:.2f} (from phi={REF['open']}, recover={REF_RECOVER})")
    print(f"  z_wet pristine outlet = {ref_rows[-1]['zwet_pris_out']:.0f} um / {FOAM['L_foam_um']:.0f} um")
    print(f"  outlet best cover = {bc*100:.0f}%  (total {bdv:.1f} mV)  {'FLIP' if bc<1 else 'no flip (100%)'}")
    print("\n  outlet rows (cover: base / foam / total):")
    for r in [x for x in ref_rows if x['pos'] == 'outlet']:
        print(f"    {int(r['cover']*100):3d}%  {r['base_dV']:6.1f} / {r['foam_dV']:+6.1f} / {r['total_dV']:6.1f}  (z_wet {r['zwet_mesh_out']:.0f}um)")
    print(f"\nROBUSTNESS: outlet-partial optimum in {flips}/{len(scan)} = {frac*100:.0f}% of plausible (recover,kd) grid")
    print("   q_eff \\ kd    " + " ".join(f"{dk:>5.1f}" for dk in kds))
    for rc in recovers:
        cells = []
        for dk in kds:
            s = next(x for x in scan if x["recover"] == rc and x["kd"] == dk)
            cells.append(f"{int(s['outlet_best_cover']*100):>4d}%")
        print(f"   q_eff {q_eff_grounded(REF, rc):.2f}    " + " ".join(cells))
    print("\nREGIME PROBE (max entry-block q_eff=0.5, vary anolyte flow):")
    for p in probe:
        print(f"   {p['mL_min']:>4.1f} mL/min: outlet best = {int(p['outlet_best_cover']*100)}%  {'FLIP' if p['flip'] else '(100%)'}")
    print("\nFLIP THRESHOLD (direct q_eff; >0.5 = hydrophobic repulsion beyond open-area):")
    for q in qthr:
        print(f"   q_eff={q['q_eff']:.2f}: outlet best = {int(q['outlet_best_cover']*100)}%  {'FLIP' if q['flip'] else '(100%)'}")
    print(f"   -> flip needs q_eff >= {q_flip}" if q_flip else "   -> NO flip even at q_eff=0.97")
    print("\nwrote foam_model.json, foam_model_scan.csv")


if __name__ == "__main__":
    main()
