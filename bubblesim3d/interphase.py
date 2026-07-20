"""Gas/liquid interphase relations shared by the 3-D parcel and flow solvers.

Only dimensionless literature correlations live here. There is deliberately no
user-tuned drag strength: the exchange rate follows from bubble diameter,
liquid properties, gas/liquid slip and local phase fraction.
"""
from __future__ import annotations

import numpy as np

from bubblesim.constants import G


def schiller_naumann_cd(reynolds):
    """Drag coefficient for a spherical dispersed phase."""
    re = np.maximum(np.asarray(reynolds, dtype=np.float64), np.finfo(float).tiny)
    return np.where(re < 1000.0,
                    (24.0 / re) * (1.0 + 0.15 * re ** 0.687),
                    0.44)


def terminal_velocity(radius, d_rho, mu, rho_l, iters=20):
    """Terminal rise speed [m/s] from buoyancy/Schiller--Naumann balance."""
    r = np.asarray(radius, dtype=np.float64)
    if r.size == 0:
        return r
    speed = (2.0 / 9.0) * float(d_rho) * G * r * r / float(mu)
    for _ in range(int(iters)):
        re = 2.0 * r * np.abs(speed) * float(rho_l) / float(mu)
        cd = schiller_naumann_cd(re)
        next_speed = np.sqrt(np.maximum(
            0.0, (8.0 / 3.0) * float(d_rho) * G * r / (cd * float(rho_l))))
        speed = 0.5 * (speed + next_speed)
    return speed


def momentum_exchange_rate(alpha_g, diameter, relative_speed, rho_l, mu_l):
    """Liquid acceleration coefficient ``k`` [1/s] for spherical bubbles.

    F_lg = 3/4 C_D rho_l alpha_g |u_g-u_l| (u_g-u_l) / d_b.
    Dividing by liquid mass per mixture volume gives ``du_l/dt=k(u_g-u_l)``.
    """
    alpha = np.clip(np.asarray(alpha_g, dtype=np.float64), 0.0,
                    1.0 - np.sqrt(np.finfo(float).eps))
    d = np.asarray(diameter, dtype=np.float64)
    slip = np.maximum(np.asarray(relative_speed, dtype=np.float64), 0.0)
    valid = (alpha > 0.0) & (d > 0.0) & (slip > 0.0)
    re = np.zeros_like(alpha)
    re[valid] = float(rho_l) * slip[valid] * d[valid] / float(mu_l)
    cd = np.zeros_like(alpha)
    cd[valid] = schiller_naumann_cd(re[valid])
    rate = np.zeros_like(alpha)
    rate[valid] = (0.75 * cd[valid] * alpha[valid] * slip[valid]
                   / ((1.0 - alpha[valid]) * d[valid]))
    return rate, re, cd
