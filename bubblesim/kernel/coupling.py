"""Bubble <-> solver-grid projection operators.

The Lagrangian bubble population lives in continuous coordinates; spatial
solvers need field representations of it. `void_profile` projects bubbles onto
a 1D grid along the gap normal (z), giving the eps(z) the 1D solver feeds into
a layer-resolved Bruggeman resistance — the upgrade from the 0D scalar eps.

v1 coordinate note: a bubble's off-electrode coordinate is stored as `b.y`
(see kernel/bubbles/bubble.py) and is the gap-normal z here. Attached bubbles
sit tangent to the wall, so their center is at z = r.
"""


def void_profile(bubbles, L, n_cells, area):
    """Gas volume fraction per z-cell over [0, L] (electrode -> membrane/bulk).

    Each bubble's volume is spread uniformly over its z-extent [zc - r, zc + r]
    (zc = max(y, r): attached bubbles are wall-tangent), clipped to the domain.
    Returns a list of n_cells fractions, each capped at 0.95. Total gas volume
    inside the domain is conserved by construction (up to the cap and clipping).
    """
    dz = L / n_cells
    eps = [0.0] * n_cells
    cell_vol = area * dz
    for b in bubbles:
        zc = max(b.y, b.r)
        lo, hi = zc - b.r, zc + b.r
        span = hi - lo
        if span <= 0.0 or lo >= L:
            continue
        v_per_m = b.volume() / span                  # uniform smearing along z
        i0 = max(0, int(lo / dz))
        i1 = min(n_cells - 1, int(hi / dz))
        for i in range(i0, i1 + 1):
            seg = min(hi, (i + 1) * dz) - max(lo, i * dz)
            if seg > 0.0:
                eps[i] += v_per_m * seg / cell_vol
    return [min(0.95, e) for e in eps]
