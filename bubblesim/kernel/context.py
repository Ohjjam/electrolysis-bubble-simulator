"""The property/context bundle — the single frozen interface between the
operating point and every physics consumer.

`build_context(op, params)` evaluates all state-dependent property correlations
and model coefficients into one flat dict. Solvers, the bubble model and the
tests all read from this dict, so its keys are an **interface contract: add
keys, never rename or remove them** (existing consumers and golden tests bind to
`j0`, `tafel_b`, `j_lim_eff`, `kappa`, `sigma`, `d_rho`, ...). New physics phases
append keys (e.g. `j0_anode`, `eta_conc` inputs) without disturbing this set.
"""
from .. import properties as prop
from . import transport, chemistry, watertransport


def build_context(op, params) -> dict:
    """Assemble the property bundle used by the physics for the current state."""
    med = getattr(op, "electrolyte", "KOH")
    hf = getattr(op, "high_fidelity", False)   # Pitzer activity + Gilliam conductivity (KOH)
    # high_fidelity adds the water-vapor (p_sat) and water-activity Nernst terms;
    # both default to the ideal (golden-safe: p_w=0, a_H2O=1 at the 1 bar reference).
    a_H2O = prop.water_activity_koh(op.c_electrolyte) if (hf and med == "KOH") else 1.0
    p_w = prop.saturation_pressure(op.T) if hf else 0.0
    d = {
        "E_rev": prop.reversible_voltage(op.T, op.P, a_H2O=a_H2O, p_w=p_w),
        "kappa": prop.conductivity(med, op.c_electrolyte, op.T, high_fidelity=hf),
        "sigma": prop.surface_tension_med(med, op.T, op.c_electrolyte),
        "rho_l": prop.liquid_density_med(med, op.c_electrolyte),
        "rho_g": prop.gas_density(op.electrode, op.T, op.P),
        "mu": prop.liquid_viscosity_med(med, op.c_electrolyte, op.T),
        "fritz_scale": params.fritz_scale,
        "j0": params.j0,
        "tafel_b": params.tafel_b,
        "j_lim_eff": params.j_lim * (1.0 + params.flow_jlim * op.u_flow),
        "Cd_flow": params.Cd_flow,
        "k_mhd": params.k_mhd,
        "r_min_detach": params.r_min_detach,
    }
    # --- two-electrode (Butler-Volmer) coefficients + series resistances ---
    # (additive keys; the lumped solver ignores them, so golden values are unchanged)
    a, c = params.anode, params.cathode
    # activity-corrected concentration order (a = gamma_pm * c), normalized to the
    # reference concentration (6.0 M = j0_arrhenius c_ref) so defaults are golden-safe.
    act = chemistry.activity_for(op.c_electrolyte, op.T, med, high_fidelity=hf)
    act_ref = chemistry.activity_for(6.0, op.T, med, high_fidelity=hf)
    d["j0_anode"] = prop.j0_arrhenius(a.j0_ref, a.Ea_j0, op.T, op.c_electrolyte,
                                      a.gamma_c, activity=act, activity_ref=act_ref)
    d["j0_cathode"] = prop.j0_arrhenius(c.j0_ref, c.Ea_j0, op.T, op.c_electrolyte,
                                        c.gamma_c, activity=act, activity_ref=act_ref)
    d["alpha_a_anode"], d["alpha_c_anode"] = a.alpha_a, a.alpha_c
    d["alpha_a_cathode"], d["alpha_c_cathode"] = c.alpha_a, c.alpha_c
    d["r_membrane_area"] = params.r_membrane_area
    d["r_contact_area"] = params.r_contact_area

    # --- dry-cathode membrane water transport (add-only; 0 when disabled) ------
    # An anolyte-only AEM cell feeds the cathode through the membrane alone:
    # back-diffusion supplies it, electro-osmotic drag (OH- -> anode) steals from
    # it. Yields a water-supply limiting current; the solver turns it into
    # eta_water. Defaults (op.dry_cathode=False) give 0 -> golden-safe.
    k_w, j_lim_w = watertransport.dry_cathode_terms(
        op, getattr(op, "t_mem_um", 50.0) * 1e-6)
    d["water_permeance"] = k_w                 # [mol/(m^2 s)] membrane ceiling
    d["j_lim_water"] = j_lim_w                 # [A/m^2] 0 = no dry-cathode limit

    # --- mass transport: Sherwood-grounded limiting current + Henry saturation ---
    d["sh_enhancement"] = transport.flow_enhancement(op, d, params)
    d["j_lim_transport"] = params.j_lim * d["sh_enhancement"]
    d["z_primary"] = prop.GAS[op.electrode]["z"]
    d["c_sat_gas"] = transport.saturation_concentration(op.P, params.k_henry)
    d["k_vogt"] = params.k_vogt            # bubble self-stirring (applied in-solver, j-dependent)
    d["j_ref_vogt"] = params.j_ref_vogt

    # --- electrolyte chemistry (bulk; surface pH is current-dependent, set in solver) ---
    d["electrolyte"] = med
    d["ionic_strength"] = chemistry.ionic_strength(op.c_electrolyte, med)
    d["activity_coeff"] = chemistry.activity_for(op.c_electrolyte, op.T, med, high_fidelity=hf)
    d["pH_bulk"] = chemistry.bulk_pH(op.c_electrolyte, op.T, med)
    d["t_carrier"] = prop.ELECTROLYTES[med]["t_carrier"]
    # (coalescence threshold is read straight from ELECTROLYTES where needed —
    #  population.coalesce / server — so no context key for it, avoiding a dangling node)
    # carrier-ion diffusivity rises with T (Stokes-Einstein D ~ T/mu); the old
    # fixed D_reactant made j_lim/delta temperature-independent. At 298.15 K this
    # is exactly params.D_reactant. (Used by the 1D solver's derived j_lim.)
    d["D_carrier"] = params.D_reactant * (op.T / 298.15) * (
        prop.liquid_viscosity_med(med, op.c_electrolyte, 298.15) / max(d["mu"], 1e-9))
    # Nernst diffusion-layer thickness delta = L_char / Sh. The no-flow floor is
    # the larger of the fixed sh0 and the buoyancy-driven free-convection Sherwood
    # (representative density deficit ~2%); forced flow raises it via sh_enhancement.
    nu = d["mu"] / max(d["rho_l"], 1e-9)
    Sc = nu / max(d["D_carrier"], 1e-12)
    sh_nat = transport.natural_convection_sherwood(0.02, params.L_char, nu, Sc)
    d["delta_bl"] = params.L_char / max(params.sh0 * d["sh_enhancement"], sh_nat)

    # --- geometry the solvers need for void-resistance partitioning ---
    d["gap_m"] = op.gap_mm * 1e-3
    d["near_layer_m"] = params.near_layer

    d["d_rho"] = d["rho_l"] - d["rho_g"]
    return d
