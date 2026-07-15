"""0D (lumped) electrochemistry solvers.

`ZeroDSolver` is the original model: the whole cell reduced to one effective
Tafel branch plus an ohmic series resistance. Bubbles couple in through two
channels:

  * coverage theta  -> blocks active area: j_geo = (1 - theta) * j_local
  * void fraction eps -> raises electrolyte resistance via Bruggeman:
                           kappa_eff = kappa * (1 - eps)^1.5

At fixed cell voltage V the implicit balance

    j_geo = (1 - theta) * j0 * 10 ** ((V - E_rev - j_geo * R_area) / b)

is solved by bisection for j_geo, capped by a mass-transport limit. The
free-function form (`solve_current_density`, `overpotentials`) is preserved and
re-exported from `bubblesim.electrochem` for backward compatibility; the
`ZeroDSolver` class wraps it behind the `Solver` protocol.

The two-electrode Butler-Volmer fidelity will be added here as a sibling solver.
"""
import math

from .base import ElectroState
from ..constants import F, R_GAS
from ..kernel.kinetics import tafel_lumped, butler_volmer
from ..kernel.transport import conc_overpotential, vogt_enhancement, vogt_limit
from ..kernel import chemistry, watertransport
from ..kernel._solve import bisect


def solve_current_density(op, props, theta, eps):
    """Return geometric current density j_geo [A/m^2] for the current state.

    Implicit balance V = E_rev + eta_act(j) + eta_conc(j) + j R_area, where the
    concentration overpotential eta_conc = -(RT/zF) ln(1 - j/j_lim) bends the
    polarization curve smoothly toward the transport limit (previously the lumped
    model had only a hard cap and no transport-limit voltage penalty)."""
    E_rev = props["E_rev"]
    kappa_eff = props["kappa"] * (1.0 - eps) ** 1.5
    R_area = (op.gap_mm * 1e-3) / max(kappa_eff, 1e-6)     # area-specific ohmic resistance [ohm*m^2]

    j0 = props["j0"]
    b = props["tafel_b"]
    j_lim = props["j_lim_eff"]
    z = props.get("z_primary", 2)
    one_minus_theta = max(1e-3, 1.0 - theta)

    drive = op.V_cell - E_rev
    if drive <= 0.0:
        return 0.0

    def residual(j):
        # activation overpotential left after ohmic AND concentration losses
        eta = drive - j * R_area - conc_overpotential(j, j_lim, z, op.T)
        if eta <= 0.0:
            return j                      # forces bisection to lower j (residual > 0)
        return j - tafel_lumped(j0, b, eta, one_minus_theta)

    hi = j_lim * (1.0 - 1e-9)             # eta_conc is capped (~0.3 V) by the clamp in
                                          # conc_overpotential; the hard transport limit is
    if residual(hi) < 0.0:                # enforced by this explicit return-hi branch
        return hi                         # transport-limited
    return bisect(residual, 0.0, hi, 80)   # ~1e-24 relative tolerance


def overpotentials(op, props, theta, eps, j):
    """Decompose the applied voltage for reporting [all in V]."""
    E_rev = props["E_rev"]
    kappa_eff = props["kappa"] * (1.0 - eps) ** 1.5
    R_area = (op.gap_mm * 1e-3) / max(kappa_eff, 1e-6)
    eta_ohmic = j * R_area
    eta_conc = conc_overpotential(j, props["j_lim_eff"], props.get("z_primary", 2), op.T)
    eta_act = op.V_cell - E_rev - eta_ohmic - eta_conc
    return {"E_rev": E_rev, "eta_act": eta_act, "eta_conc": eta_conc, "eta_ohmic": eta_ohmic}


class ZeroDSolver:
    """Lumped 0D fidelity (one effective Tafel branch + ohmic resistance).

    CA mode inverts the Tafel+ohmic balance for j (bisection). CP mode is the
    closed-form forward direction: V = E_rev + b log10(j/((1-theta) j0)) + j R.
    """

    def solve(self, op, context, surfaces) -> ElectroState:
        s = surfaces[0]                       # primary electrode patch
        theta = s.coverage()
        eps = s.void_fraction()
        if getattr(op, "mode", "CA") == "CP":
            kappa_eff = context["kappa"] * (1.0 - eps) ** 1.5
            R_area = (op.gap_mm * 1e-3) / max(kappa_eff, 1e-6)
            omt = max(1e-3, 1.0 - theta)
            j = max(0.0, min(op.j_set, 0.995 * context["j_lim_eff"]))
            eta_act = max(0.0, context["tafel_b"]
                          * math.log10(max(j, 1e-12) / (omt * context["j0"])))
            eta_conc = conc_overpotential(j, context["j_lim_eff"],
                                          context.get("z_primary", 2), op.T)
            V = context["E_rev"] + eta_act + eta_conc + j * R_area
            ov = {"E_rev": context["E_rev"], "eta_act": eta_act,
                  "eta_conc": eta_conc, "eta_ohmic": j * R_area}
            return ElectroState(j=j, overpotentials=ov, V=V)
        j = solve_current_density(op, context, theta, eps)
        ov = overpotentials(op, context, theta, eps, j)
        return ElectroState(j=j, overpotentials=ov)


def _invert_bv(jk, j0, alpha_a, alpha_c, T, eta_hi=3.0, n=60):
    """Overpotential magnitude [V] that drives a kinetic current density `jk` >= 0.

    Butler-Volmer (in magnitude form) is monotone increasing in the overpotential
    magnitude, so invert it by bisection on [0, eta_hi]. `jk` is the *local* (per
    active area) current density j / (1 - theta).
    """
    if jk <= 0.0:
        return 0.0
    g = lambda eta: butler_volmer(j0, alpha_a, alpha_c, eta, T) - jk
    if g(eta_hi) < 0.0:          # past the bracket (transport caps j upstream) -> clamp
        return eta_hi
    return bisect(g, 0.0, eta_hi, n)


class ZeroDTwoElectrodeSolver:
    """Two-electrode 0D fidelity.

    Anode (OER) and cathode (HER) each obey the full Butler-Volmer law and pass
    the same cell current density j (series circuit). The full-cell balance

        V_cell = E_cell + eta_anode(j) + eta_cathode(j)
                 + j * (R_ohmic + R_membrane + R_contact)

    is solved for j by bisection — the right side rises monotonically with j, so
    f(j) = (right side) - V_cell has a single root on [0, j_lim]. Each electrode's
    overpotential magnitude is found by inverting Butler-Volmer at the local
    kinetic current density j / (1 - theta).

    Coverage is per electrode (it blocks that electrode's active area); the void
    fraction is a gap property feeding the ohmic resistance. By default only the
    primary electrode (op.electrode) carries bubbles and the counter electrode is
    ideal (bubble-free); set Operating.track_both to track a second Surface.

    `n_outer` / `n_inner` are the bisection iteration counts for the cell-balance
    and per-electrode BV inversions. Defaults reproduce the reference numerics;
    interactive front-ends may lower them (32/28 still gives ~uV resolution).
    """

    def __init__(self, n_outer=80, n_inner=60):
        self.n_outer = n_outer
        self.n_inner = n_inner

    def solve(self, op, context, surfaces) -> ElectroState:
        dual = op.track_both and len(surfaces) > 1
        if dual:
            # convention: surfaces[0] = cathode (HER), surfaces[1] = anode (OER)
            theta_c, theta_a = surfaces[0].coverage(), surfaces[1].coverage()
            eps_c, eps_a = surfaces[0].void_fraction(), surfaces[1].void_fraction()
        else:
            theta_primary = surfaces[0].coverage()
            if op.electrode == "OER":
                theta_a, theta_c = theta_primary, 0.0
            else:
                theta_a, theta_c = 0.0, theta_primary
            eps_c = eps_a = surfaces[0].void_fraction()

        E_cell = context["E_rev"]
        kappa = max(context["kappa"], 1e-6)
        gap, L_n = context["gap_m"], context["near_layer_m"]
        if dual:
            # series ohmic path: bubble-laden near-layer at each electrode
            # (own Bruggeman correction) + clear bulk in between
            L_n = min(L_n, 0.5 * gap)
            R_ohm = (L_n / kappa) * ((1.0 - eps_c) ** -1.5 + (1.0 - eps_a) ** -1.5) \
                    + max(0.0, gap - 2.0 * L_n) / kappa
            R_ohm_clear = gap / kappa
        else:
            R_ohm = gap / (kappa * (1.0 - eps_c) ** 1.5)
            R_ohm_clear = gap / kappa
        R_total = R_ohm + context["r_membrane_area"] + context["r_contact_area"]

        j0_a, j0_c = context["j0_anode"], context["j0_cathode"]
        aa_a, ac_a = context["alpha_a_anode"], context["alpha_c_anode"]
        aa_c, ac_c = context["alpha_a_cathode"], context["alpha_c_cathode"]
        T = op.T
        j_lim_base = context["j_lim_transport"]    # Sherwood-grounded transport limit
        z = context["z_primary"]
        k_vogt, j_ref_v = context["k_vogt"], context["j_ref_vogt"]

        def jlim_of(jj):     # bubble self-stirring (Vogt) raises the limit with current
            return j_lim_base * vogt_enhancement(jj, j_ref_v, k_vogt)

        omt_a = max(1e-3, 1.0 - theta_a)
        omt_c = max(1e-3, 1.0 - theta_c)

        def eta_a_of(j):
            return _invert_bv(j / omt_a, j0_a, aa_a, ac_a, T, n=self.n_inner)

        def eta_c_of(j):
            return _invert_bv(j / omt_c, j0_c, aa_c, ac_c, T, n=self.n_inner)

        # DRY CATHODE: with no liquid feed, every electron needs a water molecule
        # dragged (electro-osmosis) or diffused through the membrane. The ON/OFF
        # switch is op.dry_cathode — NOT "j_lim_water > 0", because a membrane
        # that passes no water gives j_lim_water == 0, which is TOTAL starvation,
        # the exact opposite of "feature disabled".
        dry = bool(getattr(op, "dry_cathode", False))
        j_lim_w = context.get("j_lim_water", 0.0) if dry else 0.0

        def eta_w_of(j):
            return watertransport.eta_water(j, j_lim_w, T) if dry else 0.0

        j_lim_fp = vogt_limit(j_lim_base, j_ref_v, k_vogt)   # self-consistent ceiling
        if dry:                               # water supply can be the tighter wall
            j_lim_fp = min(j_lim_fp, max(j_lim_w, 1e-9))
        mode = getattr(op, "mode", "CA")
        if mode == "CP":
            # galvanostatic: j imposed, V follows. Clamp below the self-consistent
            # Vogt-enhanced limit; beyond it eta_conc diverges (voltage runaway).
            j = max(0.0, min(op.j_set, 0.995 * j_lim_fp))
        else:
            drive = op.V_cell - E_cell
            if drive <= 0.0:
                j = 0.0
            else:
                def f(j):     # monotone increasing in j; root = operating current density
                    return (E_cell + eta_a_of(j) + eta_c_of(j)
                            + conc_overpotential(j, jlim_of(j), z, T) + eta_w_of(j)
                            + j * R_total - op.V_cell)
                hi = 0.995 * j_lim_fp     # exact ceiling: bisect can't return above it
                j = hi if f(hi) < 0.0 else bisect(f, 0.0, hi, self.n_outer)

        eta_a, eta_c = eta_a_of(j), eta_c_of(j)
        eta_w = eta_w_of(j)            # dry-cathode water starvation (0 when off)
        j_lim = jlim_of(j)             # Vogt-enhanced limit at the operating current
        V_cp = (E_cell + eta_a + eta_c + conc_overpotential(j, j_lim, z, T)
                + eta_w + j * R_total)
        # bubble bottleneck diagnostics: how much voltage each bubble channel costs.
        # Coverage: blocking area scales j0 by (1-theta); on the dominant Tafel
        # branch that costs exactly (RT / alpha F) ln(1/(1-theta)). Void: extra
        # ohmic drop versus a bubble-free gap.
        fRT = R_GAS * T / F
        ov = {
            "E_rev": E_cell,
            "eta_act": eta_a + eta_c,
            "eta_act_anode": eta_a,
            "eta_act_cathode": eta_c,
            "eta_conc": conc_overpotential(j, j_lim, z, T),
            "eta_ohmic": j * R_total,
            "eta_membrane": j * context["r_membrane_area"],
            "eta_bub_cov_anode": (fRT / aa_a) * math.log(1.0 / omt_a),
            "eta_bub_cov_cathode": (fRT / aa_c) * math.log(1.0 / omt_c),
            "eta_bub_void": j * (R_ohm - R_ohm_clear),
            "eta_water": eta_w,        # dry-cathode water starvation (0 = wet/off)
        }
        med = context.get("electrolyte", "KOH")
        c_b = op.c_electrolyte
        fields = {
            "pH_bulk": chemistry.bulk_pH(c_b, T, med),
            "pH_anode": chemistry.local_pH(c_b, j, j_lim, "OER", T, med),
            "pH_cathode": chemistry.local_pH(c_b, j, j_lim, "HER", T, med),
        }
        return ElectroState(j=j, overpotentials=ov, fields=fields,
                            V=(V_cp if mode == "CP" else None))
