"""Text demo of the v2 multiphysics — no matplotlib required.

    python demo_multiphysics.py

Showcases the two-electrode Butler-Volmer fidelity: overpotential decomposition,
the electrode-surface local pH split, membrane/contact resistance, the thermal
feedback (T as a state), and a lumped-vs-two_electrode polarization comparison.
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")   # robust on Windows consoles
except Exception:
    pass

from bubblesim import Operating, Params, Simulator
from bubblesim.kernel.context import build_context
from bubblesim.solvers.zerod import ZeroDSolver, ZeroDTwoElectrodeSolver


class Flat:
    """Bubble-free electrode, for clean polarization curves."""
    def coverage(self):
        return 0.0

    def void_fraction(self):
        return 0.0


def solve2e(op, params=None):
    params = params or Params()
    return ZeroDTwoElectrodeSolver().solve(op, build_context(op, params), [Flat()])


def hr(title):
    print("\n" + "=" * 72 + f"\n{title}\n" + "=" * 72)


hr("Two-electrode Butler-Volmer overpotential split (bubble-free, 6 M KOH, 60 C)")
print(f"{'V_cell':>7} {'j[A/cm2]':>9} {'eta_OER':>8} {'eta_HER':>8} {'eta_conc':>9} {'eta_ohm':>8}")
for V in (1.6, 1.8, 2.0, 2.2, 2.4):
    ov = solve2e(Operating(V_cell=V, model="two_electrode")).overpotentials
    j = solve2e(Operating(V_cell=V, model="two_electrode")).j
    print(f"{V:>7.2f} {j/1e4:>9.4f} {ov['eta_act_anode']:>8.4f} "
          f"{ov['eta_act_cathode']:>8.4f} {ov['eta_conc']:>9.4f} {ov['eta_ohmic']:>8.4f}")
print("  note: eta_OER(anode) > eta_HER(cathode) -> sluggish OER is rate-limiting "
      "(j0_OER << j0_HER)")

hr("Electrode-surface local pH (OH- produced at cathode, consumed at anode)")
print(f"{'V_cell':>7} {'pH_bulk':>8} {'pH_cathode':>11} {'pH_anode':>9}")
for V in (1.8, 2.0, 2.2):
    f = solve2e(Operating(V_cell=V, model="two_electrode")).fields
    print(f"{V:>7.2f} {f['pH_bulk']:>8.3f} {f['pH_cathode']:>11.3f} {f['pH_anode']:>9.3f}")

hr("Membrane / contact resistance (V = 2.2)")
op = Operating(V_cell=2.2, model="two_electrode")
for Rm in (0.0, 1e-4, 3e-4):
    st = solve2e(op, Params(r_membrane_area=Rm))
    print(f"  R_mem={Rm:.0e} ohm*m2  ->  j={st.j/1e4:.4f} A/cm2, "
          f"eta_ohmic={st.overpotentials['eta_ohmic']:.4f} V")

hr("Energy balance: current heats the cell (thermal=True, weak cooling)")
op = Operating(V_cell=2.2, T=313.15, model="two_electrode", thermal=True)
p = Params(T_ambient=313.15, thermal_mass=0.05, hA_cool=0.02)
h = Simulator(op, p, seed=0).run(t_end=1.0, dt=5e-4)
print(f"  T: {h['T'][0]-273.15:.2f} C  ->  {h['T'][-1]-273.15:.2f} C   "
      f"(current -> heat -> T up -> kappa up: positive feedback, cooling-bounded)")

hr("Cross-tab: lumped vs two_electrode polarization (the architecture enables this)")
print(f"{'V':>5} {'j_lumped':>10} {'j_2elec':>9}")
for V in (1.7, 1.9, 2.1, 2.3):
    op = Operating(V_cell=V)
    ctx = build_context(op, Params())
    jl = ZeroDSolver().solve(op, ctx, [Flat()]).j
    j2 = ZeroDTwoElectrodeSolver().solve(op, ctx, [Flat()]).j
    print(f"{V:>5.1f} {jl/1e4:>10.4f} {j2/1e4:>9.4f}")
