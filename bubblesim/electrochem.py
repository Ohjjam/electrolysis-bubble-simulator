"""Lumped electrochemistry: solve the geometric current density at fixed voltage.

The whole cell is reduced to one effective Tafel branch plus an ohmic series
resistance. Bubbles couple in through two channels:

  * coverage theta  -> blocks active area: j_geo = (1 - theta) * j_local
  * void fraction eps -> raises electrolyte resistance via Bruggeman:
                           kappa_eff = kappa * (1 - eps)^1.5

At fixed cell voltage V we must solve the implicit balance

    j_geo = (1 - theta) * j0 * 10 ** ( (V - E_rev - j_geo * R_area) / b )

for the geometric current density j_geo, capped by a mass-transport limit.
"""


def solve_current_density(op, props, theta, eps):
    """Return geometric current density j_geo [A/m^2] for the current state."""
    E_rev = props["E_rev"]
    kappa_eff = props["kappa"] * (1.0 - eps) ** 1.5
    R_area = (op.gap_mm * 1e-3) / max(kappa_eff, 1e-6)     # area-specific ohmic resistance [ohm*m^2]

    j0 = props["j0"]
    b = props["tafel_b"]
    j_lim = props["j_lim_eff"]
    one_minus_theta = max(1e-3, 1.0 - theta)

    drive = op.V_cell - E_rev
    if drive <= 0.0:
        return 0.0

    def residual(j):
        eta = drive - j * R_area          # activation overpotential left after ohmic loss
        if eta <= 0.0:
            return j                      # forces bisection to lower j (residual > 0)
        j_kin = one_minus_theta * j0 * 10.0 ** (eta / b)
        return j - j_kin

    lo, hi = 0.0, j_lim
    if residual(hi) < 0.0:
        # still kinetically climbing at the transport limit -> transport-limited
        return j_lim
    for _ in range(80):                   # bisection: ~1e-24 relative tolerance
        mid = 0.5 * (lo + hi)
        if residual(mid) > 0.0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def overpotentials(op, props, theta, eps, j):
    """Decompose the applied voltage for reporting [all in V]."""
    E_rev = props["E_rev"]
    kappa_eff = props["kappa"] * (1.0 - eps) ** 1.5
    R_area = (op.gap_mm * 1e-3) / max(kappa_eff, 1e-6)
    eta_ohmic = j * R_area
    eta_act = op.V_cell - E_rev - eta_ohmic
    return {"E_rev": E_rev, "eta_act": eta_act, "eta_ohmic": eta_ohmic}
