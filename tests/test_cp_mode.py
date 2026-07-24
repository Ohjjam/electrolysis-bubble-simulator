"""Physics tests for galvanostatic (CP) operation — fixed current, voltage responds.

The key consistency law: CP is the inverse of CA. Solving CA at voltage V gives
j*; solving CP at j* must give back V (within solver tolerance). Coverage at
fixed current must *raise* the voltage — that is the sawtooth carrier under
commercial constant-current operation.

Run with:  python -m pytest tests/ -q   (or: python tests/test_cp_mode.py)
"""
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params, Simulator                 # noqa: E402
from bubblesim.kernel.context import build_context                 # noqa: E402
from bubblesim.solvers.zerod import ZeroDSolver, ZeroDTwoElectrodeSolver  # noqa: E402


class Flat:
    def __init__(self, theta=0.0, eps=0.0):
        self._t, self._e = theta, eps
    def coverage(self):
        return self._t
    def void_fraction(self):
        return self._e


def _solve(solver_cls, op, theta=0.0, eps=0.0):
    return solver_cls().solve(op, build_context(op, Params()), [Flat(theta, eps)])


def test_cp_inverts_ca_two_electrode():
    """CA(V)->j* then CP(j*)->V* must reconstruct V."""
    op_cv = Operating(V_cell=2.1, model="two_electrode")
    j_star = _solve(ZeroDTwoElectrodeSolver, op_cv).j
    op_cp = Operating(mode="CP", j_set=j_star, model="two_electrode")
    V_star = _solve(ZeroDTwoElectrodeSolver, op_cp).V
    assert math.isclose(V_star, 2.1, rel_tol=1e-3)


def test_cp_inverts_ca_lumped():
    op_cv = Operating(V_cell=2.0)
    j_star = _solve(ZeroDSolver, op_cv).j
    op_cp = Operating(mode="CP", j_set=j_star)
    V_star = _solve(ZeroDSolver, op_cp).V
    assert math.isclose(V_star, 2.0, rel_tol=1e-3)


def test_cp_voltage_monotonic_in_current():
    """Higher demanded current -> higher required voltage (polarization)."""
    Vs = [_solve(ZeroDTwoElectrodeSolver,
                 Operating(mode="CP", j_set=j, model="two_electrode")).V
          for j in (500.0, 2000.0, 8000.0)]
    assert Vs[0] < Vs[1] < Vs[2]


def test_cp_coverage_raises_voltage():
    """At fixed j, bubble coverage must cost voltage — the CP sawtooth driver."""
    op = Operating(mode="CP", j_set=2000.0, model="two_electrode")
    V0 = _solve(ZeroDTwoElectrodeSolver, op, theta=0.0).V
    V1 = _solve(ZeroDTwoElectrodeSolver, op, theta=0.4).V
    assert V1 > V0


def test_cp_preserves_setpoint_and_flags_transport_infeasibility():
    """Galvanostatic mode must not silently turn into a lower-current run."""
    op = Operating(mode="CP", j_set=1.0e9, model="two_electrode")
    st = _solve(ZeroDTwoElectrodeSolver, op)
    assert st.j == op.j_set
    assert st.fields["operating_feasible"] is False
    assert st.fields["transport_limit_exceeded"] is True
    assert st.fields["voltage_is_lower_bound"] is True
    assert st.fields["j_limit_A_m2"] < st.j
    assert math.isfinite(st.V)


def test_simulator_cp_constant_current_sawtooth_voltage():
    """End-to-end CP run: j stays pinned at the setpoint while V fluctuates
    (bubbles modulate the voltage, not the current)."""
    op = Operating(mode="CP", j_set=3000.0, model="two_electrode")
    h = Simulator(op, seed=0).run(t_end=0.4, dt=5e-4)
    settle = [v for t, v in zip(h["t"], h["j"]) if t > 0.1]
    assert all(math.isclose(v, 0.3, rel_tol=1e-6) for v in settle)   # A/cm^2
    Vs = [v for t, v in zip(h["t"], h["V"]) if t > 0.1]
    assert statistics.pstdev(Vs) > 1e-5                              # V moves
    assert min(Vs) > 1.4                                             # sane range


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
