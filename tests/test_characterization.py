"""Characterization (golden-value) tests — a refactor safety net.

The sanity tests in `test_physics.py` check *trends* (monotonicity, limiting
cases), so they stay green even if a behavior-preserving refactor accidentally
shifts the numbers. These tests pin the *exact* outputs of the current model so
that the Phase-0 restructuring (moving modules into `kernel/`, extracting
`build_context`, introducing the `Solver` indirection) provably changes nothing.

The values were captured from the lumped 0D model at commit-of-record with the
default seed (0), so they are deterministic. Tolerances are tight (rel 1e-9):
a pure move/extraction reproduces float ops exactly, so any drift is a real
logic change and should fail here.

When a *physics* phase legitimately changes these numbers, re-baseline this file
in the same commit and note why.

Run with:  python -m pytest tests/ -q     (or: python tests/test_characterization.py)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params, Simulator        # noqa: E402
from bubblesim import electrochem                          # noqa: E402
from bubblesim.sweeps import steady_means                  # noqa: E402

REL = 1e-9   # pure refactors are bit-identical; this catches real logic drift

# --- golden values: lumped 0D model, default Params, seed=0 ----------------
# RE-BASELINED (physics-audit completion): the lumped solver now carries a
# concentration overpotential (eta_conc, smooth transport limit), coverage is the
# Poisson union 1-exp(-sum/A) (was the overlap-double-counting linear sum), KOH
# viscosity is super-linear (0.89 mPa.s base + 0.035 c^2), and the bubble rise
# velocity uses the Schiller-Naumann Re-aware drag. j therefore drops slightly
# (transport penalty), theta/eps rise (truer coverage + slower rise), r_d is
# unchanged (departure physics untouched at E_ext=0). Re-baselined again after
# removing the arbitrary residual 0.05/0.9 coalescence probabilities: above the
# measured critical coalescence concentration, this reduced model now reports
# inhibited coalescence instead of silently forcing 5% of contacts to merge.
# RE-BASELINED (2026-07-22 Sol audit): concentration polarisation now uses the
# monovalent ionic carrier charge |z|=1. HER/OER molecule stoichiometry z=2/4 is
# reserved for Faraday gas production, so changing the display electrode label
# can no longer change the same full-cell transport loss.
GOLDEN_STEADY_V2 = {
    "j":         0.3252074411712452,
    "I":         0.3252074411712452,
    "theta":     0.5600887164585785,
    "eps":       0.5625952587214317,
    "r_d":       0.0015241237104220628,
    "n_bub":     69.0,
    "eta_ohmic": 0.22023211524525405,
}

# solve_current_density(Operating(V_cell=V), props, theta, eps) -> j [A/m^2]
GOLDEN_SOLVE_J = [
    # (V_cell, theta, eps, expected_j)
    (2.0, 0.0, 0.0, 9930.76410284713),
    (2.0, 0.4, 0.2, 6869.323589453472),
    (1.8, 0.1, 0.1, 3064.586994270546),
]


def test_construct_with_no_args():
    """Operating() and Params() must remain zero-argument constructible."""
    assert Operating() is not None
    assert Params() is not None


def test_steady_means_golden():
    """steady_means at the default operating point reproduces pinned values."""
    m = steady_means(Operating(V_cell=2.0))
    for k, want in GOLDEN_STEADY_V2.items():
        assert math.isclose(m[k], want, rel_tol=REL), f"{k}: {m[k]!r} != {want!r}"


def test_solve_current_density_golden():
    """The lumped electrochemistry solve reproduces pinned current densities."""
    for V, theta, eps, want in GOLDEN_SOLVE_J:
        op = Operating(V_cell=V)
        props = Simulator(op=op).props()
        j = electrochem.solve_current_density(op, props, theta, eps)
        assert math.isclose(j, want, rel_tol=REL), \
            f"V={V} theta={theta} eps={eps}: {j!r} != {want!r}"


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
