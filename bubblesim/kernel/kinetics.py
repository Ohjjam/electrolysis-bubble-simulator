"""Electrode reaction kinetics — pure functions (no spatial assumptions).

The lumped Tafel law is what the 0D solver uses today. Butler-Volmer (the full
two-exponential form, reducing to a Tafel line at large |eta|) lands with the
two-electrode fidelity and will live here alongside it.
"""
import math

from ..constants import F, R_GAS


def tafel_lumped(j0, b, eta, one_minus_theta):
    """Lumped Tafel kinetic current density [A/m^2]:

        j_kin = (1 - theta) * j0 * 10^(eta / b)

    `b` is the decadic Tafel slope [V/decade]; `(1 - theta)` blocks the active
    area shadowed by attached-bubble footprints.
    """
    return one_minus_theta * j0 * 10.0 ** (eta / b)


def butler_volmer(j0, alpha_a, alpha_c, eta, T):
    """Net faradaic current density [A/m^2] from the full Butler-Volmer equation:

        j = j0 [ exp(alpha_a * F * eta / RT) - exp(-alpha_c * F * eta / RT) ]

    The sign of the overpotential `eta` sets the direction; at large |eta| one
    exponential dominates and this reduces to a Tafel line of slope
    2.303 RT / (alpha F). (Reserved for the two-electrode solver.)
    """
    f = F / (R_GAS * T)
    return j0 * (math.exp(alpha_a * f * eta) - math.exp(-alpha_c * f * eta))
