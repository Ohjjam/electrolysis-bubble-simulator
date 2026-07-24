"""Porous-electrode fidelity  (model="porous")  -- Newman macrohomogeneous theory.

The headline solver: a real 3-D electrode (Ni/stainless foam, carbon paper,
mesh) carrying a nanostructured catalyst is NOT meshed. It is homogenized into
effective properties (kernel.morphology) and the reaction distribution is
resolved along ONE depth axis d in [0, L_e] by the coupled charge balance

    i_s + i_l = I                       (solid + liquid current = total, const)
    i_s = -sigma_eff dphi_s/dd          (electron transport in the matrix)
    i_l = -kappa_eff dphi_l/dd          (ion transport in the pores)
    di_s/dd = -a * j_loc(eta)           (charge transfer along the depth)
    eta = phi_s - phi_l - E_eq,  j_loc = Butler-Volmer per REAL area

Eliminating phi gives a single nonlinear BVP for the overpotential profile:

    eta'' = a (1/sigma_eff + 1/kappa_eff) j_loc(eta)
    eta'(0)   = -I / sigma_eff          (d=0 current collector: all current solid)
    eta'(L_e) = +I / kappa_eff          (d=L_e separator: all current ionic)

solved by **Newton** (the report's item 2.1 -- a few iterations, not fixed-count
bisection) on a tridiagonal system (Thomas). The electrode's effective
overpotential (activation distribution + internal matrix/pore ohmic) is then

    eta_eff = eta(0) + (1/kappa_eff) integral_0^L (I - i_s) dd

and the cell balance is identical to the two-electrode solver with eta_eff(j)
in place of the planar Butler-Volmer inversion. A thin electrode (flat_plate)
collapses to a uniform reaction j_loc = j/R_f, i.e. the planar result.

numpy only (solver boundary; the kernel stays stdlib).
"""
import numpy as np

from .base import ElectroState
from ..constants import F, R_GAS
from ..kernel import morphology as morph
from ..kernel import chemistry
from ..kernel.transport import conc_overpotential, vogt_enhancement, vogt_limit
from ..kernel._solve import bisect


def _trapz(y, h):
    """Trapezoidal integral with uniform spacing h (np.trapz was removed in numpy 2)."""
    return h * (float(np.sum(y)) - 0.5 * float(y[0] + y[-1]))


def _bv_jd(eta, j0, aa, ac, f):
    """Butler-Volmer (magnitude form, eta >= 0) current density and d j/d eta."""
    ea = np.clip(aa * f * eta, -60.0, 60.0)
    ec = np.clip(ac * f * eta, -60.0, 60.0)
    e1, e2 = np.exp(ea), np.exp(-ec)
    return j0 * (e1 - e2), j0 * (aa * f * e1 + ac * f * e2)


def _thomas(a, b, c, d):
    """Solve a tridiagonal system (sub a[len n-1], diag b[n], super c[n-1], rhs d)."""
    n = len(b)
    cp = np.empty(n - 1)
    dp = np.empty(n)
    cp[0] = c[0] / b[0]
    dp[0] = d[0] / b[0]
    for i in range(1, n - 1):
        m = b[i] - a[i - 1] * cp[i - 1]
        cp[i] = c[i] / m
        dp[i] = (d[i] - a[i - 1] * dp[i - 1]) / m
    m = b[n - 1] - a[n - 2] * cp[n - 2]
    dp[n - 1] = (d[n - 1] - a[n - 2] * dp[n - 2]) / m
    x = np.empty(n)
    x[n - 1] = dp[n - 1]
    for i in range(n - 2, -1, -1):
        x[i] = dp[i] - cp[i] * x[i + 1]
    return x


def _newton_eta(eta, A, se, ke, I, h, inv_h2, N, j0, aa, ac, f):
    """Damped Newton for the depth BVP eta'' = A(d) j_loc(eta); A may vary with
    depth (gas feedback). Tridiagonal Jacobian via Thomas; converges in ~5 iters."""
    for _ in range(40):
        j, dj = _bv_jd(eta, j0, aa, ac, f)
        Fv = np.empty(N)
        Fv[1:-1] = (eta[:-2] - 2 * eta[1:-1] + eta[2:]) * inv_h2 - A[1:-1] * j[1:-1]
        Fv[0] = (2 * eta[1] - 2 * eta[0] + 2 * h * I / se) * inv_h2 - A[0] * j[0]
        Fv[-1] = (2 * eta[-2] - 2 * eta[-1] + 2 * h * I / ke) * inv_h2 - A[-1] * j[-1]
        sub = np.full(N - 1, inv_h2)
        sup = np.full(N - 1, inv_h2)
        sub[-1] = 2 * inv_h2                    # Neumann ghost at d=L
        sup[0] = 2 * inv_h2                     # Neumann ghost at d=0
        diag = -2 * inv_h2 - A * dj
        step = np.clip(_thomas(sub, diag, sup, -Fv), -0.4, 0.4)   # damp overshoot
        eta = np.maximum(0.0, eta + step)
        if np.max(np.abs(step)) < 1e-11:
            break
    return eta


def pore_limiting_current(eff, c_b, D_carrier, t_carrier):
    """Carrier-ion diffusion ceiling through the homogenized pore [A/m^2]."""
    L = max(float(eff["L_e"]), 1e-9)
    eps = max(0.0, float(eff["eps_p"]))
    D_pore = float(D_carrier) * (eps ** 1.5 if eps > 0.0 else 1.0)
    return (F * D_pore * max(0.0, float(c_b))
            / (L * max(1e-3, 1.0 - float(t_carrier))))


def porous_eta(I, eff, kappa, j0_real, aa, ac, T, omt=1.0, N=33,
               gas_feedback=False, escape=1.0, c_b=6.0e3, D_carrier=1.0e-9, t_carrier=0.0):
    """Solve the depth BVP for total current density I [A/m^2]; return eta_eff and
    depth diagnostics. `omt` = (1 - coverage) blocks active area, `j0_real` is the
    intrinsic exchange current density PER REAL catalyst area.

    With `gas_feedback`, internal gas saturation s_g(d) (gas generated along the
    depth, funnelling out to the collector, poorly escaping in a tight foam)
    blocks active area a_eff = a(1-s_g) and lowers the pore conductivity
    kappa_eff = kappa(1-mean s_g)^1.5 -- the bubble-in-porous blanketing feedback.

    In-pore mass transport: the carrier ion is supplied at the separator face and
    consumed along the depth, so its concentration is depleted toward the
    collector; the resulting (reaction-weighted) concentration overpotential is
    added to eta_eff and the depth profile c(d)/c_b returned (`c_b` [mol/m^3]).
    """
    L = eff["L_e"]
    d_mm = (np.linspace(0.0, L, N) * 1e3).tolist()
    i_lim_pore = pore_limiting_current(eff, c_b, D_carrier, t_carrier)
    if I <= 0.0:
        z = [0.0] * N
        return {"eta_eff": 0.0, "util": 1.0, "pen_mm": L * 1e3,
                "eta": z, "j_loc": z, "d_mm": d_mm, "s_g_max": 0.0,
                "c_pore": [1.0] * N, "eta_conc_pore": 0.0,
                "j_lim_pore": float(i_lim_pore),
                "pore_transport_exceeded": False}

    a = eff["a"] * max(1e-3, omt)              # coverage blocks active area
    se = max(eff["sigma_eff"], 1e-9)
    ke0 = max(morph.kappa_eff(kappa, eff), 1e-9)
    f = F / (R_GAS * T)
    h = L / (N - 1)
    inv_h2 = 1.0 / (h * h)
    Rf_eff = a * L                             # effective roughness incl. coverage

    eta0 = (1.0 / (aa * f)) * np.log1p(I / max(Rf_eff * j0_real, 1e-30))
    eta = np.full(N, max(1e-3, float(eta0)))
    a_arr = np.full(N, a)
    ke = ke0
    A = a_arr * (1.0 / se + 1.0 / ke)
    eta = _newton_eta(eta, A, se, ke, I, h, inv_h2, N, j0_real, aa, ac, f)

    s_g = np.zeros(N)
    if gas_feedback:
        s_max = 0.6
        k_g = 2.5 * (1.2 - min(1.0, escape))   # tighter foam (low escape) traps more gas
        for _ in range(4):                     # s_g <-> reaction fixed point
            j, _d = _bv_jd(eta, j0_real, aa, ac, f)
            aj = a * np.abs(j)
            seg = 0.5 * (aj[:-1] + aj[1:]) * h
            Phi = np.concatenate([np.cumsum(seg[::-1])[::-1], [0.0]])  # gas flux toward exit
            s_g = s_max * (1.0 - np.exp(-k_g * Phi / 1.0e4))
            a_arr = a * (1.0 - s_g)
            ke = ke0 * (1.0 - float(s_g.mean())) ** 1.5
            A = a_arr * (1.0 / se + 1.0 / ke)
            eta = _newton_eta(eta, A, se, ke, I, h, inv_h2, N, j0_real, aa, ac, f)

    j, _ = _bv_jd(eta, j0_real, aa, ac, f)
    aj = a_arr * j
    cum = np.concatenate([[0.0], np.cumsum(0.5 * (aj[:-1] + aj[1:]) * h)])
    i_s = I - cum                              # solid current; i_s(0)=I, i_s(L)~0
    i_l = I - i_s                              # liquid current; rises 0 -> I
    # in-pore reactant depletion: carrier supplied at the separator (d=L, i_s=0)
    # and consumed toward the collector (i_s=I); a pore-scale limiting current
    # (Bruggeman pore diffusivity, migration relief via t_carrier) sets c(d)/c_b.
    c_ratio = np.clip(1.0 - i_s / max(i_lim_pore, 1e-9), 0.02, 1.0)
    wj = np.abs(j) + 1e-30
    c_react = float(np.sum(wj * c_ratio) / np.sum(wj))     # reaction-weighted mean conc
    eta_conc_pore = -(R_GAS * T / F) * float(np.log(max(0.02, c_react)))
    eta_eff = float(eta[0] + _trapz(i_l, h) / ke) + eta_conc_pore
    jmax = float(np.max(np.abs(j))) or 1.0
    util = float((_trapz(np.abs(j), h) / L) / jmax)        # 1 = uniform reaction
    front = float(np.interp(0.632 * I, i_l, np.linspace(0.0, L, N)))
    return {"eta_eff": eta_eff, "util": util, "pen_mm": front * 1e3,
            "eta": eta.tolist(), "j_loc": j.tolist(), "d_mm": d_mm,
            "s_g_max": float(s_g.max()),
            "c_pore": c_ratio.tolist(), "eta_conc_pore": eta_conc_pore,
            "j_lim_pore": float(i_lim_pore),
            "pore_transport_exceeded": bool(I >= i_lim_pore)}


class PorousSolver:
    """Porous-electrode cell solver. Each electrode is a depth-resolved porous
    column; the cell balance mirrors `ZeroDTwoElectrodeSolver` with eta_eff(j)
    from the BVP replacing the planar Butler-Volmer inversion.

    In porous mode the morphology library owns the electrode area (R_f, a), so the
    context exchange current density is treated as intrinsic (per real area) -- set
    the separate ECSA roughness knob to 1.
    """

    def __init__(self, n_outer=60, N=33):
        self.n_outer = n_outer
        self.N = N

    def solve(self, op, context, surfaces) -> ElectroState:
        dual = op.track_both and len(surfaces) > 1
        if dual:
            theta_c, theta_a = surfaces[0].coverage(), surfaces[1].coverage()
            eps_c, eps_a = surfaces[0].void_fraction(), surfaces[1].void_fraction()
        else:
            tp = surfaces[0].coverage()
            theta_a, theta_c = (tp, 0.0) if op.electrode == "OER" else (0.0, tp)
            eps_c = eps_a = surfaces[0].void_fraction()

        E_cell = context["E_rev"]
        kappa = max(context["kappa"], 1e-6)
        gap, L_n = context["gap_m"], context["near_layer_m"]
        if dual:
            L_n = min(L_n, 0.5 * gap)
            R_ohm = (L_n / kappa) * ((1.0 - eps_c) ** -1.5 + (1.0 - eps_a) ** -1.5) \
                + max(0.0, gap - 2.0 * L_n) / kappa
            R_ohm_clear = gap / kappa
        else:
            R_ohm = gap / (kappa * (1.0 - eps_c) ** 1.5)
            R_ohm_clear = gap / kappa
        R_total = R_ohm + context["r_membrane_area"] + context["r_contact_area"]

        # measured overrides (None -> use morphology preset)
        ov = {}
        if getattr(op, "rf_override", None) is not None:
            ov["R_f"] = op.rf_override
        if getattr(op, "Le_override_mm", None) is not None:
            ov["L_e"] = op.Le_override_mm * 1e-3
        if getattr(op, "eps_override", None) is not None:
            ov["eps_p"] = op.eps_override
        if getattr(op, "sigma_override", None) is not None:
            ov["sigma_s"] = op.sigma_override
        eff = morph.effective_electrode(op.substrate, op.nanostructure,
                                        op.cat_loading, ov or None)
        j0_a, j0_c = context["j0_anode"], context["j0_cathode"]
        aa_a, ac_a = context["alpha_a_anode"], context["alpha_c_anode"]
        aa_c, ac_c = context["alpha_a_cathode"], context["alpha_c_cathode"]
        T = op.T
        j_lim_base, z = context["j_lim_transport"], context.get("z_transport", 1)
        k_vogt, j_ref_v = context["k_vogt"], context["j_ref_vogt"]
        omt_a, omt_c = max(1e-3, 1.0 - theta_a), max(1e-3, 1.0 - theta_c)
        gasfb = getattr(op, "gas_feedback", False)
        esc = eff["escape_factor"]

        c_b = op.c_electrolyte * 1000.0                 # mol/L -> mol/m^3
        D_c, t_c = context["D_carrier"], context["t_carrier"]

        def col_a(j):
            return porous_eta(j, eff, kappa, j0_a, aa_a, ac_a, T, omt_a, self.N,
                              gas_feedback=gasfb, escape=esc,
                              c_b=c_b, D_carrier=D_c, t_carrier=t_c)

        def col_c(j):
            # Positive current is a cathodic HER magnitude here: swap the
            # coefficients so alpha_c controls the growing exponential.
            return porous_eta(j, eff, kappa, j0_c, ac_c, aa_c, T, omt_c, self.N,
                              gas_feedback=gasfb, escape=esc,
                              c_b=c_b, D_carrier=D_c, t_carrier=t_c)

        def jlim_of(jj):
            return j_lim_base * vogt_enhancement(jj, j_ref_v, k_vogt)

        j_lim_external = vogt_limit(j_lim_base, j_ref_v, k_vogt)
        j_lim_pore = pore_limiting_current(eff, c_b, D_c, t_c)
        j_lim_fp = min(j_lim_external, j_lim_pore)
        mode = getattr(op, "mode", "CA")
        if mode == "CP":
            j = max(0.0, op.j_set)
        else:
            drive = op.V_cell - E_cell
            if drive <= 0.0:
                j = 0.0
            else:
                def fbal(jj):
                    return (E_cell + col_a(jj)["eta_eff"] + col_c(jj)["eta_eff"]
                            + conc_overpotential(jj, jlim_of(jj), z, T)
                            + jj * R_total - op.V_cell)
                # Keep the historical CA solve path.  The pore model currently
                # has a finite concentration floor, so its internal ceiling is
                # a validity flag rather than a mathematically divergent root
                # bracket.  CP nevertheless reports that ceiling explicitly.
                hi = 0.995 * j_lim_external
                j = hi if fbal(hi) < 0.0 else bisect(fbal, 0.0, hi, self.n_outer)

        ra, rc = col_a(j), col_c(j)
        eta_a, eta_c = ra["eta_eff"], rc["eta_eff"]
        j_lim = jlim_of(j)
        eta_conc = conc_overpotential(j, j_lim, z, T)
        V = E_cell + eta_a + eta_c + eta_conc + j * R_total
        fRT = R_GAS * T / F
        ov = {
            "E_rev": E_cell, "eta_act": eta_a + eta_c,
            "eta_act_anode": eta_a, "eta_act_cathode": eta_c,
            "eta_conc": eta_conc, "eta_ohmic": j * R_total,
            "eta_membrane": j * context["r_membrane_area"],
            "eta_bub_void": j * (R_ohm - R_ohm_clear),
            "util_anode": ra["util"], "util_cathode": rc["util"],
            "R_f": eff["R_f"],
        }
        med = context.get("electrolyte", "KOH")
        c_b = op.c_electrolyte
        fields = {
            "pH_bulk": chemistry.bulk_pH(c_b, T, med),
            "pH_anode": chemistry.local_pH(c_b, j, j_lim, "OER", T, med),
            "pH_cathode": chemistry.local_pH(c_b, j, j_lim, "HER", T, med),
            # depth profiles for the click-to-drill-in view (Track 4)
            "d_mm": rc["d_mm"], "jloc_c": rc["j_loc"], "eta_d_c": rc["eta"],
            "jloc_a": ra["j_loc"], "eta_d_a": ra["eta"],
            "L_e_mm": eff["L_e"] * 1e3, "morph_name": eff["name"],
            "util_c": rc["util"], "util_a": ra["util"],
            "pen_mm_c": rc["pen_mm"], "pen_mm_a": ra["pen_mm"],
            "s_g_c": rc["s_g_max"], "s_g_a": ra["s_g_max"],
            "c_pore_c": rc["c_pore"], "c_pore_a": ra["c_pore"],
            "operating_feasible": bool(j < j_lim_fp),
            "transport_limit_exceeded": bool(j >= j_lim_fp),
            "external_transport_limit_exceeded": bool(
                j >= j_lim_external),
            "pore_transport_exceeded": bool(j >= j_lim_pore),
            "j_requested_A_m2": float(op.j_set) if mode == "CP" else None,
            "j_limit_A_m2": float(j_lim_fp),
            "j_limit_external_A_m2": float(j_lim_external),
            "j_limit_pore_A_m2": float(j_lim_pore),
            "voltage_is_lower_bound": bool(mode == "CP" and j >= j_lim_fp),
            "model_input_valid": bool(context.get("input_range_valid", False)),
            "model_input_issues": list(context.get("input_range_issues", [])),
        }
        return ElectroState(j=j, overpotentials=ov, fields=fields,
                            V=(V if mode == "CP" else None))
