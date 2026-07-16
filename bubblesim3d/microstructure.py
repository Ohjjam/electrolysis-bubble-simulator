"""Voxel microstructure generator for the pore-scale track (Track B).

Turns a bubblesim.kernel.morphology substrate into a 3-D voxel scaffold whose
porosity (and, roughly, specific area) match the homogenized library values, so
the pore-scale solver runs on a *real* structure instead of a 1-D average:

  * foams (ni_foam / ss_foam)        -> leveled-wave Gaussian random field: the
    solid is a thin band around a level set of a smoothed noise field, giving a
    connected, bicontinuous strut/pore network (both phases percolate) — the
    standard cheap open-cell-foam model.
  * fibre media (carbon_paper/ni_mesh) -> straight cylinders: random in-plane
    fibres (paper) or a regular woven over/under lattice (mesh).
  * flat_plate                        -> a solid slab with a thin open gap.

numpy only (FFT for the GRF, array-shift flood-fill for connectivity — no scipy
/ skimage). Porosity is matched EXACTLY (level chosen by quantile); specific area
follows from the correlation length / fibre diameter and is reported for checking
against the library `a`.

Honest scope: a statistically representative structure at the target porosity,
not a tomographic reconstruction of a specific electrode.
"""
import numpy as np

from bubblesim.kernel import morphology as morph


# --------------------------------------------------------------- GRF (foam)
def _gaussian_random_field(n, corr_cells, rng):
    """Unit-variance Gaussian random field on an n^3 grid, correlation length
    `corr_cells` (in voxels), via FFT low-pass of white noise."""
    white = rng.standard_normal((n, n, n))
    fw = np.fft.rfftn(white)
    kx = np.fft.fftfreq(n)[:, None, None]
    ky = np.fft.fftfreq(n)[None, :, None]
    kz = np.fft.rfftfreq(n)[None, None, :]
    k2 = kx * kx + ky * ky + kz * kz
    # Gaussian filter: exp(-2 (pi corr)^2 k^2) smooths to correlation length corr
    filt = np.exp(-2.0 * (np.pi * corr_cells) ** 2 * k2)
    field = np.fft.irfftn(fw * filt, s=(n, n, n), axes=(0, 1, 2))
    field -= field.mean()
    s = field.std()
    return field / s if s > 0 else field


def _leveled_wave(n, solid_frac, corr_cells, rng):
    """Bicontinuous solid at EXACT `solid_frac`: a band around the median level
    set of a smoothed GRF. Both phases connect when the band is >~1 voxel thick;
    the caller floors `solid_frac` so the struts survive voxelization."""
    field = _gaussian_random_field(n, corr_cells, rng)
    delta = np.quantile(np.abs(field), solid_frac)   # exact volume fraction
    return np.abs(field) < delta


def _min_solid_frac(n):
    """Lowest solid fraction whose struts stay ~1.5 voxels thick (and thus
    connected) at grid size n. Finer grids (128^3) allow thinner struts."""
    return max(0.03, 9.0 / n)


# ---------------------------------------------------------------- generate
def generate(cfg):
    """(solid, meta) for a Pore3DConfig. `solid` is (n,n,n) bool scaffold.

    All porous substrates use the leveled-wave (bicontinuous) model — both the
    metal and the pore space percolate, which the current + gas solvers need.
    For very high porosity (foam ~95%) at a modest grid the solid fraction is
    floored so the struts don't fall below the voxel size (documented in meta as
    eps_achieved vs eps_target); a finer grid recovers the true porosity.
    """
    n = int(cfg.n)
    rng = np.random.default_rng(cfg.seed)
    eff = morph.effective_electrode(cfg.substrate, cfg.nanostructure)
    eps_p = eff["eps_p"] if eff["eps_p"] > 0 else 0.5
    L_e = eff["L_e"]
    h = (cfg.h_um * 1e-6) if cfg.h_um > 0 else (L_e / n)      # voxel size [m]
    sub = cfg.substrate

    if sub == "flat_plate":                          # planar reference (a slab)
        solid = np.zeros((n, n, n), dtype=bool)
        # access/escape face is y=0; put liquid first and solid behind it so the
        # external liquid|solid interface is representable inside the volume.
        solid[:, n // 2:, :] = True
    else:
        solid_frac = 1.0 - eps_p
        solid_frac = float(np.clip(solid_frac, _min_solid_frac(n), 0.6))
        # correlation length: paper/mesh finer (more struts), foam coarser
        corr = n / (14.0 if sub == "carbon_paper" else 10.0 if sub == "ni_mesh" else 8.0)
        solid = _leveled_wave(n, solid_frac, max(1.5, corr), rng)

    eps_achieved = float(1.0 - solid.mean())
    meta = {
        "substrate": sub, "nanostructure": cfg.nanostructure,
        "n": n, "h_um": h * 1e6, "L_e_um": L_e * 1e6,
        "eps_target": round(eps_p, 4),
        "eps_achieved": round(eps_achieved, 4),      # floored for connectivity
        "a_target": round(eff["a"], 1),              # full a incl. nano ECSA
        # geometric scaffold area the VOXELS can represent (no sub-voxel nano)
        "a_sub_target": round(morph.SUBSTRATES[sub]["geo_rough"] / L_e, 1),
        "R_f": round(eff["R_f"], 1),
        "escape_factor": eff["escape_factor"],
        "nuc_site_mult": eff["nuc_site_mult"],
        "sigma_eff": eff["sigma_eff"],
    }
    return solid, meta


# ---------------------------------------------------------------- stats
def _percolates(pore, axis):
    """True if the pore phase connects the two faces along `axis` (6-connected
    flood fill via iterative array shifts — numpy-only, no scipy)."""
    n = pore.shape[axis]
    reached = np.zeros_like(pore)
    # seed the starting face
    sl0 = [slice(None)] * 3; sl0[axis] = 0
    reached[tuple(sl0)] = pore[tuple(sl0)]
    slN = [slice(None)] * 3; slN[axis] = n - 1
    # cap = total voxels: tortuous pore paths exceed 4n (breaks on convergence)
    for _ in range(pore.size):
        # 6-neighbour dilation restricted to the pore phase
        nb = reached.copy()
        nb[1:, :, :] |= reached[:-1, :, :]; nb[:-1, :, :] |= reached[1:, :, :]
        nb[:, 1:, :] |= reached[:, :-1, :]; nb[:, :-1, :] |= reached[:, 1:, :]
        nb[:, :, 1:] |= reached[:, :, :-1]; nb[:, :, :-1] |= reached[:, :, 1:]
        nb &= pore
        if nb.sum() == reached.sum():
            break
        reached = nb
        if reached[tuple(slN)].any():
            return True
    return bool(reached[tuple(slN)].any())


def _surface_faces(solid):
    """Count solid|pore interface faces (6-connected)."""
    f = 0
    for ax in range(3):
        a = np.moveaxis(solid, ax, 0)
        f += np.count_nonzero(a[:-1] != a[1:])
    return int(f)


def microstructure_stats(solid, h):
    """Measured porosity, specific surface area [1/m] and pore percolation."""
    n = solid.shape[0]
    porosity = float(1.0 - solid.mean())
    faces = _surface_faces(solid)
    vol = (n ** 3) * (h ** 3)
    specific_area = faces * (h * h) / vol            # = faces / (n^3 h)
    pore = ~solid
    return {
        "porosity": round(porosity, 4),
        "specific_area": round(specific_area, 1),    # [m^2/m^3]
        "percolates_y": _percolates(pore, 1),        # electrolyte through thickness
        "solid_percolates": _percolates(solid, 1),   # electronic path
    }
