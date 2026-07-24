"""1D gap solver: the two-electrode cell with z-resolved physics (Phase 5).

What the extra dimension buys over the 0D two-electrode solver:

  * ohmic drop      — the void profile eps(z) (projected from the actual
                      Lagrangian bubbles) enters a layer-resolved Bruggeman
                      resistance  R = sum dz / (kappa (1-eps_k)^1.5)  instead of
                      a single scalar eps.
  * mass transport  — each electrode gets a Nernst diffusion layer of thickness
                      delta = min(L_char/Sh, 0.8 L_side); the carrier-ion
                      limiting current is *derived*  j_lim = F D c / (delta (1-t))
                      (migration relief via the transference number), not a
                      Params knob. eta_conc per electrode is the exact Nernstian
                      (RT/F) ln(c_b/c_s) with c_s from the linear profile.
  * observables     — phi(z), c(z)/c_b and eps(z) profiles are returned in
                      ElectroState.fields for plotting.

Kinetics (Butler-Volmer inversion) and CP/CA logic are shared with the 0D
solver — the kernel split doing its job. In 1D steady state the potential
"PDE" collapses to current continuity (i(z) = j = const), so the ohmic field is
an integral, not a linear solve; numpy keeps the per-step cost trivial.
"""
import math

import numpy as np

from .base import ElectroState
from .zerod import _invert_bv
from ..constants import F, R_GAS
from ..kernel import chemistry
from ..kernel.coupling import void_profile
from ..kernel.transport import vogt_enhancement, vogt_limit
from ..kernel._solve import bisect


class OneDGapSolver:
    """Two-electrode cell with z-resolved void, ohmic and diffusion-layer physics."""

    def __init__(self, n_cells=48, n_inner=40):
        self.n = n_cells
        self.n_inner = n_inner

    # ----------------------------------------------------------- per-side pieces
    def _side(self, op, context, surf, L_side, z_side=2):
        """Resolve one electrode side: eps(z), layer resistances, diffusion layer.

        The Nernst layer is thinned per electrode by gas-evolution micro-convection:
        HER (z=2) evolves 2x the gas VOLUME per charge of OER (z=4), so its layer
        is thinner and its limiting current higher (Vogt/Janssen-Hoogland)."""
        eps = np.array(void_profile(surf.bubbles, L_side, self.n, surf.A_patch))
        dz = L_side / self.n
        r_layers = dz / (context["kappa"] * (1.0 - eps) ** 1.5)
        gas_evo = 1.0 + 0.5 * (2.0 / z_side)              # HER -> 1.5, OER -> 1.25
        delta = min(context["delta_bl"] / gas_evo, 0.8 * L_side)
        c_m3 = op.c_electrolyte * 1000.0                  # mol/L -> mol/m^3
        j_lim = F * context["D_carrier"] * c_m3 / (delta * (1.0 - context["t_carrier"]))
        return eps, r_layers, float(r_layers.sum()), delta, j_lim

    # ------------------------------------------------------------------- solve
    def solve(self, op, context, surfaces) -> ElectroState:
        dual = op.track_both and len(surfaces) > 1
        L_side = 0.5 * context["gap_m"] if dual else context["gap_m"]

        z_c = 2 if dual else context["z_primary"]        # surfaces[0]: HER in dual, else primary
        eps_c, rl_c, Rc, delta_c, jlim_c = self._side(op, context, surfaces[0], L_side, z_c)
        if dual:
            eps_a, rl_a, Ra, delta_a, jlim_a = self._side(op, context, surfaces[1], L_side, 4)
        else:
            # single-patch mode: surfaces[0]'s profile spans the whole gap and the
            # counter side is ideal (bubble-free, depletion-free). j_lim -> inf so
            # it contributes ZERO concentration overpotential (using jlim_c here
            # double-counted eta_conc and reported a phantom counter-electrode pH).
            eps_a, rl_a, Ra, delta_a, jlim_a = np.zeros(self.n), None, 0.0, delta_c, float("inf")
        R_ohm = Rc + Ra
        R_total = R_ohm + context["r_membrane_area"] + context["r_contact_area"]
        j_lim_base = min(jlim_c, jlim_a)
        k_vogt, j_ref_v = context["k_vogt"], context["j_ref_vogt"]

        def vg(jj):     # bubble self-stirring (Vogt) limiting-current enhancement
            return vogt_enhancement(jj, j_ref_v, k_vogt)

        theta_c = surfaces[0].coverage()
        theta_a = surfaces[1].coverage() if dual else 0.0
        if not dual and op.electrode == "OER":
            theta_a, theta_c = theta_c, 0.0
        omt_c = max(1e-3, 1.0 - theta_c)
        omt_a = max(1e-3, 1.0 - theta_a)

        E_cell = context["E_rev"]
        T = op.T
        j0_a, j0_c = context["j0_anode"], context["j0_cathode"]
        aa_a, ac_a = context["alpha_a_anode"], context["alpha_c_anode"]
        aa_c, ac_c = context["alpha_a_cathode"], context["alpha_c_cathode"]
        fRT = R_GAS * T / F

        def eta_conc_of(j):
            # exact Nernstian; Vogt enhances each side's limit at this current
            f_v = vg(j)
            s_c = max(1e-9, 1.0 - j / (jlim_c * f_v))
            s_a = max(1e-9, 1.0 - j / (jlim_a * f_v))
            return -fRT * (math.log(s_c) + math.log(s_a))

        def eta_acts(j):
            return (_invert_bv(j / omt_a, j0_a, aa_a, ac_a, T, n=self.n_inner),
                    # HER is cathodic. In positive-magnitude form the growing
                    # exponential is governed by alpha_c, exactly as in 0D.
                    _invert_bv(j / omt_c, j0_c, ac_c, aa_c, T, n=self.n_inner))

        j_lim_fp = vogt_limit(j_lim_base, j_ref_v, k_vogt)   # self-consistent ceiling
        mode = getattr(op, "mode", "CA")
        if mode == "CP":
            j = max(0.0, op.j_set)
        else:
            drive = op.V_cell - E_cell
            if drive <= 0.0:
                j = 0.0
            else:
                def f(j):
                    ea, ec = eta_acts(j)
                    return E_cell + ea + ec + eta_conc_of(j) + j * R_total - op.V_cell
                hi = 0.995 * j_lim_fp     # exact ceiling: bisect can't return above it
                j = hi if f(hi) < 0.0 else bisect(f, 0.0, hi, 60)

        eta_a, eta_c = eta_acts(j)
        eta_conc = eta_conc_of(j)
        V_cp = E_cell + eta_a + eta_c + eta_conc + j * R_total
        # Vogt-enhanced limits at the operating current (for profiles / pH / report)
        f_v = vg(j)
        jlim_c, jlim_a, j_lim = jlim_c * f_v, jlim_a * f_v, j_lim_base * f_v

        # ------------------------------------------------------------- profiles
        z = (np.arange(self.n) + 0.5) * (L_side / self.n)
        c_ratio_c = 1.0 - (j / jlim_c) * np.clip((delta_c - z) / delta_c, 0.0, 1.0)
        phi_c = -j * np.cumsum(rl_c)                      # potential drop into the gap
        primary_oer = bool(not dual and op.electrode == "OER")
        fields = {
            "z_mm": (z * 1e3).tolist(),
            "delta_mm": delta_c * 1e3,
            "j_lim_1d": j_lim,
            "profile_electrode": ("both" if dual else op.electrode),
        }
        if primary_oer:
            # The single supplied surface is the anode.  Earlier code solved the
            # right profile but stored it in cathode-labelled fields.
            fields["eps_a"] = eps_c.tolist()
            fields["c_a"] = c_ratio_c.tolist()
            fields["phi_a"] = (-phi_c).tolist()
        else:
            fields["eps_c"] = eps_c.tolist()
            fields["c_c"] = c_ratio_c.tolist()
            fields["phi_c"] = phi_c.tolist()
        if dual:
            c_ratio_a = 1.0 - (j / jlim_a) * np.clip((delta_a - z) / delta_a, 0.0, 1.0)
            fields["eps_a"] = eps_a.tolist()
            fields["c_a"] = c_ratio_a.tolist()

        med = context.get("electrolyte", "KOH")
        c_b = op.c_electrolyte
        jlim_a_report = jlim_c if primary_oer else jlim_a
        jlim_c_report = float("inf") if primary_oer else jlim_c
        fields.update({
            "pH_bulk": chemistry.bulk_pH(c_b, T, med),
            "pH_anode": chemistry.local_pH(c_b, j, jlim_a_report, "OER", T, med),
            "pH_cathode": chemistry.local_pH(c_b, j, jlim_c_report, "HER", T, med),
            "operating_feasible": bool(mode != "CP" or j < j_lim_fp),
            "transport_limit_exceeded": bool(mode == "CP" and j >= j_lim_fp),
            "j_requested_A_m2": float(op.j_set) if mode == "CP" else None,
            "j_limit_A_m2": float(j_lim_fp),
            "voltage_is_lower_bound": bool(mode == "CP" and j >= j_lim_fp),
            "model_input_valid": bool(context.get("input_range_valid", False)),
            "model_input_issues": list(context.get("input_range_issues", [])),
        })

        ov = {
            "E_rev": E_cell,
            "eta_act": eta_a + eta_c,
            "eta_act_anode": eta_a,
            "eta_act_cathode": eta_c,
            "eta_conc": eta_conc,
            "eta_ohmic": j * R_total,
            "eta_membrane": j * context["r_membrane_area"],
            "eta_bub_cov_anode": (fRT / aa_a) * math.log(1.0 / omt_a),
            "eta_bub_cov_cathode": (fRT / ac_c) * math.log(1.0 / omt_c),
            "eta_bub_void": j * (R_ohm - context["gap_m"] / context["kappa"]),
        }
        return ElectroState(j=j, overpotentials=ov, fields=fields,
                            V=(V_cp if mode == "CP" else None))
