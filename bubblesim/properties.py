"""Physical-property correlations for the electrolyte and evolved gas.

These are deliberately simple, literature-informed correlations meant to give
*physically reasonable trends* and order-of-magnitude values for alkaline
(KOH) water electrolysis. They are the first thing to recalibrate against a
specific paper or dataset. Every correlation is flagged with its assumption.

Internally everything is SI. Concentration `c` is in mol/L (KOH).
"""
import math

from .constants import R_GAS

EPS_WATER = 78.0  # relative permittivity of the aqueous electrolyte [-]

# electrons transferred and molar mass per evolved-gas molecule
GAS = {
    "HER": {"gas": "H2", "z": 2, "M": 2.016e-3},    # cathode: 2 H2O + 2e- -> H2 + 2 OH-
    "OER": {"gas": "O2", "z": 4, "M": 31.998e-3},   # anode: 4 OH- -> O2 + 2 H2O + 4e-
}


def reversible_voltage(T):
    """Reversible (thermodynamic) cell voltage for water splitting [V].

    1.229 V at 298.15 K with a -0.9 mV/K temperature coefficient (entropy term).
    Pressure / activity (Nernst) corrections are omitted in v1.
    """
    return 1.229 - 0.9e-3 * (T - 298.15)


def conductivity_KOH(c, T):
    """Ionic conductivity of aqueous KOH [S/m].

    Rough parabolic fit peaking near ~6 mol/L (kappa_25 ~ 60 S/m at 6 M),
    with a ~2 %/K temperature rise. Replace with Gilliam et al. (2007) for
    quantitative work.
    """
    kappa_25 = max(1.0, 20.0 * c - 1.667 * c * c)
    return kappa_25 * (1.0 + 0.02 * (T - 298.15))


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
    """Dynamic viscosity [Pa*s]: water Arrhenius-type T dependence, KOH thickening."""
    mu_w = 1.0e-3 * math.exp(1800.0 * (1.0 / T - 1.0 / 298.15))
    return mu_w * (1.0 + 0.10 * c)


def gas_density(electrode, T, P):
    """Ideal-gas density of the evolved gas [kg/m^3]."""
    M = GAS[electrode]["M"]
    return P * M / (R_GAS * T)


def gas_diffusivity(electrode, T):
    """Dissolved-gas diffusivity [m^2/s], scaled linearly with T (rough)."""
    base = 5.0e-9 if electrode == "HER" else 2.4e-9
    return base * (T / 298.15)
