"""Energy balance: reaction + ohmic heat vs cooling, making the cell temperature
a dynamic state instead of a fixed input.

Total heat dissipated is I (V_cell - V_tn), where V_tn = dH / (zF) ~ 1.48 V is
the thermoneutral voltage: at V_cell = V_tn the cell is (adiabatically) heat
balanced; above it the surplus electrical power becomes heat. Because V_cell
already carries the ohmic (j^2 R) and activation losses, this single expression
captures all irreversible heating plus the reversible (entropic) term.

The lumped balance  C dT/dt = Q_gen - Q_cool  closes the loop: current heats the
cell, raising T, which lowers E_rev and raises conductivity (a positive feedback
bounded by cooling). Defaults are calibration knobs; a real cell's thermal mass
makes T evolve over minutes, far slower than the bubble dynamics.
"""
from ..constants import F
from ..properties import saturation_pressure

V_THERMONEUTRAL = 1.481   # thermoneutral cell voltage for water splitting [V]
DELTA_H_VAP = 42.0e3      # latent heat of water vaporization [J/mol] (~25-100 C avg)


def heat_flux(j, V_cell, V_tn=V_THERMONEUTRAL):
    """Areal heat generation rate [W/m^2] = j (V_cell - V_tn), clamped at 0
    (this lumped model does not draw heat in below the thermoneutral voltage)."""
    return max(0.0, j * (V_cell - V_tn))


def cooling_rate(T, T_amb, hA):
    """Newtonian heat removal [W] = hA (T - T_amb)  (hA = coeff * area [W/K])."""
    return hA * (T - T_amb)


def temperature_step(T, Q_gen, Q_cool, C, dt):
    """Explicit-Euler update of the lumped energy balance  C dT/dt = Q_gen - Q_cool."""
    return T + (Q_gen - Q_cool) / C * dt


def steady_temperature(Q_gen, T_amb, hA):
    """Steady-state temperature where Q_gen balances cooling: T = T_amb + Q_gen/hA."""
    return T_amb + Q_gen / hA if hA > 0 else float("inf")


def gas_cooling_rate(j, area, T, P, eta_F=1.0):
    """Heat carried off by the evolved gases [W] -- latent heat of the water vapor
    that saturates the H2/O2 leaving the cell (a first-order cooling channel in
    real electrolyzers; Ulleberg 2003).

        n_dot_H2 = eta_F j A / (2F);  dry co-gas = 1.5 mol per mol H2 (H2 + O2/2)
        n_dot_H2O(vapor) = 1.5 n_dot_H2 * p_sat(T) / (P - p_sat(T))
        Q_evap = n_dot_H2O * dH_vap
    """
    n_H2 = eta_F * max(0.0, j) * area / (2.0 * F)
    p_w = min(0.95 * P, saturation_pressure(T))
    n_H2O = 1.5 * n_H2 * p_w / max(1.0, P - p_w)
    return n_H2O * DELTA_H_VAP


V_THERMONEUTRAL_LHV = 1.253   # LHV-based thermoneutral voltage for water splitting [V]


def voltage_efficiency_hhv(V_cell, V_tn=V_THERMONEUTRAL):
    """Thermal (HHV) voltage efficiency = V_tn / V_cell -- the standard
    electrolyzer figure of merit (1.481 V / V_cell). (Carmo et al. 2013.)"""
    return V_tn / V_cell if V_cell > 0.0 else 0.0


def voltage_efficiency_lhv(V_cell, V_lhv=V_THERMONEUTRAL_LHV):
    """LHV voltage efficiency = 1.253 V / V_cell."""
    return V_lhv / V_cell if V_cell > 0.0 else 0.0


def energy_efficiency(V_cell, eta_faraday=1.0, V_tn=V_THERMONEUTRAL):
    """Overall (HHV) energy efficiency = Faradaic efficiency * voltage efficiency."""
    return eta_faraday * voltage_efficiency_hhv(V_cell, V_tn)
