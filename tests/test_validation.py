"""External-validity tests: does the model reproduce REAL electrochemistry?

Internal correctness (formulas/units) is covered by the other suites; this file
checks the model against MEASURED / textbook benchmarks, which is what makes it
credible as a real water-electrolysis simulator:

  * thermodynamic anchors  (E_rev, thermoneutral voltage)
  * a measured alkaline polarization curve -- the AHEAD paper (Zhang et al.,
    Sci. Adv. 12, eadz1865, 2026): 30 wt% KOH, 80 C, NiFe/NiMo, zero-gap;
    serpentine ~0.785 A/cm^2 @ 2.0 V, ~1.0 A/cm^2 @ ~2.05 V.

Tolerances are loose (a reduced-order model + a calibration, not a fit), but tight
enough to catch the "2.0 V -> 2 A/cm^2" over-prediction that an uncalibrated model
gives. If the kinetic defaults drift, these fail.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params, Simulator                          # noqa: E402
from bubblesim.properties import reversible_voltage                          # noqa: E402
from bubblesim.kernel import energy                                          # noqa: E402
from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver                  # noqa: E402

_SOLVER = ZeroDTwoElectrodeSolver()


def _ahead_cell(V):
    """AHEAD alkaline zero-gap cell at the calibrated defaults; bubble-free
    kinetic+ohmic polarization point -> j [A/cm^2] and the overpotential split."""
    op = Operating(model="two_electrode", track_both=True, electrolyte="KOH",
                   c_electrolyte=6.9, T=353.15, gap_mm=0.5, V_cell=V, high_fidelity=True)
    sim = Simulator(op=op, params=Params())
    st = _SOLVER.solve(op, sim.props(), sim.surfaces)
    return st.j / 1e4, st.overpotentials


def test_reversible_voltage_anchors():
    assert math.isclose(reversible_voltage(298.15), 1.229, abs_tol=2e-3)      # 25 C
    assert math.isclose(reversible_voltage(353.15), 1.180, abs_tol=8e-3)      # 80 C
    assert math.isclose(energy.V_THERMONEUTRAL, 1.481, abs_tol=1e-3)


def test_ahead_polarization_point():
    """~0.785 A/cm^2 at 2.0 V (80 C) -- within 12% of the measured serpentine cell."""
    j, _ = _ahead_cell(2.0)
    assert abs(j - 0.785) / 0.785 < 0.12, f"j@2.0V={j:.3f} A/cm2 (AHEAD ~0.785)"


def test_polarization_realistic_range_and_monotonic():
    """A real alkaline cell sits ~0.3-1.2 A/cm^2 at 2.0 V (NOT ~2+); monotone in V."""
    j16, j18, j20 = _ahead_cell(1.6)[0], _ahead_cell(1.8)[0], _ahead_cell(2.0)[0]
    assert j16 < j18 < j20
    assert 0.3 < j20 < 1.2, f"j@2.0V={j20:.3f} A/cm2 outside realistic alkaline range"


def test_oer_is_the_bottleneck():
    """At the operating point the anode (OER) carries the larger activation loss."""
    _, ov = _ahead_cell(2.0)
    assert ov["eta_act_anode"] > ov["eta_act_cathode"]


def test_full_cell_tafel_slope_sane():
    """Effective full-cell Tafel slope in the low-overpotential region ~120-300 mV/dec."""
    pts = [(_ahead_cell(V)[0]) for V in (1.55, 1.6, 1.65, 1.7)]
    Vs = [1.55, 1.6, 1.65, 1.7]
    xs = [math.log10(j * 1e4) for j in pts if j > 1e-4]
    if len(xs) >= 2:
        b = (Vs[len(Vs) - 1] - Vs[0]) / (xs[-1] - xs[0]) * 1000.0
        assert 100.0 < b < 320.0, f"effective Tafel slope {b:.0f} mV/dec"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1; print(f"  FAIL  {fn.__name__}  {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
