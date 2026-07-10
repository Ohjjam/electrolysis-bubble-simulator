"""Physics tests for the mass-transport module (Phase 2).

Dimensionless groups, the limiting-current flow enhancement (Sherwood scaling),
the concentration overpotential limiting behavior, surface concentration, and
Henry supersaturation. Limiting cases and trends rather than magnitudes.

Run with:  python -m pytest tests/ -q   (or: python tests/test_transport.py)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params                            # noqa: E402
from bubblesim.kernel.context import build_context                 # noqa: E402
from bubblesim.kernel import transport as tr                       # noqa: E402


def test_dimensionless_groups():
    """Re, Sc, Sh follow their definitions; Sh -> sh0 at no flow."""
    assert math.isclose(tr.reynolds(1000.0, 0.1, 5e-3, 1e-3), 500.0)
    assert math.isclose(tr.schmidt(1e-3, 1000.0, 1e-9), 1000.0)
    assert tr.sherwood(0.0, 1000.0, sh0=2.0, coeff=6e-4) == 2.0          # no-flow floor
    assert tr.sherwood(500.0, 1000.0, sh0=2.0, coeff=6e-4) > 2.0         # forced convection adds


def test_flow_raises_limiting_current():
    """The Sherwood enhancement is 1 at no flow and rises with cross-flow."""
    P = Params()
    e0 = build_context(Operating(u_flow=0.0), P)["sh_enhancement"]
    e1 = build_context(Operating(u_flow=0.3), P)["sh_enhancement"]
    assert math.isclose(e0, 1.0, rel_tol=1e-12)
    assert e1 > e0
    j0 = build_context(Operating(u_flow=0.0), P)["j_lim_transport"]
    j1 = build_context(Operating(u_flow=0.3), P)["j_lim_transport"]
    assert j1 > j0


def test_conc_overpotential_limits():
    """eta_conc is 0 at zero current, positive below the limit, and grows
    without bound as j -> j_lim."""
    z, T, j_lim = 2, 333.15, 4.0e4
    assert tr.conc_overpotential(0.0, j_lim, z, T) == 0.0
    mid = tr.conc_overpotential(0.5 * j_lim, j_lim, z, T)
    near = tr.conc_overpotential(0.999 * j_lim, j_lim, z, T)
    assert 0.0 < mid < near
    assert tr.conc_overpotential(j_lim, j_lim, z, T) > near        # clamped, large, finite


def test_surface_concentration_depletes_with_current():
    """Surface/bulk ratio falls from 1 toward 0 as j approaches j_lim."""
    j_lim = 4.0e4
    assert math.isclose(tr.surface_conc_ratio(0.0, j_lim), 1.0)
    assert tr.surface_conc_ratio(0.5 * j_lim, j_lim) < 1.0
    assert tr.surface_conc_ratio(0.5 * j_lim, j_lim) > tr.surface_conc_ratio(0.9 * j_lim, j_lim)


def test_henry_supersaturation():
    """c_sat = P/k_H; supersaturation ratio S = c/c_sat."""
    c_sat = tr.saturation_concentration(2.0e5, 7.7e4)
    assert math.isclose(c_sat, 2.0e5 / 7.7e4)
    assert tr.supersaturation(2.0 * c_sat, c_sat) > 1.0
    assert tr.supersaturation(0.0, c_sat) == 0.0


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
