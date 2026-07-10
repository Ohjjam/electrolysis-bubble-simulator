"""Physics tests for the 1D gap solver (Phase 5) and the bubble->grid projection.

The headline consistency law: with no bubbles and far from the transport limit,
1D must agree with the 0D two-electrode solver (the cheap model is exact there).
Near the limit they diverge — by design, that is what the extra dimension buys.

Run with:  python -m pytest tests/ -q   (or: python tests/test_oned.py)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params, Simulator                 # noqa: E402
from bubblesim.bubble import Bubble                                 # noqa: E402
from bubblesim.kernel.coupling import void_profile                  # noqa: E402
from bubblesim.kernel.context import build_context                  # noqa: E402
from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver         # noqa: E402
from bubblesim.solvers.oned import OneDGapSolver                    # noqa: E402


class Flat:
    def __init__(self, theta=0.0, bubbles=None):
        self._t = theta
        self.bubbles = bubbles or []
        self.A_patch = 6.0e-3 * 5.0e-3
    def coverage(self):
        return self._t
    def void_fraction(self):
        return 0.0


def test_projection_conserves_volume():
    """Total gas volume on the grid equals the bubbles' volume (no cap hit)."""
    A = 6.0e-3 * 5.0e-3
    bubbles = [Bubble(x=0.0, y=2.0e-4, r=5.0e-5),
               Bubble(x=0.0, y=8.0e-4, r=8.0e-5)]
    L, n = 2.0e-3, 50
    eps = void_profile(bubbles, L, n, A)
    vol_grid = sum(e * A * (L / n) for e in eps)
    vol_true = sum(b.volume() for b in bubbles)
    assert math.isclose(vol_grid, vol_true, rel_tol=1e-9)


def test_projection_attached_sits_at_wall():
    """An attached bubble (y=0) projects onto the first cells, not nowhere."""
    A = 6.0e-3 * 5.0e-3
    eps = void_profile([Bubble(x=0.0, y=0.0, r=1.0e-4)], 2.0e-3, 40, A)
    assert eps[0] > 0.0 and sum(eps) > 0.0


def test_bubble_free_ohmic_matches_0d():
    """No bubbles -> layer-resolved resistance collapses to gap/kappa, so the
    1D eta_ohmic equals the 0D one at the same current."""
    op = Operating(mode="CP", j_set=2000.0, model="oned")
    ctx = build_context(op, Params())
    st1 = OneDGapSolver().solve(op, ctx, [Flat()])
    st0 = ZeroDTwoElectrodeSolver().solve(op, ctx, [Flat()])
    assert math.isclose(st1.overpotentials["eta_ohmic"],
                        st0.overpotentials["eta_ohmic"], rel_tol=1e-6)


def test_cross_fidelity_agreement_far_from_limit():
    """Cheap-model validity: bubble-free, low current -> 1D and 0D agree on V
    within a few percent (conc terms differ by construction near the limit)."""
    op = Operating(mode="CP", j_set=500.0, model="oned")
    ctx = build_context(op, Params())
    V1 = OneDGapSolver().solve(op, ctx, [Flat()]).V
    V0 = ZeroDTwoElectrodeSolver().solve(op, ctx, [Flat()]).V
    assert abs(V1 - V0) / V0 < 0.03


def test_derived_limiting_current_and_flow():
    """j_lim is derived from D, c, delta, t_carrier — and flow raises it."""
    op0 = Operating(mode="CP", j_set=1000.0, model="oned", u_flow=0.0)
    op1 = Operating(mode="CP", j_set=1000.0, model="oned", u_flow=0.4)
    j0 = OneDGapSolver().solve(op0, build_context(op0, Params()), [Flat()])
    j1 = OneDGapSolver().solve(op1, build_context(op1, Params()), [Flat()])
    assert j1.fields["j_lim_1d"] > j0.fields["j_lim_1d"]
    assert j0.fields["delta_mm"] > j1.fields["delta_mm"] or \
           math.isclose(j0.fields["delta_mm"], j1.fields["delta_mm"])  # capped case


def test_profiles_physical():
    """c(z)/c_b rises from the depleted surface to 1 in the bulk; eps(z) is
    concentrated near the wall when bubbles are attached."""
    bubbles = [Bubble(x=1e-3, y=0.0, r=8.0e-5) for _ in range(5)]
    op = Operating(mode="CP", j_set=3000.0, model="oned")
    st = OneDGapSolver().solve(op, build_context(op, Params()), [Flat(bubbles=bubbles)])
    c = st.fields["c_c"]
    assert c[0] < c[-1] <= 1.0 + 1e-12
    eps = st.fields["eps_c"]
    assert eps[0] > eps[-1]


def test_bubbles_raise_1d_ohmic():
    """Wall-attached bubbles must increase the layer-resolved resistance."""
    op = Operating(mode="CP", j_set=2000.0, model="oned")
    ctx = build_context(op, Params())
    clean = OneDGapSolver().solve(op, ctx, [Flat()]).overpotentials["eta_ohmic"]
    bubbly = OneDGapSolver().solve(op, ctx, [Flat(bubbles=[
        Bubble(x=1e-3, y=0.0, r=2.0e-4) for _ in range(8)])]).overpotentials["eta_ohmic"]
    assert bubbly > clean


def test_simulator_runs_oned_dual():
    """End-to-end coupled run on the 1D fidelity with both electrodes."""
    op = Operating(mode="CP", j_set=2000.0, model="oned", track_both=True)
    sim = Simulator(op, seed=0)
    h = sim.run(t_end=0.15, dt=5e-4)
    assert h["j"][-1] > 0.0
    assert max(h["n_bub"]) > 0
    assert sim.last_state.fields["z_mm"]          # profiles present


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
