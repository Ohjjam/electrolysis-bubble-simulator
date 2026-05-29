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

from .constants import F, R_GAS
from . import properties as prop, electrochem
from .surface import Surface
from .config import Operating, Params

_TRACE_KEYS = ["t", "j", "I", "theta", "eps", "r_d", "n_bub",
               "eta_act", "eta_ohmic", "V"]


class Simulator:
    def __init__(self, op: Operating = None, params: Params = None, seed: int = 0):
        self.op = op or Operating()
        self.p = params or Params()
        self.rng = random.Random(seed)
        self.surface = Surface(self.op, self.p, self.rng)
        self.t = 0.0
        self.history = {k: [] for k in _TRACE_KEYS}

    def props(self) -> dict:
        """Assemble the property bundle used by the physics for the current state."""
        op = self.op
        d = {
            "E_rev": prop.reversible_voltage(op.T),
            "kappa": prop.conductivity_KOH(op.c_electrolyte, op.T),
            "sigma": prop.surface_tension(op.T, op.c_electrolyte),
            "rho_l": prop.liquid_density(op.c_electrolyte),
            "rho_g": prop.gas_density(op.electrode, op.T, op.P),
            "mu": prop.liquid_viscosity(op.c_electrolyte, op.T),
            "fritz_scale": self.p.fritz_scale,
            "j0": self.p.j0,
            "tafel_b": self.p.tafel_b,
            "j_lim_eff": self.p.j_lim * (1.0 + self.p.flow_jlim * op.u_flow),
            "Cd_flow": self.p.Cd_flow,
            "k_mhd": self.p.k_mhd,
            "r_min_detach": self.p.r_min_detach,
        }
        d["d_rho"] = d["rho_l"] - d["rho_g"]
        return d

    def step(self, dt: float) -> float:
        op = self.op
        P = self.props()

        theta = self.surface.coverage()
        eps = self.surface.void_fraction()
        j = electrochem.solve_current_density(op, P, theta, eps)

        # evolved-gas volume rate on the patch (Faraday + ideal gas)
        z = prop.GAS[op.electrode]["z"]
        I_patch = j * self.surface.A_patch
        n_dot = I_patch / (z * F)                 # mol/s
        Q = n_dot * R_GAS * op.T / op.P           # m^3/s of gas at cell conditions

        self.surface.grow(self.p.f_to_bubble * Q, dt)
        self.surface.nucleate(j, dt)
        self.surface.coalesce()
        r_d = self.surface.detach(P, j)
        self.surface.advect(dt, P)

        self.t += dt
        ov = electrochem.overpotentials(op, P, theta, eps, j)
        h = self.history
        h["t"].append(self.t)
        h["j"].append(j / 1e4)                    # A/cm^2
        h["I"].append(j * (op.A_cm2 * 1e-4))      # total electrode current [A]
        h["theta"].append(theta)
        h["eps"].append(eps)
        h["r_d"].append(r_d)
        h["n_bub"].append(len(self.surface.bubbles))
        h["eta_act"].append(ov["eta_act"])
        h["eta_ohmic"].append(ov["eta_ohmic"])
        h["V"].append(op.V_cell)
        return j

    def run(self, t_end: float, dt: float) -> dict:
        for _ in range(int(round(t_end / dt))):
            self.step(dt)
        return self.history
