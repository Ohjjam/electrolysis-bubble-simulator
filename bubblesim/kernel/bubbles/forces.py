"""Detachment physics: the effective departure radius of an attached bubble.

A bubble lets go when the *detaching* forces (buoyancy + flow drag + electric
DEP + MHD-driven shear) overcome the surface-tension adhesion that pins its
contact line. We anchor on the classic Fritz (1935) departure diameter for the
quiescent, field-free case and then let the extra forces shrink the departure
radius via a buoyancy-equivalent force balance.
"""
import math

from ...constants import G, EPS0
from ... import properties as prop


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
    # surface-tension adhesion acts along the contact line: F_adh = A_adh * r
    # (proportional to the footprint radius and sigma; Oguz & Prosperetti 1993,
    # Duhar & Colin 2006), NOT a frozen Fritz-radius constant. A_adh is calibrated
    # so the field-free balance still departs at the Fritz radius (buoy r^3 = A r).
    A_adh = buoy_coeff * r_d0 * r_d0

    # MHD: Lorentz body force j x B stirs the electrolyte -> extra shear velocity
    u_eff = op.u_flow + props["k_mhd"] * j * op.B_field
    c_drag = 0.5 * props["Cd_flow"] * rho_l * u_eff * u_eff * math.pi   # F_d = c_drag * r^2

    # negative dielectrophoresis: F_DEP = 2 pi eps0 eps_l Re(K) a^3 grad(|E|^2)
    # scales with the bubble VOLUME (r^3), NOT r^2 (Jones, 'Electromechanics of
    # Particles' 1995, Eq. 2.27). No true field gradient is available in `op`, so
    # op.E_ext is read as a DEP drive and grad(|E|^2) is proxied as E_ext^2/L_dep
    # over a near-surface length. Default E_ext=0 makes the term vanish (golden-safe).
    K = abs((1.0 - prop.EPS_WATER) / (1.0 + 2.0 * prop.EPS_WATER))
    L_dep = 1.0e-4
    dep_coeff = 2.0 * math.pi * EPS0 * prop.EPS_WATER * K * op.E_ext * op.E_ext / L_dep

    r_min = props["r_min_detach"]

    def net(r):                      # detaching minus adhesion; >0 => the bubble departs
        # buoyancy & DEP ~ r^3, flow drag ~ r^2, contact-line adhesion ~ r^1
        return (buoy_coeff + dep_coeff) * r ** 3 + c_drag * r * r - A_adh * r

    if net(r_min) >= 0.0:            # already detaching at the floor radius
        return r_min
    lo, hi = r_min, r_d0            # net(r_min)<0, net(r_d0)>=0 -> single crossing
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if net(mid) > 0.0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
