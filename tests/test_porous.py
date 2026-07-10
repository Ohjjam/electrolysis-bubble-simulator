"""Track 2 -- porous-electrode (Newman) depth solver.

Physics contracts:
  * charge conservation: integral of a*j_loc over depth == total current I
  * thin flat plate (fully penetrated) reduces to the planar Butler-Volmer result
  * a high-area scaffold (foam) lowers the overpotential / cell voltage at fixed j
  * higher current concentrates the reaction near a face -> utilization drops
  * CA and CP are mutually consistent (solve V->j, then j->V recovers V)
  * extreme inputs stay finite (no NaN / blow-up)

Run with:  python -m pytest tests/ -q   (or: python tests/test_porous.py)
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params                          # noqa: E402
from bubblesim.kernel.context import build_context               # noqa: E402
from bubblesim.kernel import morphology as morph                 # noqa: E402
from bubblesim.solvers import porous                             # noqa: E402
from bubblesim.solvers.zerod import _invert_bv                   # noqa: E402


class Flat:
    def __init__(self, theta=0.0, eps=0.0):
        self._t, self._e = theta, eps
    def coverage(self):
        return self._t
    def void_fraction(self):
        return self._e


def _solve(op, surf=None):
    surf = surf or [Flat(), Flat()]
    return porous.PorousSolver().solve(op, build_context(op, Params()), surf)


def test_charge_conservation():
    """integral_0^L a * j_loc(d) dd must equal the imposed total current I."""
    eff = morph.effective_electrode("ni_foam", "nanoparticle")
    I = 3000.0
    r = porous.porous_eta(I, eff, 60.0, 1.0, 0.5, 0.5, 333.15)
    jl = np.array(r["j_loc"]) * eff["a"]
    h = eff["L_e"] / (len(jl) - 1)
    integral = h * (jl.sum() - 0.5 * (jl[0] + jl[-1]))     # trapezoid
    assert math.isclose(integral, I, rel_tol=0.02)


def test_flat_plate_reduces_to_planar():
    """flat_plate + planar_film, fully penetrated -> uniform reaction j_loc=I/R_f,
    so eta_eff matches the planar Butler-Volmer inversion."""
    eff = morph.effective_electrode("flat_plate", "planar_film")
    j0, aa, ac, T = 1.0, 0.5, 0.5, 333.15
    for I in (200.0, 2000.0):
        r = porous.porous_eta(I, eff, 60.0, j0, aa, ac, T)
        eta_planar = _invert_bv(I / eff["R_f"], j0, aa, ac, T)
        assert math.isclose(r["eta_eff"], eta_planar, rel_tol=0.06)
        assert r["util"] > 0.9                       # essentially uniform


def test_foam_area_lowers_overpotential():
    """At the same current, a high-area foam needs far less overpotential than a
    flat plate (the whole point of a porous electrode)."""
    flat = morph.effective_electrode("flat_plate", "planar_film")
    foam = morph.effective_electrode("ni_foam", "nanoparticle")
    eta_flat = porous.porous_eta(3000.0, flat, 60.0, 1.0, 0.5, 0.5, 333.15)["eta_eff"]
    eta_foam = porous.porous_eta(3000.0, foam, 60.0, 1.0, 0.5, 0.5, 333.15)["eta_eff"]
    assert eta_foam < eta_flat


def test_utilization_drops_with_current():
    """Higher current -> reaction concentrates near a face -> lower utilization."""
    eff = morph.effective_electrode("ni_foam", "nanoparticle")
    lo = porous.porous_eta(500.0, eff, 60.0, 1.0, 0.5, 0.5, 333.15)["util"]
    hi = porous.porous_eta(80000.0, eff, 60.0, 1.0, 0.5, 0.5, 333.15)["util"]
    assert lo > hi
    assert hi < 0.8


def test_foam_lowers_cell_voltage_cp():
    """End-to-end CP: a foam cell runs at a lower voltage than a flat-plate cell."""
    common = dict(model="porous", mode="CP", j_set=3000.0, track_both=True)
    Vf = _solve(Operating(substrate="flat_plate", nanostructure="planar_film", **common)).V
    Vfoam = _solve(Operating(substrate="ni_foam", nanostructure="nanoparticle", **common)).V
    assert math.isfinite(Vf) and math.isfinite(Vfoam)
    assert Vfoam < Vf


def test_porous_ca_cp_inversion():
    """CA(V)->j then CP(j)->V reconstructs the cell voltage."""
    op_ca = Operating(model="porous", V_cell=2.2, track_both=True)
    j = _solve(op_ca).j
    assert j > 0.0
    V = _solve(Operating(model="porous", mode="CP", j_set=j, track_both=True)).V
    assert math.isclose(V, 2.2, rel_tol=1.5e-2)


def test_coverage_raises_voltage_cp():
    """Bubble coverage blocks active area -> higher voltage at fixed current."""
    op = Operating(model="porous", mode="CP", j_set=3000.0, track_both=True)
    V0 = _solve(op, [Flat(0.0), Flat(0.0)]).V
    V1 = _solve(op, [Flat(0.5), Flat(0.5)]).V
    assert V1 > V0


def test_porous_finite_at_extremes():
    for op in (Operating(model="porous", mode="CA", V_cell=4.0, track_both=True),
               Operating(model="porous", mode="CP", j_set=1.0e9, track_both=True),
               Operating(model="porous", mode="CA", V_cell=2.0, substrate="carbon_paper",
                         nanostructure="nanowire", track_both=True),
               Operating(model="porous", mode="CA", V_cell=2.0, substrate="ss_foam",
                         nanostructure="nanoporous", cat_loading=3.0, track_both=True)):
        st = _solve(op)
        assert math.isfinite(st.j) and st.j >= 0.0
        if st.V is not None:
            assert math.isfinite(st.V)
        for key in ("jloc_c", "eta_d_c", "jloc_a"):
            assert all(math.isfinite(v) for v in st.fields[key])


def test_gas_feedback_raises_overpotential():
    """Internal gas saturation blocks area/conductivity -> higher overpotential."""
    eff = morph.effective_electrode("ni_foam", "nanoparticle")
    base = porous.porous_eta(8000.0, eff, 60.0, 1.0, 0.5, 0.5, 333.15, gas_feedback=False)
    gas = porous.porous_eta(8000.0, eff, 60.0, 1.0, 0.5, 0.5, 333.15,
                            gas_feedback=True, escape=eff["escape_factor"])
    assert base["s_g_max"] == 0.0
    assert gas["s_g_max"] > 0.05               # meaningful gas holdup
    assert gas["eta_eff"] > base["eta_eff"]    # blanketing costs overpotential
    assert math.isfinite(gas["eta_eff"])


def test_gas_feedback_worse_in_tight_foam():
    """A tighter foam (poor gas escape) traps more gas than an open structure."""
    eff = morph.effective_electrode("ni_foam", "nanoparticle")
    opn = porous.porous_eta(8000.0, eff, 60.0, 1.0, 0.5, 0.5, 333.15, gas_feedback=True, escape=1.0)
    tight = porous.porous_eta(8000.0, eff, 60.0, 1.0, 0.5, 0.5, 333.15, gas_feedback=True, escape=0.4)
    assert tight["s_g_max"] > opn["s_g_max"]


def test_gas_feedback_raises_cell_voltage():
    """End-to-end: turning gas feedback on raises the porous cell voltage."""
    common = dict(model="porous", mode="CP", j_set=6000.0, track_both=True)
    V0 = _solve(Operating(**common)).V
    Vg = _solve(Operating(gas_feedback=True, **common)).V
    assert math.isfinite(Vg) and Vg > V0


def test_profiles_present_and_shaped():
    st = _solve(Operating(model="porous", mode="CP", j_set=5000.0, track_both=True))
    f = st.fields
    n = len(f["d_mm"])
    assert n > 10 and len(f["jloc_c"]) == n and len(f["eta_d_c"]) == n
    assert f["L_e_mm"] > 0.0 and 0.0 < f["util_c"] <= 1.0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}  {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {fn.__name__}  {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
