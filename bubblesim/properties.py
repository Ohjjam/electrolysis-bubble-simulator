"""Physical-property correlations for the electrolyte and evolved gas.

These are deliberately simple, literature-informed correlations meant to give
*physically reasonable trends* and order-of-magnitude values for alkaline
(KOH) water electrolysis. They are the first thing to recalibrate against a
specific paper or dataset. Every correlation is flagged with its assumption.

Internally everything is SI. Concentration `c` is in mol/L (KOH).
"""
import math

from .constants import F, R_GAS

EPS_WATER = 78.0  # relative permittivity of the aqueous electrolyte [-]

# electrons transferred and molar mass per evolved-gas molecule
GAS = {
    "HER": {"gas": "H2", "z": 2, "M": 2.016e-3},    # cathode: 2 H2O + 2e- -> H2 + 2 OH-
    "OER": {"gas": "O2", "z": 4, "M": 31.998e-3},   # anode: 4 OH- -> O2 + 2 H2O + 4e-
}


def saturation_pressure(T):
    """Saturation vapor pressure of water [Pa] (Antoine eq., ~1-100 degC).

        log10(p[mmHg]) = 8.07131 - 1730.63 / (233.426 + T_C)
    ~19.9 kPa at 60 degC, ~101.3 kPa at 100 degC. The evolved gas leaves the cell
    water-vapor saturated, so its dry partial pressure is (P - p_sat).
    """
    T_C = T - 273.15
    return 10.0 ** (8.07131 - 1730.63 / (233.426 + T_C)) * 133.322   # mmHg -> Pa


def dry_gas_pressure(P, p_w=0.0):
    """Dry product-gas partial pressure [Pa] used by every wet-gas path.

    The one-pascal floor is numerical only.  Callers must inspect
    ``P > p_w`` (exposed as ``thermodynamic_state_valid`` in the context)
    before interpreting a result physically.
    """
    return max(1.0, float(P) - max(0.0, float(p_w)))


def water_activity_koh(c):
    """Water activity a_w in aqueous KOH (Balej 1985-anchored linear fit).

    1.0 at 0 M, 0.80 at 5 M, 0.72 at 7 M (a_w = 1 - 0.04 c over the electrolyzer
    range). Concentrated alkali lowers a_w below 1, raising the reversible voltage
    by (RT/2F) ln(1/a_w)."""
    return max(0.2, 1.0 - 0.040 * c)


def reversible_voltage(T, P=1.0e5, P_ref=1.0e5, a_H2O=1.0, p_w=0.0):
    """Reversible (thermodynamic) cell voltage for water splitting [V].

    1.229 V at 298.15 K with a -0.9 mV/K temperature coefficient (entropy term),
    plus the full Nernst term for the products 1 H2 + 1/2 O2 per 2 e- and the
    water reactant:

        E_rev = E_rev(T) + (RT/2F) ln[(P_dry/P_ref)^1.5 / a_H2O]

    `p_w` is the water-vapor partial pressure the wet evolved gas displaces, so
    the dry product pressure is P_dry = P - p_w (significant hot/near-boiling).
    `a_H2O` < 1 in concentrated electrolyte raises E_rev. Both default to the
    ideal (p_w=0, a_H2O=1), so the 1 bar / pure-water reference is bit-identical
    (golden-safe); build_context enables them only under high_fidelity.
    """
    E = 1.229 - 0.9e-3 * (T - 298.15)
    P_dry = dry_gas_pressure(P, p_w)
    return (E + (R_GAS * T) / (2.0 * F) * 1.5 * math.log(P_dry / P_ref)
            - (R_GAS * T) / (2.0 * F) * math.log(a_H2O))


def j0_arrhenius(j0_ref, Ea, T, c, gamma=0.0, T_ref=298.15, c_ref=6.0,
                 activity=1.0, activity_ref=1.0):
    """Exchange current density [A/m^2] with Arrhenius T-dependence and a
    power-law dependence on the reactant *activity* a = gamma_pm * c:

        j0 = j0_ref * ( (activity * c) / (activity_ref * c_ref) )^gamma
                    * exp[ -(Ea / R) (1/T - 1/T_ref) ]

    Using activity (not raw concentration) for the order makes the kinetics
    consistent with the non-ideal electrolyte. Defaults activity=activity_ref=1
    reproduce the ideal (c/c_ref) form exactly, and at c=c_ref with equal
    activities the ratio is 1 (reduces to j0_ref).
    """
    ratio = (activity * c) / (activity_ref * c_ref)
    return j0_ref * ratio ** gamma * math.exp(-(Ea / R_GAS) * (1.0 / T - 1.0 / T_ref))


# --------------------------------------------------------------- electrolytes
# Per-medium coefficients (order-of-magnitude, flagged rough — recalibrate for
# quantitative work). `i_factor`: ionic strength I = i_factor * c.
# `c_coalesce`: transition concentration above which bubble coalescence is
# inhibited (salt-specific, Craig-type). Buffer: pKa2(H2PO4-/HPO4 2-) = 7.2,
# `beta` = lumped buffer-damping strength per mol/L.
ELECTROLYTES = {
    # t_carrier: transference number of the reacting carrier ion (OH- / H+ /
    # phosphate) — migration carries that fraction of its flux, relieving
    # diffusion: j_lim is boosted by 1/(1 - t_carrier).
    "KOH":   {"type": "alkaline", "i_factor": 1.0, "c_coalesce": 0.3,
              "rho_slope": 48.0, "sigma_slope": 0.0013, "mu_slope": 0.10,
              "t_carrier": 0.78},
    "H2SO4": {"type": "acid",     "i_factor": 3.0, "c_coalesce": 0.07,
              "rho_slope": 62.0, "sigma_slope": 0.0007, "mu_slope": 0.12,
              "t_carrier": 0.81},
    "PB":    {"type": "buffer",   "i_factor": 2.0, "c_coalesce": 0.15,
              "rho_slope": 90.0, "sigma_slope": 0.0010, "mu_slope": 0.20,
              "pH": 7.2, "beta": 12.0, "t_carrier": 0.30},
}


def conductivity_KOH(c, T):
    """Ionic conductivity of aqueous KOH [S/m].

    Rough parabolic fit peaking near ~6 mol/L (kappa_25 ~ 60 S/m at 6 M),
    with a ~2 %/K temperature rise. Replace with Gilliam et al. (2007) for
    quantitative work.
    """
    kappa_25 = max(1.0, 20.0 * c - 1.667 * c * c)
    return kappa_25 * (1.0 + 0.02 * (T - 298.15))


def conductivity_koh_gilliam(c, T):
    """Specific conductivity of aqueous KOH [S/m] -- Gilliam et al. (2007)
    correlation (Int. J. Hydrogen Energy), valid ~0-12 mol/L and 0-100 C, far
    more accurate at electrolyzer concentration/temperature than the parabolic fit:

        kappa[S/cm] = -2.041 m - 0.0028 m^2 + 0.005332 m T + 207.2 m/T
                      + 0.001043 m^3 - 3.0e-7 m^2 T^2        (m = mol/L, T = K)
    """
    m = max(0.0, c)
    k = (-2.041 * m - 0.0028 * m * m + 0.005332 * m * T + 207.2 * m / T
         + 0.001043 * m * m * m - 3.0e-7 * m * m * T * T)
    return max(0.1, k) * 100.0                                # S/cm -> S/m


def conductivity(electrolyte, c, T, high_fidelity=False):
    """Ionic conductivity [S/m] for the selected electrolyte.

    KOH delegates to the original parabolic correlation (bit-identical) by
    default; `high_fidelity=True` switches KOH to the Gilliam (2007) correlation.
    H2SO4 peaks near ~3.9 M (~83 S/m); phosphate buffer is an order of magnitude
    lower. The acid/buffer fits stay parabolic.
    """
    if electrolyte == "H2SO4":
        # Casteel-Amis-type rational fit: peaks ~83 S/m near ~3.9 M, then tails
        # gently (~70 S/m at 7 M) instead of the old parabola collapsing to the
        # 1 S/m floor above ~7 M (CRC conductivity tables; Darling 1964).
        kappa_25 = 42.6 * c / (1.0 + 0.0657 * c * c)
        return kappa_25 * (1.0 + 0.012 * (T - 298.15))
    if electrolyte == "PB":
        kappa_25 = 6.5 * c / (1.0 + 0.16 * c * c)            # peak ~8 S/m near 2.5 M, no collapse
        return max(0.2, kappa_25) * (1.0 + 0.02 * (T - 298.15))
    return conductivity_koh_gilliam(c, T) if high_fidelity else conductivity_KOH(c, T)


def surface_tension(T, c):
    """Electrolyte/gas surface tension [N/m].

    Water (~0.0728 N/m at 25 degC) decreasing ~0.15 mN/m per K, increasing
    mildly with KOH concentration (electrolytes raise surface tension).
    """
    return 0.0728 - 1.5e-4 * (T - 298.15) + 0.0013 * c


def liquid_density(c):
    """Electrolyte density [kg/m^3]; KOH adds ~+48 kg/m^3 per mol/L (rough)."""
    return 1000.0 + 48.0 * c


def liquid_viscosity(c, T):
    """Dynamic viscosity [Pa*s]: water Arrhenius T-dependence + super-linear KOH
    thickening. Base water 0.89 mPa.s at 25 degC; 30 wt% (~6.9 M) KOH reaches
    ~3 mPa.s (~3.4x water). The old linear (1+0.10c) under-predicted ~2x at 6-7 M."""
    mu_w = 0.89e-3 * math.exp(1800.0 * (1.0 / T - 1.0 / 298.15))
    return mu_w * (1.0 + 0.10 * c + 0.035 * c * c)


def surface_tension_med(electrolyte, T, c):
    """Surface tension [N/m] with a per-electrolyte concentration slope.
    KOH path is bit-identical to `surface_tension`."""
    if electrolyte == "KOH":
        return surface_tension(T, c)
    s = ELECTROLYTES[electrolyte]["sigma_slope"]
    return 0.0728 - 1.5e-4 * (T - 298.15) + s * c


def liquid_density_med(electrolyte, c):
    """Electrolyte density [kg/m^3] with a per-medium slope (KOH bit-identical)."""
    if electrolyte == "KOH":
        return liquid_density(c)
    return 1000.0 + ELECTROLYTES[electrolyte]["rho_slope"] * c


def liquid_viscosity_med(electrolyte, c, T):
    """Dynamic viscosity [Pa*s] with a per-medium thickening slope (KOH bit-identical)."""
    if electrolyte == "KOH":
        return liquid_viscosity(c, T)
    mu_w = 1.0e-3 * math.exp(1800.0 * (1.0 / T - 1.0 / 298.15))
    return mu_w * (1.0 + ELECTROLYTES[electrolyte]["mu_slope"] * c)


def gas_density(electrode, T, P):
    """Ideal-gas density of the evolved gas [kg/m^3]."""
    M = GAS[electrode]["M"]
    return P * M / (R_GAS * T)


def gas_diffusivity(electrode, T, c=0.0, electrolyte="KOH"):
    """Dissolved-gas diffusivity [m^2/s] via Stokes-Einstein  D ~ T / mu(T).

        D = base * (T/298.15) * mu(c,298.15)/mu(c,T)

    Because water viscosity falls ~2x from 25->60 degC, D roughly DOUBLES over
    that range; the old linear-in-T form captured only ~12% of that real rise.
    Concentration lowers D through the per-electrolyte viscosity mu(c). base =
    5.0e-9 (H2) / 2.4e-9 (O2) at 25 C; default electrolyte/c reproduces water.
    """
    base = 5.0e-9 if electrode == "HER" else 2.4e-9
    mu_ref = liquid_viscosity_med(electrolyte, c, 298.15)
    mu_T = liquid_viscosity_med(electrolyte, c, T)
    return base * (T / 298.15) * (mu_ref / mu_T)
