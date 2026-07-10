"""Physics tests for the electrolyte-chemistry module (Phase 3).

Ionic strength, the Davies activity coefficient (including its high-I upturn),
the temperature dependence of pKw, bulk pH, and the current-driven local
(surface) pH split between the electrodes — plus that the two-electrode solver
reports it.

Run with:  python -m pytest tests/ -q   (or: python tests/test_chemistry.py)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params                            # noqa: E402
from bubblesim.kernel import chemistry as chem                     # noqa: E402
from bubblesim.kernel.context import build_context                 # noqa: E402
from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver        # noqa: E402


class FakeSurface:
    def __init__(self, theta=0.0, eps=0.0):
        self._t, self._e = theta, eps
    def coverage(self):
        return self._t
    def void_fraction(self):
        return self._e


def test_ionic_strength_one_to_one():
    assert chem.ionic_strength(6.0) == 6.0


def test_davies_activity_trend():
    """Activity coefficient dips below 1 at moderate I, then turns back up at
    high ionic strength (the Davies upturn)."""
    assert chem.davies_activity(0.5) < 1.0
    assert chem.davies_activity(6.0) > chem.davies_activity(0.5)


def test_pkw_decreases_with_temperature():
    assert math.isclose(chem.pKw(298.15), 14.0, abs_tol=1e-9)
    assert chem.pKw(333.15) < 14.0


def test_bulk_ph_strongly_alkaline():
    """6 M KOH is strongly alkaline (pH well above 13)."""
    assert chem.bulk_pH(6.0, 333.15) > 13.0


def test_local_ph_splits_under_current():
    """No split at zero current; cathode rises and anode falls under load."""
    c, T, j_lim = 6.0, 333.15, 4.0e4
    bulk = chem.bulk_pH(c, T)
    # zero current -> surface == bulk on both electrodes
    assert math.isclose(chem.local_pH(c, 0.0, j_lim, "HER", T), bulk, rel_tol=1e-12)
    assert math.isclose(chem.local_pH(c, 0.0, j_lim, "OER", T), bulk, rel_tol=1e-12)
    # under current -> cathode more alkaline than bulk, anode less
    j = 0.5 * j_lim
    pH_c = chem.local_pH(c, j, j_lim, "HER", T)
    pH_a = chem.local_pH(c, j, j_lim, "OER", T)
    assert pH_c > bulk > pH_a


def test_solver_reports_local_ph():
    """The two-electrode solver surfaces the local-pH split in its fields."""
    op = Operating(V_cell=2.1, model="two_electrode")
    ctx = build_context(op, Params())
    st = ZeroDTwoElectrodeSolver().solve(op, ctx, [FakeSurface()])
    f = st.fields
    assert f["pH_cathode"] > f["pH_bulk"] > f["pH_anode"]


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
