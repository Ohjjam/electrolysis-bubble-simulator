"""Robustness / stress tests (report item 4.2): extreme & degenerate inputs must
not crash, NaN, or grow memory unboundedly -- the solver should clamp and stay
finite. Complements the golden/monotonicity tests (which only cover the normal
range).

Run with:  python -m pytest tests/ -q   (or: python tests/test_stress.py)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params, Simulator                 # noqa: E402
from bubblesim.kernel.context import build_context                 # noqa: E402
from bubblesim.solvers import get_solver                           # noqa: E402
from bubblesim.solvers.oned import OneDGapSolver                   # noqa: E402


class Flat:
    """Minimal surface stub: fixed coverage/void plus the bubbles/A_patch that the
    1D solver's void projection reads."""
    def __init__(self, theta=0.0, eps=0.0, bubbles=None):
        self._t, self._e = theta, eps
        self.bubbles = bubbles or []
        self.A_patch = 6.0e-3 * 5.0e-3
    def coverage(self):
        return self._t
    def void_fraction(self):
        return self._e


def _all_finite(x):
    """Recursively assert every number in a scalar / list / dict is finite."""
    if isinstance(x, bool) or x is None or isinstance(x, str):
        return True
    if isinstance(x, (int, float)):
        return math.isfinite(x)
    if isinstance(x, (list, tuple)):
        return all(_all_finite(v) for v in x)
    if isinstance(x, dict):
        return all(_all_finite(v) for v in x.values())
    return True


def _check_state(st):
    assert math.isfinite(st.j), f"j not finite: {st.j}"
    assert st.j >= 0.0
    if st.V is not None:
        assert math.isfinite(st.V)
    assert _all_finite(st.overpotentials), st.overpotentials
    assert _all_finite(st.fields)


# extreme but plausible (and a few absurd) operating points
EXTREMES = [
    dict(u_flow=10.0),                 # absurd cross-flow
    dict(T=373.15),                    # 100 C
    dict(T=293.15),                    # cold
    dict(P=1.0e7),                     # 100 bar
    dict(P=5.0e4),                     # sub-atmospheric
    dict(c_electrolyte=0.5),           # dilute
    dict(c_electrolyte=10.0),          # saturated
    dict(contact_angle=10.0),          # superwetting
    dict(contact_angle=170.0),         # superphobic
    dict(gap_mm=0.5), dict(gap_mm=10.0),
    dict(B_field=3.0, E_ext=3.0e6),    # max fields
]


def test_extreme_inputs_all_solvers_modes():
    """Every solver, both modes, at each extreme -> finite j/V, no exception."""
    for model in ("lumped", "two_electrode", "oned"):
        solver = get_solver(model)
        for extra in EXTREMES:
            for mode, drive in (("CA", dict(V_cell=4.0)), ("CP", dict(j_set=1.0e9))):
                op = Operating(model=model, mode=mode, **drive, **extra)
                st = solver.solve(op, build_context(op, Params()), [Flat()])
                _check_state(st)


def test_extreme_with_coverage_and_void():
    """Heavy coverage / void at high drive must stay finite and current-bounded."""
    for model in ("two_electrode", "oned"):
        op = Operating(model=model, mode="CA", V_cell=4.0, contact_angle=160.0)
        st = get_solver(model).solve(op, build_context(op, Params()), [Flat(theta=0.9, eps=0.55)])
        _check_state(st)


def test_below_reversible_is_zero():
    """V below the reversible voltage -> exactly zero current, finite."""
    for model in ("lumped", "two_electrode", "oned"):
        op = Operating(model=model, mode="CA", V_cell=0.5)
        st = get_solver(model).solve(op, build_context(op, Params()), [Flat()])
        assert st.j == 0.0


def test_cp_huge_setpoint_clamps():
    """A galvanostatic setpoint far above any limit clamps finite (no runaway)."""
    for model in ("two_electrode", "oned"):
        op = Operating(model=model, mode="CP", j_set=1.0e12)
        st = get_solver(model).solve(op, build_context(op, Params()), [Flat()])
        _check_state(st)
        assert st.j < 1.0e9      # clamped well below the absurd setpoint


def test_degenerate_params_no_crash():
    """Degenerate but user-reachable Params values must not crash the solve."""
    for p in (Params(k_vogt=0.0), Params(j_ref_vogt=0.0), Params(r_membrane_area=1.0),
              Params(sh0=1.0)):
        op = Operating(model="two_electrode", mode="CP", j_set=2000.0)
        st = get_solver("two_electrode").solve(op, build_context(op, p), [Flat()])
        _check_state(st)


def test_oned_profiles_finite_at_extremes():
    """1D field profiles (numpy) stay finite under extreme flow / drive, with a
    dense wall-attached bubble layer exercising the void projection."""
    from bubblesim.bubble import Bubble
    for extra in (dict(u_flow=10.0), dict(V_cell=4.0), dict(gap_mm=0.5, c_electrolyte=0.5)):
        op = Operating(model="oned", mode="CA", track_both=True, **extra)
        bubs = lambda: [Bubble(x=1e-3, y=0.0, r=3.0e-4, id=i) for i in range(15)]
        st = OneDGapSolver().solve(op, build_context(op, Params()),
                                   [Flat(0.4, 0.3, bubs()), Flat(0.4, 0.3, bubs())])
        for key in ("eps_c", "c_c", "phi_c", "eps_a", "c_a"):
            if key in st.fields:
                assert _all_finite(st.fields[key]), key


def test_simulator_extreme_run_finite_and_bounded():
    """Full coupled run with everything cranked: no NaN in the trace, and the
    bubble population stays bounded (no memory blow-up)."""
    op = Operating(mode="CP", j_set=3.0e4, model="two_electrode", track_both=True,
                   nucleation="supersaturation", thermal=True, contact_angle=150.0,
                   T=363.15, c_electrolyte=10.0)
    p = Params(thermal_mass=0.2, hA_cool=0.02)        # weak cooling -> T pushed hard
    sim = Simulator(op, p, seed=0)
    h = sim.run(t_end=0.2, dt=5e-4)
    for key, series in h.items():
        assert _all_finite(series), f"non-finite in history[{key}]"
    # site_count caps attached bubbles per surface; detached are culled in advect
    assert max(h["n_bub"]) < 5000


def test_supersaturation_extreme_no_nan():
    """Supersaturation nucleation at extreme low pressure (huge S) stays finite."""
    op = Operating(V_cell=2.5, nucleation="supersaturation", P=5.0e4)
    h = Simulator(op, seed=0).run(t_end=0.2, dt=5e-4)
    assert _all_finite(h["j"]) and _all_finite(h["theta"])


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
