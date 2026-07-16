"""Dissolved-gas source + supersaturation nucleation weighting (Track B).

Bridges the external-surface current mask (current3d) to where bubbles nucleate:
  * each reacting surface voxel evolves gas at the Faradaic rate (kernel
    sources.faradaic_gas_rate — same conversion as every other fidelity),
  * dissolved gas raises the local supersaturation S = c/c_sat (kernel Henry
    saturation), and heterogeneous nucleation favours high-S surface sites,
    weighted by the substrate's nucleation-site multiplier (morphology).

The nucleation weight per surface voxel = local_current * nuc_site_mult, which
combines "more gas where more current" with "more sites on this scaffold". This
sets WHERE the voxel-filling growth (poregrowth) seeds new gas.
"""
import numpy as np

from bubblesim.kernel.sources import faradaic_gas_rate
from bubblesim.kernel.transport import saturation_concentration, supersaturation


def total_gas_rate(total_current_A, electrode, T, P, eta_F=1.0, *, wet=False,
                   water_activity=1.0):
    """Total evolved-gas volume rate [m^3/s] for the imposed current (Faraday +
    ideal gas). area=1 because total_current_A is already the full current."""
    return faradaic_gas_rate(total_current_A, electrode, T, P, area=1.0,
                             eta_F=eta_F, wet=wet,
                             water_activity=water_activity)


def nucleation_weight(surf_current, nuc_site_mult):
    """Per-voxel nucleation preference (>=0), normalised to sum 1 over the
    reacting external surface. High-current, high-site-density voxels seed first."""
    w = np.maximum(0.0, surf_current) * float(nuc_site_mult)
    tot = w.sum()
    return w / tot if tot > 0 else w


def c_sat(P, k_henry):
    """Henry dissolved-gas saturation concentration [mol/m^3]."""
    return saturation_concentration(P, k_henry)


def supersaturation_ratio(c_dissolved, c_sat_val):
    return supersaturation(c_dissolved, c_sat_val)
