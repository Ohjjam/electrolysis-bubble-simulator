"""Track 3 -- face-field 2.5-D solver (bottleneck map).

Contracts:
  * coverage accumulates up the electrode (top > bottom) and with current
  * cross-flow sweeps the wall -> lower coverage
  * current redistributes: the clear bottom carries more than the blanketed top
  * charge is conserved: mean(j_field) == scalar mean current
  * a small electrode / low current -> nearly uniform field (reduces to 0-D)
  * CP holds the mean at the setpoint; extremes stay finite

Run with:  python -m pytest tests/ -q   (or: python tests/test_face2d.py)
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params                          # noqa: E402
from bubblesim.kernel.context import build_context               # noqa: E402
from bubblesim.solvers.face2d import Face2DSolver, coverage_field  # noqa: E402


class Flat:
    def __init__(self, eps=0.0):
        self._e = eps
    def coverage(self):
        return 0.0
    def void_fraction(self):
        return self._e


def _solve(op):
    return Face2DSolver().solve(op, build_context(op, Params()), [Flat(), Flat()])


def test_coverage_rises_up_the_electrode():
    op = Operating(model="face2d", mode="CP", j_set=4000.0, face_height_cm=15.0)
    th = coverage_field(4000.0, op, 6, 12)
    assert th[-1].mean() > th[0].mean()              # top more blanketed than bottom
    assert th[0].mean() < 0.2                        # bottom nearly clear


def test_coverage_grows_with_current_and_height():
    op_lo = Operating(model="face2d", face_height_cm=15.0)
    th_lo = coverage_field(1000.0, op_lo, 6, 12)[-1].mean()
    th_hi = coverage_field(8000.0, op_lo, 6, 12)[-1].mean()
    assert th_hi > th_lo
    small = coverage_field(4000.0, Operating(face_height_cm=1.0), 6, 12)[-1].mean()
    big = coverage_field(4000.0, Operating(face_height_cm=20.0), 6, 12)[-1].mean()
    assert big > small                               # taller electrode -> more accumulation


def test_flow_reduces_coverage():
    th_still = coverage_field(5000.0, Operating(u_flow=0.0, face_height_cm=15.0), 6, 12)[-1].mean()
    th_flow = coverage_field(5000.0, Operating(u_flow=0.3, face_height_cm=15.0), 6, 12)[-1].mean()
    assert th_flow < th_still


def test_current_redistributes_bottom_carries_more():
    st = _solve(Operating(model="face2d", mode="CP", j_set=5000.0, face_height_cm=15.0,
                          track_both=True))
    f = st.fields
    assert f["j_bot"] > f["j_top"]                   # clear bottom carries more current
    assert st.overpotentials["j_spread"] > 1.0       # non-uniform


def test_charge_conserved():
    st = _solve(Operating(model="face2d", mode="CP", j_set=3000.0, face_height_cm=12.0,
                          track_both=True))
    jf = np.array(st.fields["j_field"])
    assert math.isclose(jf.mean(), st.j, rel_tol=1e-6)


def test_cp_holds_setpoint_mean():
    st = _solve(Operating(model="face2d", mode="CP", j_set=2500.0, track_both=True))
    assert math.isclose(st.j, 2500.0, rel_tol=0.05)  # A/m^2 (mean pinned near setpoint)


def test_small_electrode_nearly_uniform():
    """A tiny / low-current electrode barely accumulates -> field ~ uniform (0-D limit)."""
    st = _solve(Operating(model="face2d", mode="CP", j_set=500.0, face_height_cm=0.5,
                          track_both=True))
    jf = np.array(st.fields["j_field"])
    assert (jf.max() - jf.min()) / jf.mean() < 0.1


def test_finite_at_extremes():
    for op in (Operating(model="face2d", mode="CA", V_cell=4.0, face_height_cm=30.0, track_both=True),
               Operating(model="face2d", mode="CP", j_set=1.0e9, track_both=True),
               Operating(model="face2d", mode="CP", j_set=4000.0, u_flow=10.0, track_both=True)):
        st = _solve(op)
        assert math.isfinite(st.j) and st.j >= 0.0
        if st.V is not None:
            assert math.isfinite(st.V)
        assert all(math.isfinite(v) for row in st.fields["j_field"] for v in row)


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
