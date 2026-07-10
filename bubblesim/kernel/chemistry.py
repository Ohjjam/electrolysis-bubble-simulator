"""Electrolyte chemistry: ionic strength, activity, water equilibrium, and the
local (surface) pH that the reaction flux sets up against mass transport.

Media-aware (KOH / H2SO4 / phosphate buffer). The half-reaction pathway differs
by medium and sets the local-pH direction at each electrode:

  alkaline (KOH):  HER  2 H2O + 2e- -> H2 + 2 OH-   (makes OH-  -> cathode pH up)
                   OER  4 OH- -> O2 + 2 H2O + 4e-   (eats  OH-  -> anode  pH down)
  acid (H2SO4):    HER  2 H+ + 2e- -> H2            (eats  H+   -> cathode pH up)
                   OER  2 H2O -> O2 + 4 H+ + 4e-    (makes H+   -> anode  pH down)
  buffer (PB):     same directions, but the conjugate pair (H2PO4-/HPO4 2-)
                   absorbs the flux: the shift is damped by the buffer capacity.

In every medium the cathode surface ends up more alkaline and the anode more
acidic than the bulk — but the *magnitude* differs enormously (strong
acid/alkali pin it; neutral buffer survives only by buffering). The associated
potential cost is already carried by the concentration overpotential
(`transport.conc_overpotential`); local pH is reported as an observable, not
double-counted into the voltage balance.
"""
import math

from ..properties import ELECTROLYTES, liquid_density_med

KA2_H2SO4 = 1.2e-2   # second dissociation constant of H2SO4 [mol/L]


def ionic_strength(c, electrolyte="KOH"):
    """Ionic strength I = 1/2 sum_i c_i z_i^2 [mol/L].

    KOH (1:1) -> I = c;  H2SO4 (2 H+ + SO4 2-) -> I = 3c;
    equimolar KH2PO4/K2HPO4 -> I ~ 2c.
    """
    return ELECTROLYTES[electrolyte]["i_factor"] * c


def davies_activity(I, z=1, A=0.509):
    """Mean activity coefficient from the Davies equation:

        log10 gamma = -A z^2 ( sqrt(I)/(1+sqrt(I)) - 0.3 I )

    Strictly valid only to ~0.5 M; at electrolyzer concentrations (several M)
    this is an extrapolation kept for the right qualitative trend (gamma turns
    back up at high I). Replace with Pitzer for quantitative work.
    """
    s = math.sqrt(I)
    return 10.0 ** (-A * z * z * (s / (1.0 + s) - 0.3 * I))


def pitzer_activity_koh(c, T=298.15):
    """Mean activity coefficient of KOH from the Pitzer ion-interaction model
    (K-OH parameters beta0/beta1/Cphi), valid to high molality unlike Davies.

        ln g+- = f^g + m B^g + m^2 C^g
        f^g = -Aphi[ sqrt(I)/(1+b sqrt I) + (2/b) ln(1+b sqrt I) ]
        B^g = 2 b0 + (2 b1 / a^2 I)[1 - e^{-a sqrt I}(1 + a sqrt I - a^2 I/2)]
        C^g = (3/2) Cphi,   a=2, b=1.2

    Molarity c is converted to molality m via the solution density. Matches the
    literature g+-(1 molal) ~ 0.75 and, unlike Davies, does not blow up at the
    several-molar concentrations of real electrolyzers.
    """
    M_KOH = 0.05610                                       # kg/mol
    rho = liquid_density_med("KOH", c) / 1000.0           # kg/L
    m = c / max(1e-6, rho - c * M_KOH)                    # mol solute / kg solvent
    if m <= 0.0:
        return 1.0
    b, alpha, Aphi = 1.2, 2.0, 0.391                      # Debye-Huckel slope at ~25 C
    b0, b1, Cphi = 0.1298, 0.320, 0.0041                 # Pitzer & Mayorga K-OH
    I = m                                                # 1:1 electrolyte
    sI = math.sqrt(I)
    f = -Aphi * (sI / (1.0 + b * sI) + (2.0 / b) * math.log(1.0 + b * sI))
    Bg = 2.0 * b0 + (2.0 * b1 / (alpha * alpha * I)) * \
        (1.0 - math.exp(-alpha * sI) * (1.0 + alpha * sI - 0.5 * alpha * alpha * I))
    return math.exp(f + m * Bg + m * m * 1.5 * Cphi)


def activity_for(c, T, electrolyte, high_fidelity=False):
    """Mean activity coefficient: Davies by default; Pitzer for KOH when
    high_fidelity (quantitative at electrolyzer concentration)."""
    if high_fidelity and electrolyte == "KOH":
        return pitzer_activity_koh(c, T)
    return davies_activity(ionic_strength(c, electrolyte))


def pKw(T):
    """Negative log of the water ion product. ~14.0 at 25 C, decreasing with
    temperature; best linear fit to Bandura-Lvov (2006) tabulated values over
    25-100 C (14.00@25, 13.42@50, 12.26@100; slope 0.0232, not 0.0265)."""
    T_C = T - 273.15
    return 14.0 - 0.0232 * (T_C - 25.0)


def hplus_H2SO4(c):
    """[H+] of c-molar H2SO4: first proton fully dissociated, second partial
    (Ka2 = 1.2e-2). Solves  x(c+x)/(c-x) = Ka2  for the second proton x."""
    if c <= 0.0:
        return 1e-7
    b = c + KA2_H2SO4
    x = 0.5 * (-b + math.sqrt(b * b + 4.0 * KA2_H2SO4 * c))
    return c + x


def bulk_pH(c, T, electrolyte="KOH"):
    """Bulk pH of the electrolyte (activity-corrected; buffer pinned at pKa2)."""
    gamma = davies_activity(ionic_strength(c, electrolyte))
    kind = ELECTROLYTES[electrolyte]["type"]
    if kind == "acid":
        return -math.log10(max(1e-12, gamma * hplus_H2SO4(c)))
    if kind == "buffer":
        return ELECTROLYTES[electrolyte]["pH"]      # equimolar pair -> pH ~ pKa2
    return pKw(T) + math.log10(max(1e-12, gamma * c))


def local_pH(c_bulk, j, j_lim, electrode, T, electrolyte="KOH"):
    """Surface pH at an electrode under current.

    The flux-perturbed carrier concentration is c_s = c_b (1 -/+ j/j_lim) for the
    consumed/produced species (1 carrier ion per electron in both pathways);
    the buffer case damps the would-be shift by ~(1 + beta*c). Bulk activity
    coefficient is reused at the surface (approximation).
    """
    x = min(0.999, j / j_lim)
    kind = ELECTROLYTES[electrolyte]["type"]
    gamma = davies_activity(ionic_strength(c_bulk, electrolyte))

    if kind == "alkaline":
        # OH- carrier: HER makes it (+), OER eats it (-)
        c_OH = c_bulk * (1.0 + x) if electrode == "HER" else max(1e-9, c_bulk * (1.0 - x))
        return pKw(T) + math.log10(max(1e-12, gamma * c_OH))

    if kind == "acid":
        # H+ carrier: HER eats it (pH up at cathode), OER makes it (pH down at anode)
        cH = hplus_H2SO4(c_bulk)
        c_s = max(1e-9, cH * (1.0 - x)) if electrode == "HER" else cH * (1.0 + x)
        return -math.log10(max(1e-12, gamma * c_s))

    # buffer: unbuffered shift surrogate (up to ~3 pH at the transport limit),
    # damped by the lumped buffer capacity (1 + beta * c)
    med = ELECTROLYTES[electrolyte]
    shift = 3.0 * x / (1.0 + med["beta"] * c_bulk)
    return med["pH"] + shift if electrode == "HER" else med["pH"] - shift
