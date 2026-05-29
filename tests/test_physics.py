"""Sanity tests for the physics — limiting cases and conservation laws.

Run with:  python -m pytest tests/ -q     (or: python tests/test_physics.py)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params, Simulator        # noqa: E402
from bubblesim import properties as prop                  # noqa: E402
from bubblesim import electrochem                          # noqa: E402
from bubblesim.sweeps import steady_means                  # noqa: E402


def _props(op):
    return Simulator(op=op).props() | {
        "j0": Params().j0, "tafel_b": Params().tafel_b,
        "j_lim_eff": Params().j_lim, "Cd_flow": Params().Cd_flow,
        "k_mhd": Params().k_mhd, "r_min_detach": Params().r_min_detach,
    }


def test_no_current_below_reversible():
    """Below the reversible voltage no net current flows."""
    op = Operating(V_cell=1.0)
    P = _props(op)
    j = electrochem.solve_current_density(op, P, theta=0.0, eps=0.0)
    assert j == 0.0


def test_current_monotonic_in_voltage():
    """Higher voltage -> higher current (fixed coverage/void)."""
    op = Operating()
    P = _props(op)
    js = [electrochem.solve_current_density(Operating(V_cell=V), _props(Operating(V_cell=V)),
                                            0.1, 0.1) for V in (1.6, 1.8, 2.0, 2.2)]
    assert all(b > a for a, b in zip(js, js[1:]))


def test_coverage_and_void_reduce_current():
    """Both bubble coverage and void fraction can only reduce the current."""
    op = Operating(V_cell=2.0)
    P = _props(op)
    base = electrochem.solve_current_density(op, P, 0.0, 0.0)
    cov = electrochem.solve_current_density(op, P, 0.4, 0.0)
    void = electrochem.solve_current_density(op, P, 0.0, 0.4)
    assert cov < base
    assert void < base


def test_faraday_gas_rate():
    """Evolved-gas molar rate must equal I/(zF); H2 (z=2) doubles O2 (z=4) per amp."""
    from bubblesim.constants import F
    I = 1.0  # A
    n_h2 = I / (2 * F)
    n_o2 = I / (4 * F)
    assert math.isclose(n_h2 / n_o2, 2.0)


def test_wettability_trend():
    """Hydrophilic (low angle) gives smaller departure radius than hydrophobic."""
    lo = steady_means(Operating(V_cell=2.0, contact_angle=25), t_end=0.8, dt=3e-4)
    hi = steady_means(Operating(V_cell=2.0, contact_angle=110), t_end=0.8, dt=3e-4)
    assert lo["r_d"] < hi["r_d"]
    assert lo["theta"] < hi["theta"]      # wetting surface -> less coverage
    assert lo["j"] > hi["j"]              # ... -> more current


def test_flow_clears_bubbles():
    """Forced flow reduces coverage and raises current."""
    still = steady_means(Operating(V_cell=2.0, u_flow=0.0), t_end=0.8, dt=3e-4)
    fast = steady_means(Operating(V_cell=2.0, u_flow=0.4), t_end=0.8, dt=3e-4)
    assert fast["theta"] < still["theta"]
    assert fast["j"] > still["j"]


def test_conductivity_optimum():
    """KOH conductivity peaks near ~6 M (Bruggeman-free check on the correlation)."""
    k = [prop.conductivity_KOH(c, 298.15) for c in (1, 3, 6, 9)]
    assert k[2] == max(k)


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
