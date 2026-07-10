"""Configuration objects: the user-facing *levers* and the internal model knobs.

`Operating` holds everything a user would turn on a real cell (the things the
simulator is meant to explore). `Params` holds model coefficients / numerics
that you calibrate once against data and then mostly leave alone.
"""
from dataclasses import dataclass, field


@dataclass
class Operating:
    """Operating levers — the knobs to explore for bubble control."""
    mode: str = "CA"             # "CA" = potentiostatic (fix V, j responds) |
                                 # "CP" = galvanostatic (fix j, V responds; commercial standard)
    V_cell: float = 2.0          # applied cell voltage [V]            (used in CA mode)
    j_set: float = 2000.0        # set current density [A/m^2]         (used in CP mode)
    electrode: str = "HER"       # primary electrode in single-patch mode ("HER" or "OER")
    electrolyte: str = "KOH"     # "KOH" (alkaline) | "H2SO4" (acid) | "PB" (phosphate buffer)
    c_electrolyte: float = 6.0   # electrolyte concentration [mol/L]
    T: float = 333.15            # temperature [K]  (~60 degC)
    P: float = 1.0e5             # pressure [Pa]
    contact_angle: float = 60.0  # wettability: gas-side contact angle [deg]
    u_flow: float = 0.0          # tangential cross-flow velocity [m/s]
    B_field: float = 0.0         # magnetic flux density [T]  (MHD convection)
    E_ext: float = 0.0           # near-surface field magnitude for DEP [V/m]
    A_cm2: float = 1.0           # total electrode geometric area [cm^2]
    gap_mm: float = 2.0          # electrode-to-membrane gap [mm]
    model: str = "lumped"        # fidelity: "lumped" (one Tafel) or "two_electrode" (Butler-Volmer)
    track_both: bool = False     # track bubbles on both electrodes (else counter = ideal, bubble-free)
    thermal: bool = False        # evolve T as a state via the energy balance (else T is fixed)
    nucleation: str = "empirical"  # "empirical" (rate ~ j) | "supersaturation" (CNT-lite, S-driven)
    # --- porous-electrode morphology (used only when model="porous") ---
    # flat_plate + planar_film reduces porous back to a planar electrode.
    substrate: str = "ni_foam"        # kernel.morphology.SUBSTRATES key
    nanostructure: str = "nanoparticle"  # kernel.morphology.NANOSTRUCTURES key
    cat_loading: float = 1.0          # catalyst loading scale (>0, 1 = nominal)
    # measured-area / structure overrides (porous; None = use morphology preset)
    rf_override: "float | None" = None        # roughness factor (ECSA) [-]
    Le_override_mm: "float | None" = None      # electrode thickness [mm]
    eps_override: "float | None" = None        # porosity [-]
    sigma_override: "float | None" = None      # matrix conductivity [S/m]
    face_height_cm: float = 10.0      # electrode height for the 2D face-field map [cm]
    high_fidelity: bool = False       # KOH: Pitzer activity + Gilliam conductivity (quantitative)
    gas_feedback: bool = False        # porous: internal gas saturation s_g(d) blocks area·kappa
    # flow-channel cell design (model="channel")
    channel_type: str = "serpentine"  # "serpentine" | "parallel" | "straight"
    n_pass: int = 4                   # serpentine passes / parallel channel count
    cell_width_cm: float = 5.0        # electrode width [cm] (serpentine run length)
    drill_inlet_gas: float = 0.0      # flow2d: upstream gas entering the inlet (set when drilling a channel region)
    custom_path: "list | None" = None # user-drawn flow channel [[x,y],...] in [0,1] cell coords (design tool)
    chan_depth_mm: float = 1.0        # channel depth [mm] (channel model; 1.0 = legacy D_CHAN)
    channel_void_ohmic: bool = False  # channel: feed path-mean void into the scalar solve
                                      # (bulk gas raises electrolyte R; off = legacy behaviour)
    void_ohmic_frac: float = 1.0      # fraction of the electrolyte path the channel void
                                      # actually obstructs (zero-gap MEA: gas sits BEHIND the
                                      # electrode -> only the porous-electrode/film part, <<1;
                                      # gap cells: ~1). Calibrate on the baseline cell.
    # --- bubble-management mesh interlayer on the anode face (kernel.meshlayer) ---
    # A hydrophobic (aerophilic) mesh laid on the electrode inside the channel.
    # t=0 disables everything (legacy behaviour, bit-identical).
    mesh_hole_mm: float = 0.0         # mesh opening size [mm] (0 = no mesh)
    mesh_open: float = 1.0            # open-area fraction phi [0..1]
    mesh_t_mm: float = 0.0            # mesh thickness [mm] (0 = no mesh)
    mesh_cover: float = 0.0           # fraction of the flow path covered [0..1] (1 = full)
    mesh_pos: str = "outlet"          # partial-cover anchor: "inlet" | "middle" | "outlet"


@dataclass
class ElectrodeParams:
    """Per-electrode Butler-Volmer kinetics (used by the two-electrode fidelity).

    The transfer coefficient is REACTION-SPECIFIC and sets the Tafel slope
    b = 2.303 RT/(alpha F): a low-Tafel-slope catalyst (e.g. NiFe-LDH OER,
    ~40-60 mV/dec) has alpha ~ 1.0-1.5, while a 120 mV/dec reaction (Ni HER) has
    alpha ~ 0.5. The defaults (set on Params.anode/cathode) represent an alkaline
    Ni (HER) / NiFe-LDH (OER) pair in KOH; recalibrate against a measured curve.
    """
    reaction: str = "HER"        # "HER" (cathode, reduction) or "OER" (anode, oxidation)
    j0_ref: float = 1.0          # exchange current density at (T_ref, c_ref) [A/m^2]
    alpha_a: float = 0.5         # anodic transfer coefficient [-]   (b_a = 2.303RT/alpha_a F)
    alpha_c: float = 0.5         # cathodic transfer coefficient [-] (b_c = 2.303RT/alpha_c F)
    Ea_j0: float = 30.0e3        # activation energy for the j0 Arrhenius term [J/mol]
    gamma_c: float = 0.5         # reaction order of j0 on electrolyte concentration [-]
    C_dl: float = 0.2            # double-layer capacitance, geometric [F/m^2] (~20 uF/cm^2;
                                 # scales with ECSA roughness on real electrodes)


@dataclass
class Params:
    """Model coefficients and numerics (calibrate against data, then leave)."""
    # --- lumped electrode kinetics (both half-reactions folded into one Tafel) ---
    fritz_scale: float = 1.0     # calibration factor on the Fritz departure radius [-]
    j0: float = 1.0              # exchange current density [A/m^2]
    tafel_b: float = 0.15        # decadic Tafel slope [V/decade]
    j_lim: float = 4.0e4         # mass-transport limiting current density [A/m^2]
    flow_jlim: float = 1.5       # fractional rise of j_lim per (m/s) of flow [s/m]
    eta_faraday: float = 1.0     # Faradaic (current) efficiency [-]: gas = eta_F * I/(zF)
                                 # (1.0 = ideal; real cells ~0.9-0.99 w/ crossover)

    # --- two-electrode kinetics (Butler-Volmer) + series resistances ---
    # alkaline NiMo (HER) / NiFe (OER) pair, CALIBRATED to the AHEAD measured I-V
    # (Zhang et al., Sci. Adv. 2026; 30 wt% KOH, 80 C, zero-gap): these j0 + r_membrane
    # reproduce the serpentine polarization curve (~0.785 A/cm^2 @ 2.0 V; ~1.08 @ 2.05 V)
    # across 1.6-2.1 V, with eta_OER (~0.65 V) >> eta_HER (~0.12 V) -- OER is the
    # kinetic bottleneck, NiMo HER fast (textbook). NOTE: j0_OER is an APPARENT
    # full-cell value (lower than intrinsic NiFe ~1e-4) that folds the cell's total
    # non-ohmic loss into the OER branch given AHEAD's low measured R_s.
    anode: "ElectrodeParams" = field(
        default_factory=lambda: ElectrodeParams("OER", j0_ref=1.3e-7, alpha_a=1.0, Ea_j0=50.0e3))
    cathode: "ElectrodeParams" = field(
        default_factory=lambda: ElectrodeParams("HER", j0_ref=130.0, Ea_j0=30.0e3))
    r_membrane_area: float = 3.2e-6  # area-specific membrane/separator R [ohm*m^2]
                                     # (~0.032 ohm*cm^2 = AHEAD EIS R_s; 0 was unphysical)
    r_contact_area: float = 0.0      # area-specific electrode + contact (electronic) R [ohm*m^2]

    # --- mass transport (boundary layer -> limiting current, conc. overpotential) ---
    D_reactant: float = 1.0e-9    # effective reactant diffusivity [m^2/s]
    L_char: float = 5.0e-3        # characteristic convection length [m] (~electrode height)
    sh0: float = 25.0             # no-flow Sherwood floor [-]: natural convection +
                                  # bubble micro-convection (~0.67 Ra^1/4 at L~5mm)
                                  # -> stagnant diffusion layer ~ L_char/sh0 ~ 200 um
    sh_coeff: float = 0.664       # laminar flat-plate forced convection, Sh = 0.664 Re^1/2 Sc^1/3
    k_henry: float = 7.7e4        # Henry constant for dissolved gas [Pa*m^3/mol] (~H2 in water)
    k_vogt: float = 0.6           # bubble self-stirring (Vogt) j_lim enhancement coeff [-] (0=off)
    j_ref_vogt: float = 1.0e4     # reference j for Vogt scaling [A/m^2] (~1 A/cm^2)

    # --- energy balance (T becomes a dynamic state when Operating.thermal=True) ---
    thermal_mass: float = 50.0    # lumped cell heat capacity C [J/K]
    hA_cool: float = 0.5          # cooling coefficient x area, hA [W/K]
    T_ambient: float = 298.15     # coolant / ambient temperature [K]

    # --- simulated representative electrode patch ---
    patch_w: float = 6.0e-3      # patch width  [m]
    patch_h: float = 5.0e-3      # patch height [m]  (buoyancy is +y)
    near_layer: float = 1.0e-3   # near-electrode layer thickness for void fraction [m]

    # --- nucleation ---
    site_density: float = 2.0e6  # base nucleation-site density [1/m^2]
    r_nuc: float = 5.0e-6        # seed (critical) radius [m]
    k_nuc: float = 40.0          # nucleation rate per free site at j_ref [1/s]
    j_ref: float = 3.0e3         # reference current density for nucleation scaling [A/m^2]
    f_to_bubble: float = 0.75    # fraction of evolved gas captured by attached bubbles [-]
    B_nuc: float = 12.0          # CNT-lite nucleation barrier: rate ~ exp(-B_nuc/ln(S)^2) [-]
                                 # onset at ln(S)^2 ~ B_nuc -> S ~ 30 (heterogeneous H2/O2
                                 # nucleation needs S ~ tens-to-hundreds, not S~5)
    k_nuc_ss: float = 60.0       # supersaturation-mode nucleation prefactor per free site [1/s]
                                 # (~matches empirical rate at S~10; sub-saturating regime)

    # --- detachment force coefficients ---
    Cd_flow: float = 1.2         # drag coefficient for flow-assisted detachment [-]
    k_mhd: float = 2.0e-5        # MHD convection velocity per (j*B) [m/s / (A/m^2 * T)]
    r_min_detach: float = 8.0e-6 # floor on departure radius [m]
    detach_spread: float = 0.3   # +/- fractional spread of per-bubble departure size [-]

    # --- coalescence ---
    c_coalesce_crit: float = 0.3 # electrolyte conc above which coalescence is inhibited [mol/L]
    p_merge_inhibited: float = 0.05  # residual merge probability when inhibited [-]
    p_merge_free: float = 0.9        # merge probability when not inhibited [-]
