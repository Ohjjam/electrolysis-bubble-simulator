"""Physics tests for EIS (impedance) and double-layer transient dynamics.

R_ct must match the numerical derivative of Butler-Volmer; the spectrum must hit
its textbook limits (R_s at high frequency, R_s + sum R_ct + R_d at dc); the
double-layer wrapper must relax the voltage exponentially after a current step,
slower with a bigger capacitance.

Run with:  python -m pytest tests/ -q   (or: python tests/test_eis.py)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params                              # noqa: E402
from bubblesim.kernel import impedance as imp                        # noqa: E402
from bubblesim.kernel.kinetics import butler_volmer                  # noqa: E402
from bubblesim.kernel.context import build_context                   # noqa: E402
from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver          # noqa: E402
from bubblesim.solvers.dynamic import DoubleLayerWrapper             # noqa: E402


class Flat:
    def coverage(self):
        return 0.0
    def void_fraction(self):
        return 0.0


def test_rct_matches_numerical_bv_slope():
    """Analytic R_ct == 1 / (numerical dj/d eta) of Butler-Volmer."""
    j0, aa, ac, eta, T = 0.5, 0.6, 0.4, 0.25, 333.15
    h = 1e-7
    dj = (butler_volmer(j0, aa, ac, eta + h, T)
          - butler_volmer(j0, aa, ac, eta - h, T)) / (2 * h)
    assert math.isclose(imp.r_ct_bv(j0, aa, ac, eta, T), 1.0 / dj, rel_tol=1e-5)


def test_rct_equilibrium_textbook_limit():
    """At eta=0, R_ct = RT / ((alpha_a+alpha_c) F j0)."""
    j0, T = 1.0, 298.15
    want = 8.314462618 * T / ((0.5 + 0.5) * 96485.33212 * j0)
    assert math.isclose(imp.r_ct_bv(j0, 0.5, 0.5, 0.0, T), want, rel_tol=1e-9)


def test_spectrum_limits():
    """Z -> R_s at high frequency; Z -> R_s + sum(R_ct + R_d) at dc."""
    R_s = 2e-5
    els = [{"R_ct": 5e-5, "C_dl": 0.2, "R_d": 1e-5, "tau_d": 0.5},
           {"R_ct": 3e-5, "C_dl": 0.4}]
    Z_hi = imp.cell_impedance([1e7], R_s, els)[0]
    Z_dc = imp.cell_impedance([1e-7], R_s, els)[0]
    assert abs(Z_hi.real - R_s) / R_s < 0.01
    assert math.isclose(Z_dc.real, R_s + 5e-5 + 1e-5 + 3e-5, rel_tol=1e-3)
    assert abs(Z_dc.imag) < 1e-7


def test_semicircle_apex_frequency():
    """Single R_ct || C_dl: -Im(Z) peaks at f = 1/(2 pi R_ct C_dl)."""
    R_ct, C = 5e-5, 0.2
    f_star = 1.0 / (2 * math.pi * R_ct * C)
    freqs = [f_star * 10 ** (k / 20.0) for k in range(-20, 21)]
    Z = imp.cell_impedance(freqs, 0.0, [{"R_ct": R_ct, "C_dl": C}])
    peak = max(range(len(Z)), key=lambda i: -Z[i].imag)
    assert abs(math.log10(freqs[peak] / f_star)) < 0.06


def test_warburg_limits():
    """Finite Warburg -> R_d at dc and rolls off at high frequency."""
    assert imp.warburg_finite(0.0, 1e-4, 1.0) == complex(1e-4, 0.0)
    hi = imp.warburg_finite(1e5, 1e-4, 1.0)
    assert abs(hi) < 1e-5


def _run_relax(C_dl, n_steps, dt=1e-3, j2=4000.0):
    """Step j_set 1000 -> j2 under the wrapper; return |V - V_steady| decay."""
    p = Params()
    p.anode.C_dl = p.cathode.C_dl = C_dl
    op = Operating(mode="CP", j_set=1000.0, model="two_electrode")
    w = DoubleLayerWrapper(ZeroDTwoElectrodeSolver(), p, dt)
    ctx = build_context(op, p)
    for _ in range(50):                      # settle at the initial point
        w.solve(op, ctx, [Flat()])
    op.j_set = j2                            # current step
    V_ss = ZeroDTwoElectrodeSolver().solve(op, ctx, [Flat()]).V
    gaps = []
    for _ in range(n_steps):
        st = w.solve(op, ctx, [Flat()])
        gaps.append(abs(st.V - V_ss))
    return gaps


def test_dl_relaxation_approaches_steady():
    """After a current step, V decays monotonically toward the steady value."""
    gaps = _run_relax(C_dl=50.0, n_steps=400)
    assert gaps[-1] < 0.05 * gaps[0]
    assert all(b <= a + 1e-12 for a, b in zip(gaps, gaps[1:]))


def test_bigger_capacitance_relaxes_slower():
    """tau = R_ct C_dl: x10 capacitance -> larger remaining gap after the same time."""
    g_small = _run_relax(C_dl=20.0, n_steps=60)[-1]
    g_big = _run_relax(C_dl=200.0, n_steps=60)[-1]
    assert g_big > g_small


def test_wrapper_passthrough_in_cv():
    """CA mode bypasses the dynamics (steady solve unchanged)."""
    p = Params()
    op = Operating(V_cell=2.0, model="two_electrode")
    w = DoubleLayerWrapper(ZeroDTwoElectrodeSolver(), p, 1e-3)
    ctx = build_context(op, p)
    st_w = w.solve(op, ctx, [Flat()])
    st_0 = ZeroDTwoElectrodeSolver().solve(op, ctx, [Flat()])
    assert math.isclose(st_w.j, st_0.j, rel_tol=1e-12)


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
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
