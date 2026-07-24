"""Mass-transport correlations: boundary layer, limiting current, concentration
overpotential, and dissolved-gas (Henry) supersaturation.

These are 0D-usable helpers and also the constitutive layer the 1D solver will
reuse. Two notes on the physics:

  * In alkaline water electrolysis the bulk electrolyte (KOH) is not the limiting
    reactant, so the concentration overpotential is small except as the current
    approaches the transport limit. It is included for completeness and for the
    regimes (high rate, poor convection) where it matters; it rises steeply
    (then capped numerically) as j -> j_lim. CA solvers bracket below the limit.
    CP solvers preserve the requested setpoint and explicitly report an
    infeasible operating point when the request exceeds the model ceiling.
  * Flow raises the limiting current through the Sherwood number
    (Sh ~ Re^1/2 Sc^1/3), which replaces the earlier ad-hoc linear bump.
"""
import math

from ..constants import F, R_GAS, G


def natural_convection_sherwood(d_rho_rel, L, nu, Sc, c=0.67):
    """Free-convection Sherwood floor for an unstirred vertical electrode:

        Sh_nat = c (Gr Sc)^(1/4),   Gr = g (d_rho/rho) L^3 / nu^2

    In a cell with no pumping, density gradients (dissolved gas + concentration)
    drive natural convection that sets the limiting current (Ibl & Schmidt;
    Newman, free-convection mass transfer) -- the real no-flow floor, distinct
    from an arbitrary fixed sh0 and from Vogt bubble micro-convection."""
    Gr = G * max(0.0, d_rho_rel) * L ** 3 / (nu * nu)
    return c * (Gr * Sc) ** 0.25


def reynolds(rho, u, L, mu):
    """Reynolds number  Re = rho u L / mu  (0 at no flow)."""
    return rho * u * L / mu


def schmidt(mu, rho, D):
    """Schmidt number  Sc = mu / (rho D) = nu / D."""
    return mu / (rho * D)


def sherwood(Re, Sc, sh0=1.0, coeff=6.0e-4):
    """Sherwood number  Sh = sh0 + coeff * Re^0.5 * Sc^(1/3).

    The forced-convection term is the laminar boundary-layer scaling
    (Sh ~ Re^1/2 Sc^1/3); `sh0` is the no-flow (diffusion / natural-convection)
    floor so Sh stays finite at u = 0.
    """
    return sh0 + coeff * Re ** 0.5 * Sc ** (1.0 / 3.0)


def mass_transfer_coeff(Sh, D, L):
    """Mass-transfer coefficient  k_m = Sh D / L  [m/s]."""
    return Sh * D / L


def flow_enhancement(op, props, params):
    """Limiting-current enhancement  Sh(Re)/sh0 = 1 + (coeff/sh0) Re^0.5 Sc^(1/3).

    Grounds the flow dependence of j_lim in the Sherwood correlation; equals 1 at
    no flow, rising ~u^1/2 with cross-flow.
    """
    rho, mu, D, L = props["rho_l"], props["mu"], params.D_reactant, params.L_char
    Re = reynolds(rho, op.u_flow, L, mu)
    Sc = schmidt(mu, rho, D)
    return sherwood(Re, Sc, params.sh0, params.sh_coeff) / params.sh0


def vogt_enhancement(j, j_ref, k_vogt):
    """Bubble self-stirring (Vogt) limiting-current enhancement [-]:

        f = 1 + k_vogt * sqrt(max(j,0) / j_ref)

    Detaching/rising bubbles agitate the boundary layer at gas-evolving
    electrodes — often the *dominant* mass-transport mechanism. Because it
    depends on the current being solved, the solvers apply it inside their
    implicit loop (consistently in CA and CP, preserving CA<->CP symmetry).
    k_vogt=0 disables it (returns 1).
    """
    if k_vogt <= 0.0 or j_ref <= 0.0:
        return 1.0
    return 1.0 + k_vogt * math.sqrt(max(j, 0.0) / j_ref)


def vogt_limit(j_lim_base, j_ref, k_vogt):
    """Self-consistent Vogt-enhanced transport limit: the EXACT fixed point of

        j = j_lim_base * (1 + k_vogt * sqrt(j / j_ref)).

    Substituting s = sqrt(j) gives a quadratic
        s^2 - (j_lim_base * k_vogt / sqrt(j_ref)) * s - j_lim_base = 0,
    solved in closed form (no iteration / under-convergence) so the CP validity
    check and the CA bracket sit exactly on the same ceiling.
    Returns j_lim_base when self-stirring is disabled.
    """
    if k_vogt <= 0.0 or j_ref <= 0.0:
        return j_lim_base
    b = j_lim_base * k_vogt / math.sqrt(j_ref)
    s = 0.5 * (b + math.sqrt(b * b + 4.0 * j_lim_base))
    return s * s


def conc_overpotential(j, j_lim, z, T):
    """Concentration (mass-transport) overpotential [V]:

        eta_conc = -(RT / zF) ln(1 - j / j_lim),   0 <= j < j_lim.

    Would diverge as j -> j_lim, but the argument is clamped at 1 - 1e-9, so
    eta_conc SATURATES at -(RT/zF) ln(1e-9) (~0.3 V at z=2, 333 K); the hard
    CA callers enforce the transport limit through their solve bracket.  CP
    callers may evaluate above it only to return a clearly flagged, finite
    lower-bound voltage rather than silently changing the requested current.
    """
    if j <= 0.0:
        return 0.0
    x = j / j_lim
    if x >= 1.0 - 1e-9:
        x = 1.0 - 1e-9
    return -(R_GAS * T) / (z * F) * math.log(1.0 - x)


def conc_differential_resistance(j, j_lim_base, z, T, j_ref=0.0,
                                 k_vogt=0.0):
    """Small-signal ``d eta_conc / d j`` [ohm*m^2].

    The DC solvers use a current-dependent Vogt limit

        L(j) = j_lim_base * (1 + k_vogt * sqrt(j / j_ref))

    inside ``eta = -(RT/zF) ln(1 - j/L(j))``.  Differentiating only the
    logarithm while treating ``L`` as a constant gives an EIS resistance that
    is not the slope of the DC model.  This helper differentiates the complete
    expression and is therefore the single EIS/DC bridge.

    ``math.inf`` is returned at or above the self-consistent transport wall:
    there is no finite linearisation of this reduced closure there.
    """
    j = max(0.0, float(j))
    base = max(float(j_lim_base), math.ulp(1.0))
    z = max(float(z), math.ulp(1.0))
    limit = base * vogt_enhancement(j, j_ref, k_vogt)
    if j >= limit:
        return math.inf

    if j > 0.0 and k_vogt > 0.0 and j_ref > 0.0:
        dlimit_dj = base * k_vogt / (2.0 * math.sqrt(j * j_ref))
    else:
        dlimit_dj = 0.0
    ratio = j / limit
    dratio_dj = (limit - j * dlimit_dj) / (limit * limit)
    return (R_GAS * T / (z * F)) * dratio_dj / (1.0 - ratio)


def surface_conc_ratio(j, j_lim):
    """Surface/bulk reactant concentration ratio  c_s/c_b = 1 - j/j_lim
    (the input to the local-pH model). Clamped to (0, 1]."""
    return max(1e-9, 1.0 - j / j_lim)


def saturation_concentration(P_gas, k_henry):
    """Henry's-law dissolved-gas saturation concentration  c_sat = P_gas / k_H
    [mol/m^3]  (k_H in [Pa*m^3/mol])."""
    return P_gas / k_henry


def supersaturation(c_dissolved, c_sat):
    """Supersaturation ratio  S = c_dissolved / c_sat  (S > 1 drives nucleation)."""
    return c_dissolved / c_sat if c_sat > 0.0 else 0.0
