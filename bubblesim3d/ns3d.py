"""3-D incompressible Navier-Stokes on a staggered MAC grid (Track A).

Chorin projection method with a staggered (Marker-And-Cell) layout so the
discrete divergence and pressure-gradient operators are CONSISTENT — the
projection drives divergence to machine precision (a collocated central-
difference scheme, like web3d/sim3d.js, leaves checkerboard modes it can't see;
we want a genuinely divergence-free field so the conservation tests mean
something).

    add forces (buoyancy from void + body force + inflow)
    -> explicit viscous diffusion             [substepped to nu*dt/h^2 <= 1/6]
    -> semi-Lagrangian advect                 [unconditionally stable]
    -> project (solve p, subtract grad p)     [divergence -> ~0, and it is the
                                               field the parcels then sample]

Staggered layout (cell size h, grid nx*ny*nz):
    U : x-faces  (nx+1, ny,   nz  ), located at (i h,      (j+.5)h, (k+.5)h)
    V : y-faces  (nx,   ny+1, nz  ), located at ((i+.5)h,  j h,     (k+.5)h)
    W : z-faces  (nx,   ny,   nz+1), located at ((i+.5)h,  (j+.5)h, k h)
    p : centres  (nx,   ny,   nz  )

Axis roles: x through-plane (electrode faces at x=0, x=Lx, no-slip),
y flow/height (inflow at y=0, open outlet at y=Ly), z width (side walls).

Viscosity is EXPLICIT (`nu` = mu/rho from the kernel context): an isotropic
Laplacian on each staggered component with no-slip ghosts at the solid walls, so
a straight duct relaxes to the parabolic Poiseuille profile and the wall shear is
a real number rather than numerical diffusion. It is substepped to stay inside
the explicit stability bound nu*dt/h^2 <= 1/6.

Honest scope: the cell-scale grid (h ~ 2 mm) does not RESOLVE the momentum
boundary layer of a 1 mm channel — the viscous term is present and correct, but
one cell across the channel cannot represent a parabola. Treat the cell view as a
qualitative buoyancy-driven visualiser (plumes, self-stirring, tilt gas-trapping)
and the Poiseuille test as proof that the operator is right when you do resolve
it. The pressure solve is warm-started from the previous step for speed.
"""
import numpy as np

from .grid import Grid3D
from bubblesim.constants import G


class NS3D:
    def __init__(self, grid: Grid3D, outlet=True, omega=1.7):
        self.g = grid
        self.OUTLET = bool(outlet)       # y-top open (p=0) outlet vs closed box
        self.omega = float(omega)
        nx, ny, nz = grid.shape
        self.U = np.zeros((nx + 1, ny, nz))
        self.V = np.zeros((nx, ny + 1, nz))
        self.W = np.zeros((nx, ny, nz + 1))
        self.p = np.zeros((nx, ny, nz))
        self.gas = np.zeros(grid.shape)
        # CellSim3D replaces this with (rho_l-rho_g)/rho_l from the property
        # context.  1.0 is the physical light-gas limit for standalone tests.
        self.buoy = 1.0
        # kinematic viscosity [m^2/s]; 0 disables the viscous term. CellSim3D
        # sets it from the kernel context (mu / rho_l).
        self.nu = 0.0
        # legacy linear drag [1/s]. It was standing in for viscosity; with `nu`
        # set it is redundant and defaults to 0 (see CellSim3D).
        self.damp = 3.0
        # z-walls: no-slip by default. Tests that want a PLANE channel (exact
        # Poiseuille in x) switch them to free-slip.
        self.noslip_z = True
        self.drag_K = 60.0       # interphase blocking [1/s per unit void]:
                                 # Brinkman-type penalization — electrolyte loses
                                 # momentum inside gassy cells, so through-flow
                                 # DEFLECTS AROUND bubble clouds instead of
                                 # passing through (grid-scale Euler-Euler drag,
                                 # not an interface-resolved bubble)
        self.fy_body = 0.0
        self.u_in = 0.0
        # inlet mask over the bottom face (nx, nz): 1 = inflow port, 0 = wall.
        # Default all-open (plain box); the cell engine restricts it to the
        # flow-field inlet port so channel velocity == pump velocity.
        self.inlet = np.ones((grid.nx, grid.nz))
        # outlet mask over the top face (nx, nz): 1 = open port (Dirichlet p=0),
        # 0 = wall (Neumann). Default all-open, i.e. the whole y-top face vents.
        # A real plate vents through a PORT, so the exit position is a design
        # lever exactly like the inlet port.
        self.outlet = np.ones((grid.nx, grid.nz))
        # SIDE ports on the z-faces (nx, ny). A real plate can be fed from an
        # edge manifold rather than from below; the physics is the same boundary
        # condition, just on a different face. Index 0 = z=0, 1 = z=Lz.
        # inflow is directed INTO the domain on both sides.
        self.inlet_z = np.zeros((2, grid.nx, grid.ny))
        self.outlet_z = np.zeros((2, grid.nx, grid.ny))
        self.up = np.array([0.0, 1.0, 0.0])
        # solid-obstacle support (ribs/lands); set via set_solid()
        self.solid = np.zeros(grid.shape, dtype=bool)
        self._Ublock = np.zeros(self.U.shape, dtype=bool)
        self._Vblock = np.zeros(self.V.shape, dtype=bool)
        self._Wblock = np.zeros(self.W.shape, dtype=bool)
        # red-black masks over pressure centres
        ii, jj, kk = np.indices(grid.shape)
        self._parity = (ii + jj + kk) % 2
        self._red = self._parity == 0
        self._black = ~self._red
        # precompute the pressure divisor (Neumann walls drop a neighbour; the
        # y-top Dirichlet outlet keeps 6). Constant across steps.
        self._ndiv = self._build_ndiv()
        self._nsum = np.zeros(grid.shape)          # reusable neighbour-sum buffer
        # precompute static face-centre coordinates for semi-Lagrangian advect
        self._fc_U = self._face_coords(self.U.shape, self._OFF_U)
        self._fc_V = self._face_coords(self.V.shape, self._OFF_V)
        self._fc_W = self._face_coords(self.W.shape, self._OFF_W)

    def _build_ndiv(self):
        """Neighbour count per pressure cell.

        A Neumann (wall / prescribed-inflow) face drops its neighbour; a
        Dirichlet outflow face keeps it, because the ghost pressure outside is a
        known 0. Every boundary type has to agree with what `project` subtracts.
        """
        ndiv = np.full(self.g.shape, 6.0)
        ndiv[0, :, :] -= 1; ndiv[-1, :, :] -= 1        # x-walls (Neumann)
        ndiv[:, 0, :] -= 1                              # y-bottom inflow (Neumann)
        # z-faces: wall/inflow -> Neumann, outflow port -> Dirichlet ghost p=0
        ndiv[:, :, 0] -= (1.0 - self.outlet_z[0])
        ndiv[:, :, -1] -= (1.0 - self.outlet_z[1])
        if self.OUTLET:
            # open cells keep the p=0 ghost neighbour (6); closed ones are walls
            ndiv[:, -1, :] -= (1.0 - self.outlet)
        else:                                          # closed box: y-top Neumann too
            ndiv[:, -1, :] -= 1
        return ndiv

    def set_ports(self, inlet=None, outlet=None, inlet_z=None, outlet_z=None):
        """Install boundary port masks and rebuild the pressure divisor.

        inlet/outlet: (nx,nz) on y=0 / y=Ly.  inlet_z/outlet_z: (2,nx,ny) on
        z=0 / z=Lz. An inflow and an outflow port may not overlap on the same
        face, and at least one outflow cell must exist anywhere — an
        incompressible flow with an inlet and no exit has no solution.
        """
        nx, ny, nz = self.g.shape
        if inlet is not None:
            self.inlet = np.asarray(inlet, dtype=float).reshape(nx, nz)
        if outlet is not None:
            self.outlet = np.asarray(outlet, dtype=float).reshape(nx, nz)
        if inlet_z is not None:
            self.inlet_z = np.asarray(inlet_z, dtype=float).reshape(2, nx, ny)
        if outlet_z is not None:
            self.outlet_z = np.asarray(outlet_z, dtype=float).reshape(2, nx, ny)
        # no cell may be both fed and vented
        self.outlet_z = self.outlet_z * (1.0 - np.minimum(1.0, self.inlet_z))
        if self.OUTLET and self.outlet.sum() + self.outlet_z.sum() <= 0:
            self.outlet = np.ones((nx, nz))
        self.set_solid(self.solid)          # rebuilds ndiv (it reads the masks)

    def set_outlet(self, mask):
        """Back-compat: install the y-top outflow mask only."""
        m = np.asarray(mask, dtype=float).reshape(self.g.nx, self.g.nz)
        if m.sum() <= 0 and self.outlet_z.sum() <= 0:
            m = np.ones_like(m)
        self.set_ports(outlet=m)

    def set_solid(self, solid):
        """Mark obstacle (land/rib) cells. A face touching a solid cell is a
        no-flow wall; a fluid cell drops each solid-facing neighbour from its
        pressure stencil (internal Neumann wall)."""
        self.solid = np.asarray(solid, dtype=bool)
        s = self.solid
        # blocked faces: interior face solid if either adjacent cell is solid;
        # every face on/adjacent to an obstacle carries zero normal velocity
        self._Ublock[:] = False
        self._Ublock[1:-1, :, :] = s[:-1] | s[1:]
        self._Ublock[0, :, :] |= s[0]; self._Ublock[-1, :, :] |= s[-1]
        self._Vblock[:] = False
        self._Vblock[:, 1:-1, :] = s[:, :-1] | s[:, 1:]
        self._Vblock[:, 0, :] |= s[:, 0]; self._Vblock[:, -1, :] |= s[:, -1]
        self._Wblock[:] = False
        self._Wblock[:, :, 1:-1] = s[:, :, :-1] | s[:, :, 1:]
        self._Wblock[:, :, 0] |= s[:, :, 0]; self._Wblock[:, :, -1] |= s[:, :, -1]
        # rebuild the pressure divisor: fluid cells drop solid neighbours
        ndiv = self._build_ndiv()
        drop = np.zeros(self.g.shape)
        drop[:-1] += s[1:]; drop[1:] += s[:-1]         # +x / -x solid neighbours
        drop[:, :-1] += s[:, 1:]; drop[:, 1:] += s[:, :-1]
        drop[:, :, :-1] += s[:, :, 1:]; drop[:, :, 1:] += s[:, :, :-1]
        ndiv = np.maximum(1.0, ndiv - drop)
        ndiv[s] = 1.0                                  # solid cells: dummy divisor
        self._ndiv = ndiv
        # relax pressure on fluid cells only
        fluid = ~s
        self._red = (self._parity == 0) & fluid
        self._black = (self._parity == 1) & fluid
        self._apply_solid()

    def _apply_solid(self):
        if not self.solid.any():
            return
        self.U[self._Ublock] = 0.0
        self.V[self._Vblock] = 0.0
        self.W[self._Wblock] = 0.0
        self.p[self.solid] = 0.0

    # --------------------------------------------------------- gravity / tilt
    def set_tilt(self, tilt_deg):
        a = np.radians(tilt_deg)
        self.up = np.array([np.sin(a), np.cos(a), 0.0])

    # --------------------------- centre-averaged velocity (for parcels / view)
    def centres(self):
        u = 0.5 * (self.U[:-1] + self.U[1:])
        v = 0.5 * (self.V[:, :-1] + self.V[:, 1:])
        w = 0.5 * (self.W[:, :, :-1] + self.W[:, :, 1:])
        return u, v, w

    def speed(self):
        u, v, w = self.centres()
        return np.sqrt(u * u + v * v + w * w)

    # ------------------------------------------------------------ boundaries
    def _apply_bc(self):
        """Prescribe the fixed (solid-wall + inflow) normal face velocities.

        The outlet face V[:, -1, :] is NOT set here — the projection updates it
        through the p=0 outlet boundary, so overwriting it afterwards (the old
        zero-gradient copy) would re-inject divergence into the top row."""
        self.U[0, :, :] = 0.0;  self.U[-1, :, :] = 0.0      # electrode x-faces
        self.V[:, 0, :] = self.u_in * self.inlet            # y-bottom inflow port
        if self.OUTLET:
            self.V[:, -1, :] *= self.outlet                 # closed part of the top
        else:
            self.V[:, -1, :] = 0.0                          # closed-box solid top
        # z-faces: inflow prescribed (pointing INTO the domain), outflow left to
        # the projection, everything else a wall. Multiplying by the outflow mask
        # keeps the projected value on the port and zeroes the plate.
        self.W[:, :, 0] = (self.u_in * self.inlet_z[0]
                           + self.W[:, :, 0] * self.outlet_z[0])
        self.W[:, :, -1] = (-self.u_in * self.inlet_z[1]
                            + self.W[:, :, -1] * self.outlet_z[1])
        self._apply_solid()                                 # zero flow through lands

    # --------------------------------------------------------------- forces
    def add_forces(self, dt):
        gb = G * self.buoy
        d = max(0.0, 1.0 - self.damp * dt)
        # interpolate centre gas fraction onto each face (used by both the
        # buoyancy source and the blocking drag)
        g = self.gas
        gx = np.zeros_like(self.U)          # x-faces
        gx[1:-1, :, :] = 0.5 * (g[:-1] + g[1:])
        gy = np.zeros_like(self.V)          # y-faces
        gy[:, 1:-1, :] = 0.5 * (g[:, :-1] + g[:, 1:])
        gz = np.zeros_like(self.W)          # z-faces
        gz[:, :, 1:-1] = 0.5 * (g[:, :, :-1] + g[:, :, 1:])
        # (1) blocking drag: penalize liquid momentum inside gassy cells
        # (Brinkman / Euler-Euler interphase drag) -> flow reroutes around
        # bubble curtains via the pressure projection
        K = self.drag_K * dt
        self.U *= d / (1.0 + K * gx)
        self.V *= d / (1.0 + K * gy)
        self.W *= d / (1.0 + K * gz)
        # (2) buoyancy from void, along 'up' (applied after the drag so the
        # bubble plume itself still drives an upward liquid current)
        self.U += gb * gx * dt * self.up[0]
        self.V += gb * gy * dt * self.up[1] + self.fy_body * dt
        self.W += gb * gz * dt * self.up[2]
        self._apply_bc()

    # ------------------------------------------------------------- viscosity
    @staticmethod
    def _lap(f, gx0, gx1, gy0, gy1, gz0, gz1, h):
        """6-point Laplacian with per-face ghost SIGNS.

        sign = -1 -> no-slip wall half a cell outside (ghost = -f, so the wall
        value interpolates to zero); sign = +1 -> zero-gradient (outflow);
        sign = 0 -> the face is prescribed, its Laplacian is discarded anyway.
        """
        lap = -6.0 * f
        lap[1:, :, :] += f[:-1, :, :];  lap[0, :, :] += gx0 * f[0, :, :]
        lap[:-1, :, :] += f[1:, :, :];  lap[-1, :, :] += gx1 * f[-1, :, :]
        lap[:, 1:, :] += f[:, :-1, :];  lap[:, 0, :] += gy0 * f[:, 0, :]
        lap[:, :-1, :] += f[:, 1:, :];  lap[:, -1, :] += gy1 * f[:, -1, :]
        lap[:, :, 1:] += f[:, :, :-1];  lap[:, :, 0] += gz0 * f[:, :, 0]
        lap[:, :, :-1] += f[:, :, 1:];  lap[:, :, -1] += gz1 * f[:, :, -1]
        return lap / (h * h)

    def diffuse(self, dt):
        """Explicit viscous update, substepped to the stability bound.

        Obstacle faces already carry zero velocity (`_apply_solid`), so a fluid
        face next to a rib sees a zero neighbour — the standard no-slip
        treatment for a voxelized wall. Only the DOMAIN ghosts need signs:
          * electrode x-walls, z side walls  -> no-slip (-1)
          * y=0 inflow plane                 -> no tangential slip (-1)
          * y=Ly outlet                      -> zero gradient (+1)
        """
        if self.nu <= 0.0:
            return
        h = self.g.h
        n_sub = max(1, int(np.ceil(6.0 * self.nu * dt / (h * h))))
        sdt = self.nu * dt / n_sub
        zs = -1.0 if self.noslip_z else 1.0
        # a venting z-face is an outflow: tangential zero-gradient, not no-slip.
        # (Per-face, not per-cell — the ghost sign is a whole-slab choice.)
        zs0 = 1.0 if self.outlet_z[0].any() else zs
        zs1 = 1.0 if self.outlet_z[1].any() else zs
        yo = 1.0 if self.OUTLET else -1.0            # outlet: zero-gradient
        for _ in range(n_sub):
            # U: normal on x (prescribed), tangential on y and z
            self.U += sdt * self._lap(self.U, 1, 1, -1, yo, zs0, zs1, h)
            # V: normal on y (prescribed at both ends), tangential on x and z
            self.V += sdt * self._lap(self.V, -1, -1, 1, 1, zs0, zs1, h)
            # W: normal on z (prescribed), tangential on x and y
            self.W += sdt * self._lap(self.W, -1, -1, -1, yo, 1, 1, h)
            self._apply_bc()

    # --------------------------------------------------------------- project
    def _divergence(self):
        h = self.g.h
        return ((self.U[1:] - self.U[:-1]) +
                (self.V[:, 1:] - self.V[:, :-1]) +
                (self.W[:, :, 1:] - self.W[:, :, :-1])) / h

    def _neighbour_sum(self, p):
        s = self._nsum
        s.fill(0.0)
        s[1:, :, :] += p[:-1, :, :]; s[:-1, :, :] += p[1:, :, :]
        s[:, 1:, :] += p[:, :-1, :]; s[:, :-1, :] += p[:, 1:, :]
        s[:, :, 1:] += p[:, :, :-1]; s[:, :, :-1] += p[:, :, 1:]
        return s

    def project(self, iters=60, warm=True, tol=0.0, chunk=8):
        """Chorin projection. `tol` (relative, div*h/v_max) enables an early exit.

        The linear residual R = ndiv*p - sum(neighbours) + rhs is exactly the
        divergence the corrected velocity will still carry, times h^2. So we can
        stop the SOR the moment the flow is divergence-free ENOUGH instead of
        burning a fixed sweep count — with a warm start most steps converge in a
        fraction of the budget, and the hard steps get the sweeps they need.
        """
        h = self.g.h
        div = self._divergence()
        p = self.p
        if not warm:                     # cold solve (standalone / tests)
            p.fill(0.0)
        rhs = div * h * h
        om = self.omega
        ndiv = self._ndiv                # precomputed divisor (Neumann/Dirichlet)
        red, black = self._red, self._black
        vs = max(float(np.abs(self.U).max()), float(np.abs(self.V).max()),
                 float(np.abs(self.W).max()), 1e-9) if tol > 0 else 0.0
        fluid = ~self.solid
        done = 0
        # red-black SOR; update only the masked cells (half the work per sweep)
        while done < iters:
            n = min(chunk, iters - done) if tol > 0 else iters
            for _ in range(n):
                s = self._neighbour_sum(p)
                p[red] = (1 - om) * p[red] + om * (s[red] - rhs[red]) / ndiv[red]
                s = self._neighbour_sum(p)
                p[black] = (1 - om) * p[black] + om * (s[black] - rhs[black]) / ndiv[black]
            done += n
            if tol <= 0:
                break
            res = np.abs(ndiv * p - self._neighbour_sum(p) + rhs)
            res[self.solid] = 0.0
            if float(res.max()) / (h * vs) < tol:      # res/h^2 * h / v_max
                break
        self.sweeps = done
        # subtract pressure gradient. Interior faces use the neighbour difference;
        # the outlet top face uses the Dirichlet ghost p=0. Solid-wall + inflow
        # normal faces are prescribed, so they are left untouched.
        self.U[1:-1, :, :] -= (p[1:, :, :] - p[:-1, :, :]) / h
        self.V[:, 1:-1, :] -= (p[:, 1:, :] - p[:, :-1, :]) / h
        self.W[:, :, 1:-1] -= (p[:, :, 1:] - p[:, :, :-1]) / h
        if self.OUTLET:                                   # ghost p=0 above the port
            self.V[:, -1, :] -= self.outlet * (0.0 - p[:, -1, :]) / h
        # side outflow ports: ghost p=0 just outside the z-faces
        if self.outlet_z[0].any():
            self.W[:, :, 0] -= self.outlet_z[0] * (p[:, :, 0] - 0.0) / h
        if self.outlet_z[1].any():
            self.W[:, :, -1] -= self.outlet_z[1] * (0.0 - p[:, :, -1]) / h
        self._apply_bc()

    def max_divergence(self):
        return float(np.abs(self._divergence()).max())

    # --------------------------------------------------------------- advect
    def _sample(self, field, origin, pts):
        """Trilinear sample of a staggered `field` whose index (0,0,0) sits at
        `origin` (in cell units) — pts are (N,3) metres."""
        g = np.asarray(pts) / self.g.h - np.asarray(origin)     # index-space coords
        nx, ny, nz = field.shape
        i0 = np.floor(g).astype(np.int64)
        i0[:, 0] = np.clip(i0[:, 0], 0, nx - 2)
        i0[:, 1] = np.clip(i0[:, 1], 0, ny - 2)
        i0[:, 2] = np.clip(i0[:, 2], 0, nz - 2)
        fr = np.clip(g - i0, 0.0, 1.0)
        i, j, k = i0[:, 0], i0[:, 1], i0[:, 2]
        fx, fy, fz = fr[:, 0], fr[:, 1], fr[:, 2]
        c000 = field[i, j, k];         c100 = field[i + 1, j, k]
        c010 = field[i, j + 1, k];     c110 = field[i + 1, j + 1, k]
        c001 = field[i, j, k + 1];     c101 = field[i + 1, j, k + 1]
        c011 = field[i, j + 1, k + 1]; c111 = field[i + 1, j + 1, k + 1]
        lx0 = c000 + (c100 - c000) * fx; lx1 = c010 + (c110 - c010) * fx
        lx2 = c001 + (c101 - c001) * fx; lx3 = c011 + (c111 - c011) * fx
        ly0 = lx0 + (lx1 - lx0) * fy;    ly1 = lx2 + (lx3 - lx2) * fy
        return ly0 + (ly1 - ly0) * fz

    # face-origin offsets in cell units (see layout in the module docstring)
    _OFF_U = (0.0, 0.5, 0.5)
    _OFF_V = (0.5, 0.0, 0.5)
    _OFF_W = (0.5, 0.5, 0.0)

    def _sample_vel(self, pts):
        return (self._sample(self.U, self._OFF_U, pts),
                self._sample(self.V, self._OFF_V, pts),
                self._sample(self.W, self._OFF_W, pts))

    def _face_coords(self, shape, origin):
        ii, jj, kk = np.indices(shape)
        x = (ii + origin[0]) * self.g.h
        y = (jj + origin[1]) * self.g.h
        z = (kk + origin[2]) * self.g.h
        return np.stack([x.ravel(), y.ravel(), z.ravel()], axis=1)

    def advect(self, dt):
        U0, V0, W0 = self.U.copy(), self.V.copy(), self.W.copy()
        for field, off, fc, comp in ((self.U, self._OFF_U, self._fc_U, 0),
                                     (self.V, self._OFF_V, self._fc_V, 1),
                                     (self.W, self._OFF_W, self._fc_W, 2)):
            uu, vv, ww = self._sample_vel(fc)                   # full velocity at faces
            back = fc - dt * np.stack([uu, vv, ww], axis=1)
            src = (self._sample(U0, self._OFF_U, back) if comp == 0 else
                   self._sample(V0, self._OFF_V, back) if comp == 1 else
                   self._sample(W0, self._OFF_W, back))
            field[...] = src.reshape(field.shape)
        self._apply_bc()

    # ----------------------------------------------------------------- step
    def step(self, dt, proj_iters=60, tol=0.0):
        """forces -> viscosity -> ADVECT -> project.

        The projection is LAST, so the field everything downstream samples (the
        bubble parcels, the arrow overlay, the slice view) is the divergence-free
        one. Projecting before the advection instead left the sampled field
        carrying the advection's own divergence — a 6x larger residual for the
        same sweep count, and it is the field that actually moves the bubbles.
        """
        self.add_forces(dt)
        self.diffuse(dt)
        self.advect(dt)
        self.project(proj_iters, tol=tol)

    # ------------------------------------- point sampling for parcels (centre)
    def sample_velocity(self, pts):
        """Full velocity at arbitrary points (N,3) [m] -> (u,v,w) each (N,)."""
        if len(pts) == 0:
            z = np.zeros(0)
            return z, z, z
        return self._sample_vel(np.asarray(pts, dtype=np.float64))
