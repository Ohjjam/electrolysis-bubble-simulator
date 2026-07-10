"""The coupled simulator: ties the electrochemistry to the bubble population.

Per time step:
  1. read bubble state -> coverage theta, void fraction eps
  2. solve current density j at the fixed cell voltage (theta, eps couple in)
  3. convert current to an evolved-gas volume rate (Faraday)
  4. grow / nucleate / coalesce / detach / advect the bubbles
  5. record the trace

The feedback in steps 1->2->3->4 and back is exactly the "surface changes ->
current changes -> a bubble leaves -> current jumps" loop: it produces the
sawtooth current trace characteristic of gas-evolving electrodes.
"""
import random
from dataclasses import replace

from .surface import Surface
from .config import Operating, Params
from .properties import GAS, gas_density
from .kernel.context import build_context
from .kernel.sources import faradaic_gas_rate, faradaic_molar_rate
from .kernel import energy
from .solvers import get_solver

_TRACE_KEYS = ["t", "j", "I", "theta", "theta_a", "eps", "r_d", "n_bub",
               "eta_act", "eta_ohmic", "V", "T"]


class Simulator:
    def __init__(self, op: Operating = None, params: Params = None, seed: int = 0,
                 solver=None):
        self.op = replace(op) if op is not None else Operating()   # own copy (T may evolve)
        self.p = params or Params()
        self.rng = random.Random(seed)
        self.surface = Surface(self.op, self.p, self.rng)
        self.surfaces = [self.surface]        # [0] = primary (single) / cathode-HER (dual)
        if self.op.track_both:
            self.surfaces.append(Surface(self.op, self.p, self.rng))   # [1] = anode-OER
        self.solver = solver or get_solver(self.op.model)
        self.t = 0.0
        self.last_state = None                # most recent ElectroState (rich UI readouts)
        self.history = {k: [] for k in _TRACE_KEYS}

    def props(self) -> dict:
        """Property bundle for the current state (delegates to the kernel)."""
        return build_context(self.op, self.p)

    def _grow_nucleate(self, surf, electrode, j, ctx, dt):
        """Grow attached bubbles and seed new ones on `surf`.

        Empirical mode (default): the original Faradaic-split growth + rate~j
        nucleation (byte-identical). Supersaturation mode: ALL evolved gas enters
        the dissolved pool, attached bubbles grow diffusion-limited from that pool
        (Epstein-Plesset) and DEBIT it, and nucleation fires on the resulting
        supersaturation -- one conserved gas balance, no double-counting."""
        if getattr(self.op, "nucleation", "empirical") != "supersaturation":
            Q = faradaic_gas_rate(j, electrode, self.op.T, self.op.P,
                                  surf.A_patch, self.p.eta_faraday)
            surf.grow(self.p.f_to_bubble * Q, dt)
            surf.nucleate(j, dt, supersaturation=None)
            return
        c_sat = ctx["c_sat_gas"]
        D = ctx["D_carrier"]
        k_m = D / max(ctx["delta_bl"], 1e-12)
        M, rho_g = GAS[electrode]["M"], gas_density(electrode, self.op.T, self.op.P)
        uptake = surf.grow_from_supersaturation(c_sat, D, M, rho_g, dt)      # drains the pool
        gas_in = faradaic_molar_rate(j, electrode, surf.A_patch, self.p.eta_faraday)
        S = surf.update_supersaturation(gas_in, c_sat, k_m, dt, uptake_mol=uptake)
        surf.nucleate(j, dt, supersaturation=S)

    def step(self, dt: float) -> float:
        op = self.op
        P = self.props()

        # electrochemical solve (fidelity-specific); bubbles couple in via surfaces
        state = self.solver.solve(op, P, self.surfaces)
        self.last_state = state
        j = state.j
        ov = state.overpotentials
        V_now = state.V if state.V is not None else op.V_cell   # CP: V is the response

        # coverage / void for the trace (pre-mutation; the solver read the same state)
        theta = self.surface.coverage()
        theta_a = self.surfaces[1].coverage() if len(self.surfaces) > 1 else 0.0
        eps = self.surface.void_fraction()

        if len(self.surfaces) > 1:
            # dual mode: each electrode evolves its own gas at the same cell j.
            # HER gets 2x the volume of OER per unit charge (z = 2 vs 4); the gas
            # density (H2 vs O2) enters each electrode's own property context.
            r_d = 0.0
            for surf, electrode in ((self.surfaces[0], "HER"), (self.surfaces[1], "OER")):
                P_e = build_context(replace(op, electrode=electrode), self.p)
                self._grow_nucleate(surf, electrode, j, P_e, dt)
                surf.coalesce()
                r_de = surf.detach(P_e, j)
                surf.advect(dt, P_e)
                if electrode == "HER":
                    r_d = r_de
        else:
            self._grow_nucleate(self.surface, op.electrode, j, P, dt)
            self.surface.coalesce()
            r_d = self.surface.detach(P, j)
            self.surface.advect(dt, P)

        self.t += dt
        if op.thermal:
            # lumped energy balance: current heats the cell, cooling removes it;
            # the new T feeds next step's properties (E_rev, kappa, ...) -> feedback
            A = op.A_cm2 * 1e-4
            Q_gen = energy.heat_flux(j, V_now) * A
            # cooling = forced convection/conduction + latent heat carried off by the
            # water-vapor-saturated product gases (a real first-order channel)
            Q_cool = (energy.cooling_rate(op.T, self.p.T_ambient, self.p.hA_cool)
                      + energy.gas_cooling_rate(j, A, op.T, op.P, self.p.eta_faraday))
            op.T = energy.temperature_step(op.T, Q_gen, Q_cool, self.p.thermal_mass, dt)
        h = self.history
        h["t"].append(self.t)
        h["j"].append(j / 1e4)                    # A/cm^2
        h["I"].append(j * (op.A_cm2 * 1e-4))      # total electrode current [A]
        h["theta"].append(theta)
        h["theta_a"].append(theta_a)
        h["eps"].append(eps)
        h["r_d"].append(r_d)
        h["n_bub"].append(sum(len(s.bubbles) for s in self.surfaces))
        h["eta_act"].append(ov["eta_act"])
        h["eta_ohmic"].append(ov["eta_ohmic"])
        h["V"].append(V_now)
        h["T"].append(op.T)
        return j

    def run(self, t_end: float, dt: float) -> dict:
        for _ in range(int(round(t_end / dt))):
            self.step(dt)
        return self.history
