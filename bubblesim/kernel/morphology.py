"""Electrode morphology library  ->  effective (homogenized) properties.

The headline goal: model *real* electrodes -- Ni/stainless foam, carbon paper,
mesh -- carrying nanostructured catalysts (nanoparticle/nanowire/nanosphere/
nanoporous), WITHOUT meshing the geometry. Following Newman porous-electrode
theory, a 3-D porous structure is represented by a handful of *effective*
properties on a 1-D depth axis:

    R_f      roughness factor   = real active area / geometric footprint  [-]
    a        specific area      = R_f / L_e                            [m^2/m^3]
    L_e      electrode thickness                                          [m]
    eps_p    matrix porosity (electrolyte-filled void fraction)          [-]
    sigma_s  solid-matrix electronic conductivity                      [S/m]
    sigma_eff= sigma_s (1-eps_p)^1.5   (Bruggeman for the solid)        [S/m]
    tau      tortuosity = eps_p^-0.5   (Bruggeman for the liquid)        [-]

These feed (a) the existing 0-D/1-D solvers via R_f (which already multiplies j0
through the ECSA), and (b) the porous-electrode BVP solver (`solvers/porous.py`)
which resolves the reaction distribution j_loc(d) through the thickness.

Numbers are representative literature values (commented per entry), not fits to
one paper -- the user supplies the intrinsic catalyst j0 separately, so this
library only sets *area* and *transport* geometry, which is where foams and
nanostructures actually act. Everything is a plain function of two dropdown
choices plus an optional catalyst-loading scale, so it is fully controllable.

stdlib only (kernel boundary).
"""

# ----------------------------------------------------------------------------
# Substrates (기재).  geo_rough = internal geometric area / footprint, i.e. how
# much MORE area the bare 3-D scaffold offers than a flat plate of the same
# footprint (dimensionless).  sigma_s = bulk electronic conductivity of the
# strut material.  escape = how easily detached gas leaves the structure
# (1 = open plate, <1 = foam traps bubbles).
# ----------------------------------------------------------------------------
SUBSTRATES = {
    # flat reference: a thin catalyst skin on a solid plate. With R_f~1 and a
    # fully penetrated reaction (L_pen >> L_e), the porous solver collapses to the
    # planar electrode -- i.e. the existing 0-D/1-D behaviour.
    "flat_plate":   dict(name="평판 (flat plate)",     geo_rough=1.0,  L_e=2.0e-5,
                         eps_p=0.0,  sigma_s=1.4e7, escape=1.00, metal="Ni"),
    # Ni foam: ~1.6 mm, ~95% porous, internal area tens x footprint. sigma_Ni=1.43e7 S/m.
    "ni_foam":      dict(name="Ni 폼 (nickel foam)",   geo_rough=30.0, L_e=1.6e-3,
                         eps_p=0.95, sigma_s=1.43e7, escape=0.60, metal="Ni"),
    # 316L stainless foam: similar geometry, ~10x lower sigma (1.35e6 S/m).
    "ss_foam":      dict(name="STS 폼 (stainless foam)", geo_rough=28.0, L_e=1.6e-3,
                         eps_p=0.94, sigma_s=1.35e6, escape=0.60, metal="SS"),
    # Carbon paper (GDL): ~190 um, ~80% porous, through-plane sigma ~7e4 S/m.
    "carbon_paper": dict(name="카본 페이퍼 (GDL)",      geo_rough=8.0,  L_e=1.9e-4,
                         eps_p=0.80, sigma_s=7.0e4,  escape=0.70, metal="C"),
    # Woven Ni mesh: thin, moderately open.
    "ni_mesh":      dict(name="Ni 메쉬 (mesh)",         geo_rough=3.0,  L_e=2.5e-4,
                         eps_p=0.60, sigma_s=1.43e7, escape=0.85, metal="Ni"),
}

# ----------------------------------------------------------------------------
# Catalyst nanostructures (촉매 형상).  r_cat = ECSA of the catalyst coating per
# unit substrate area (dimensionless, scales ~linearly with loading).  j0_mult =
# modest intrinsic-activity shift from faceting/strain (the DOMINANT effect of
# nanostructuring is AREA via r_cat, not intrinsic activity -- kept near 1).
# nuc_mult = nucleation-site enhancement (sharp tips/pores favour gas nuclei).
# C_dl_area = double-layer capacitance per REAL area [F/m^2] (~0.2 typical).
# ----------------------------------------------------------------------------
NANOSTRUCTURES = {
    "planar_film":  dict(name="평막 (planar film)",        r_cat=1.5,   j0_mult=1.00,
                         nuc_mult=1.0, C_dl_area=0.20),
    "nanoparticle": dict(name="나노입자 (nanoparticle)",    r_cat=80.0,  j0_mult=1.10,
                         nuc_mult=2.0, C_dl_area=0.20),
    "nanowire":     dict(name="나노와이어 (nanowire)",       r_cat=120.0, j0_mult=1.15,
                         nuc_mult=2.5, C_dl_area=0.20),
    "nanosphere":   dict(name="나노구 (nanosphere)",        r_cat=90.0,  j0_mult=1.05,
                         nuc_mult=1.8, C_dl_area=0.20),
    "nanoporous":   dict(name="나노다공 (nanoporous/dendritic)", r_cat=300.0, j0_mult=1.20,
                         nuc_mult=2.0, C_dl_area=0.20),
}


def rf_from_bet(specific_area_m2_g, loading_mg_cm2):
    """Roughness factor from a BET specific area and catalyst loading.

        R_f = ECSA/geometric = specific_area [m^2/g] * loading [g per m^2 geometric]
    and 1 mg/cm^2 = 10 g/m^2, so R_f = specific_area * loading_mg_cm2 * 10.
    """
    return max(1.0, float(specific_area_m2_g) * float(loading_mg_cm2) * 10.0)


def rf_from_cdl(cdl_measured_F_m2, cdl_specific_F_m2=0.40):
    """Roughness factor from a measured double-layer capacitance.

        R_f = C_dl(measured) / C_dl(specific)
    with the specific (smooth-surface) capacitance ~0.40 F/m^2 (= 40 uF/cm^2),
    the common ECSA reference for metals/oxides.
    """
    return max(1.0, float(cdl_measured_F_m2) / max(1e-12, float(cdl_specific_F_m2)))


def effective_electrode(substrate="flat_plate", nanostructure="planar_film",
                        cat_loading=1.0, overrides=None):
    """Homogenized effective properties for a (substrate x nanostructure) pair.

    `cat_loading` (>0, 1.0 = nominal) scales the catalyst ECSA linearly -- twice
    the loading, twice the catalyst area (until transport limits bite, which the
    porous solver, not this geometry library, captures).

    `overrides` (dict, optional) replaces preset-derived values with the user's
    MEASURED ones -- any of {R_f, L_e [m], eps_p, sigma_s} -- so a real electrode
    can be entered instead of a library estimate. Dependent quantities (a,
    sigma_eff, tau) are recomputed consistently from whatever values win.

    Reductions (tested):
      flat_plate + planar_film -> R_f ~ 1, eps_p = 0, sigma_eff = sigma_s
        i.e. a planar electrode == the existing 0-D/1-D behaviour.
    """
    sub = SUBSTRATES[substrate]
    nano = NANOSTRUCTURES[nanostructure]
    load = max(1e-3, float(cat_loading))

    # nanostructured catalyst coats ALL of the scaffold's internal area -> the
    # two area enhancements multiply.
    R_f = max(1.0, sub["geo_rough"] * nano["r_cat"] * load)
    L_e = sub["L_e"]
    eps_p = sub["eps_p"]
    sigma_s = sub["sigma_s"]

    ov = overrides or {}
    if ov.get("R_f") is not None:
        R_f = max(1.0, float(ov["R_f"]))
    if ov.get("L_e") is not None:
        L_e = max(1e-7, float(ov["L_e"]))
    if ov.get("eps_p") is not None:
        eps_p = min(0.99, max(0.0, float(ov["eps_p"])))
    if ov.get("sigma_s") is not None:
        sigma_s = max(1.0, float(ov["sigma_s"]))

    a = R_f / L_e                                   # m^2 active / m^3 electrode
    sigma_eff = sigma_s * (1.0 - eps_p) ** 1.5      # Bruggeman, solid phase
    tau = eps_p ** -0.5 if eps_p > 0.0 else 1.0     # Bruggeman, liquid phase

    name = f"{sub['name']} + {nano['name']}"
    if ov:
        name += " (측정값)"
    return {
        "substrate": substrate, "nanostructure": nanostructure,
        "name": name, "overridden": bool(ov),
        "R_f": R_f, "a": a, "L_e": L_e, "eps_p": eps_p, "tau": tau,
        "sigma_s": sigma_s, "sigma_eff": sigma_eff,
        "j0_mult": nano["j0_mult"], "C_dl_area": nano["C_dl_area"],
        "nuc_site_mult": nano["nuc_mult"], "escape_factor": sub["escape"],
        "metal": sub["metal"], "cat_loading": load,
    }


def kappa_eff(kappa, eff):
    """Effective ionic conductivity inside the pores: kappa * eps_p^1.5
    (Bruggeman). This already EQUALS kappa*eps_p/tau with tau=eps_p^-0.5, so one
    must use eps^1.5 OR eps/tau -- not eps^1.5/tau (that double-counted Bruggeman
    and under-predicted pore conductivity)."""
    ep = eff["eps_p"]
    if ep <= 0.0:
        return kappa                                # planar: bulk electrolyte
    return kappa * ep ** 1.5


def penetration_depth(eff, kappa, dj_deta):
    """Analytic reaction penetration depth of a porous electrode [m]:

        L_pen = sqrt( (sigma_eff + kappa_eff) / (a * dj/d_eta * sigma_eff * kappa_eff/(sigma_eff+kappa_eff)) )

    Simplified standard form L_pen = sqrt( sigma_eff*kappa_eff /
    ((sigma_eff+kappa_eff) * a * dj/d_eta) ).  If L_pen >= L_e the whole
    thickness works (high utilization); if L_pen << L_e only a surface skin
    reacts.  Used both as a diagnostic and to sanity-check the BVP solver.
    """
    ke = kappa_eff(kappa, eff)
    se = eff["sigma_eff"]
    denom = (se + ke) * eff["a"] * max(dj_deta, 1e-30)
    if denom <= 0.0:
        return eff["L_e"]
    return (se * ke / denom) ** 0.5


def morphology_warnings(substrate, nanostructure, electrolyte, reaction):
    """Substrate x electrolyte (x reaction) compatibility flags -- same spirit as
    the catalyst warnings: surface the chemistry traps, don't silently allow them.
    """
    w = []
    metal = SUBSTRATES[substrate]["metal"]
    acid = electrolyte == "H2SO4"
    if metal == "SS" and acid:
        w.append("⚠ 스테인리스는 산성/산화 전위에서 부식 — 알칼리(KOH)용")
    if metal == "Ni" and acid:
        w.append("⚠ Ni는 산성에서 용해 — 알칼리 전용 기재")
    if metal == "C" and reaction == "OER":
        w.append("⚠ 카본은 높은 양극 전위(OER)에서 산화/부식 — HER/GDL용")
    return w


def list_presets():
    """(key, korean-label) lists for the two UI dropdowns."""
    return {
        "substrates": [(k, v["name"]) for k, v in SUBSTRATES.items()],
        "nanostructures": [(k, v["name"]) for k, v in NANOSTRUCTURES.items()],
    }
