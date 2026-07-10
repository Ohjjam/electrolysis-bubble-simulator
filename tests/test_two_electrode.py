"""Physics tests for the two-electrode Butler-Volmer fidelity (Phase 1).

Kinetics limiting cases (reduction to known laws), Arrhenius monotonicity, and
the full-cell two-electrode solve (trends + voltage-balance conservation). The
solver-physics tests drive the solver directly with a fake fixed-coverage
surface, so they are fast and isolate the electrochemistry from the bubble loop.

Run with:  python -m pytest tests/ -q   (or: python tests/test_two_electrode.py)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params, Simulator                 # noqa: E402
from bubblesim.constants import F, R_GAS                           # noqa: E402
from bubblesim.properties import j0_arrhenius                      # noqa: E402
from bubblesim.kernel.kinetics import butler_volmer                # noqa: E402
from bubblesim.kernel.context import build_context                 # noqa: E402
from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver        # noqa: E402


class FakeSurface:
    """Stand-in for a Surface with fixed coverage / void (no bubble loop)."""
    def __init__(self, theta=0.0, eps=0.0):
        self._theta, self._eps = theta, eps

    def coverage(self):
        return self._theta

    def void_fraction(self):
        return self._eps


def _solve(op, params=None, theta=0.0, eps=0.0):
    params = params or Params()
    ctx = build_context(op, params)
    return ZeroDTwoElectrodeSolver().solve(op, ctx, [FakeSurface(theta, eps)])


# ---------------------------------------------------------------- kinetics
def test_butler_volmer_zero_at_equilibrium():
    """No net current at zero overpotential."""
    assert butler_volmer(1.0, 0.5, 0.5, 0.0, 333.15) == 0.0


def test_butler_volmer_tafel_limit():
    """At large anodic overpotential BV collapses onto the Tafel exponential."""
    T, eta = 333.15, 0.4
    f = F / (R_GAS * T)
    j = butler_volmer(1.0, 0.5, 0.5, eta, T)
    tafel = 1.0 * math.exp(0.5 * f * eta)          # back-reaction term negligible
    assert math.isclose(j, tafel, rel_tol=1e-3)


def test_butler_volmer_symmetric_is_odd():
    """With alpha_a == alpha_c, BV is an odd function of overpotential."""
    T = 333.15
    assert math.isclose(butler_volmer(1.0, 0.5, 0.5, -0.1, T),
                        -butler_volmer(1.0, 0.5, 0.5, 0.1, T), rel_tol=1e-12)


def test_j0_arrhenius_reference_and_monotonic():
    """j0 equals j0_ref at the reference point and rises with temperature."""
    assert math.isclose(j0_arrhenius(2.0, 40e3, 298.15, 6.0, gamma=0.5,
                                     T_ref=298.15, c_ref=6.0), 2.0, rel_tol=1e-12)
    lo = j0_arrhenius(1.0, 40e3, 300.0, 6.0)
    hi = j0_arrhenius(1.0, 40e3, 340.0, 6.0)
    assert hi > lo


# ----------------------------------------------------- two-electrode solve
def test_no_current_below_reversible():
    """Below the reversible cell voltage, no current flows."""
    op = Operating(V_cell=1.0, model="two_electrode")
    assert _solve(op).j == 0.0


def test_current_monotonic_in_voltage():
    """Higher cell voltage -> higher current density."""
    js = [_solve(Operating(V_cell=V, model="two_electrode")).j
          for V in (1.6, 1.8, 2.0, 2.2)]
    assert all(b > a for a, b in zip(js, js[1:]))


def test_coverage_reduces_current():
    """Coverage on the primary electrode blocks active area -> lower current."""
    op = Operating(V_cell=2.0, model="two_electrode")
    assert _solve(op, theta=0.5).j < _solve(op, theta=0.0).j


def test_membrane_resistance_reduces_current():
    """Adding membrane/contact series resistance lowers the current at fixed V."""
    op = Operating(V_cell=2.0, model="two_electrode")
    base = _solve(op, Params()).j
    with_R = _solve(op, Params(r_membrane_area=2e-4, r_contact_area=1e-4)).j
    assert with_R < base


def test_voltage_balance_closes():
    """The returned overpotentials reconstruct the applied cell voltage."""
    op = Operating(V_cell=2.0, model="two_electrode")
    st = _solve(op)
    ov = st.overpotentials
    recon = ov["E_rev"] + ov["eta_act"] + ov["eta_conc"] + ov["eta_ohmic"]
    assert math.isclose(recon, op.V_cell, rel_tol=1e-6, abs_tol=1e-6)


def test_simulator_runs_two_electrode():
    """End-to-end: a short coupled run on the two-electrode fidelity evolves a
    positive current and nucleates bubbles (sawtooth coupling intact)."""
    sim = Simulator(Operating(V_cell=2.0, model="two_electrode"), seed=0)
    h = sim.run(t_end=0.2, dt=3e-4)
    assert h["j"][-1] > 0.0
    assert max(h["n_bub"]) > 0


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
