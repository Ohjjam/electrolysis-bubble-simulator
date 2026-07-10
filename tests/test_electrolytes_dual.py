"""Physics tests for electrolyte media (KOH / H2SO4 / phosphate buffer) and the
dual-electrode bubble mode (track_both).

Run with:  python -m pytest tests/ -q   (or: python tests/test_electrolytes_dual.py)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params, Simulator                 # noqa: E402
from bubblesim import properties as prop                            # noqa: E402
from bubblesim.kernel import chemistry as chem                      # noqa: E402
from bubblesim.kernel.context import build_context                  # noqa: E402
from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver         # noqa: E402


# ----------------------------------------------------------------- media props
def test_koh_path_unchanged():
    """electrolyte="KOH" must reproduce the original correlations exactly."""
    assert prop.conductivity("KOH", 6.0, 333.15) == prop.conductivity_KOH(6.0, 333.15)
    assert prop.liquid_density_med("KOH", 6.0) == prop.liquid_density(6.0)
    assert prop.surface_tension_med("KOH", 333.15, 6.0) == prop.surface_tension(333.15, 6.0)
    d = build_context(Operating(), Params())
    assert d["electrolyte"] == "KOH"


def test_conductivity_peaks_per_medium():
    """KOH peaks near 6 M; H2SO4 near ~4 M and is the most conductive; PB is
    an order of magnitude below both."""
    k_koh = [prop.conductivity("KOH", c, 298.15) for c in (2, 6, 9)]
    assert k_koh[1] == max(k_koh)
    k_acid = [prop.conductivity("H2SO4", c, 298.15) for c in (1, 4, 7)]
    assert k_acid[1] == max(k_acid)
    assert max(k_acid) > max(k_koh)
    assert prop.conductivity("PB", 1.0, 298.15) < 0.2 * prop.conductivity("KOH", 6.0, 298.15)


def test_bulk_ph_per_medium():
    """0.5 M H2SO4 is strongly acidic; PB sits near neutral; KOH strongly basic."""
    assert chem.bulk_pH(0.5, 298.15, "H2SO4") < 1.0
    assert 6.5 < chem.bulk_pH(1.0, 298.15, "PB") < 7.5
    assert chem.bulk_pH(6.0, 298.15, "KOH") > 13.0


def test_hplus_h2so4_between_first_and_second_dissociation():
    """c <= [H+] <= 2c (first proton full, second partial)."""
    c = 0.5
    h = chem.hplus_H2SO4(c)
    assert c < h < 2.0 * c


def test_local_ph_direction_universal():
    """In every medium the cathode surface is more alkaline than the anode."""
    for med, c in (("KOH", 6.0), ("H2SO4", 0.5), ("PB", 1.0)):
        pH_c = chem.local_pH(c, 2.0e4, 4.0e4, "HER", 333.15, med)
        pH_a = chem.local_pH(c, 2.0e4, 4.0e4, "OER", 333.15, med)
        assert pH_c > pH_a, med


def test_buffer_damps_ph_shift():
    """The phosphate buffer's local-pH excursion is far smaller than the
    unbuffered surrogate would be, and shrinks with buffer concentration."""
    lo = chem.local_pH(0.1, 2.0e4, 4.0e4, "HER", 298.15, "PB") - 7.2
    hi = chem.local_pH(1.0, 2.0e4, 4.0e4, "HER", 298.15, "PB") - 7.2
    assert 0.0 < hi < lo < 1.0


def test_ionic_strength_factors():
    assert chem.ionic_strength(1.0, "KOH") == 1.0
    assert chem.ionic_strength(1.0, "H2SO4") == 3.0
    assert chem.ionic_strength(1.0, "PB") == 2.0


def test_acid_cell_still_polarizes():
    """The two-electrode solve works in H2SO4 (kappa, pH, activity all swap in)."""
    class Flat:
        def coverage(self): return 0.0
        def void_fraction(self): return 0.0
    op = Operating(V_cell=2.0, model="two_electrode", electrolyte="H2SO4",
                   c_electrolyte=0.5)
    st = ZeroDTwoElectrodeSolver().solve(op, build_context(op, Params()), [Flat()])
    assert st.j > 0.0
    assert st.fields["pH_bulk"] < 1.0


# ----------------------------------------------------------------- dual mode
def test_dual_mode_runs_and_both_electrodes_bubble():
    """track_both evolves bubbles on both electrodes from the same cell current."""
    op = Operating(V_cell=2.2, model="two_electrode", track_both=True)
    sim = Simulator(op, seed=0)
    assert len(sim.surfaces) == 2
    sim.run(t_end=0.3, dt=5e-4)
    n_c = len(sim.surfaces[0].bubbles)
    n_a = len(sim.surfaces[1].bubbles)
    assert n_c > 0 and n_a > 0


def test_dual_mode_h2_gets_twice_the_gas():
    """Same charge -> H2 volume is 2x O2 volume (z = 2 vs 4), so the cathode
    accumulates more attached-gas volume than the anode."""
    op = Operating(V_cell=2.2, model="two_electrode", track_both=True)
    sim = Simulator(op, seed=0)
    sim.run(t_end=0.25, dt=5e-4)
    vol_c = sum(b.volume() for b in sim.surfaces[0].bubbles)
    vol_a = sum(b.volume() for b in sim.surfaces[1].bubbles)
    assert vol_c > 1.3 * vol_a       # ~2x in expectation, loose for detachment noise


def test_dual_voltage_balance_closes():
    """ov reconstructs V_cell in dual mode too (series Bruggeman path)."""
    class Half:
        def __init__(self, th, ep): self.th, self.ep = th, ep
        def coverage(self): return self.th
        def void_fraction(self): return self.ep
    op = Operating(V_cell=2.1, model="two_electrode", track_both=True)
    st = ZeroDTwoElectrodeSolver().solve(op, build_context(op, Params()),
                                         [Half(0.2, 0.15), Half(0.1, 0.05)])
    ov = st.overpotentials
    recon = ov["E_rev"] + ov["eta_act"] + ov["eta_conc"] + ov["eta_ohmic"]
    assert math.isclose(recon, op.V_cell, rel_tol=1e-6, abs_tol=1e-6)
    # bubble diagnostics present and positive where coverage/void exist
    assert ov["eta_bub_cov_cathode"] > ov["eta_bub_cov_anode"] > 0.0
    assert ov["eta_bub_void"] > 0.0


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
