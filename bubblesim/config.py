"""Configuration objects: the user-facing *levers* and the internal model knobs.

`Operating` holds everything a user would turn on a real cell (the things the
simulator is meant to explore). `Params` holds model coefficients / numerics
that you calibrate once against data and then mostly leave alone.
"""
from dataclasses import dataclass


@dataclass
class Operating:
    """Operating levers — the knobs to explore for bubble control."""
    V_cell: float = 2.0          # applied cell voltage [V]
    electrode: str = "HER"       # "HER" (cathode, H2, z=2) or "OER" (anode, O2, z=4)
    c_electrolyte: float = 6.0   # KOH concentration [mol/L]
    T: float = 333.15            # temperature [K]  (~60 degC)
    P: float = 1.0e5             # pressure [Pa]
    contact_angle: float = 60.0  # wettability: gas-side contact angle [deg]
    u_flow: float = 0.0          # tangential cross-flow velocity [m/s]
    B_field: float = 0.0         # magnetic flux density [T]  (MHD convection)
    E_ext: float = 0.0           # near-surface field magnitude for DEP [V/m]
    A_cm2: float = 1.0           # total electrode geometric area [cm^2]
    gap_mm: float = 2.0          # electrode-to-membrane gap [mm]


@dataclass
class Params:
    """Model coefficients and numerics (calibrate against data, then leave)."""
    # --- lumped electrode kinetics (both half-reactions folded into one Tafel) ---
    fritz_scale: float = 1.0     # calibration factor on the Fritz departure radius [-]
    j0: float = 1.0              # exchange current density [A/m^2]
    tafel_b: float = 0.15        # decadic Tafel slope [V/decade]
    j_lim: float = 4.0e4         # mass-transport limiting current density [A/m^2]
    flow_jlim: float = 1.5       # fractional rise of j_lim per (m/s) of flow [s/m]

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

    # --- detachment force coefficients ---
    Cd_flow: float = 1.2         # drag coefficient for flow-assisted detachment [-]
    k_mhd: float = 2.0e-5        # MHD convection velocity per (j*B) [m/s / (A/m^2 * T)]
    r_min_detach: float = 8.0e-6 # floor on departure radius [m]
    detach_spread: float = 0.3   # +/- fractional spread of per-bubble departure size [-]

    # --- coalescence ---
    c_coalesce_crit: float = 0.3 # electrolyte conc above which coalescence is inhibited [mol/L]
    p_merge_inhibited: float = 0.05  # residual merge probability when inhibited [-]
    p_merge_free: float = 0.9        # merge probability when not inhibited [-]
