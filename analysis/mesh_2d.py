# -*- coding: utf-8 -*-
"""2-D maps of net ΔV@1000 for the revised mesh model.

Opening size controls calculated bubble/edge contact continuously. Open fraction
and thickness set the channel solid-volume obstruction chi=(1-phi)t/d. The map
therefore shows the competition between contact-angle-driven capture, reduced
gas residence, while catalyst contact/compression blockage remains unmodelled.
"""
import sys
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "analysis"))
import mesh_study as ms

OUT = ROOT / "analysis" / "out"
D0 = ms.D0
D_CH = D0["d_ch_mm"]

# pristine reference V@1000
_pris = ms.run_lsv(D0, None)
V0_1000 = ms.Vat(_pris, 1000.0) * 1000.0


def dV1000(hole, phi, t, cover=1.0, pos="outlet"):
    if t >= D_CH:                    # cannot mount
        return None
    mesh = {"hole_mm": hole, "open": phi, "t_mm": t, "cover": cover, "pos": pos}
    r = ms.run_lsv(D0, mesh)
    return V0_1000 - ms.Vat(r, 1000.0) * 1000.0     # + = saves, - = hurts


def grid(xs, ys, fx):
    return [[fx(x, y) for x in xs] for y in ys]


def main():
    holes = [0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]        # opening size mm
    phis = [0.05, 0.10, 0.20, 0.35, 0.50, 0.70]             # open fraction
    ts = [0.20, 0.40, 0.60, 0.80, 0.88]                     # thickness mm (<0.9)

    T_THICK = 0.85
    PHI_DENSE = 0.10

    # (hole × phi) at thick t=0.85
    g1 = grid(holes, phis, lambda h, p: dV1000(h, p, T_THICK))
    # (hole × thickness) at dense phi=0.10
    g2 = grid(holes, ts, lambda h, t: dV1000(h, PHI_DENSE, t))

    def flatten(xs, ys, g, xn, yn):
        rows = []
        for j, y in enumerate(ys):
            for i, x in enumerate(xs):
                rows.append({xn: x, yn: y, "dV1000": (round(g[j][i], 1) if g[j][i] is not None else None)})
        return rows

    r1 = flatten(holes, phis, g1, "hole_mm", "phi")
    r2 = flatten(holes, ts, g2, "hole_mm", "t_mm")

    # reversal contour: for each hole (at t=0.85, phi grid) find where dV crosses 0
    neg1 = [x for x in r1 if x["dV1000"] is not None and x["dV1000"] < 0]
    neg2 = [x for x in r2 if x["dV1000"] is not None and x["dV1000"] < 0]

    # a few named extreme meshes with mechanism decomposition (reuse mech_decomp)
    import mech_decomp as md
    def decomp(hole, phi, t, tag):
        md.REF = {"hole_mm": hole, "open": phi, "t_mm": t, "cover": 1.0, "pos": "outlet"}
        d = md.decomp_at(1000)
        return {"tag": tag, "hole": hole, "phi": phi, "t": t,
                "V0": d["V_pristine"], "Vmesh": d["V_full"], "net": d["net_mV"],
                "peel": d["steps_mV"]["접촉·젖음성 포획"],
                "push": d["steps_mV"]["유로 폐색에 따른 체류시간 감소"],
                "block": d["steps_mV"]["촉매 접촉·압착 차단 (미모델링)"]}
    extremes = [
        decomp(1.18, 0.50, 0.48, "기준 (fine·중밀도·얇음)"),
        decomp(1.18, 0.10, 0.85, "촘촘+두꺼움 (fine)"),
        decomp(6.0, 0.10, 0.85, "촘촘+두꺼움+거침 (coarse)"),
        decomp(7.0, 0.05, 0.88, "극단: 최대 차단·최소 접촉"),
    ]
    # restore REF
    md.REF = ms.REF_MESH

    # LOW-CURRENT reversal: blocking is a fixed floor, benefit scales with gas.
    # At low j there is little gas to peel/sweep, so a high-block mesh can HURT.
    def dV_at(hole, phi, t, j, cover=1.0, pos="outlet"):
        if t >= D_CH:
            return None
        r = ms.run_lsv(D0, {"hole_mm": hole, "open": phi, "t_mm": t, "cover": cover, "pos": pos})
        r0 = ms.run_lsv(D0, None)
        return (ms.Vat(r0, j) - ms.Vat(r, j)) * 1000.0
    js = [20, 50, 100, 200, 300, 500, 1000, 2000]
    cross = {}
    for tag, (h, p, t) in {"기준(fine·얇음)": (1.18, 0.50, 0.48),
                           "coarse·촘촘·두꺼움": (6.0, 0.10, 0.85),
                           "극단 차단": (7.0, 0.05, 0.88)}.items():
        cross[tag] = {"hole": h, "phi": p, "t": t,
                      "dV_by_j": {str(j): round(dV_at(h, p, t, j), 1) for j in js}}
    print("\nLOW-CURRENT reversal - net dV(j) [+saves/-hurts]:")
    print("   j:        " + " ".join(f"{j:>6d}" for j in js))
    for tag, d in cross.items():
        print(f"  {tag:20s} " + " ".join(f"{d['dV_by_j'][str(j)]:>6.1f}" for j in js))

    out = {"V0_1000": round(V0_1000, 1), "d_ch_mm": D_CH, "cross_j": cross, "js": js,
           "grid_hole_phi": {"t_mm": T_THICK, "holes": holes, "phis": phis, "z": g1},
           "grid_hole_t": {"phi": PHI_DENSE, "holes": holes, "ts": ts, "z": g2},
           "reversal_hole_phi": neg1, "reversal_hole_t": neg2,
           "extremes": extremes}
    (OUT / "mesh_2d.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    with open(OUT / "mesh_2d_reversal.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["grid", "hole_mm", "phi_or_t", "dV1000_mV(+절감/-손해)"])
        for x in r1:
            w.writerow(["hole×phi @t=0.85", x["hole_mm"], x["phi"], x["dV1000"]])
        for x in r2:
            w.writerow(["hole×t @phi=0.10", x["hole_mm"], x["t_mm"], x["dV1000"]])

    print(f"pristine V@1000 = {V0_1000:.1f} mV;  d_ch={D_CH} mm")
    print("\n(hole × phi) net ΔV@1000 at t=0.85 mm  [+saves / -hurts]:")
    print("  hole\\phi " + " ".join(f"{p:>7.2f}" for p in phis))
    for i, h in enumerate(holes):
        print(f"  {h:>5.1f}   " + " ".join(
            (f"{g1[j][i]:>7.1f}" if g1[j][i] is not None else "   n/a") for j in range(len(phis))))
    print(f"\n  NEGATIVE (mesh hurts) cells: {len(neg1)}")
    for x in neg1:
        print(f"    hole={x['hole_mm']} phi={x['phi']} -> {x['dV1000']} mV")
    print("\nEXTREME mesh decomposition @1000 (capture / flow / block / net):")
    for e in extremes:
        print(f"  {e['tag']:28s} peel {e['peel']:+6.1f}  push {e['push']:+7.1f}  block {e['block']:+6.1f}  net {e['net']:+7.1f}")
    print("\nwrote mesh_2d.json, mesh_2d_reversal.csv")


if __name__ == "__main__":
    main()
