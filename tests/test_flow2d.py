"""In-tool 2-D two-phase bubble-flow CFD (Euler-Lagrange), model="flow2d".

This is the self-contained "real CFD" path: the liquid Navier-Stokes is actually
solved and bubbles are two-way coupled, so vortices / bubble self-stirring EMERGE.
2-D, sub-grid bubbles (no interface resolution) -- not 3-D VOF.

Contracts:
  * stays finite/stable over a long run
  * bubbles nucleate on the electrode wall and reach a bounded steady population
  * the flow develops beyond the inlet (vmax > u_in) and vorticity is non-trivial
    -> bubble-induced convection is emergent, not prescribed
  * more current -> more bubbles; no current -> ~no bubbles
  * snapshot is well-formed and JSON-friendly

Run with:  python -m pytest tests/ -q   (or: python tests/test_flow2d.py)
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim.solvers.flow2d import FlowChannel2D                # noqa: E402


def _run(j=4000.0, steps=800, dt=2.0e-3, **kw):
    f = FlowChannel2D(seed=0, **kw)
    for _ in range(steps):
        f.step(dt, j, 3.0e-4, 60.0)
    return f


def test_stable_and_finite():
    f = _run()
    assert np.isfinite(f.u).all() and np.isfinite(f.v).all() and np.isfinite(f.omega).all()
    assert np.abs(f.u).max() < 5.0                  # no runaway


def test_bubbles_nucleate_and_bound():
    f = _run()
    n = len(f.bub)
    assert 20 < n < 700                             # populated but bounded (not blown up / capped)
    assert any(b[3] < 0.5 for b in f.bub)           # some detached (rose off the wall)
    assert all(0.0 <= b[0] <= f.Lx and 0.0 <= b[1] <= f.Ly for b in f.bub)


def test_flow_is_emergent():
    f = _run()
    s = f.snapshot()
    assert s["vmax"] > f.u_in * 1.1                 # plumes speed the flow past the inlet value
    assert (f.omega.max() - f.omega.min()) > 10.0   # non-trivial vorticity (vortices)


def test_more_current_more_bubbles():
    lo = len(_run(j=1500.0).bub)
    hi = len(_run(j=8000.0).bub)
    assert hi > lo
    assert len(_run(j=0.0, steps=300).bub) < 5      # no current -> ~no gas


def test_snapshot_well_formed():
    s = _run(steps=300).snapshot()
    assert s["nx"] > 0 and s["ny"] > 0 and len(s["speed"]) > 0
    assert all(math.isfinite(v) for row in s["speed"] for v in row)
    for b in s["bub"]:
        assert len(b) == 4 and all(math.isfinite(v) for v in b)   # [id, x/Lx, y/Ly, r]
        assert 0.0 <= b[1] <= 1.0 and 0.0 <= b[2] <= 1.0    # normalized coords


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
