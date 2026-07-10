"""In-tool 2-D two-phase bubble-flow solver (Euler-Lagrange) -- model="flow2d".

We cannot run a 3-D interface-resolved (VOF) CFD interactively, or even write one
that runs here: resolving bubble interfaces in 3-D is a fundamental compute wall
(hours-days/case on HPC, regardless of software). This is the closest REAL,
self-contained alternative -- no OpenFOAM/COMSOL needed:

  * a 2-D channel cross-section, ONE wall = electrode, the others = walls
  * the LIQUID flow is actually solved -- incompressible Navier-Stokes in
    vorticity-streamfunction form (Jacobi pressure-free Poisson)
  * bubbles are Lagrangian particles: nucleate on the electrode, grow from the
    local gas flux, detach at the departure radius, ride the SOLVED flow plus a
    buoyant slip, and push the liquid back (two-way: their buoyancy is a
    vorticity source) -> vortices and bubble self-stirring EMERGE, not prescribed.

Honest scope: 2-D (not 3-D); bubbles are sub-grid particles (interfaces not
resolved -> no true coalescence/breakup shapes); coarse grid + an eddy viscosity
for interactive stability. Real coupled CFD physics, one dimension down. numpy.
"""
import numpy as np

from ..constants import G


class FlowChannel2D:
    def __init__(self, nx=96, ny=24, Lx=0.048, Ly=0.012, u_in=0.04,
                 nu=2.0e-5, c_buoy=1.0, seed=0, gas_factor=1.0, T=333.15, P=1.0e5):
        self.nx, self.ny = nx, ny
        self.Lx, self.Ly = Lx, Ly
        self.h = Ly / ny
        self.u_in = u_in
        self.nu = nu
        self.T, self.P = T, P                      # for the ideal-gas molar volume in growth
        self.c_buoy = c_buoy                       # O(1) calibration on the reduced-gravity buoyancy source
        self.gas_factor = gas_factor               # gas volume per charge: 1.0 (H2) vs 0.5 (O2)
        self.rng = np.random.default_rng(seed)
        self.omega = np.zeros((ny, nx))
        self.psi = np.zeros((ny, nx))
        self.u = np.full((ny, nx), u_in)
        self.v = np.zeros((ny, nx))
        self.bub = []                             # list of [x, y, r, attached, id]
        self._next_id = 0                         # stable per-bubble id -> client can interpolate motion
        self._ylin = np.arange(ny) * self.h       # for inlet psi = u_in * y
        self._nuc_accum = 0.0
        self.inlet_gas = 0.0                      # bubbles/s entering at the inlet (upstream gas, for drill-in)
        self._inlet_accum = 0.0

    # ---- incompressible flow (vorticity-streamfunction) ----------------------
    def _poisson(self, iters=40):
        """Jacobi solve lap(psi) = -omega with channel BCs."""
        h2 = self.h * self.h
        p = self.psi
        Q = self.u_in * self.Ly                   # total flux (top wall streamline)
        for _ in range(iters):
            p[0, :] = 0.0                          # bottom wall (electrode)
            p[-1, :] = Q                           # top wall
            p[:, 0] = self.u_in * self._ylin       # inlet: uniform u
            p[:, -1] = p[:, -2]                    # outlet: zero-gradient
            p[1:-1, 1:-1] = 0.25 * (p[1:-1, 2:] + p[1:-1, :-2]
                                    + p[2:, 1:-1] + p[:-2, 1:-1]
                                    + h2 * self.omega[1:-1, 1:-1])
        self.psi = p

    def _velocity(self):
        h = self.h
        self.u[1:-1, :] = (self.psi[2:, :] - self.psi[:-2, :]) / (2 * h)     # u = d psi/dy
        self.v[:, 1:-1] = -(self.psi[:, 2:] - self.psi[:, :-2]) / (2 * h)    # v = -d psi/dx
        self.u[0, :] = 0.0; self.u[-1, :] = 0.0                              # no-slip walls
        self.v[0, :] = 0.0; self.v[-1, :] = 0.0
        self.u[:, 0] = self.u_in                                             # inlet
        np.clip(self.u, -5 * self.u_in - 0.2, 5 * self.u_in + 0.5, out=self.u)
        np.clip(self.v, -0.5, 0.5, out=self.v)

    def _void_field(self):
        void = np.zeros((self.ny, self.nx))
        cell = self.h * self.h
        for b in self.bub:
            i = min(self.nx - 1, max(0, int(b[0] / self.h)))
            j = min(self.ny - 1, max(0, int(b[1] / self.h)))
            void[j, i] += min(1.0, np.pi * b[2] * b[2] / cell)
        return np.minimum(0.6, void)

    def step(self, dt, j_current, r_dep, contact_angle):
        h, nu = self.h, self.nu
        void = self._void_field()
        u, v, w = self.u, self.v, self.omega
        # upwind advection of vorticity (stable), + diffusion + buoyancy source
        dwdx = np.where(u > 0, w - np.roll(w, 1, 1), np.roll(w, -1, 1) - w) / h
        dwdy = np.where(v > 0, w - np.roll(w, 1, 0), np.roll(w, -1, 0) - w) / h
        lap = (np.roll(w, 1, 1) + np.roll(w, -1, 1) + np.roll(w, 1, 0)
               + np.roll(w, -1, 0) - 4 * w) / (h * h)
        dvoiddx = (np.roll(void, -1, 1) - np.roll(void, 1, 1)) / (2 * h)
        # vorticity source = curl of the buoyancy body force = (reduced gravity) * d(void)/dx.
        # The buoyancy force is +eps (rho_l-rho_g) g e_y; its curl is g'*d eps/dx with the
        # reduced gravity g' = g (rho_l-rho_g)/rho_l ~ g (rho_g << rho_l). c_buoy is an O(1)
        # calibration only (void is a sub-grid area-fraction proxy).
        src = self.c_buoy * G * dvoiddx
        w = w + dt * (-u * dwdx - v * dwdy + nu * lap + src)
        np.clip(w, -1e4, 1e4, out=w)
        self.omega = w
        self._poisson()
        # Thom wall vorticity (no-slip top/bottom)
        self.omega[0, 1:-1] = -2.0 * (self.psi[1, 1:-1] - self.psi[0, 1:-1]) / (h * h)
        self.omega[-1, 1:-1] = -2.0 * (self.psi[-2, 1:-1] - self.psi[-1, 1:-1]) / (h * h)
        # inlet/outlet vorticity BCs (else np.roll wraps inlet<->outlet periodically):
        self.omega[:, 0] = 0.0                     # uniform-plug inlet -> zero vorticity
        self.omega[:, -1] = self.omega[:, -2]      # convective (zero-gradient) outflow
        self._velocity()
        self._bubbles(dt, j_current, r_dep, contact_angle)

    # ---- Lagrangian bubbles --------------------------------------------------
    def _sample_uv(self, x, y):
        i = min(self.nx - 2, max(0, int(x / self.h)))
        j = min(self.ny - 2, max(0, int(y / self.h)))
        return self.u[j, i], self.v[j, i]

    def _bubbles(self, dt, j_current, r_dep, contact_angle):
        from ..constants import F
        # nucleate on the electrode wall (bottom), rate ~ current density
        rate = 10.0 * self.gas_factor * max(0.0, j_current) / 1.0e4 * self.nx   # bubbles/s along the wall
        self._nuc_accum += rate * dt
        while self._nuc_accum >= 1.0 and len(self.bub) < 700:
            self._nuc_accum -= 1.0
            self.bub.append([self.rng.uniform(0.02, 0.96) * self.Lx, 2.0e-5, 2.0e-5, 1.0, self._next_id])
            self._next_id += 1
        # upstream gas entering from the inlet (used when drilling into a downstream region)
        self._inlet_accum += self.inlet_gas * dt
        while self._inlet_accum >= 1.0 and len(self.bub) < 700:
            self._inlet_accum -= 1.0
            self.bub.append([0.01 * self.Lx, self.rng.uniform(0.25, 0.85) * self.Ly,
                             self.rng.uniform(1.5e-4, 3.0e-4), 0.0, self._next_id])
            self._next_id += 1
        # per-bubble gas volume rate [m^3/s] = (j/zF) * Vm * A_site, grounded in the
        # ideal-gas molar volume Vm=RT/P and the wall area served by one nucleation
        # column (Lx/nx wide x cell depth h), not a bare magic constant.
        from ..constants import R_GAS
        Vm = R_GAS * self.T / self.P
        A_site = (self.Lx / self.nx) * self.h
        grow = (max(0.0, j_current) / (2.0 * F)) * Vm * A_site * self.gas_factor
        kept = []
        for b in self.bub:
            x, y, r, att, bid = b
            if att > 0.5:                            # attached: grow on the wall, then detach
                vol = 4.0 / 3.0 * np.pi * r ** 3 + grow * dt
                r = (3.0 * vol / (4.0 * np.pi)) ** (1.0 / 3.0)
                if r >= r_dep:
                    att, y = 0.0, 2.2 * r            # lift off
                else:
                    y = r
            else:                                    # detached: ride the solved flow + buoyant slip
                uu, vv = self._sample_uv(x, min(y, self.Ly - 1.5 * self.h))   # sample below the top wall
                v_slip = min(0.25, 2.222e5 * G * r * r)          # Stokes rise (d_rho~1000,mu~1e-3), capped
                x += uu * dt
                y += (vv + v_slip) * dt
                if y > self.Ly - r:
                    y = self.Ly - r                  # the top is a WALL: ride along it, don't vanish
            if att > 0.5:
                kept.append([x, y, r, att, bid])     # attached: grows on the electrode wall
            elif 0.0 <= x < self.Lx:                 # detached: removed only at the downstream OUTLET
                kept.append([x, y, r, att, bid])
        self.bub = kept

    # ---- output --------------------------------------------------------------
    def snapshot(self, every=2):
        spd = np.sqrt(self.u * self.u + self.v * self.v)
        sub = spd[::every, ::every]
        return {
            "nx": self.nx, "ny": self.ny, "Lx": self.Lx, "Ly": self.Ly,
            "speed": [[round(float(x), 4) for x in row] for row in sub],
            "u_in": self.u_in,
            "bub": [[b[4], round(b[0] / self.Lx, 4), round(b[1] / self.Ly, 4),
                     round(b[2], 6)] for b in self.bub],   # [id, x/Lx, y/Ly, r] -> client interpolates by id
            "vmax": float(np.sqrt(self.u ** 2 + self.v ** 2).max()),
            "n_bub": len(self.bub),
        }
