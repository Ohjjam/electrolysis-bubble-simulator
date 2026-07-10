"""3-D secondary current distribution on the pore-scale scaffold (Track B).

Solves the linearized porous-electrode potential on the OPEN pore phase — the
electrolyte potential psi obeys a screened-Poisson (modified-Helmholtz) balance

    laplacian(psi) = psi / lambda^2

with lambda the reaction penetration depth (morphology.penetration_depth): near
the accessible separator face psi ~ 1 and the reaction is fast; deeper in the
electrode psi decays over lambda, so the reaction concentrates in a skin when
lambda << thickness and spreads through the whole electrode when lambda >>
thickness — the classic Newman porous-electrode result, here on the REAL 3-D
scaffold geometry instead of a 1-D average.

The local reaction current at each scaffold-surface voxel is proportional to psi
there, normalised so the total equals the imposed geometric current. As gas
fills pore voxels they drop out of the conducting pore (blocked), so the current
redistributes to the still-open channels — the gas->current coupling.

Reduced-model honesty: this is a linearized single-phase-potential solve (metal
treated iso-potential at high sigma_eff), not a full coupled Newton over both
phases + Butler-Volmer — it captures the penetration/redistribution physics that
sets WHERE bubbles form, which is what the gas model needs.

RB-SOR, numpy only.
"""
import numpy as np

from bubblesim.kernel import morphology as morph
from bubblesim.kernel.kinetics import butler_volmer
from bubblesim.kernel.context import build_context


def _surface_faces_mask(solid):
    """Boolean (n,n,n): open-pore voxels that touch a solid voxel (the reacting
    scaffold surface, seen from the electrolyte side)."""
    pore = ~solid
    touch = np.zeros_like(pore)
    touch[:-1] |= solid[1:];  touch[1:] |= solid[:-1]
    touch[:, :-1] |= solid[:, 1:];  touch[:, 1:] |= solid[:, :-1]
    touch[:, :, :-1] |= solid[:, :, 1:];  touch[:, :, 1:] |= solid[:, :, :-1]
    return pore & touch


def penetration_cells(op, params, eff, h):
    """Reaction penetration depth lambda in voxels for this operating point."""
    ctx = build_context(op, params)
    kappa = ctx["kappa"]
    # BV slope di/deta at a representative overpotential (0.1 V) for the primary
    # reaction, per real area, times specific area a -> volumetric slope
    T = op.T
    react = ctx["j0_cathode"] if op.electrode == "HER" else ctx["j0_anode"]
    if op.electrode == "HER":
        aa, ac = ctx["alpha_a_cathode"], ctx["alpha_c_cathode"]
    else:
        aa, ac = ctx["alpha_a_anode"], ctx["alpha_c_anode"]
    eta = 0.1
    j1 = butler_volmer(react * eff["R_f"], aa, ac, eta, T)
    j2 = butler_volmer(react * eff["R_f"], aa, ac, eta + 1e-3, T)
    dj_deta = max(1e-6, (j2 - j1) / 1e-3)
    lam = morph.penetration_depth(eff, kappa, dj_deta * eff["a"])   # [m]
    return max(0.5, lam / h)


class Current3D:
    """Screened-Poisson reaction-distribution solver on the pore phase."""

    def __init__(self, solid, lam_cells, access_axis=1, omega=1.7):
        self.solid = solid
        self.n = solid.shape[0]
        self.lam2 = float(lam_cells) ** 2
        self.axis = access_axis                    # separator/accessible face axis
        self.omega = omega
        self.surf = _surface_faces_mask(solid)     # reacting surface voxels
        ii, jj, kk = np.indices(solid.shape)
        self._parity = (ii + jj + kk) % 2

    def solve(self, blocked=None, iters=120):
        """psi on open pore voxels (1 at the accessible face, decaying inward).

        `blocked` (bool) = gas-filled pore voxels removed from conduction."""
        n = self.n
        open_pore = ~self.solid
        if blocked is not None:
            open_pore = open_pore & (~blocked)
        psi = np.zeros(self.solid.shape)
        # Dirichlet psi=1 on the accessible (separator) face's open pores
        face = [slice(None)] * 3; face[self.axis] = 0
        drive = np.zeros(self.solid.shape, dtype=bool)
        drive[tuple(face)] = open_pore[tuple(face)]
        psi[drive] = 1.0
        relax = open_pore & (~drive)
        red = relax & (self._parity == 0)
        black = relax & (self._parity == 1)
        # divisor: open-pore neighbours + the screened term (lam^2 in cell units).
        # laplacian(psi) - psi/lam2 = 0 -> psi = sum_nb / (n_nb + 1/lam2)
        nb_count = np.zeros(self.solid.shape)
        for ax in range(3):
            nb_count += np.roll(open_pore, 1, ax).astype(float)
            nb_count += np.roll(open_pore, -1, ax).astype(float)
        # roll wraps; zero the wrapped edges so boundaries are no-flux
        # (approximate: interior dominates). divisor:
        divisor = nb_count + 1.0 / self.lam2
        divisor[divisor < 1e-9] = 1e-9
        om = self.omega

        def nbsum(p):
            s = np.zeros_like(p)
            s[1:] += p[:-1] * open_pore[:-1]; s[:-1] += p[1:] * open_pore[1:]
            s[:, 1:] += p[:, :-1] * open_pore[:, :-1]; s[:, :-1] += p[:, 1:] * open_pore[:, 1:]
            s[:, :, 1:] += p[:, :, :-1] * open_pore[:, :, :-1]
            s[:, :, :-1] += p[:, :, 1:] * open_pore[:, :, 1:]
            return s

        for _ in range(iters):
            s = nbsum(psi)
            psi[red] = (1 - om) * psi[red] + om * (s[red] / divisor[red])
            s = nbsum(psi)
            psi[black] = (1 - om) * psi[black] + om * (s[black] / divisor[black])
            np.clip(psi, 0.0, 1.0, out=psi)
        self.psi = psi
        return psi

    def surface_current(self, total_current_A, blocked=None):
        """Per-surface-voxel current [A] proportional to psi, summing to
        `total_current_A`. Blocked (gas-covered) surface voxels carry no current."""
        surf = self.surf
        if blocked is not None:
            surf = surf & (~blocked)
        w = self.psi * surf
        tot = w.sum()
        if tot <= 0:
            return np.zeros_like(self.psi)
        return w * (total_current_A / tot)
