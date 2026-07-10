"""Track 4 cell design -- flow-channel bottleneck solver (model="channel").

Contracts:
  * gas builds up DOWNSTREAM: coverage at the outlet > at the inlet
  * a longer path (more serpentine passes) -> worse outlet bottleneck
  * higher flow sweeps gas out -> lower bottleneck
  * parallel (short channels) bottlenecks less than serpentine (one long path)
  * the 2-D path segments are finite and inside the unit cell
  * charge conserved (mean redistributed current == scalar current); finite extremes

Run with:  python -m pytest tests/ -q   (or: python tests/test_channel.py)
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params                          # noqa: E402
from bubblesim.kernel.context import build_context               # noqa: E402
from bubblesim.solvers.channel import ChannelSolver              # noqa: E402


class Flat:
    def coverage(self):
        return 0.0
    def void_fraction(self):
        return 0.0


def _solve(op):
    return ChannelSolver().solve(op, build_context(op, Params()), [Flat(), Flat()])


def _common(**kw):
    return dict(model="channel", mode="CP", j_set=6000.0, track_both=True,
                cell_width_cm=5.0, face_height_cm=10.0, **kw)


def test_gas_builds_up_downstream():
    st = _solve(Operating(**_common(channel_type="serpentine", n_pass=5, u_flow=0.05)))
    f = st.fields
    assert f["theta_out"] > f["theta_in"]            # outlet more blanketed
    assert f["theta_out"] > 0.05


def test_longer_path_worse():
    lo = _solve(Operating(**_common(channel_type="serpentine", n_pass=2, u_flow=0.05))).fields["theta_out"]
    hi = _solve(Operating(**_common(channel_type="serpentine", n_pass=8, u_flow=0.05))).fields["theta_out"]
    assert hi > lo                                   # more passes -> longer path -> worse


def test_flow_reduces_bottleneck():
    slow = _solve(Operating(**_common(channel_type="serpentine", n_pass=6, u_flow=0.03))).fields["theta_out"]
    fast = _solve(Operating(**_common(channel_type="serpentine", n_pass=6, u_flow=0.4))).fields["theta_out"]
    assert fast < slow


def test_parallel_beats_serpentine():
    serp = _solve(Operating(**_common(channel_type="serpentine", n_pass=6, u_flow=0.05))).fields["theta_out"]
    par = _solve(Operating(**_common(channel_type="parallel", n_pass=6, u_flow=0.05))).fields["theta_out"]
    assert par < serp                                # short parallel channels clog less


def test_segments_well_formed():
    st = _solve(Operating(**_common(channel_type="serpentine", n_pass=4)))
    segs = st.fields["segments"]
    assert len(segs) > 10
    for s in segs:
        assert len(s) == 8                           # x0,y0,x1,y1,j,eps,theta,eff
        for v in s:
            assert math.isfinite(v)
        for k in (0, 1, 2, 3):
            assert -0.01 <= s[k] <= 1.01             # x/y inside the unit cell


def test_custom_drawn_path():
    """A user-drawn flow path (design tool) is used as the channel geometry."""
    op = Operating(model="channel", mode="CP", j_set=5000.0, track_both=True,
                   custom_path=[[0.05, 0.1], [0.9, 0.1], [0.9, 0.5], [0.1, 0.5], [0.1, 0.9], [0.9, 0.9]])
    st = _solve(op)
    assert st.fields["ctype"] == "custom"
    segs = st.fields["segments"]
    assert len(segs) > 10 and all(len(s) == 8 for s in segs)
    assert st.fields["theta_out"] >= st.fields["theta_in"]      # still accumulates downstream
    # all path points inside the unit cell
    for s in segs:
        for k in (0, 1, 2, 3):
            assert -0.01 <= s[k] <= 1.01


def test_charge_conserved_and_finite():
    st = _solve(Operating(**_common(channel_type="serpentine", n_pass=5)))
    segs = np.array(st.fields["segments"])
    assert math.isclose(segs[:, 4].mean(), st.j, rel_tol=0.05)   # mean current ~ scalar
    for op in (Operating(**_common(channel_type="serpentine", n_pass=8, u_flow=0.0)),
               Operating(**_common(channel_type="straight")),
               Operating(model="channel", mode="CA", V_cell=4.0, track_both=True)):
        s = _solve(op)
        assert math.isfinite(s.j) and s.j >= 0.0
        if s.V is not None:
            assert math.isfinite(s.V)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1; print(f"  FAIL  {fn.__name__}  {e}")
        except Exception as e:
            failed += 1; print(f"  ERROR {fn.__name__}  {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
