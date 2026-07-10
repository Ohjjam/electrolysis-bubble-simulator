"""CellSim3D — the cell-scale 3-D engine (Track A).

One dimension up from bubblesim.solvers.flow2d, at cell scale: incompressible
NS on the gap + Lagrangian gas parcels, two-way coupled through the void field.
The scalar operating point (cell voltage, mean current density, overpotential
split) still comes from the FROZEN kernel electrochemistry
(ZeroDTwoElectrodeSolver over build_context) — this engine is a 3-D field
visualiser wrapped around the same canonical numbers, never a re-derivation.

Honest scope: sub-grid parcels (no resolved interfaces -> not VOF); the
electrode-face current redistribution (θ-driven) lands in P2. Here every face
sees the mean current density.
"""
import numpy as np

from .grid import Grid3D
from .ns3d import NS3D
from .parcels import Parcels
from . import faceredist
from bubblesim.kernel.context import build_context
from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver


class _Stub:
    """Surface stand-in carrying the 3-D bubble population's coverage / void
    into the scalar two-electrode solve (same pattern as face2d._Stub) — so
    bubble blanketing RAISES the cell voltage, closing the blocking feedback."""

    def __init__(self, theta, eps):
        self._t, self._e = theta, eps

    def coverage(self):
        return self._t

    def void_fraction(self):
        return self._e


class CellSim3D:
    def __init__(self, op, params, dims, h, cap=6000, tilt=0.0, seed=0, cfg=None):
        self.op = op
        self.params = params
        self.grid = Grid3D(*dims, h)
        self.ns = NS3D(self.grid)
        self.ns.set_tilt(tilt)
        self.ns.u_in = max(0.0, op.u_flow)
        self.tilt = tilt
        # voxelize the flow field (ribs/lands) so flow steers around the lands
        self.face_c = self.face_a = None
        self.n_lay = 0
        self.inlet_area = 0.0
        self.port_in = self.port_out = None
        self.in_face = self.out_face = None
        elec_planes = None
        if cfg is not None:
            from .geometry import voxelize, port_edges
            solid, self.face_c, self.face_a = voxelize(cfg, self.grid)
            self.ns.set_solid(solid)
            nx, ny, nz = self.grid.shape
            # each port lives on the edge the designer picked; the pump feeds
            # only its cells (channel velocity == u_flow, no gap jets) and the
            # rest of every boundary face is plate.
            self.in_face, port_in, self.out_face, port_out =                 port_edges(cfg, self.grid, ~self.face_c)
            self.port_in, self.port_out = port_in, port_out
            zeros_y = np.zeros((nx, nz)); zeros_z = np.zeros((2, nx, ny))
            inlet, outlet = zeros_y.copy(), zeros_y.copy()
            inlet_z, outlet_z = zeros_z.copy(), zeros_z.copy()
            if self.in_face == "bottom":
                inlet[:] = port_in[None, :]
            else:
                inlet_z[0 if self.in_face == "left" else 1] = port_in[None, :]
            if self.out_face == "top":
                outlet[:] = port_out[None, :]
            else:
                outlet_z[0 if self.out_face == "left" else 1] = port_out[None, :]
            self.ns.set_ports(inlet=inlet, outlet=outlet,
                              inlet_z=inlet_z, outlet_z=outlet_z)
            # electrode (catalyst) planes = the core boundaries: in a zero-gap
            # cell the gas emerges on the MEMBRANE side of each channel
            self.n_lay = max(1, min(cfg.layer_counts()[0], (self.grid.nx - 1) // 2))
            elec_planes = (self.n_lay * h, self.grid.Lx - self.n_lay * h)
            # open inlet cross-section [m^2] -> pumped liquid flow rate, so the
            # UI can show the gas/liquid ratio (an under-pumped cell chokes)
            if self.in_face == "bottom":
                open_face = ~solid[:, 0, :]
                n_open = int((open_face & (self.ns.inlet > 0)).sum())
            else:
                k = 0 if self.in_face == "left" else -1
                open_face = ~solid[:, :, k]
                n_open = int((open_face & (self.ns.inlet_z[0 if k == 0 else 1] > 0)).sum())
            self.inlet_area = float(n_open) * h * h
        rng = np.random.default_rng(seed)
        # PHYSICAL channel depth (mm -> m): the opposite plate confines the
        # bubble, so a 0.2 mm channel must not let a 450 um sphere grow.
        self.channel_depth = max(1e-5, float(cfg.d_ch_mm) * 1e-3)
        self.parcels = Parcels(self.grid, op, rng, cap=cap,
                               face_masks=(self.face_c, self.face_a),
                               elec_planes=elec_planes, params=params,
                               channel_depth=self.channel_depth,
                               # gas leaves where the liquid leaves. An all-open
                               # top needs no test at all.
                               vent_face=self.out_face,
                               vent_line=(self.port_out
                                          if self.port_out is not None
                                          and not (self.out_face == "top"
                                                   and self.port_out.all())
                                          else None))
        # kernel scalar solver (cached like server_app's CachedSolver)
        self._solver = ZeroDTwoElectrodeSolver(n_outer=28, n_inner=24)
        self._every = 8
        self._n = 0
        self._state = None
        self.t = 0.0
        self.ctx = build_context(op, params)
        # REAL viscosity from the electrolyte, not a stand-in linear drag. The
        # old `damp = 3 /s` was an artificial momentum sink with no physical
        # counterpart; with nu present it goes.
        self.ns.nu = float(self.ctx["mu"]) / float(self.ctx["rho_l"])
        self.ns.damp = 0.0
        self._resolve()

    # --------------------------------------------------------- electrochem
    def _resolve(self):
        """Refresh the frozen-kernel scalar operating point, fed by the 3-D
        bubbles: their coverage/void enter the two-electrode balance, so gas
        blanketing raises the voltage (CP) / cuts the current (CA)."""
        self.ctx = build_context(self.op, self.params)
        self.ns.nu = float(self.ctx["mu"]) / float(self.ctx["rho_l"])  # T, c dependent
        p = self.parcels
        if len(p.r):
            stubs = [_Stub(p.coverage(0), p.void_near_wall(0)),
                     _Stub(p.coverage(1), p.void_near_wall(1))]
        else:
            stubs = [_Stub(0.0, 0.0), _Stub(0.0, 0.0)]
        self._state = self._solver.solve(self.op, self.ctx, stubs)
        return self._state

    def cell_current_A_m2(self):
        return max(0.0, self._state.j) if self._state else 0.0

    def cell_voltage(self):
        # in CA mode the solver's state.V may be None (V is the input) -> fall
        # back to the operating voltage
        if self._state is not None and self._state.V is not None:
            return self._state.V
        return self.op.V_cell

    # ---------------------------------------------------------------- update
    def set_operating(self, op, tilt=None):
        """Live parameter change (no domain rebuild)."""
        self.op = op
        self.parcels.op = op
        self.ns.u_in = max(0.0, op.u_flow)
        if tilt is not None:
            self.tilt = tilt
            self.ns.set_tilt(tilt)
        self._resolve()

    # ----------------------------------------------------------------- step
    # Relative divergence (div*h/v_max) the pressure solve must reach before it
    # may stop early; `proj_iters` is a CAP, not a fixed budget. Measured on the
    # default serpentine cell: a flat 12 sweeps left 1.27% residual at 0.24x
    # realtime; cap 80 + this tol leaves 0.21% at ~52 sweeps and 0.16x realtime.
    # Easy steps cost less than the old fixed budget; hard steps get what they need.
    PROJ_TOL = 2.0e-3

    def step(self, dt, proj_iters=80, tol=None):
        # refresh the scalar electrochem occasionally (it varies slowly)
        if self._n % self._every == 0:
            self._resolve()
        self._n += 1
        j = self.cell_current_A_m2()
        # two-way coupling: bubbles -> void -> buoyancy
        self.ns.gas = self.parcels.deposit_void()
        self.ns.step(dt, proj_iters, tol=self.PROJ_TOL if tol is None else tol)
        # bubble lifecycle (nucleate -> grow -> detach -> rise) in one call
        self.parcels.step(self.ns, j, dt, self.ctx)
        self.t += dt

    # ------------------------------------------------------------- snapshot
    def gas_liquid(self):
        """(gas, liquid) volumetric flow rates [m^3/s] and their ratio.

        A cell whose Faradaic gas rate rivals the pumped liquid rate CHOKES:
        the channel fills with gas, holdup runs away, ohmic loss climbs. This
        is the design number that tells you whether the pump is big enough.
        """
        from bubblesim.kernel.sources import faradaic_gas_rate as _fgr
        j = self.cell_current_A_m2()
        A = self.grid.Ly * self.grid.Lz
        q_gas = (_fgr(j, "HER", self.op.T, self.op.P, A)
                 + _fgr(j, "OER", self.op.T, self.op.P, A) * 0.5)
        q_liq = max(0.0, self.op.u_flow) * self.inlet_area
        return q_gas, q_liq, (q_gas / q_liq if q_liq > 0 else float("inf"))

    def _exit_radius(self):
        """Mean radius of the bubbles about to leave the cell — the size a gas
        separator downstream would actually see (coalescence has acted on them)."""
        p = self.parcels
        if len(p.r) == 0:
            return 0.0
        m = (~p.attached) & (p.pos[:, 1] > 0.8 * self.grid.Ly)
        if not m.any():
            m = ~p.attached
        return float(p.r[m].mean()) if m.any() else 0.0

    def diagnostics(self):
        p = self.parcels
        r_mean, r_std = p.size_stats()
        n_att = int(np.count_nonzero(p.attached)) if len(p.r) else 0
        # same near-wall-corrected departure radius the bubbles actually use,
        # including the seed floor the lifecycle enforces
        r_dep = max(2 * p.R_NUC,
                    p.departure_radius(self.ctx, max(1e-6, self.cell_current_A_m2())))
        n_real = float(p.mult.sum()) if len(p.r) else 0.0
        q_gas, q_liq, gl = self.gas_liquid()
        # --- numbers the UI needs to UNFOLD one representative bubble back into
        # the real site population for a true-micron local view. Each tracked
        # bubble stands for `mult` real ones, so a um-sized window would almost
        # never contain a tracked one; the local panel reconstructs the patch
        # from these (all straight out of the physics, nothing invented).
        from bubblesim.kernel.sources import faradaic_gas_rate as _fgr
        from .parcels import terminal_velocity as _vt
        A_face = self.grid.Ly * self.grid.Lz
        sites_m2 = self.params.site_density * (0.5 + self.op.contact_angle / 90.0)
        n_sites = max(1.0, sites_m2 * A_face)
        q_her = _fgr(self.cell_current_A_m2(), "HER", self.op.T, self.op.P, A_face)
        rate_m3_s = q_her / n_sites                  # gas fed to ONE real site
        v_term = float(_vt(np.array([r_dep]), self.ctx["d_rho"],
                           self.ctx["mu"], self.ctx["rho_l"])[0])
        return {
            "q_gas_mLs": round(q_gas * 1e6, 3),
            "q_liq_mLs": round(q_liq * 1e6, 3),
            "gas_liq": round(gl, 2) if np.isfinite(gl) else 999.0,
            "sites_per_mm2": round(sites_m2 * 1e-6, 3),
            "rate_um3_ms": round(rate_m3_s * 1e15, 4),   # um^3 per ms per site
            "v_term_mm_s": round(v_term * 1e3, 3),       # riser speed at r_dep
            "r_nuc_um": round(p.R_NUC * 1e6, 2),
            "spread": p.DETACH_SPREAD,
            "n_bub": int(len(p.r)),
            "n_attached": n_att,
            "n_free": int(len(p.r)) - n_att,
            "r_dep_um": round(r_dep * 1e6, 1),       # real departure radius
            "r_conf_um": round(p.r_conf() * 1e6, 1), # channel-gap size limit
            "d_ch_um": round(self.channel_depth * 1e6, 1),
            "p_merge": round(p.p_merge(), 3),        # coalescence on contact
            "n_merge": int(p.n_merge),               # on the wall
            "n_merge_free": int(p.n_merge_free),     # in the rising swarm
            "r_exit_um": round(self._exit_radius() * 1e6, 1),
            "sweeps": int(getattr(self.ns, "sweeps", 0)),
            "nu": float(self.ns.nu),
            "mult": round(float(p.site_mult(0)), 1), # 1 tracked = N real (attached)
            "n_real_est": int(n_real),               # real bubbles represented
            "r_mean_mm": round(r_mean * 1e3, 4),
            "r_std_mm": round(r_std * 1e3, 4),      # >0 => real size distribution
            "theta_c": round(p.coverage(0), 4),
            "theta_a": round(p.coverage(1), 4),
            "holdup": round(p.holdup(), 5),
            "vmax": round(float(self.ns.speed().max()), 4),
            "j_Acm2": round(self.cell_current_A_m2() / 1.0e4, 4),
            "V_cell": round(self.cell_voltage(), 4),
            "up": [round(float(x), 3) for x in self.ns.up],
        }

    def face_current_maps(self):
        """Electrode-face coverage + current-density maps from the 3-D parcels."""
        return faceredist.face_maps(self.parcels, self.grid,
                                    self.cell_current_A_m2(), self.op.contact_angle,
                                    self.face_c, self.face_a)

    def velocity_slice(self, frac=0.5):
        """Mid-plane (constant-z) speed field for a 2-D overlay: (ny, nx)."""
        k = int(np.clip(int(frac * self.grid.nz), 0, self.grid.nz - 1))
        sp = self.ns.speed()[:, :, k]           # (nx, ny)
        return {"nx": self.grid.nx, "ny": self.grid.ny,
                "field": np.round(sp.T, 5).ravel().tolist()}   # row-major (ny, nx)

    def snapshot(self, with_faces=True):
        snap = {
            "t": round(self.t, 4),
            "grid": {"nx": self.grid.nx, "ny": self.grid.ny, "nz": self.grid.nz,
                     "h_mm": self.grid.h * 1e3, "n_lay": self.n_lay,
                     "Lx_mm": self.grid.Lx * 1e3, "Ly_mm": self.grid.Ly * 1e3,
                     "Lz_mm": self.grid.Lz * 1e3},
            "bubbles": self.parcels.snapshot_flat(),
            "n_bub": int(len(self.parcels.r)),
            "diag": self.diagnostics(),
        }
        # gas-holdup height profile (mean void over x,z per y layer) — the
        # inlet->outlet accumulation curve, tiny payload, every poll
        snap["eps_prof"] = np.round(self.ns.gas.mean(axis=(0, 2)), 4).tolist()
        if with_faces:
            snap["faces"] = self.face_current_maps()
            # the PHYSICS land mask, so the renderer draws the ribs exactly
            # where the engine has them (turn gaps included) — bubbles passing
            # a gap must never look like they ghost through a drawn rib
            if self.face_c is not None:
                land = ~self.face_c
                snap["land2d"] = {"ny": int(land.shape[0]), "nz": int(land.shape[1]),
                                  "m": land.astype(int).ravel().tolist()}
            # the actual inlet/outlet boundary cells, so both views can DRAW the
            # ports where the projection really applies them
            if self.port_in is not None:
                snap["ports"] = {"nz": int(self.grid.nz), "ny": int(self.grid.ny),
                                 "in_face": self.in_face, "out_face": self.out_face,
                                 "in": self.port_in.astype(int).tolist(),
                                 "out": self.port_out.astype(int).tolist()}
            # full 3-D holdup field for the Euler-style contour view (~few KB,
            # refreshed on the faces cadence — the field evolves slowly)
            snap["gas3d"] = {"nx": self.grid.nx, "ny": self.grid.ny,
                             "nz": self.grid.nz,
                             "f": np.round(self.ns.gas, 3).ravel().tolist()}
            # centre velocities for the vector-arrow overlay (paper-style):
            # shows the flow deflecting around bubble clouds / lands
            u, v, w = self.ns.centres()
            snap["vel3d"] = {"u": np.round(u, 3).ravel().tolist(),
                             "v": np.round(v, 3).ravel().tolist(),
                             "w": np.round(w, 3).ravel().tolist()}
        return snap
