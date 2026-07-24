"""CellSim3D — the cell-scale 3-D reduced-order engine (Track A).

One dimension up from bubblesim.solvers.flow2d, at cell scale: incompressible
NS on the gap + Lagrangian gas parcels, two-way coupled through the void field.
The scalar operating point (cell voltage, mean current density, overpotential
split) still comes from the FROZEN kernel electrochemistry
(ZeroDTwoElectrodeSolver over build_context) — this engine is a 3-D field
visualiser wrapped around the same canonical numbers, never a re-derivation.

Honest scope: sub-grid representative parcels coupled to one incompressible
liquid velocity field. This is neither VOF nor a two-fluid CFD model: parcel
void, slip and d32 enter momentum exchange, but no gas-phase continuity
equation displaces liquid volume. The electrode-face current map is a
charge-conserving display diagnostic only; scalar electrochemistry and the
Faraday source continue to use the 0-D mean current density.
"""
import numpy as np

from .grid import Grid3D
from .ns3d import NS3D
from .parcels import Parcels
from . import faceredist
from bubblesim.constants import G
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
        self.cfg = cfg
        self.inlet_area = 0.0
        self.inlet_area_voxel = 0.0
        self.inlet_area_requested = 0.0
        self.channel_area_per_circuit = 0.0
        self.channel_area_requested_per_circuit = 0.0
        self.liquid_circuits = 0
        self.port_in = self.port_out = None
        self.in_face = self.out_face = None
        self.flow_connected = True
        elec_planes = None
        if cfg is not None:
            from .geometry import voxelize, port_edges, flow_connects
            solid, self.face_c, self.face_a = voxelize(cfg, self.grid)
            self.ns.set_solid(solid)
            nx, ny, nz = self.grid.shape
            self.n_lay = max(1, min(cfg.layer_counts()[0], (self.grid.nx - 1) // 2))
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
            # An anolyte-only cell has no liquid feed on the cathode (x-low)
            # channel. Close that part of both hydraulic boundaries instead of
            # merely applying a scalar water penalty while still pumping it.
            if bool(getattr(op, "dry_cathode", False)):
                inlet[:self.n_lay] = 0.0; outlet[:self.n_lay] = 0.0
                inlet_z[:, :self.n_lay] = 0.0; outlet_z[:, :self.n_lay] = 0.0
            self.ns.set_ports(inlet=inlet, outlet=outlet,
                              inlet_z=inlet_z, outlet_z=outlet_z)
            # a plate with no inlet->outlet channel cannot conserve mass; say so
            # loudly instead of reporting a converged-looking dead simulation
            self.flow_connected = flow_connects(self.face_c, port_in, self.in_face,
                                                port_out, self.out_face)
            # electrode (catalyst) planes = the core boundaries: in a zero-gap
            # cell the gas emerges on the MEMBRANE side of each channel
            elec_planes = (self.n_lay * h, self.grid.Lx - self.n_lay * h)
            # Open RESOLVED inlet cross-section [m^2]. ``u_flow`` is a channel
            # velocity, so the boundary condition and every velocity-based
            # closure must see that same value. The former mapping preserved
            # the requested sub-voxel area by diluting the voxel velocity;
            # departure/transport closures still used u_flow, giving two
            # velocities in one calculation.
            if self.in_face == "bottom":
                open_face = ~solid[:, 0, :]
                n_open = int((open_face & (self.ns.inlet > 0)).sum())
            else:
                k = 0 if self.in_face == "left" else -1
                open_face = ~solid[:, :, k]
                n_open = int((open_face & (self.ns.inlet_z[0 if k == 0 else 1] > 0)).sum())
            self.inlet_area_voxel = float(n_open) * h * h
            self.liquid_circuits = 1 if bool(getattr(op, "dry_cathode", False)) else 2
            self.channel_area_requested_per_circuit = cfg.channel_area_m2()
            self.inlet_area_requested = (self.channel_area_requested_per_circuit
                                         * self.liquid_circuits)
            self.inlet_area = self.inlet_area_voxel
            self.channel_area_per_circuit = (self.inlet_area / self.liquid_circuits
                                             if self.liquid_circuits else 0.0)
            self._sync_inlet_velocity()
        rng = np.random.default_rng(seed)
        # Use the depth the voxel domain ACTUALLY resolves. Mixing a requested
        # sub-voxel depth into parcel shear/confinement while NS used n_lay*h
        # gave two different channels in one calculation.
        # box mode (cfg=None) has no flow channel; Parcels accepts channel_depth
        # =None (no gap confinement). The rest of __init__ already brackets cfg
        # use with `if cfg is not None`, and diagnostics() guards cfg is None too.
        self.channel_depth = (max(1e-5, self.n_lay * self.grid.h)
                              if cfg is not None else None)
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
        self.ns.buoy = float(self.ctx["d_rho"]) / max(float(self.ctx["rho_l"]), 1e-12)
        self.ns.set_fluid_properties(self.ctx["rho_l"], self.ctx["mu"])
        self.ns.damp = 0.0
        self._resolve()

    # --------------------------------------------------------- electrochem
    def _resolve(self):
        """Refresh the frozen-kernel scalar operating point, fed by the 3-D
        bubbles: their coverage/void enter the two-electrode balance, so gas
        blanketing raises the voltage (CP) / cuts the current (CA)."""
        self.ctx = build_context(self.op, self.params)
        self.ns.nu = float(self.ctx["mu"]) / float(self.ctx["rho_l"])  # T, c dependent
        self.ns.buoy = float(self.ctx["d_rho"]) / max(float(self.ctx["rho_l"]), 1e-12)
        self.ns.set_fluid_properties(self.ctx["rho_l"], self.ctx["mu"])
        p = self.parcels
        if len(p.r):
            layer = float(self.ctx["near_layer_m"])
            stubs = [_Stub(p.coverage(0), p.void_near_wall(0, layer_m=layer)),
                     _Stub(p.coverage(1), p.void_near_wall(1, layer_m=layer))]
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
        # Parcels carry gas volume, not moles. Re-express the complete resident
        # and cumulative ledger at the new T/P basis before adding a new source.
        from bubblesim.kernel.sources import gas_molar_volume
        new_ctx = build_context(op, self.params)
        old_vm = gas_molar_volume(
            self.op.T, self.op.P,
            wet=bool(getattr(self.op, "high_fidelity", False)),
            water_activity=self.ctx.get("water_activity", 1.0))
        new_vm = gas_molar_volume(
            op.T, op.P,
            wet=bool(getattr(op, "high_fidelity", False)),
            water_activity=new_ctx.get("water_activity", 1.0))
        self.parcels.rescale_volume_basis(new_vm / old_vm)
        self.op = op
        self.parcels.op = op
        self._sync_inlet_velocity()
        if tilt is not None:
            self.tilt = tilt
            self.ns.set_tilt(tilt)
        self._resolve()

    def _sync_inlet_velocity(self):
        """Apply the requested mean velocity on the resolved voxel inlet."""
        q_target = max(0.0, self.op.u_flow) * self.inlet_area
        self.ns.u_in = (q_target / self.inlet_area_voxel
                        if self.inlet_area_voxel > 0.0 else 0.0)

    # ----------------------------------------------------------------- step
    # Relative divergence (div*h/v_max) the pressure solve must reach before it
    # may stop early; `proj_iters` is a CAP, not a fixed budget. Measured on the
    # default serpentine cell: a flat 12 sweeps left 1.27% residual at 0.24x
    # realtime; cap 80 + this tol leaves 0.21% at ~52 sweeps and 0.16x realtime.
    # Easy steps cost less than the old fixed budget; hard steps get what they need.
    PROJ_TOL = 2.0e-3

    def step(self, dt, proj_iters=80, tol=None, *, trace_hook=None):
        # refresh the scalar electrochem occasionally (it varies slowly)
        if self._n % self._every == 0:
            self._resolve()
        self._n += 1
        j = self.cell_current_A_m2()
        # Two-way coupling from parcel-derived phase fraction, Sauter diameter
        # and gas velocity. NS3D derives the exchange rate from local physics;
        # there is no fitted global drag strength.
        gas, gas_velocity, diameter = self.parcels.interphase_fields(self.ns, self.ctx)
        self.ns.set_interphase(gas, gas_velocity, diameter)
        self.ns.step(dt, proj_iters, tol=self.PROJ_TOL if tol is None else tol)
        # bubble lifecycle (nucleate -> grow -> detach -> rise) in one call
        self.parcels.step(self.ns, j, dt, self.ctx, trace_hook=trace_hook)
        self.t += dt

    # ------------------------------------------------------------- snapshot
    def gas_liquid(self):
        """(gas, liquid) volumetric flow rates [m^3/s] and their ratio.

        The ratio is a screening diagnostic, not a quantitative choking
        prediction. This reduced model has no gas-phase continuity equation
        and cannot close liquid displacement at high void fraction.
        """
        from bubblesim.kernel.sources import faradaic_gas_rate as _fgr
        j = self.cell_current_A_m2()
        A = self.grid.Ly * self.grid.Lz
        kw = {"eta_F": self.params.eta_faraday,
              "wet": bool(getattr(self.op, "high_fidelity", False)),
              "water_activity": self.ctx.get("water_activity", 1.0)}
        q_gas = (_fgr(j, "HER", self.op.T, self.op.P, A, **kw)
                 + _fgr(j, "OER", self.op.T, self.op.P, A, **kw))
        q_liq = max(0.0, self.op.u_flow) * self.inlet_area
        return q_gas, q_liq, (q_gas / q_liq if q_liq > 0 else float("inf"))

    def _geom_widths(self):
        if self.cfg is None or self.cfg.ff == "custom":
            return {"h_mm": round(self.grid.h * 1e3, 2)}
        pitch, rib, chan = self.cfg.rib_channel_mm()
        return {"h_mm": round(self.grid.h * 1e3, 2),
                "pitch_mm": round(pitch, 2),
                "rib_mm": round(rib, 2),
                "chan_mm": round(chan, 2),
                "rib_req_mm": round(self.cfg.w_land_mm, 2),
                "chan_req_mm": round(self.cfg.w_ch_mm, 2)}

    def _exit_radius(self):
        """Mean radius of the bubbles about to leave the cell — the size a gas
        separator downstream would actually see (coalescence has acted on them)."""
        p = self.parcels
        if len(p.r) == 0:
            return 0.0
        p._ensure_state_arrays()
        free = (~p.attached) & (~p.mesh_attached)
        m = free & (p.pos[:, 1] > 0.8 * self.grid.Ly)
        if not m.any():
            m = free
        if not m.any():
            return 0.0
        weights = np.maximum(0.0, p.mult[m])
        return (float(np.sum(weights * p.r[m]) / weights.sum())
                if weights.sum() > 0.0 else 0.0)

    def diagnostics(self):
        p = self.parcels
        r_mean, r_std = p.size_stats()
        p._ensure_state_arrays()
        n_att = int(np.count_nonzero(p.attached)) if len(p.r) else 0
        n_mesh = int(np.count_nonzero(p.mesh_attached)) if len(p.r) else 0
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
        q_her = _fgr(self.cell_current_A_m2(), "HER", self.op.T, self.op.P, A_face,
                     eta_F=self.params.eta_faraday,
                     wet=bool(getattr(self.op, "high_fidelity", False)),
                     water_activity=self.ctx.get("water_activity", 1.0))
        rate_m3_s = q_her / n_sites                  # gas fed to ONE real site
        v_term = float(_vt(np.array([r_dep]), self.ctx["d_rho"],
                           self.ctx["mu"], self.ctx["rho_l"])[0])
        if len(p.r):
            eo = (G * float(self.ctx["d_rho"]) * (2.0 * p.r) ** 2
                  / max(float(self.ctx["sigma"]), 1e-30))
            tomiyama_in_range = float(np.mean((eo >= 1.39) & (eo <= 5.74)))
            eo_min, eo_max = float(eo.min()), float(eo.max())
        else:
            tomiyama_in_range = 0.0
            eo_min = eo_max = 0.0
        geom = self._geom_widths()
        quant_tol_mm = 0.5 * self.grid.h * 1e3
        if self.cfg is not None and self.cfg.ff != "custom":
            geom_match = (
                abs(geom["rib_mm"] - self.cfg.w_land_mm) <= quant_tol_mm + 1e-12
                and abs(geom["chan_mm"] - self.cfg.w_ch_mm) <= quant_tol_mm + 1e-12
                and abs(self.n_lay * self.grid.h * 1e3 - self.cfg.d_ch_mm)
                    <= quant_tol_mm + 1e-12)
        else:
            geom_match = True
        fields = self._state.fields if self._state is not None else {}
        med = str(self.ctx.get("electrolyte", "KOH"))
        if self.ctx.get("input_range_valid", False):
            electrolyte_status = (
                "KOH correlation range; target-cell calibration/validation still required")
        elif med == "KOH":
            electrolyte_status = "KOH input outside a stated property/activity range"
        else:
            electrolyte_status = (
                "rough property path; electrolyte-specific kinetics and validation required")
        vmax = float(self.ns.speed().max())
        rel_div = self.ns.max_divergence() * self.grid.h / max(vmax, 1e-12)
        return {
            "q_gas_mLs": round(q_gas * 1e6, 3),
            "q_liq_mLs": round(q_liq * 1e6, 3),
            "q_liq_per_circuit_mLs": round(
                max(0.0, self.op.u_flow) * self.channel_area_per_circuit * 1e6, 3),
            "liquid_circuits": self.liquid_circuits,
            # Keep the old key as the requested CAD-area value for API
            # compatibility. The resolved fields are authoritative for the
            # live flow solve and gas/liquid ratio.
            "inlet_area_physical_mm2": round(self.inlet_area_requested * 1e6, 4),
            "inlet_area_requested_mm2": round(self.inlet_area_requested * 1e6, 4),
            "inlet_area_resolved_mm2": round(self.inlet_area * 1e6, 4),
            "inlet_area_voxel_mm2": round(self.inlet_area_voxel * 1e6, 4),
            "inlet_velocity_requested_m_s": round(max(0.0, self.op.u_flow), 8),
            "inlet_velocity_resolved_m_s": round(float(self.ns.u_in), 8),
            "gas_liq": round(gl, 2) if np.isfinite(gl) else 999.0,
            "sites_per_mm2": round(sites_m2 * 1e-6, 3),
            "rate_um3_ms": round(rate_m3_s * 1e15, 4),   # um^3 per ms per site
            "v_term_mm_s": round(v_term * 1e3, 3),       # riser speed at r_dep
            # Read-only context for the browser's visual trajectory particles.
            # It lets the renderer use the SAME radius-dependent
            # Schiller-Naumann slip as Parcels without changing solver state.
            "bubble_slip_model": {
                "d_rho_kg_m3": float(self.ctx["d_rho"]),
                "mu_Pa_s": float(self.ctx["mu"]),
                "rho_l_kg_m3": float(self.ctx["rho_l"]),
                "g_m_s2": float(G),
                "sigma_N_m": float(self.ctx["sigma"]),
            },
            "r_nuc_um": round(p.R_NUC * 1e6, 2),
            "spread": p.DETACH_SPREAD,
            "n_bub": int(len(p.r)),
            "n_attached": n_att,
            "n_mesh_attached": n_mesh,
            "n_free": int(len(p.r)) - n_att - n_mesh,
            "r_dep_um": round(r_dep * 1e6, 1),       # real departure radius
            "r_conf_um": round(p.r_conf() * 1e6, 1), # channel-gap size limit
            "d_ch_um": round(self.channel_depth * 1e6, 1) if self.channel_depth else 0.0,
            "p_merge": round(p.p_merge(), 3),        # continuous medium efficiency
            "n_merge": int(p.n_merge),               # on the wall
            "n_merge_mesh": int(p.n_merge_mesh),     # on PP strands
            "n_merge_free": int(p.n_merge_free),     # in the rising swarm
            "n_merge_real": float(p.n_merge_real),
            "n_mesh_capture": int(p.n_mesh_capture),
            "n_mesh_release_force": int(p.n_mesh_release_force),
            "n_mesh_release_edge": int(p.n_mesh_release_edge),
            "mesh_release_model": "Young-Dupre static angle; no hysteresis input",
            "interphase_model": "Schiller-Naumann local d32/slip",
            "interphase_rate_max_s": round(float(self.ns.interphase_rate_max), 4),
            "interphase_re_max": round(float(self.ns.interphase_re_max), 4),
            "alpha_g_raw_max": round(float(p.alpha_raw_max), 4),
            "alpha_g_overfilled_cells": int(p.alpha_overfilled_cells),
            "alpha_g_clipped_volume_mL": round(
                float(p.deposition_clipped_volume) * 1e6, 9),
            "interphase_fields_consistent_after_clip": True,
            "dispersed_bubble_valid": bool(p.alpha_overfilled_cells == 0),
            "r_exit_um": round(self._exit_radius() * 1e6, 1),
            "sweeps": int(getattr(self.ns, "sweeps", 0)),
            "flow_ok": bool(self.flow_connected),
            "model_scope": "reduced-order parcels + incompressible liquid",
            "two_phase_quantitative": False,
            "model_quantitative_ready": False,
            "calibration_required_for_absolute_prediction": True,
            "loss_decomposition_identifiable": False,
            "loss_decomposition_status": (
                "apparent OER j0 and fitted series resistance are not independently "
                "identifiable from one full-cell polarization curve"),
            "electrochem_spatial_model": "0D mean; face redistribution is display-only",
            "nucleation_model_3d": "Faradaic gas-budget seed purchase; k_nuc/B_nuc are not used",
            "electrolyte_property_status": electrolyte_status,
            "electrolyte_property_validated_path": bool(
                self.ctx.get("input_range_valid", False)),
            "thermodynamic_state_valid": bool(
                self.ctx.get("thermodynamic_state_valid", True)),
            "activity_model_in_range": bool(
                self.ctx.get("activity_model_in_range", False)),
            "input_range_valid": bool(self.ctx.get("input_range_valid", False)),
            "input_range_issues": list(self.ctx.get("input_range_issues", [])),
            "transport_limit_model": self.ctx.get("transport_limit_model"),
            "j_lim_calibrated_A_m2": float(self.ctx.get("j_lim_transport", 0.0)),
            "j_lim_delta_proxy_A_m2": float(self.ctx.get("j_lim_from_delta_proxy", 0.0)),
            "transport_limit_proxy_ratio": float(
                self.ctx.get("transport_limit_proxy_ratio", 0.0)),
            "mhd_proxy_active": bool(
                abs(float(getattr(self.op, "B_field", 0.0))) > 0.0),
            "dep_proxy_active": bool(
                abs(float(getattr(self.op, "E_ext", 0.0))) > 0.0),
            "dep_gradient_length_um": float(
                self.ctx.get("dep_gradient_length", 0.0)) * 1e6,
            "operating_feasible": bool(fields.get("operating_feasible", True)),
            "transport_limit_exceeded": bool(fields.get("transport_limit_exceeded", False)),
            "voltage_is_lower_bound": bool(fields.get("voltage_is_lower_bound", False)),
            "j_requested_A_m2": fields.get("j_requested_A_m2"),
            "j_limit_A_m2": fields.get("j_limit_A_m2"),
            # what the GRID actually resolves, vs what the sliders asked for.
            # The pass pitch is H/n_ch; w_ch_mm and w_land_mm only set the ratio,
            # and both get quantised to whole cells.
            **geom,
            "channel_depth_requested_mm": round(self.cfg.d_ch_mm, 4) if self.cfg else None,
            "channel_depth_achieved_mm": round(self.n_lay * self.grid.h * 1e3, 4),
            "channel_depth_cells": int(self.n_lay),
            "grid_has_multiple_depth_cells": bool(self.n_lay >= 2),
            "grid_quantization_tolerance_mm": round(quant_tol_mm, 4),
            "grid_geometry_matches_request": bool(geom_match),
            "geometry_contract": (
                "resolved voxel geometry is authoritative; requested in-plane "
                "widths set only the rib/channel ratio when pitch and n_ch conflict"),
            "flow_path_requested_cm": (
                round(float(self.cfg.L_flow_cm), 4) if self.cfg else None),
            "h_requested_mm": round((self.cfg.h_requested or self.grid.h) * 1e3, 3)
                              if self.cfg is not None else round(self.grid.h * 1e3, 3),
            "H_requested_mm": round(self.cfg.H_cm * 10.0, 3) if self.cfg else round(self.grid.Ly * 1e3, 3),
            "W_requested_mm": round(self.cfg.W_cm * 10.0, 3) if self.cfg else round(self.grid.Lz * 1e3, 3),
            "H_achieved_mm": round(self.grid.Ly * 1e3, 3),
            "W_achieved_mm": round(self.grid.Lz * 1e3, 3),
            "grid_coarsened": bool(self.cfg and self.grid.h > (self.cfg.h_requested or self.grid.h) * 1.000001),
            "nu": float(self.ns.nu),
            "mult": round(float(p.site_mult(0)), 1), # attached seed expected-count weight
            "n_real_est": int(round(n_real)),        # compatibility: rounded expectation
            "n_expected_bubbles": float(n_real),
            "multiplicity_semantics": "nonnegative statistical expected bubble count",
            "multiplicity_min": float(p.mult.min()) if len(p.mult) else 0.0,
            "r_mean_mm": round(r_mean * 1e3, 4),
            "r_std_mm": round(r_std * 1e3, 4),      # >0 => real size distribution
            "theta_c": round(p.coverage(0), 4),
            "theta_a": round(p.coverage(1), 4),
            "holdup": round(p.holdup(np.count_nonzero(~self.ns.solid)), 5),
            "pending_gas_mL": round(p.pending_gas() * 1e6, 9),
            "gas_closure_error": float(p.gas_closure_error()),
            "deposition_unresolved_mL": round(p.deposition_unresolved_volume * 1e6, 9),
            "gas_volume_state_rescales": int(p.state_volume_rescales),
            "thinning_skipped": int(p.thinning_skipped),
            "thinning_moment_error": float(p.thinning_moment_error),
            "bubble_eotvos_min": eo_min,
            "bubble_eotvos_max": eo_max,
            "tomiyama_original_range_fraction": tomiyama_in_range,
            "correlation_range_status": (
                "runtime applicability diagnostic only; combined correlations "
                "are not validated for this confined electrolysis channel"),
            "vmax": round(vmax, 4),
            "projection_relative_divergence": float(rel_div),
            "projection_tolerance": float(self.PROJ_TOL),
            "projection_converged": bool(rel_div <= self.PROJ_TOL),
            "j_Acm2": round(self.cell_current_A_m2() / 1.0e4, 4),
            "V_cell": round(self.cell_voltage(), 4),
            "up": [round(float(x), 3) for x in self.ns.up],
            # voltage breakdown at the operating point (V), so the UI can draw a
            # "where does the cell voltage go" bar at a glance
            "eta": self._eta_breakdown(),
        }

    def _eta_breakdown(self):
        ov = self._state.overpotentials if self._state else {}
        return {k: round(float(ov.get(k, 0.0)), 4) for k in
                ("E_rev", "eta_act_anode", "eta_act_cathode",
                 "eta_conc", "eta_ohmic", "eta_water")}

    def eis(self, f_lo=1e-1, f_hi=1e6, n=60):
        """Small-signal EIS spectrum at the current operating point (analytic).

        Linearises the two-electrode balance: per electrode R_ct is the inverse
        Butler-Volmer slope at the present overpotential, in parallel with the
        double-layer C_dl (both scaled by 1-theta for bubble-covered area), plus
        a finite-length Warburg from the diffusion layer; R_s is the series
        resistance the solver already reports. Returns Nyquist arrays in ohm*cm^2.
        (Same construction as the 2-D app's LiveSim.eis.)
        """
        from bubblesim.kernel import impedance as imp
        from bubblesim.kernel.transport import conc_differential_resistance
        st, ctx, op = self._state, self.ctx, self.op
        if st is None:
            return {"error": "no operating point yet"}
        ov = st.overpotentials
        j = max(self.cell_current_A_m2(), 1e-3)
        T = op.T
        th_c, th_a = self.parcels.coverage(0), self.parcels.coverage(1)
        R_s = ov.get("eta_ohmic", 0.0) / j                     # series R [ohm*m^2]
        Rct_a = imp.r_ct_bv(max(1e-3, 1 - th_a) * ctx["j0_anode"],
                            ctx["alpha_a_anode"], ctx["alpha_c_anode"],
                            ov.get("eta_act_anode", 0.0), T)
        Rct_c = imp.r_ct_bv(max(1e-3, 1 - th_c) * ctx["j0_cathode"],
                            ctx["alpha_a_cathode"], ctx["alpha_c_cathode"],
                            ov.get("eta_act_cathode", 0.0), T)
        R_d = conc_differential_resistance(
            j, ctx["j_lim_transport"], ctx.get("z_transport", 1), T,
            ctx["j_ref_vogt"], ctx["k_vogt"])
        if not np.isfinite(R_d):
            return {
                "error": "no finite EIS linearisation at/above transport limit",
                "valid": False,
                "operating_feasible": bool(
                    st.fields.get("operating_feasible", False)),
            }
        delta = min(ctx.get("delta_bl", 3e-5), 0.8 * ctx.get("gap_m", 5e-4))
        tau_d = delta * delta / max(ctx.get("D_carrier", 3e-9), 1e-12)
        Ca = max(1e-3, self.params.anode.C_dl) * max(1e-3, 1 - th_a)
        Cc = max(1e-3, self.params.cathode.C_dl) * max(1e-3, 1 - th_c)
        els = [{"R_ct": Rct_a, "C_dl": Ca, "R_d": 0.5 * R_d, "tau_d": tau_d},
               {"R_ct": Rct_c, "C_dl": Cc, "R_d": 0.5 * R_d, "tau_d": tau_d}]
        freqs = imp.log_freqs(f_lo, f_hi, n)
        Z = imp.cell_impedance(freqs, R_s, els)
        return {
            "f": list(freqs),
            "re": [round(z_.real * 1e4, 4) for z_ in Z],       # ohm*m^2 -> ohm*cm^2
            "im": [round(-z_.imag * 1e4, 4) for z_ in Z],      # Nyquist: -Im
            "Rs": round(R_s * 1e4, 4),
            "Rct_a": round(Rct_a * 1e4, 4), "Rct_c": round(Rct_c * 1e4, 4),
            "Rd": round(R_d * 1e4, 4),
            "valid": True,
            "transport_linearization": "d(DC eta_conc)/dj including Vogt dL/dj",
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

    def snapshot(self, with_faces=True, *, with_geometry=None,
                 with_gas=None, with_velocity=None):
        """Return a JSON-ready state snapshot.

        ``with_faces=True`` keeps the legacy all-heavy-fields contract.  New
        clients can request electrode maps, static geometry, gas holdup and
        velocity independently so the default cutaway view does not serialize
        multi-megabyte analysis arrays it is not displaying.
        """
        if with_geometry is None:
            with_geometry = with_faces
        if with_gas is None:
            with_gas = with_faces
        if with_velocity is None:
            with_velocity = with_faces
        snap = {
            "t": round(self.t, 4),
            "grid": {"nx": self.grid.nx, "ny": self.grid.ny, "nz": self.grid.nz,
                     "h_mm": self.grid.h * 1e3, "n_lay": self.n_lay,
                     "Lx_mm": self.grid.Lx * 1e3, "Ly_mm": self.grid.Ly * 1e3,
                     "Lz_mm": self.grid.Lz * 1e3},
            "bubbles": self.parcels.snapshot_flat(),
            "mesh3d": self.parcels.mesh_snapshot(),
            "merge_events": list(self.parcels.merge_events),
            "n_bub": int(len(self.parcels.r)),
            "diag": self.diagnostics(),
        }
        # gas-holdup height profile (mean void over x,z per y layer) — the
        # inlet->outlet accumulation curve, tiny payload, every poll
        snap["eps_prof"] = np.round(self.ns.gas.mean(axis=(0, 2)), 4).tolist()
        if with_faces:
            snap["faces"] = self.face_current_maps()
        if with_geometry:
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
        if with_gas:
            # Full 3-D holdup field for the Euler-style contour view.  This is
            # opt-in because a capped high-resolution grid is no longer a
            # "few KB" once represented as JSON numbers.
            snap["gas3d"] = {"nx": self.grid.nx, "ny": self.grid.ny,
                             "nz": self.grid.nz,
                             "f": np.round(self.ns.gas, 3).ravel().tolist()}
        if with_velocity:
            # centre velocities for the vector-arrow overlay (paper-style):
            # shows the flow deflecting around bubble clouds / lands
            u, v, w = self.ns.centres()
            snap["vel3d"] = {"u": np.round(u, 3).ravel().tolist(),
                             "v": np.round(v, 3).ravel().tolist(),
                             "w": np.round(w, 3).ravel().tolist()}
        return snap
