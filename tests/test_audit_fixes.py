"""Regression guards for the physics-audit completion pass.

The frozen characterization test pins only the lumped 0D path; these lock in the
specific physics the audit corrected/added so they cannot silently regress
(per the audit golden-test strategy, point D). Trend/range assertions, not exact
golden values, so a legitimate recalibration still passes.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params, Simulator, electrochem            # noqa: E402
from bubblesim.properties import (gas_diffusivity, liquid_viscosity,        # noqa: E402
                                  reversible_voltage, water_activity_koh,
                                  saturation_pressure, conductivity)
from bubblesim.kernel.morphology import effective_electrode, kappa_eff      # noqa: E402
from bubblesim.kernel import energy, chemistry                             # noqa: E402
from bubblesim.kernel.sources import faradaic_molar_rate                    # noqa: E402
from bubblesim.kernel.context import build_context                         # noqa: E402
from bubblesim.kernel.bubbles.population import Surface                     # noqa: E402
from bubblesim.kernel.bubbles import forces                                # noqa: E402


def test_gas_diffusivity_stokes_einstein():
    """D ~ T/mu(T): ~2x rise over 25->60 C (was ~1.12x linear-in-T)."""
    ratio = gas_diffusivity("HER", 333.15) / gas_diffusivity("HER", 298.15)
    assert 1.9 < ratio < 2.3, ratio


def test_bruggeman_no_double_count():
    """kappa_eff = kappa * eps^1.5 (not eps^1.5/tau)."""
    eff = effective_electrode("ni_foam", "planar_film")
    assert math.isclose(kappa_eff(60.0, eff), 60.0 * eff["eps_p"] ** 1.5, rel_tol=1e-12)


def test_lumped_has_conc_overpotential():
    """The lumped solver now reports a positive concentration overpotential."""
    op = Operating(V_cell=2.2)
    props = Simulator(op=op).props()
    ov = electrochem.overpotentials(op, props, 0.0, 0.0, 8000.0)
    assert "eta_conc" in ov and ov["eta_conc"] > 0.0


def test_conc_overpotential_lowers_current():
    """Removing the transport limit (huge j_lim) raises j: the penalty is real."""
    op = Operating(V_cell=2.0)
    props = Simulator(op=op).props()
    j = electrochem.solve_current_density(op, props, 0.0, 0.0)
    p2 = dict(props); p2["j_lim_eff"] = 1e12
    assert electrochem.solve_current_density(op, p2, 0.0, 0.0) > j


def test_coverage_saturates_below_union():
    """Poisson-union coverage stays below the overlap-double-counting linear sum."""
    s = Surface(Operating(), Params(), __import__("random").Random(0))
    from bubblesim.kernel.bubbles.bubble import Bubble
    for i in range(400):
        s.bubbles.append(Bubble(x=0.0, y=0.0, r=2.0e-4, attached=True, id=i))
    theta = s.coverage()
    linear = sum(math.pi * s.footprint_radius(b) ** 2 for b in s.bubbles) / s.A_patch
    assert theta <= 0.95 and theta < linear


def test_koh_viscosity_concentrated():
    """30 wt% (~6.9 M) KOH ~3 mPa.s at 25 C (was ~1.6 mPa.s)."""
    assert 2.5e-3 < liquid_viscosity(6.9, 298.15) < 3.6e-3


def test_water_activity_and_reversible_voltage():
    assert water_activity_koh(0.0) == 1.0
    assert 0.70 < water_activity_koh(6.0) < 0.82
    assert reversible_voltage(298.15, a_H2O=0.75) > reversible_voltage(298.15)


def test_high_fidelity_shifts_reversible_voltage():
    """high_fidelity activates the p_sat + water-activity Nernst corrections."""
    base = build_context(Operating(c_electrolyte=6.0), Params())["E_rev"]
    hf = build_context(Operating(c_electrolyte=6.0, high_fidelity=True), Params())["E_rev"]
    assert abs(hf - base) > 1e-4
    assert saturation_pressure(373.15) > 0.9e5     # ~1 atm at 100 C


def test_pkw_high_temperature():
    assert abs(chemistry.pKw(373.15) - 12.26) < 0.15


def test_acid_conductivity_no_collapse():
    """H2SO4 conductivity stays substantial at high c (old parabola hit the floor)."""
    assert conductivity("H2SO4", 8.0, 298.15) > 30.0


def test_efficiency_definitions():
    assert math.isclose(energy.voltage_efficiency_hhv(1.481), 1.0, rel_tol=1e-3)
    assert math.isclose(energy.voltage_efficiency_hhv(2.0), 1.481 / 2.0)
    assert energy.voltage_efficiency_lhv(2.0) < energy.voltage_efficiency_hhv(2.0)


def test_faradaic_efficiency_scales_gas():
    full = faradaic_molar_rate(1.0e4, "HER", 1.0e-4, 1.0)
    assert math.isclose(faradaic_molar_rate(1.0e4, "HER", 1.0e-4, 0.5), 0.5 * full)


def test_terminal_velocity_self_limits():
    """A 50 um bubble rises at mm/s-scale (Re-aware drag), far below the old 0.3 cap."""
    v = Surface._terminal_velocity(5.0e-5, 1000.0, 1.0e-3, 1000.0)
    assert 0.0 < v < 0.05


def test_dep_assists_detachment():
    """A near-surface field (E_ext>0) shrinks the departure radius (DEP, r^3 group)."""
    props = Simulator().props()
    r0 = forces.departure_radius(Operating(E_ext=0.0), props, 5000.0)
    rE = forces.departure_radius(Operating(E_ext=3.0e6), props, 5000.0)
    assert rE < r0


def test_oer_more_sluggish_than_her():
    """After the alkaline kinetic retune, the anode (OER) carries more activation
    overpotential than the cathode (HER) at the same cell current."""
    op = Operating(model="two_electrode", track_both=True, V_cell=2.0)
    sim = Simulator(op=op)
    from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver
    st = ZeroDTwoElectrodeSolver().solve(sim.op, sim.props(), sim.surfaces)
    assert st.overpotentials["eta_act_anode"] > st.overpotentials["eta_act_cathode"]


def test_supersaturation_growth_drains_pool():
    """Epstein-Plesset growth captures gas from the dissolved pool (mass debit)."""
    import random
    from bubblesim.kernel.bubbles.bubble import Bubble
    s = Surface(Operating(), Params(), random.Random(0))
    for i in range(5):
        s.bubbles.append(Bubble(x=0.0, y=0.0, r=1.0e-5, attached=True, id=i))
    s.c_dissolved = 10.0
    dn = s.grow_from_supersaturation(c_sat=1.0, D=2.0e-9, M=2.016e-3, rho_g=0.08, dt=1.0e-3)
    assert dn > 0.0 and s.bubbles[0].r > 1.0e-5


def test_supersaturation_high_threshold():
    """With B_nuc~12, nucleation stays off at modest supersaturation (S=2)."""
    import random
    s = Surface(Operating(), Params(), random.Random(0))
    n0 = len(s.bubbles)
    s.nucleate(j=1.0e4, dt=1.0, supersaturation=2.0)
    assert len(s.bubbles) == n0


def test_eis_cpe_depresses_arc():
    from bubblesim.kernel.impedance import electrode_branch
    w = 2.0 * math.pi * 10.0
    assert electrode_branch(w, 0.01, 0.2, n=1.0) != electrode_branch(w, 0.01, 0.2, n=0.8)


def test_flow2d_runs_and_flows():
    from bubblesim.solvers.flow2d import FlowChannel2D
    fc = FlowChannel2D(nx=48, ny=16, u_in=0.05)
    for _ in range(25):
        fc.step(2.0e-3, 5000.0, 1.5e-4, 60.0)
    snap = fc.snapshot()
    assert snap["vmax"] > 0.0


def test_porous_in_pore_concentration():
    op = Operating(model="porous", V_cell=2.0, substrate="ni_foam", nanostructure="nanoparticle")
    sim = Simulator(op=op)
    from bubblesim.solvers.porous import PorousSolver
    st = PorousSolver(n_outer=30).solve(op, sim.props(), sim.surfaces)
    cp = st.fields["c_pore_c"]
    assert len(cp) > 0 and all(0.0 < c <= 1.0 for c in cp)


def test_gas_cooling_positive():
    assert energy.gas_cooling_rate(1.0e4, 1.0e-4, 333.15, 1.0e5) > 0.0


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
