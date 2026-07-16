"""Physics tests for the energy balance (Phase 4).

Thermoneutral voltage, heat-generation / cooling terms, the lumped temperature
update and its steady state, and the opt-in coupling in the Simulator (current
heats the cell when thermal=True; T is fixed when thermal=False).

Run with:  python -m pytest tests/ -q   (or: python tests/test_energy.py)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params, Simulator                 # noqa: E402
from bubblesim.kernel import energy                                # noqa: E402


def test_thermoneutral_voltage():
    assert math.isclose(energy.V_THERMONEUTRAL, 1.48, abs_tol=0.01)


def test_heat_flux_above_and_below_thermoneutral():
    """Heat = j (V - V_tn): generation above, absorption below."""
    assert math.isclose(energy.heat_flux(1.0e4, 2.0),
                        1.0e4 * (2.0 - energy.V_THERMONEUTRAL))
    assert math.isclose(energy.heat_flux(1.0e4, 1.40),
                        1.0e4 * (1.40 - energy.V_THERMONEUTRAL))


def test_cooling_rate():
    assert math.isclose(energy.cooling_rate(330.0, 300.0, 0.5), 0.5 * 30.0)


def test_temperature_step_rises_when_generation_exceeds_cooling():
    assert energy.temperature_step(300.0, Q_gen=2.0, Q_cool=1.0, C=1.0, dt=0.1) > 300.0
    assert energy.temperature_step(300.0, Q_gen=1.0, Q_cool=2.0, C=1.0, dt=0.1) < 300.0


def test_steady_temperature():
    """Q_gen = hA (T - T_amb)  =>  T = T_amb + Q_gen/hA."""
    assert math.isclose(energy.steady_temperature(1.0, 300.0, 0.5), 300.0 + 2.0)


def test_simulator_heats_cell_under_current():
    """With thermal on and the coolant at the start temperature, the cell heats."""
    op = Operating(V_cell=2.0, T=333.15, thermal=True)
    p = Params(T_ambient=333.15, thermal_mass=0.5, hA_cool=0.05)
    h = Simulator(op, p, seed=0).run(t_end=0.3, dt=2e-4)
    assert h["T"][-1] > h["T"][0]


def test_simulator_isothermal_when_thermal_off():
    """Default (thermal off): temperature stays exactly at its initial value."""
    op = Operating(V_cell=2.0, T=333.15)        # thermal=False by default
    h = Simulator(op, seed=0).run(t_end=0.2, dt=3e-4)
    assert h["T"][0] == 333.15
    assert h["T"][-1] == 333.15


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
