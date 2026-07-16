"""Source terms: converting current into evolved-gas (and later, heat).

Shared by every fidelity — the Faraday + ideal-gas conversion of current to a
gas volume rate is the same whether the current came from a 0D or a 2D solver.
"""
from ..constants import F, R_GAS
from ..properties import GAS, saturation_pressure


def faradaic_gas_rate(j, electrode, T, P, area, eta_F=1.0, *, wet=False,
                      water_activity=1.0):
    """Evolved-gas volume rate [m^3/s] at cell conditions.

        I = j * area ;  n_dot = eta_F * I / (z F)
        Q_dry = n_dot * R T / P
        Q_wet = n_dot * R T / (P - a_w p_sat)  when wet=True

    `z` electrons per gas molecule (HER: H2, z=2; OER: O2, z=4) so HER evolves
    twice the gas volume of OER per unit charge. `eta_F` is the Faradaic (current)
    efficiency (<1 from side reactions / crossover); default 1.0 = ideal.
    """
    z = GAS[electrode]["z"]
    I = j * area
    n_dot = eta_F * I / (z * F)    # mol/s
    p_gas = P
    if wet:
        p_w = max(0.0, float(water_activity)) * saturation_pressure(T)
        p_gas = max(0.05 * P, P - min(0.95 * P, p_w))
    return n_dot * R_GAS * T / p_gas   # m^3/s at cell T and wet/dry pressure


def faradaic_molar_rate(j, electrode, area, eta_F=1.0):
    """Evolved-gas molar rate [mol/s] = eta_F * j * area / (z F).

    The dissolved-gas / supersaturation model needs moles, not volume; this is
    the same Faraday law without the ideal-gas volume conversion.
    """
    z = GAS[electrode]["z"]
    return eta_F * j * area / (z * F)


def crossover_molar_flux(area, permeability, thickness, p_partial, dp_perm=0.0):
    """Gas crossover molar flux through the separator/membrane [mol/s] (estimator).

        N = (permeability * p_partial / thickness + convective(dp_perm)) * area

    `permeability` [mol/(m s Pa)] (Schalenbach et al. 2016), `p_partial` the
    producing-side dissolved-gas partial pressure [Pa]. The H2-in-O2 crossover it
    estimates is the LFL (~4 vol%) safety metric that limits low-load operation.

    NOTE: a full crossover balance needs cell-level two-electrode + separator
    geometry the single-patch kernel lacks, so this is a standalone estimator,
    NOT yet wired into the core gas balance (add when the cell model gains a
    separator with two distinct gas compartments).
    """
    diff = permeability * max(0.0, p_partial) / max(1e-9, thickness)
    return max(0.0, (diff + max(0.0, dp_perm)) * area)
