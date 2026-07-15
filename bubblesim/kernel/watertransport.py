"""Membrane water transport for a DRY-CATHODE (anolyte-only) AEM cell.

The cell this models: liquid KOH anolyte is pumped past the ANODE only; the
cathode compartment is fed no liquid ("dry cathode"). HER still needs water --

    cathode:  2 H2O + 2 e-  ->  H2 + 2 OH-        (consumes 1 H2O per electron)
    anode:    4 OH-         ->  O2 + 2 H2O + 4 e- (makes 0.5 H2O per electron)

so every electron that crosses must be paid for with a water molecule that
reached the cathode THROUGH the membrane. Two membrane fluxes compete:

1. ELECTRO-OSMOTIC DRAG (a LOSS for the cathode).  In an AEM the charge carrier
   is OH-, which travels cathode -> anode, and each ion drags `n_drag` water
   molecules along with it. The OH- flux equals j/F (z = 1), so the drag flux is

       N_eod = n_drag * j / F              [mol H2O / m^2 / s]   cathode -> anode

   (This is the sign trap: in a PEM, H+ moves anode -> cathode and drag FEEDS
   the cathode. In an AEM it STARVES it -- drag and consumption add up.)

2. BACK-DIFFUSION (the SUPPLY).  The anode side is flooded and the cathode side
   is dry, so water diffuses down that activity gradient, anode -> cathode:

       N_diff <= D_w * c_w / t_mem = k_w   [mol H2O / m^2 / s]

   k_w is the ceiling, reached when the cathode-side water activity is driven to
   zero. (Hydraulic permeation from a pressure difference is neglected --
   balanced-pressure operation.)

Steady state at the cathode:  N_diff = (1 + n_drag) * j / F.  The membrane can
only deliver k_w, so there is a WATER-SUPPLY LIMITING CURRENT

       j_lim_water = F * k_w / (1 + n_drag)                      [A/m^2]

and below it the cathode-side water activity falls to a_w = 1 - j/j_lim_water.
HER is first order in water, so that activity loss costs a Nernst-like
overpotential of exactly the mass-transport form the rest of the kernel uses
(one H2O per electron -> z = 1):

       eta_water = -(RT / F) * ln(1 - j / j_lim_water)

HONEST SCOPE: a reduced-order (single lumped permeance) treatment. It does NOT
resolve the water-content profile lambda(x) through the membrane, membrane
dry-out hysteresis, or the change in membrane conductivity as it dries -- all of
which make a real dry cathode worse, not better, so this term is a LOWER bound
on the dry-cathode penalty. Defaults leave it OFF (`Operating.dry_cathode`), so
every existing result is bit-identical.
"""
import math

from ..constants import F, R_GAS

# Defaults are order-of-magnitude engineering values for a hydrated AEM, chosen
# BEFORE looking at any dry-cathode data (same blind rule as kernel.meshlayer).
# They are exposed as sliders -- treat them as knobs, not measurements.
N_DRAG_DEFAULT = 2.5      # [mol H2O / mol OH-] AEM electro-osmotic drag; the
                          # literature spread is wide (~1-5, rises with hydration)
D_W_DEFAULT = 1.0e-9      # [m^2/s] water diffusivity inside a hydrated ionomer
C_W_MEM = 4.0e4           # [mol/m^3] water concentration in a hydrated membrane
                          # (~40 M vs 55.5 M for bulk water)


def water_permeance(t_mem_m, D_w=D_W_DEFAULT, c_w=C_W_MEM):
    """Max diffusive water flux the membrane can deliver, k_w [mol/(m^2 s)].

    k_w = D_w * c_w / t_mem  -- the flux at the largest possible driving force
    (cathode-side water activity driven to zero). Thinner membrane -> more water
    gets through, which is one real reason thin AEMs tolerate dry cathodes.
    """
    t = max(1e-7, float(t_mem_m))
    return max(0.0, float(D_w)) * max(0.0, float(c_w)) / t


def water_limiting_current(k_w, n_drag=N_DRAG_DEFAULT):
    """Water-supply limiting current density [A/m^2].

        j_lim_water = F * k_w / (1 + n_drag)

    The (1 + n_drag) is the whole story: the cathode must be supplied not only
    with the water HER consumes (1 per electron) but also with the water the
    OH- current drags AWAY from it (n_drag per electron).
    """
    return F * max(0.0, float(k_w)) / (1.0 + max(0.0, float(n_drag)))


def water_activity_cathode(j, j_lim_water):
    """Cathode-side water activity a_w = 1 - j/j_lim_water, clamped to (0, 1]."""
    if j_lim_water <= 0.0:
        return 1e-9
    return max(1e-9, 1.0 - float(j) / float(j_lim_water))


ETA_SAT = -math.log(1e-9)      # the clamp's saturation factor (~20.7)


def eta_water(j, j_lim_water, T):
    """Dry-cathode water-starvation overpotential [V] (>= 0).

    Same mass-transport form the rest of the kernel uses, with z = 1 because HER
    consumes exactly one H2O per electron. Saturates (does not diverge) at the
    limit; the caller clamps j.

    j_lim_water <= 0 means the membrane passes NO water, i.e. total starvation —
    so it must return the SATURATED penalty, not zero. (Returning 0 here made the
    worst possible membrane look identical to a wet cell: the D_w -> 0 limit ran
    the model backwards. "Feature is off" is the CALLER's business — it must not
    be encoded as a zero limit.)
    """
    if j <= 0.0:
        return 0.0
    if j_lim_water <= 0.0:
        return (R_GAS * float(T)) / F * ETA_SAT
    x = min(1.0 - 1e-9, float(j) / float(j_lim_water))
    return -(R_GAS * float(T)) / F * math.log(1.0 - x)


def dry_cathode_terms(op, t_mem_m):
    """(k_w, j_lim_water) for this operating point, or (0, 0) when disabled."""
    if not getattr(op, "dry_cathode", False):
        return 0.0, 0.0
    k_w = water_permeance(t_mem_m,
                          D_w=getattr(op, "D_w_mem", D_W_DEFAULT),
                          c_w=getattr(op, "c_w_mem", C_W_MEM))
    return k_w, water_limiting_current(k_w, getattr(op, "n_drag", N_DRAG_DEFAULT))
