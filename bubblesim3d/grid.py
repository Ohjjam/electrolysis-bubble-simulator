"""Uniform Cartesian grid shared by both 3-D tracks.

Axis convention (matches web3d/sim3d.js and the kernel bubble frame):
    x (axis 0): through-plane — cathode face at x=0, anode face at x=Lx
    y (axis 1): flow / height — buoyancy acts along +y in a vertical cell
    z (axis 2): cell width    — ribs/channels repeat along z

Fields are numpy arrays of shape (nx, ny, nz); cell centres sit at
((i+0.5)h, (j+0.5)h, (k+0.5)h). Particle positions are metres in the same
frame, carried as (N, 3) float arrays.
"""
import numpy as np


class Grid3D:
    def __init__(self, nx, ny, nz, h):
        self.nx, self.ny, self.nz = int(nx), int(ny), int(nz)
        self.h = float(h)
        self.shape = (self.nx, self.ny, self.nz)
        self.n = self.nx * self.ny * self.nz
        self.Lx = self.nx * self.h
        self.Ly = self.ny * self.h
        self.Lz = self.nz * self.h

    # ------------------------------------------------------------- fields
    def field(self, fill=0.0, dtype=np.float64):
        if fill == 0.0:
            return np.zeros(self.shape, dtype=dtype)
        return np.full(self.shape, fill, dtype=dtype)

    @property
    def cell_volume(self):
        return self.h ** 3

    def centers(self, axis):
        """Cell-centre coordinates along one axis [m]."""
        n = self.shape[axis]
        return (np.arange(n) + 0.5) * self.h

    # ------------------------------------------------------- interpolation
    def _base_frac(self, pts):
        """Common trilinear setup: base cell index (clamped) + fraction."""
        g = pts / self.h - 0.5                      # cell-centred grid coords
        i0 = np.floor(g).astype(np.int64)
        hi = np.array([self.nx - 2, self.ny - 2, self.nz - 2])
        i0 = np.clip(i0, 0, hi)
        fr = np.clip(g - i0, 0.0, 1.0)
        return i0, fr

    def sample(self, f, pts):
        """Trilinear sample of field `f` at positions `pts` (N,3) [m] -> (N,)."""
        if len(pts) == 0:
            return np.zeros(0)
        i0, fr = self._base_frac(np.asarray(pts, dtype=np.float64))
        i, j, k = i0[:, 0], i0[:, 1], i0[:, 2]
        fx, fy, fz = fr[:, 0], fr[:, 1], fr[:, 2]
        c000 = f[i, j, k];         c100 = f[i + 1, j, k]
        c010 = f[i, j + 1, k];     c110 = f[i + 1, j + 1, k]
        c001 = f[i, j, k + 1];     c101 = f[i + 1, j, k + 1]
        c011 = f[i, j + 1, k + 1]; c111 = f[i + 1, j + 1, k + 1]
        lx0 = c000 + (c100 - c000) * fx
        lx1 = c010 + (c110 - c010) * fx
        lx2 = c001 + (c101 - c001) * fx
        lx3 = c011 + (c111 - c011) * fx
        ly0 = lx0 + (lx1 - lx0) * fy
        ly1 = lx2 + (lx3 - lx2) * fy
        return ly0 + (ly1 - ly0) * fz

    def deposit27(self, f, pts, w):
        """Scatter weights `w` (N,) at `pts` (N,3), smeared over 3x3x3 cells.

        Same trick as sim3d.js _depositGas: a sub-cell parcel dumped into one
        cell spikes the local void -> runaway buoyancy jets; spreading over
        ~27 cells recovers the physical few-% void fraction.
        """
        if len(pts) == 0:
            return
        pts = np.asarray(pts, dtype=np.float64)
        ci = np.clip((pts / self.h).astype(np.int64),
                     0, [self.nx - 1, self.ny - 1, self.nz - 1])
        share = np.asarray(w, dtype=np.float64) / 27.0
        for di in (-1, 0, 1):
            ii = np.clip(ci[:, 0] + di, 0, self.nx - 1)
            for dj in (-1, 0, 1):
                jj = np.clip(ci[:, 1] + dj, 0, self.ny - 1)
                for dk in (-1, 0, 1):
                    kk = np.clip(ci[:, 2] + dk, 0, self.nz - 1)
                    np.add.at(f, (ii, jj, kk), share)

    def clamp_points(self, pts, margin):
        """Clamp positions into the box with a per-point margin (N,) or scalar."""
        m = np.broadcast_to(np.asarray(margin, dtype=np.float64), (len(pts),))
        pts[:, 0] = np.clip(pts[:, 0], m, self.Lx - m)
        pts[:, 1] = np.clip(pts[:, 1], m, None)     # top (y=Ly) is the outlet
        pts[:, 2] = np.clip(pts[:, 2], m, self.Lz - m)
        return pts
