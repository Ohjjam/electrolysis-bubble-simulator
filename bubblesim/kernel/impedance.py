"""Small-signal impedance (EIS) and double-layer time constants.

Linearizing the cell around its operating point gives the spectrum analytically
— no sinusoidal time simulation needed. Per electrode the faradaic branch is the
charge-transfer resistance R_ct = (dj/d eta)^-1 from Butler-Volmer, in parallel
with the double-layer capacitance C_dl, in series with a finite-length Warburg
element from the Nernst diffusion layer:

    Z_cell(w) = R_s + sum_e [ (R_ct,e + Z_W,e) || 1/(i w C_dl,e) ]

R_s is the series (electrolyte + membrane + contact) resistance the solver
already computes. All quantities are area-specific (ohm*m^2, F/m^2), matching
the rest of the kernel. The same R_ct C_dl product is the relaxation time the
transient (chronopotentiometry) response shows after a current step.
"""
import cmath
import math

from ..constants import F, R_GAS


def r_ct_bv(j0_eff, alpha_a, alpha_c, eta, T):
    """Charge-transfer resistance [ohm*m^2]: inverse slope of Butler-Volmer.

        dj/d eta = j0_eff (F/RT) [ alpha_a e^{alpha_a f eta} + alpha_c e^{-alpha_c f eta} ]

    `j0_eff` is the coverage-scaled exchange current density (1-theta) j0. At
    eta = 0 this reduces to the textbook RT / ((alpha_a+alpha_c) F j0).
    """
    f = F / (R_GAS * T)
    dj = j0_eff * f * (alpha_a * math.exp(alpha_a * f * eta)
                       + alpha_c * math.exp(-alpha_c * f * eta))
    return 1.0 / max(dj, 1e-12)


def warburg_finite(omega, R_d, tau_d):
    """Finite-length (bounded) Warburg impedance [ohm*m^2]:

        Z_W = R_d * tanh(sqrt(i w tau_d)) / sqrt(i w tau_d),   tau_d = delta^2 / D

    -> R_d as w -> 0 (the dc mass-transport resistance), ~ w^-1/2 at high w.
    """
    if omega <= 0.0 or tau_d <= 0.0:
        # tau_d = 0 -> no diffusion layer, so Z_W collapses to the pure dc
        # resistance R_d (the w->0 limit). Guarding it also avoids the 0/0
        # (tanh(0)/0) that a zero tau_d would otherwise raise.
        return complex(R_d, 0.0)
    s = cmath.sqrt(1j * omega * tau_d)
    return R_d * cmath.tanh(s) / s


def electrode_branch(omega, R_ct, C_dl, R_d=0.0, tau_d=0.0, n=1.0):
    """One electrode: (R_ct + Z_W) in parallel with the double-layer admittance.

    The double layer is a constant-phase element (CPE) Y = C_dl (i w)^n, which
    real rough / porous / bubble-covered electrodes show as a depressed arc
    (0.7 < n < ~0.95; Brug et al. 1984). n = 1.0 reduces to the ideal capacitor
    (bit-identical to before)."""
    Zf = R_ct + (warburg_finite(omega, R_d, tau_d) if R_d > 0.0 else 0.0)
    Yc = C_dl * (1j * omega) ** n if omega > 0.0 else 0.0
    return Zf / (1.0 + Zf * Yc)


def cell_impedance(freqs, R_s, electrodes):
    """Full-cell spectrum. `electrodes` = list of dicts with keys
    R_ct, C_dl, and optionally R_d, tau_d, n (CPE exponent). Returns complex Z."""
    out = []
    for f_hz in freqs:
        w = 2.0 * math.pi * f_hz
        Z = complex(R_s, 0.0)
        for e in electrodes:
            Z += electrode_branch(w, e["R_ct"], e["C_dl"],
                                  e.get("R_d", 0.0), e.get("tau_d", 0.0), e.get("n", 1.0))
        out.append(Z)
    return out


def log_freqs(f_lo=1e-3, f_hi=1e4, n=60):
    """Log-spaced frequency grid [Hz] (stdlib; no numpy in the kernel)."""
    la, lb = math.log10(f_lo), math.log10(f_hi)
    return [10.0 ** (la + (lb - la) * i / (n - 1)) for i in range(n)]
