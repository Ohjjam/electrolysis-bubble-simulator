"""Electrode-face current redistribution from the resolved 3-D bubbles (Track A).

The 3-D analogue of bubblesim.solvers.face2d, but the coverage field theta(y,z)
comes from the ACTUAL near-wall bubbles (their contact footprints stamped onto
the face) instead of face2d's empirical accumulation law. Given the scalar
operating point j_mean (frozen kernel two-electrode balance), the local current
redistributes at the common overpotential:

    j(y,z) = j_mean * active*(1-theta) / mean_full(active*(1-theta))

so bubble-blanketed patches (and rib-shadowed lands) carry less current and
clear channels carry more — the face bottleneck map.

Resolution: the map is binned FINER than the flow grid (res x per axis, default
3 -> ~0.7 mm bins on the default cell) and each bubble's footprint is stamped
as a DISK over the bins it covers, so the texture reads as smooth patches
instead of blocky single-cell blobs.

Honest scope: an electrode-network reduction driven by the 3-D coverage, not a
resolved 3-D gap-potential solve.
"""
import numpy as np


def face_coverage(parcels, grid, side, contact_angle_deg,
                  ny_f=None, nz_f=None, slab_cells=2, cap=0.9):
    """theta(y,z) on one electrode face from near-wall bubble footprints.

    Bins catalyst-attached bubbles into an (ny_f, nz_f) map; each
    footprint (pi (r sin beta)^2) is spread uniformly over the bins inside its
    contact disk. theta saturates via the kernel's Poisson-union closure:
    theta = cap (1 - exp(-area/bin_area)).
    """
    ny_f = int(ny_f or grid.ny)
    nz_f = int(nz_f or grid.nz)
    by, bz = grid.Ly / ny_f, grid.Lz / nz_f
    th = np.zeros((ny_f, nz_f))
    if len(parcels.r) == 0:
        return th
    # near-ELECTRODE bubbles (catalyst plane in a zero-gap cell — parcels
    # knows where its electrode surfaces actually are)
    # Match scalar electrochemistry: only catalyst-attached bubbles block the
    # catalyst. Free near-wall risers and mesh-held bubbles remain visual parcel
    # states, not a second display-only coverage definition.
    parcels._ensure_state_arrays()
    m = parcels.attached & (parcels.side == side)
    if not m.any():
        return th
    y = parcels.pos[m, 1]
    z = parcels.pos[m, 2]
    sinb = abs(np.sin(np.radians(contact_angle_deg)))
    rf = parcels.r[m] * sinb                        # contact footprint radius
    foot = parcels.mult[m] * np.pi * rf * rf        # mult real footprints [m^2]
    area = np.zeros((ny_f, nz_f))
    r_eff = np.maximum(rf, 0.51 * max(by, bz))      # cover at least ~1 bin
    for i in range(len(y)):
        r = r_eff[i]
        j0 = max(0, int((y[i] - r) / by)); j1 = min(ny_f - 1, int((y[i] + r) / by))
        k0 = max(0, int((z[i] - r) / bz)); k1 = min(nz_f - 1, int((z[i] + r) / bz))
        if j1 < j0 or k1 < k0:
            continue
        yy = (np.arange(j0, j1 + 1) + 0.5) * by
        zz = (np.arange(k0, k1 + 1) + 0.5) * bz
        inside = ((yy[:, None] - y[i]) ** 2 + (zz[None, :] - z[i]) ** 2) <= r * r
        cnt = int(inside.sum())
        if cnt == 0:
            jj = min(ny_f - 1, max(0, int(y[i] / by)))
            kk = min(nz_f - 1, max(0, int(z[i] / bz)))
            area[jj, kk] += foot[i]
        else:
            patch = area[j0:j1 + 1, k0:k1 + 1]
            patch[inside] += foot[i] / cnt
    return cap * (1.0 - np.exp(-area / (by * bz)))


def redistribute(j_mean, theta, active=None):
    """Redistribute a whole-face geometric mean current density.

    ``j_mean`` and the Faraday source both use the full geometric electrode
    area.  The masked map therefore conserves its mean over the full face; an
    active-only mean would lose current in proportion to the land fraction.
    """
    omt = 1.0 - theta
    if active is not None:
        omt = np.where(active, omt, 0.0)
    denom = omt.mean()
    jf = j_mean * omt / max(1e-9, float(denom))
    return jf


def _smooth(a, passes=2):
    """3x3 box blur (edge-clamped): merges per-bubble stamps into coherent
    coverage patches so the map reads as a field, not per-bin speckle."""
    for _ in range(passes):
        p = np.pad(a, 1, mode="edge")
        a = (p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:] +
             p[1:-1, :-2] + p[1:-1, 1:-1] + p[1:-1, 2:] +
             p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:]) / 9.0
    return a


def face_maps(parcels, grid, j_mean_A_m2, contact_angle_deg,
              face_c=None, face_a=None, res=3):
    """Both electrode-face current maps for the renderer, as A/cm^2, binned at
    `res`x the flow-grid resolution. Land (rib) cells are marked with -1 so the
    client can draw them as neutral structure lines instead of colormap noise."""
    out = {}
    ny_f, nz_f = grid.ny * res, grid.nz * res
    for side, key, active in ((0, "cathode", face_c), (1, "anode", face_a)):
        th = _smooth(face_coverage(parcels, grid, side, contact_angle_deg,
                                   ny_f, nz_f))
        act = None
        if active is not None:
            act = np.repeat(np.repeat(active, res, axis=0), res, axis=1)
        jf = redistribute(j_mean_A_m2, th, act) / 1.0e4      # -> A/cm^2
        jv = jf[act] if (act is not None and act.any()) else jf
        j_spread = round(float(jv.max() / max(1e-9, jv.min())), 3) if jv.size else 1.0
        if act is not None:
            jf = np.where(act, jf, -1.0)                     # -1 = land (no electrolyte)
            th_out = np.where(act, th, -1.0)
        else:
            th_out = th
        out[key] = {
            "ny": ny_f, "nz": nz_f,
            "j": np.round(jf, 3).ravel().tolist(),
            "theta": np.round(th_out, 3).ravel().tolist(),
            "theta_mean": round(float(th.mean()), 4),
            "j_spread": j_spread,
        }
    return out
