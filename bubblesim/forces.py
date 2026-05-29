"""Detachment physics: the effective departure radius of an attached bubble.

A bubble lets go when the *detaching* forces (buoyancy + flow drag + electric
DEP + MHD-driven shear) overcome the surface-tension adhesion that pins its
contact line. We anchor on the classic Fritz (1935) departure diameter for the
quiescent, field-free case and then let the extra forces shrink the departure
radius via a buoyancy-equivalent force balance.
"""
import math

from .constants import G, EPS0
from . import properties as prop


def fritz_radius(sigma, d_rho, contact_angle_deg):
    """Fritz (1935) departure radius for a quiescent bubble [m].

        d_d = 0.0208 * beta[deg] * sqrt(sigma / (g * d_rho)),   r_d = d_d / 2

    Wettability enters directly through the contact angle beta: a more
    hydrophobic surface (large beta) pins larger bubbles before they leave.
    """
    d_d = 0.0208 * contact_angle_deg * math.sqrt(sigma / (G * d_rho))
    return 0.5 * d_d


def departure_radius(op, props, j):
    """Effective departure radius [m] including flow, DEP and MHD assistance.

    A bubble of radius r feels detaching forces
        buoyancy : F_b(r) = (4/3) pi d_rho g r^3        ~ r^3
        flow drag: F_d(r) = 1/2 Cd rho_l u_eff^2 pi r^2 ~ r^2
        neg-DEP  : F_E(r) = 2 pi eps0 eps_l |K| E^2 r^2  ~ r^2   (pushes off electrode)
    and is pinned by a surface-tension adhesion calibrated so that, with no flow
    or field, it leaves exactly at the Fritz radius:  F_adh = F_b(r_d0).
    The departure radius is the r that satisfies F_b(r)+F_d(r)+F_E(r) = F_adh,
    solved on (r_min, r_d0]. Stronger detaching forces -> smaller r_d -> more
    frequent departure. Solving the balance self-consistently (rather than at a
    fixed reference radius) makes r_d vary smoothly with the levers.
    """
    sigma = props["sigma"]
    d_rho = props["d_rho"]
    rho_l = props["rho_l"]

    r_d0 = fritz_radius(sigma, d_rho, op.contact_angle) * props.get("fritz_scale", 1.0)
    buoy_coeff = (4.0 / 3.0) * math.pi * d_rho * G          # F_b = buoy_coeff * r^3
    adhesion = buoy_coeff * r_d0 ** 3                       # pinning force (Fritz-calibrated)

    # MHD: Lorentz body force j x B stirs the electrolyte -> extra shear velocity
    u_eff = op.u_flow + props["k_mhd"] * j * op.B_field
    c_drag = 0.5 * props["Cd_flow"] * rho_l * u_eff * u_eff * math.pi   # F_d = c_drag * r^2

    # negative dielectrophoresis (gas bubble, |K| ~ 0.49): F_E = c_dep * r^2
    K = abs((1.0 - prop.EPS_WATER) / (1.0 + 2.0 * prop.EPS_WATER))
    c_dep = 2.0 * math.pi * EPS0 * prop.EPS_WATER * K * op.E_ext * op.E_ext

    c2 = c_drag + c_dep
    r_min = props["r_min_detach"]

    def detaching(r):
        return buoy_coeff * r ** 3 + c2 * r * r

    if detaching(r_min) >= adhesion:
        return r_min
    lo, hi = r_min, r_d0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if detaching(mid) > adhesion:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
