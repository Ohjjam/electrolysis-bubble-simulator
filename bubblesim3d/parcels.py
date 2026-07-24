"""Lagrangian gas bubbles for the cell-scale engine (Track A).

Each tracked bubble follows the SAME lifecycle as the kernel's representative
patch (bubblesim.kernel.bubbles.population.Surface), lifted into 3-D:

    nucleate  -> a small seed appears at a RANDOM spot on the electrode face
                 (continuous position, not a grid site) at the Faradaic rate
    grow      -> while attached it accumulates the evolved gas (r^2-weighted,
                 the kernel Surface.grow rule) and swells on the wall
    detach    -> when it reaches its departure radius (kernel
                 forces.departure_radius, with per-bubble spread) it lets go
    rise      -> the freed bubble rides the solved flow + buoyant slip (kernel
                 Schiller-Naumann terminal velocity) with Tomiyama/Antal
                 wall-normal drift, and vents at the outlet

REPRESENTATIVE MULTIPLICITY (the honest answer to real bubble sizes): at real
electrolysis departure sizes (~50-300 um diameter) a working cell detaches
HUNDREDS OF THOUSANDS of bubbles per second — tracking each one is the
documented millions-of-bubbles wall. So each tracked bubble carries a
multiplicity `mult`: its RADIUS is a genuine single-bubble radius (drives
slip, detachment, the rendered size), while its GAS CONTENT is
W = mult * V(r) and its coverage footprint is weighted by `mult`.  `mult` is a
non-negative STATISTICAL EXPECTED COUNT, not an integer literal count: weighted
cohort splitting can therefore leave 0 < mult < 1.  This is required to conserve
moments without rejecting collisions.  Attached seed weights originate from
(nucleation-site count)/(tracked slots); free risers are adaptively thinned with
non-negative weights that preserve expected bubble number, interfacial area and
gas volume independently on each electrode side.

COALESCENCE: a bubble does not "pop" in the liquid — when two touch they MERGE
(and only burst at a free surface, which here is the outlet vent). Merging is
resolved statistically because the neighbours of a tracked bubble are its own
`mult` real siblings, below the tracked resolution: as a wall bubble swells, the
chance that a Poisson-distributed neighbour falls inside its new reach grows by
dP = P(reach_new) - P(reach_old), and a merge is drawn against dP * p_merge —
rate-consistent (independent of dt) rather than a per-step coin flip.
p_merge uses the electrolyte database's critical concentration as a continuous
half-inhibition scale, so concentrated KOH suppresses rather than hard-disables
coalescence.
A merge halves `mult` and grows r by 2^(1/3): W = mult*V(r) is untouched.
Free-swarm coalescence is resolved statistically; interface deformation and
ion-resolved film chemistry are not.

CONFINEMENT: the opposite plate is `channel_depth` away, so no bubble can grow
past ~90% of the gap — beyond that it bridges the channel (slug flow) instead of
staying a free sphere. Both the departure radius and the growth step are capped,
otherwise a narrow (0.2 mm) channel shows bubbles poking through the far wall.

WALL-NORMAL FORCES: a free bubble feels Tomiyama (2002) shear-induced lift and
Antal (1991) wall lubrication, balanced against Stokes drag. At electrolysis
sizes (Eo_d ~ 1e-3) the lift coefficient is positive and beats the wall force at
every standoff, so bubbles are PRESSED onto the electrode and settle ~1.05 r out
— the classic small-bubble wall peaking. The near-wall layer is now a result of
the force balance, not of a missing force. (The correlation's sign flips above
Eo_d = 4, so mm bubbles would migrate to the core.)

SWARM COALESCENCE: rising bubbles also merge, via the Prince & Blanch (1990)
collision kernel times a film-drainage efficiency, times the electrolyte's
salting-out inhibition. The observable is the EXIT bubble size: ~42 um in 6 M
KOH, ~84 um in 0.1 M. It needs one stated closure — the smeared cell void
fraction is concentrated into the real near-wall sheet, capped at random close
packing — and neither bound drives the answer (see _n_local).

NOT MODELLED (honest scope; mirrored in docs/3D_EQUATIONS.md section 5):
  * no growth after detachment — a free bubble's radius only changes by merging;
  * no turbulent dispersion (this cell is laminar, Re ~ 4e2, so the Prince-Blanch
    turbulent collision term and its dissipation rate do not apply);
  * `r_min_detach` is a MODEL floor: at 1 m/s in a 1 mm channel the force balance
    asks for a smaller bubble than the kernel will represent, and r_dep lands on
    it. Below ~0.6 m/s the floor never binds.

Gas is conserved at all times:
    produced = resident (attached + free) + pending seed budget + vented
Physics is reused from bubblesim.kernel, never reimplemented.
"""
from dataclasses import replace

import numpy as np

from .grid import Grid3D
from bubblesim.constants import G
from bubblesim.properties import ELECTROLYTES
from bubblesim.kernel.sources import faradaic_gas_rate
from bubblesim.kernel.bubbles import forces
from .interphase import terminal_velocity


class Parcels:
    """Bubble population on the two electrode faces of a Grid3D.

    A tracked bubble is a real (representative) bubble with a full attached->
    detached lifecycle — NOT a fixed-volume computational parcel.
    """

    R_NUC = 5.0e-6          # fallback only; instance value comes from Params.r_nuc
                            # BELOW the departure radius at every flow rate, or
                            # the 2*R_NUC detachment floor binds and every bubble
                            # leaves at the seed size (r_dep -> ~16 um at 1 m/s).
    DETACH_SPREAD = 0.30    # fallback only; instance value comes from Params
    N_SITES = 140           # TRACKED attached slots per face (each represents
                            # `mult` real nucleation sites — see module docstring)
    FREE_TARGET = 1400      # tracked free risers to keep (adaptively thinned)
    SUB_FRAC = 0.25         # max share of one growth-to-departure cycle's gas
                            # per wall substep (see _wall_substeps)
    MAX_SUB = 32

    # --- wall-normal force balance on a FREE bubble -------------------------
    # Tomiyama (Chem. Eng. Sci. 57, 2002) shear-induced lift, small-bubble
    # branch: C_L = 0.288 tanh(0.121 Re_b). Positive -> toward the wall in
    # co-current upward flow, which is why small bubbles wall-peak.
    CL_A, CL_B = 0.288, 0.121
    # Antal (Int. J. Multiphase Flow 17, 1991) wall lubrication:
    # C_W = max(0, Cw1 + Cw2 * r / y_w), Cw1 = -0.104 - 0.06|u_rel|, Cw2 = 0.147.
    # C_W > 0 only within ~1.4 r of the wall, so it sets a standoff, not a push.
    CW1_A, CW1_B, CW2 = -0.104, -0.06, 0.147

    # --- free-swarm coalescence (Prince & Blanch, AIChE J. 36, 1990) ---------
    H0, HF = 1.0e-4, 1.0e-8   # initial / critical film thickness [m]
    CONF_FRAC = 0.45        # a bubble cannot exceed ~90% of the channel gap in
                            # diameter: beyond that it bridges the channel (slug
                            # flow) rather than growing as a free sphere

    def __init__(self, grid: Grid3D, op, rng, cap=6000,
                 face_masks=None, elec_planes=None, params=None,
                 channel_depth=None, vent_face="top", vent_line=None):
        self.g = grid
        self.op = op
        self.params = params           # kernel Params (site density for mult)
        self.rng = rng
        self.cap = int(cap)
        # One authoritative parameter source.  The old Track-A constants differed
        # from Params and OER was additionally multiplied by 0.5 even though the
        # Faraday source already uses z=4.
        if params is not None:
            self.R_NUC = float(params.r_nuc)
            self.DETACH_SPREAD = float(params.detach_spread)
        # PHYSICAL channel depth [m]: the opposite plate confines the bubble.
        # None -> unconfined (plain box tests).
        self.channel_depth = channel_depth
        # Where the gas actually LEAVES: the same boundary cells the liquid
        # exits through. `vent_face` is "top" | "left" | "right"; `vent_line` is
        # a bool array over that edge's axis (z for top, y for left/right).
        # None -> the whole y-top vents (the plain-box default).
        # Gas that reaches plate instead of a port is trapped: it piles up under
        # it and crawls sideways looking for the port.
        self.vent_face = vent_face
        self.vent_line = None if vent_line is None else np.asarray(vent_line, dtype=bool)
        # (face_c, face_a) open-channel masks (ny,nz): bubbles nucleate only
        # where electrolyte touches the electrode (not under a pressed land)
        self.face_masks = face_masks
        # electrode (catalyst) plane x-positions [m]. In a zero-gap cell the
        # catalyst sits on the MEMBRANE side of each channel, so gas emerges at
        # the channel's INNER wall: (x_cathode_plane, x_anode_plane) = the
        # core boundaries. None = legacy box (outer walls are the electrodes).
        self.elec_planes = elec_planes
        z0 = lambda: np.zeros(0)
        self.pos = np.zeros((0, 3))
        self.r = z0()                     # SINGLE real-bubble radius [m]
        self.W = z0()                     # carried gas volume [m^3] = mult*V(r)
        self.mult = z0()                  # real bubbles this tracked one represents
        self.side = np.zeros(0, dtype=np.int8)      # 0 cathode (x=0), 1 anode (x=Lx)
        self.attached = np.zeros(0, dtype=bool)
        # A mesh-held bubble is no longer attached to the catalyst, but it is
        # not a free riser either. mesh_axis: 1 = y-running strand, 2 = z-running
        # strand. Keeping this state explicit avoids rendering/advecting a
        # collected bubble as if it had already detached.
        self.mesh_attached = np.zeros(0, dtype=bool)
        self.mesh_axis = np.zeros(0, dtype=np.int8)
        # Unit normal from the contacted strand axis to the bubble centre.
        # Keeping it explicit makes mesh sliding continuous: only the strand
        # coordinate changes while the sphere remains tangent to that cylinder.
        self.mesh_normal = np.zeros((0, 3), dtype=np.float64)
        self.r_dep = z0()                 # per-bubble departure radius [m]
        self.phase = z0()                 # per-bubble meander phase
        self.p_touch = z0()               # P(a neighbour lies within reach) so far
        self.n_merge = 0                  # wall coalescence events (diagnostic)
        self.n_merge_free = 0             # swarm coalescence events (diagnostic)
        self.n_merge_mesh = 0             # physical-contact merges on PP strands
        self.n_merge_real = 0.0           # represented real-bubble pair events
        self.n_mesh_capture = 0
        self.n_mesh_release_force = 0
        self.n_mesh_release_edge = 0
        self.merge_events = []            # bounded event stream for the renderer
        self._merge_seq = 0
        self.lifecycle_events = []        # ID-resolved recorder/audit stream
        self._event_seq = 0
        self._event_t = 0.0
        self.record_mode = False          # recorder disables statistical thinning
        self.ids = np.zeros(0, dtype=np.int64)
        self._next_id = 1
        self._t = 0.0
        self.alpha_raw_max = 0.0
        self.alpha_overfilled_cells = 0
        self.deposition_unresolved_volume = 0.0
        self.deposition_clipped_volume = 0.0
        self.state_volume_rescales = 0
        self.thinning_skipped = 0
        self.thinning_moment_error = 0.0
        self.produced_cum = 0.0
        self.vented_cum = 0.0
        self._pending = [0.0, 0.0]        # gas that found no home this pass

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _vol(r):
        return (4.0 / 3.0) * np.pi * r ** 3

    def rescale_volume_basis(self, factor):
        """Re-express all stored gas volumes at a new T/P state basis.

        Parcels store volume rather than moles.  A live T/P update therefore
        must transform resident, pending and cumulative ledger terms together;
        otherwise old and new gas are added in incompatible units.  Multiplicity
        stays fixed and each single-bubble radius follows ``r ~ V^(1/3)``.
        """
        factor = float(factor)
        if not np.isfinite(factor) or factor <= 0.0:
            raise ValueError("gas-volume scale must be finite and positive")
        if abs(factor - 1.0) <= 32.0 * np.finfo(float).eps:
            return
        self._ensure_state_arrays()
        radius_scale = factor ** (1.0 / 3.0)
        self.W *= factor
        self.r *= radius_scale
        self._pending = [float(v) * factor for v in self._pending]
        self.produced_cum *= factor
        self.vented_cum *= factor
        self.deposition_unresolved_volume *= factor
        self.deposition_clipped_volume *= factor
        # Keep catalyst-attached spheres tangent to their physical wall after
        # the pressure/temperature expansion or contraction.
        attached = self.attached & (~self.mesh_attached)
        if attached.any():
            off = self._wall_off(self.r[attached])
            if self.elec_planes is not None:
                xc, xa = self.elec_planes
                self.pos[attached, 0] = np.where(
                    self.side[attached] == 0, xc - off, xa + off)
            else:
                self.pos[attached, 0] = np.where(
                    self.side[attached] == 0, off, self.g.Lx - off)
        self.state_volume_rescales += 1

    def _face_area(self):
        return self.g.Ly * self.g.Lz

    def _ensure_state_arrays(self):
        """Backwards-compatible guard for small tests/legacy saved fixtures."""
        n = len(self.r)
        if len(self.mesh_attached) != n:
            self.mesh_attached = np.zeros(n, dtype=bool)
        if len(self.mesh_axis) != n:
            self.mesh_axis = np.zeros(n, dtype=np.int8)
        if self.mesh_normal.shape != (n, 3):
            self.mesh_normal = np.zeros((n, 3), dtype=np.float64)

    @staticmethod
    def _event_value(value):
        """Convert numpy values to compact JSON-ready lifecycle metadata."""
        if isinstance(value, np.ndarray):
            return [float(v) for v in value.ravel()]
        if isinstance(value, (np.floating, float)):
            return float(value)
        if isinstance(value, (np.integer, int)):
            return int(value)
        if isinstance(value, (np.bool_, bool)):
            return bool(value)
        if isinstance(value, (list, tuple)):
            return [Parcels._event_value(v) for v in value]
        return value

    def _emit_event(self, event_type, **fields):
        """Append one stable-ID lifecycle transition for offline recording."""
        self._event_seq += 1
        event = {
            "seq": int(self._event_seq),
            "t": float(self._event_t),
            "type": str(event_type),
        }
        event.update({key: self._event_value(value)
                      for key, value in fields.items()})
        self.lifecycle_events.append(event)
        if len(self.lifecycle_events) > 8192:
            del self.lifecycle_events[:-8192]
        return event

    def _record_merge(self, a, b, radius, side, attached, radius_a=None,
                      radius_b=None, ids=None, state=None):
        self._merge_seq += 1
        self.merge_events.append({
            "seq": self._merge_seq, "t": float(self._event_t),
            "a": [float(v) for v in a], "b": [float(v) for v in b],
            "r": float(radius), "side": int(side),
            "ra": float(radius if radius_a is None else radius_a),
            "rb": float(radius if radius_b is None else radius_b),
            "attached": bool(attached),
        })
        if len(self.merge_events) > 128:
            del self.merge_events[:-128]
        self._emit_event(
            "merge",
            ids=[] if ids is None else ids,
            side=int(side),
            state=("attached" if attached else "free") if state is None else state,
            position_a=a,
            position_b=b,
            radius_a_m=float(radius if radius_a is None else radius_a),
            radius_b_m=float(radius if radius_b is None else radius_b),
            radius_after_m=float(radius),
        )

    def _gap(self):
        """Physical electrode-to-plate channel depth [m]."""
        if self.channel_depth is not None and self.channel_depth > 0:
            return float(self.channel_depth)
        # legacy box / bare-grid tests: the grid's own channel depth
        return float(self.elec_planes[0] if self.elec_planes is not None
                     else 0.25 * self.g.Lx)

    def r_conf(self):
        """Largest radius a free sphere can reach before it bridges the channel."""
        return self.CONF_FRAC * self._gap()

    # standoff that keeps a wall bubble's centre out of the neighbouring SOLID
    # cell. It must be a rounding guard, nothing more: at 0.1*h (= 200 um on a
    # 2 mm grid) it was 5x the bubble radius, so every bubble floated a fifth of
    # a millimetre off the catalyst instead of touching it.
    EPS_WALL = 1.0e-3      # in units of the cell size h

    def _wall_off(self, r):
        return r + self.EPS_WALL * self.g.h

    def _wall_x(self, side, r):
        """x so a bubble of radius r sits TANGENT to its ELECTRODE surface.

        With elec_planes (zero-gap cell) that surface is the catalyst plane on
        the membrane side of the channel — cathode bubbles hang off x=x_c into
        the channel (x < x_c), anode off x=x_a (x > x_a). Legacy box: the
        outer walls."""
        off = self._wall_off(r)
        if self.elec_planes is not None:
            xc, xa = self.elec_planes
            return (xc - off) if side == 0 else (xa + off)
        return off if side == 0 else self.g.Lx - off

    # ---------------------------------------------------------- PP mesh layer
    def mesh_geometry(self):
        """Measured live-3D PP mesh geometry, in metres.

        Catalog opening dimensions and open-area fraction determine the two
        pitches.  Splitting the open-area ratio equally between the two woven
        directions (hole/pitch = sqrt(phi)) is the unique symmetric solution;
        it adds no fitted reference length.  The strand radius is the measured
        catalog thickness / 2.
        """
        hole_z = 1e-3 * float(getattr(self.op, "mesh_hole_x_mm", 0.0))
        hole_y = 1e-3 * float(getattr(self.op, "mesh_hole_y_mm", 0.0))
        t = 1e-3 * float(getattr(self.op, "mesh_t_mm", 0.0))
        cover = min(1.0, max(0.0, float(getattr(self.op, "mesh_cover", 0.0))))
        if not getattr(self.op, "mesh_id", "") or hole_y <= 0 or hole_z <= 0 \
                or t <= 0 or cover <= 0 or self.elec_planes is None:
            return None
        # A physical mesh thicker than the channel cannot be installed. Mesh 2
        # intentionally removes that hydraulic constraint while retaining the
        # measured strand geometry as a bubble-contact surface.
        if str(getattr(self.op, "mesh_mode", "physical")) != "hydrophobic" \
                and t >= self._gap():
            return None
        phi = min(0.99, max(0.01, float(getattr(self.op, "mesh_open", 1.0))))
        scale = 1.0 / np.sqrt(phi)
        pitch_y, pitch_z = hole_y * scale, hole_z * scale
        span = cover * self.g.Ly
        anchor = str(getattr(self.op, "mesh_pos", "outlet"))
        if anchor == "inlet":
            y0 = 0.0
        elif anchor == "middle":
            y0 = 0.5 * (self.g.Ly - span)
        else:
            y0 = self.g.Ly - span
        xa = float(self.elec_planes[1])
        return {
            "id": str(getattr(self.op, "mesh_id", "")),
            "pitch_y": pitch_y, "pitch_z": pitch_z,
            "hole_y": hole_y, "hole_z": hole_z,
            "strand_radius": 0.5 * t,
            "x_axis": xa + 0.5 * t,
            "y0": max(0.0, y0), "y1": min(self.g.Ly, y0 + span),
            "open": phi,
            "mode": str(getattr(self.op, "mesh_mode", "physical")),
        }

    def mesh_snapshot(self):
        """Small renderer payload; no voxel or solver coordinate is changed."""
        geom = self.mesh_geometry()
        if geom is None:
            return None
        return {k: (round(float(v) * 1e3, 6) if k in {
                    "pitch_y", "pitch_z", "hole_y", "hole_z", "strand_radius",
                    "x_axis", "y0", "y1"} else v)
                for k, v in geom.items()}

    def _nearest_mesh_strand(self, p, radius, geom=None):
        """Nearest physically reachable strand point for one bubble centre.

        Returns ``(axis, point, distance_to_axis)`` only when the spherical
        bubble actually intersects a measured cylindrical strand.  There is no
        attraction distance, capture probability, or teleport to a crossing.
        """
        geom = self.mesh_geometry() if geom is None else geom
        if geom is None or p[1] < geom["y0"] or p[1] > geom["y1"]:
            return None
        py, pz = geom["pitch_y"], geom["pitch_z"]
        y_line = geom["y0"] + np.rint((p[1] - geom["y0"]) / py) * py
        y_line = float(np.clip(y_line, geom["y0"], geom["y1"]))
        z_line = float(np.clip(np.rint(p[2] / pz) * pz, 0.0, self.g.Lz))
        dx = float(p[0] - geom["x_axis"])
        d_y_axis = float(np.hypot(dx, p[2] - z_line))   # strand runs along y
        d_z_axis = float(np.hypot(dx, p[1] - y_line))   # strand runs along z
        axis = 1 if d_y_axis <= d_z_axis else 2
        dist = d_y_axis if axis == 1 else d_z_axis
        if dist > float(radius) + geom["strand_radius"]:
            return None
        point = np.array([geom["x_axis"], p[1], z_line], dtype=float) if axis == 1 \
            else np.array([geom["x_axis"], y_line, p[2]], dtype=float)
        return axis, point, dist

    def _mesh_transfer_allowed(self):
        """Young-equation gas affinity: NF -> PP only when PP is preferred.

        Designer angles are water-side equivalents.  The measured underwater
        bubble angle is 180-theta_water and Young-Dupre gas affinity is
        1+cos(theta_bubble) = 1-cos(theta_water).  This is a deterministic
        thermodynamic direction test, not a fitted capture probability.
        """
        theta_e = np.radians(float(getattr(self.op, "contact_angle", 90.0)))
        theta_m = np.radians(float(getattr(self.op, "mesh_contact_angle", 90.0)))
        return (1.0 - np.cos(theta_m)) > (1.0 - np.cos(theta_e))

    def _sample_sites(self, side, want):
        """Sample electrolyte-accessible electrode sites.

        Lands are excluded on both electrodes.  On the Mesh2/OER face, a seed
        must also fit in an opening rather than starting inside a PP strand.
        Rejected gas is not lost: the caller leaves it in the pending Faradaic
        budget until an accessible tracked slot is available.
        """
        if want <= 0:
            return np.zeros(0), np.zeros(0)
        accepted_y, accepted_z = [], []
        geom = self.mesh_geometry() if side == 1 and self._mesh_transfer_allowed() else None
        for _ in range(12):
            remaining = want - len(accepted_y)
            if remaining <= 0:
                break
            count = max(16, 4 * remaining)
            ys = self.rng.uniform(0.04, 0.96, count) * self.g.Ly
            zs = self.rng.uniform(0.04, 0.96, count) * self.g.Lz
            ok = np.ones(count, dtype=bool)
            if self.face_masks is not None and self.face_masks[side] is not None:
                mask = self.face_masks[side]
                jy = np.clip((ys / self.g.h).astype(int), 0, mask.shape[0] - 1)
                kz = np.clip((zs / self.g.h).astype(int), 0, mask.shape[1] - 1)
                ok &= mask[jy, kz]
            if geom is not None:
                x = self._wall_x(side, self.R_NUC)
                for q in np.nonzero(ok)[0]:
                    if self._nearest_mesh_strand(
                            np.array([x, ys[q], zs[q]], dtype=float),
                            self.R_NUC, geom) is not None:
                        ok[q] = False
            for y, z in zip(ys[ok], zs[ok]):
                accepted_y.append(float(y))
                accepted_z.append(float(z))
                if len(accepted_y) >= want:
                    break
        return (np.asarray(accepted_y[:want], dtype=float),
                np.asarray(accepted_z[:want], dtype=float))

    def _at_top_vent(self, z):
        """Is this z inside an open outlet column of the y-top face?"""
        if self.vent_line is None:
            return np.ones(len(z), dtype=bool)
        if self.vent_face != "top":
            return np.zeros(len(z), dtype=bool)      # the top is entirely plate
        k = np.clip((z / self.g.h).astype(np.int64), 0, self.g.nz - 1)
        return self.vent_line[k]

    def _at_side_vent(self, side, y):
        """Is this y inside an open outlet row of the z=0 / z=Lz face?"""
        if self.vent_line is None or self.vent_face != side:
            return np.zeros(len(y), dtype=bool)
        j = np.clip((y / self.g.h).astype(np.int64), 0, self.g.ny - 1)
        return self.vent_line[j]

    def shear_rate(self, y_w):
        """Near-wall shear du/dy at wall distance y_w, from the SAME linear
        shear-layer model `departure_radius` uses (u = u_bulk * y_w/half)."""
        half = 0.5 * self._gap()
        u_bulk = max(0.0, self.op.u_flow)
        return np.where(y_w < half, u_bulk / max(half, 1e-12), 0.0)

    def wall_normal_velocity(self, r, v_slip, y_w, ctx):
        """Signed wall-normal drift [m/s]; + = away from the electrode.

        Stokes balance of the two wall-normal forces on a free bubble:
            lift  F_L = C_L rho V |u_rel| (du/dy)      -> toward the wall
            wall  F_W = C_W rho V u_rel^2 / r          -> away from the wall
        against Stokes drag 6 pi mu r v_n, giving
            v_n = (2 r^2 rho / 9 mu) [ C_W u_rel^2 / r  -  C_L |u_rel| gamma_dot ]
        This is the physics that was previously MISSING (the module said so).
        It turns out to be small: a few um/s, with an equilibrium standoff of
        order the bubble radius. So bubbles really do skim the wall — now for a
        reason rather than by omission.
        """
        rho, mu = float(ctx["rho_l"]), float(ctx["mu"])
        u_rel = np.abs(v_slip)
        y = np.maximum(y_w, r)                       # centre cannot enter the wall
        Re = 2.0 * r * u_rel * rho / mu
        C_L = self.lift_coefficient(r, Re, ctx)
        C_W = np.maximum(0.0, self.CW1_A + self.CW1_B * u_rel + self.CW2 * r / y)
        gdot = self.shear_rate(y)
        mob = 2.0 * r * r * rho / (9.0 * mu)         # Stokes mobility factor
        return mob * (C_W * u_rel * u_rel / r - C_L * u_rel * gdot)

    def lift_coefficient(self, r, Re, ctx):
        """Tomiyama (2002) lift coefficient, both branches.

        Eo_d = g d_rho d^2 / sigma on the bubble's long axis. Below Eo_d = 4 the
        coefficient is POSITIVE (small bubbles migrate to the wall); above it the
        wake asymmetry flips the sign and big bubbles migrate to the core. Our
        electrolysis bubbles sit at Eo_d ~ 1e-3, deep in the positive branch —
        which is exactly why they never leave the electrode.
        """
        # sigma is optional so Parcels stays usable with a bare {d_rho, mu, rho_l}
        # context (the standalone rise tests); water's value is the fallback.
        Eo = G * float(ctx["d_rho"]) * (2.0 * r) ** 2 / float(ctx.get("sigma", 0.072))
        f = 0.00105 * Eo ** 3 - 0.0159 * Eo ** 2 - 0.0204 * Eo + 0.474
        small = np.minimum(self.CL_A * np.tanh(self.CL_B * Re), f)
        return np.where(Eo < 4.0, small, np.where(Eo <= 10.0, f, -0.27))

    def _wall_dist(self, x, side):
        """(distance to this bubble's electrode plane, outward sign in +x).

        `side` must be the SAME subset as `x` — passing the full array against a
        free-only slice silently broadcasts or raises.
        """
        if self.elec_planes is None:
            return x, np.ones(len(x))                # legacy box: wall at x=0
        xc, xa = self.elec_planes
        cath = side == 0
        d = np.where(cath, xc - x, x - xa)           # >0 inside the channel
        n = np.where(cath, -1.0, +1.0)               # outward = away from plane
        return d, n

    def _in_solid(self, ns, pts):
        """Boolean: which points sit inside an obstacle (rib/core) cell."""
        if not ns.solid.any() or len(pts) == 0:
            return np.zeros(len(pts), dtype=bool)
        ci = np.clip((pts / self.g.h).astype(np.int64),
                     0, [self.g.nx - 1, self.g.ny - 1, self.g.nz - 1])
        return ns.solid[ci[:, 0], ci[:, 1], ci[:, 2]]

    # ------------------------------------------------------------ lifecycle
    def _faradaic_rate(self, j_A_m2, electrode, area, ctx):
        return faradaic_gas_rate(
            max(0.0, j_A_m2), electrode, self.op.T, self.op.P, area,
            eta_F=(self.params.eta_faraday if self.params is not None else 1.0),
            wet=bool(getattr(self.op, "high_fidelity", False)),
            water_activity=ctx.get("water_activity", 1.0))

    def _wall_substeps(self, j_A_m2, dt, r_dep, ctx):
        """Substeps needed to resolve the growth-to-departure cycle.

        At a real site density a bubble goes seed -> departure in ~1 ms, which
        is SHORTER than the flow time step (3 ms). Growing the whole step's gas
        in one pass inflates every bubble far past its departure radius before
        `_detach` can look at it, so the reported bubble size came out ~3x the
        physics. Cap each pass at SUB_FRAC of a full cycle's gas instead. Only
        the (tiny) wall arrays are touched per substep — the flow solve is not.
        """
        A = self._face_area()
        q = sum(self._faradaic_rate(j_A_m2, el, A, ctx)
                for el in ("HER", "OER"))
        budget = q * dt
        w_cycle = self._vol(r_dep) * self.N_SITES * (self.site_mult(0)
                                                     + self.site_mult(1))
        if budget <= 0.0 or w_cycle <= 0.0:
            return 1
        n = int(np.ceil(budget / (self.SUB_FRAC * w_cycle)))
        return int(np.clip(n, 1, self.MAX_SUB))

    def step(self, ns, j_A_m2, dt, ctx, trace_hook=None):
        """One bubble-dynamics step: nucleate + grow, coalesce, detach, advect."""
        self._ensure_state_arrays()
        t0 = float(self._t)
        self._t += dt
        r_dep0 = max(2 * self.R_NUC,
                     self.departure_radius(ctx, max(1e-6, j_A_m2)))
        n_sub = self._wall_substeps(j_A_m2, dt, r_dep0, ctx)
        sdt = dt / n_sub
        for substep in range(n_sub):
            event_start = len(self.lifecycle_events)
            self._event_t = t0 + (substep + 1) * sdt
            self._nucleate_and_grow(j_A_m2, sdt, ctx, r_dep0)
            self._coalesce()
            self._capture_on_mesh()
            self._detach(ctx, j_A_m2)
            if trace_hook is not None:
                trace_hook({
                    "t": float(self._event_t),
                    "stage": "wall",
                    "substep": int(substep + 1),
                    "substeps": int(n_sub),
                    "parcels": self,
                    "ns": ns,
                    "ctx": ctx,
                    "events": tuple(self.lifecycle_events[event_start:]),
                })
        # Mesh parcels do not receive Faradaic growth directly, so one
        # contact pass per outer flow step is sufficient and avoids repeating
        # the same neighbour search up to MAX_SUB times.
        event_start = len(self.lifecycle_events)
        self._event_t = t0 + dt
        self._coalesce_mesh()
        self._move_and_release_mesh(ns, dt, ctx)
        self._advect(ns, dt, ctx)
        self._coalesce_free(ns, dt, ctx)
        if trace_hook is not None:
            trace_hook({
                "t": float(self._event_t),
                "stage": "transport",
                "substep": int(n_sub),
                "substeps": int(n_sub),
                "parcels": self,
                "ns": ns,
                "ctx": ctx,
                "events": tuple(self.lifecycle_events[event_start:]),
            })

    def departure_radius(self, ctx, j_A_m2):
        """Departure radius with the NEAR-WALL velocity the bubble actually feels.

        The kernel force balance takes `op.u_flow`, but that is the BULK channel
        velocity. A departing bubble is only tens of microns tall and sits in
        the wall shear layer, where u grows ~linearly from zero. Feeding it the
        bulk value makes the drag term swamp adhesion and pins the answer at the
        `r_min_detach` floor for any real pump rate (u >= 0.2 m/s) — i.e. flow
        would stop mattering. So: size the bubble in stagnant liquid first, then
        evaluate the balance again at u_eff = u_bulk * (r_stag / half-channel),
        capped at the bulk value.

        The result is capped by the channel gap: a bubble that would need more
        room than the opposite plate allows departs when it bridges instead.
        """
        op = self.op
        u_bulk = max(0.0, op.u_flow)
        r_stag = forces.departure_radius(replace(op, u_flow=0.0), ctx, j_A_m2)
        if u_bulk <= 0.0:
            return min(r_stag, self.r_conf())
        half = 0.5 * self._gap()          # catalyst plane -> mid-channel
        u_eff = u_bulk * min(1.0, r_stag / max(half, 1e-9))
        r = forces.departure_radius(replace(op, u_flow=u_eff), ctx, j_A_m2)
        return min(r, self.r_conf())

    def site_mult(self, side):
        """Real nucleation sites each tracked attached bubble represents.

        Real active sites = kernel site density x wettability factor x face
        area (the kernel Surface.site_count rule); tracked slots = N_SITES.
        """
        dens = self.params.site_density if self.params is not None else 2.0e6
        f = 0.5 + self.op.contact_angle / 90.0
        real_sites = dens * f * self._face_area()
        return max(1.0, real_sites / self.N_SITES)

    def _nucleate_and_grow(self, j_A_m2, dt, ctx, r_dep0=None):
        seed_r = self.R_NUC
        # (1) nucleate seeds on both faces FIRST (funded from each side's budget),
        # then grow all attached (incl. the new seeds) with the remainder — so
        # every bit of the Faradaic gas is placed and conservation is exact.
        # A seed costs mult * V(seed): it stands for `mult` real seeds.
        grow_budget = [0.0, 0.0]
        (new_pos, new_r, new_W, new_mult, new_side, new_att, new_dep, new_ph,
         new_touch, new_id) = [], [], [], [], [], [], [], [], [], []
        if r_dep0 is None:
            r_dep0 = self.departure_radius(ctx, max(1e-6, j_A_m2))
        r_cap = self.r_conf()
        for side, electrode in enumerate(("HER", "OER")):
            Qdot = self._faradaic_rate(j_A_m2, electrode, self._face_area(), ctx)
            budget = Qdot * dt
            self.produced_cum += budget
            # gas that had nowhere to go last pass (no attached bubble, no room
            # for a seed) is carried forward, never dropped: produced must equal
            # resident + vented exactly
            budget += self._pending[side]
            self._pending[side] = 0.0
            if budget <= 0.0:
                continue
            mult = self.site_mult(side)
            w_seed = mult * self._vol(seed_r)
            n_att = int(np.count_nonzero(self.attached & (self.side == side)))
            room = self.cap - len(self.r) - len(new_r)
            want = min(self.N_SITES - n_att, int(budget / w_seed), max(0, room))
            want = max(0, min(want, 1 + self.N_SITES // 4))     # smooth the refill
            if want > 0:
                ys, zs = self._sample_sites(side, want)
                want = len(ys)                           # mask may reduce the batch
            if want > 0:
                new_pos.append(np.stack([np.full(want, self._wall_x(side, seed_r)),
                                         ys, zs], axis=1))
                new_r.append(np.full(want, seed_r))
                new_W.append(np.full(want, w_seed))
                new_mult.append(np.full(want, mult))
                new_side.append(np.full(want, side, dtype=np.int8))
                new_att.append(np.ones(want, dtype=bool))
                spread = self.rng.uniform(1 - self.DETACH_SPREAD,
                                          1 + self.DETACH_SPREAD, want)
                # per-bubble departure size, never larger than the channel gap
                new_dep.append(np.clip(r_dep0 * spread, 2 * seed_r,
                                       max(2 * seed_r, r_cap)))
                new_ph.append(self.rng.uniform(0, 2 * np.pi, want))
                new_touch.append(self._p_touch(np.full(want, seed_r),
                                               np.full(want, mult)))
                new_id.append(np.arange(self._next_id, self._next_id + want))
                self._next_id += want
                budget -= want * w_seed
            grow_budget[side] = budget
        if new_pos:
            old_n = len(self.r)
            self.pos = np.vstack([self.pos] + new_pos)
            self.r = np.concatenate([self.r] + new_r)
            self.W = np.concatenate([self.W] + new_W)
            self.mult = np.concatenate([self.mult] + new_mult)
            self.side = np.concatenate([self.side] + new_side)
            self.attached = np.concatenate([self.attached] + new_att)
            n_new = sum(len(v) for v in new_r)
            self.mesh_attached = np.concatenate(
                [self.mesh_attached, np.zeros(n_new, dtype=bool)])
            self.mesh_axis = np.concatenate(
                [self.mesh_axis, np.zeros(n_new, dtype=np.int8)])
            self.mesh_normal = np.vstack(
                [self.mesh_normal, np.zeros((n_new, 3), dtype=np.float64)])
            self.r_dep = np.concatenate([self.r_dep] + new_dep)
            self.phase = np.concatenate([self.phase] + new_ph)
            self.p_touch = np.concatenate([self.p_touch] + new_touch)
            self.ids = np.concatenate([self.ids] + new_id)
            for i in range(old_n, len(self.r)):
                self._emit_event(
                    "birth",
                    id=int(self.ids[i]),
                    side=int(self.side[i]),
                    position_m=self.pos[i],
                    radius_m=float(self.r[i]),
                    represented_count=float(self.mult[i]),
                    represented_volume_m3=float(self.W[i]),
                    departure_radius_m=float(self.r_dep[i]),
                )
        # (2) grow attached with the remaining gas: the budget dW is shared
        # r^2-weighted; each tracked bubble converts its share into a SINGLE-
        # bubble radius increment via its multiplicity (dV_single = dW/mult),
        # so W grows by exactly the allocated gas (conservation stays exact)
        # while r stays a real, literature-scale bubble radius.
        for side in (0, 1):
            b = grow_budget[side]
            att = self.attached & (self.side == side)
            if b <= 0.0:
                continue
            if not att.any():
                self._pending[side] += b        # nowhere to put it *this* pass
                continue
            w = self.r[att] ** 2
            wsum = w.sum()
            if wsum <= 0:
                self._pending[side] += b
                continue
            dW = b * (w / wsum)
            v_single = self._vol(self.r[att]) + dW / self.mult[att]
            r_new = (3.0 * v_single / (4.0 * np.pi)) ** (1.0 / 3.0)
            self.W[att] = self.W[att] + dW
            # A bubble can never exceed (a) its own departure radius — past that
            # the force balance has already released it — nor (b) the channel
            # gap, where it bridges to the opposite plate instead of staying a
            # sphere. Whichever binds, the radius stops there and the surplus
            # gas becomes MORE real bubbles of that size: mult is re-derived
            # from the untouched W = mult*V(r). Without this, a flow time step
            # coarser than the ~1 ms growth cycle inflated every bubble far past
            # its departure size (and straight through the opposite wall).
            r_lim = np.minimum(self.r_dep[att], r_cap)
            over = r_new > r_lim
            if over.any():
                r_new = np.minimum(r_new, r_lim)
                mult_a = self.mult[att]
                mult_a[over] = self.W[att][over] / self._vol(r_new[over])
                self.mult[att] = mult_a
            self.r[att] = r_new
            # keep the swelling bubble tangent to its electrode surface
            off = self._wall_off(r_new)
            if self.elec_planes is not None:
                xc, xa = self.elec_planes
                self.pos[att, 0] = np.where(self.side[att] == 0, xc - off, xa + off)
            else:
                self.pos[att, 0] = np.where(self.side[att] == 0, off,
                                            self.g.Lx - off)

    def _capture_on_mesh(self):
        """Transfer an OER bubble only after it geometrically touches PP."""
        self._ensure_state_arrays()
        geom = self.mesh_geometry()
        if geom is None or not self._mesh_transfer_allowed():
            return
        candidates = np.nonzero(self.attached & (self.side == 1))[0]
        for i in candidates:
            hit = self._nearest_mesh_strand(self.pos[i], self.r[i], geom)
            if hit is None:
                continue
            before = self.pos[i].copy()
            axis, axis_point, distance = hit
            delta = before - axis_point
            norm = float(np.linalg.norm(delta))
            if norm <= np.sqrt(np.finfo(float).eps) * max(
                    geom["strand_radius"] + self.r[i], 1.0e-12):
                # Exact axis coincidence is ambiguous.  The +x direction is the
                # channel-facing normal in the anode coordinate convention.
                normal = np.array([1.0, 0.0, 0.0])
            else:
                normal = delta / norm
            self.attached[i] = False
            self.mesh_attached[i] = True
            self.mesh_axis[i] = axis
            self.mesh_normal[i] = normal
            # Resolve only the sphere/cylinder overlap along the actual contact
            # normal.  This retains the approached side of the strand and
            # removes the former full-strand jump to hard-coded +x.
            self.pos[i] = axis_point + normal * (
                geom["strand_radius"] + self.r[i])
            self.p_touch[i] = 0.0
            self.n_mesh_capture += 1
            self._emit_event(
                "mesh_capture",
                id=int(self.ids[i]),
                side=int(self.side[i]),
                position_before_m=before,
                position_after_m=self.pos[i],
                radius_m=float(self.r[i]),
                mesh_axis=int(axis),
                axis_point_m=axis_point,
                contact_normal=normal,
                distance_to_axis_before_m=float(distance),
                displacement_m=float(np.linalg.norm(self.pos[i] - before)),
            )

    def _coalesce_mesh(self):
        """Merge mesh-held representative cohorts only on physical contact.

        The smaller-multiplicity cohort takes one partner volume from the larger
        cohort (the standard super-droplet update). This conserves represented
        gas exactly and does not merge non-touching bubbles merely because they
        occupy the same mesh unit cell.
        """
        self._ensure_state_arrays()
        idx = np.nonzero(self.mesh_attached & (self.mult > 0.0))[0]
        if len(idx) < 2:
            return
        efficiency = self.p_merge()
        if efficiency <= 0.0:
            return
        # Spatial hash: only bubbles in adjacent diameter-sized buckets can
        # touch. This changes no collision criterion and keeps thousands of
        # mesh-held representatives from turning into an O(N^2) live loop.
        cell = max(2.0 * float(self.r[idx].max()), np.finfo(float).tiny)
        coords = np.floor(self.pos[idx] / cell).astype(np.int64)
        buckets = {}
        for local, key in enumerate(map(tuple, coords)):
            buckets.setdefault(key, []).append(local)
        used = set()
        for qa in range(len(idx)):
            i = int(idx[qa])
            if i in used or self.mult[i] <= 0.0:
                continue
            cx, cy, cz = coords[qa]
            neighbours = []
            for ax in (-1, 0, 1):
                for ay in (-1, 0, 1):
                    for az in (-1, 0, 1):
                        neighbours.extend(buckets.get(
                            (int(cx + ax), int(cy + ay), int(cz + az)), ()))
            for qb in neighbours:
                if qb <= qa:
                    continue
                j = int(idx[qb])
                if j in used or self.mult[j] <= 0.0 or self.side[i] != self.side[j]:
                    continue
                if np.linalg.norm(self.pos[i] - self.pos[j]) > self.r[i] + self.r[j]:
                    continue
                # Contact is necessary; electrolyte film drainage supplies the
                # continuous merge efficiency instead of a concentration cutoff.
                if self.rng.random() > efficiency:
                    continue
                small, large = (i, j) if self.mult[i] <= self.mult[j] else (j, i)
                ms, ml = float(self.mult[small]), float(self.mult[large])
                remainder = ml - ms
                rs, rl = float(self.r[small]), float(self.r[large])
                r_new = (rs ** 3 + rl ** 3) ** (1.0 / 3.0)
                if r_new > self.r_conf():
                    continue
                before_s, before_l = self.pos[small].copy(), self.pos[large].copy()
                vs, vl = self._vol(rs), self._vol(rl)
                self.pos[small] = (vs * before_s + vl * before_l) / (vs + vl)
                self.r[small] = r_new
                self.mult[large] = max(0.0, remainder)
                self.W[small] = ms * self._vol(r_new)
                self.W[large] = self.mult[large] * self._vol(rl)
                self.r_dep[small] = max(float(self.r_dep[small]), r_new)
                geom = self.mesh_geometry()
                if geom is not None:
                    hit = self._nearest_mesh_strand(self.pos[small], r_new, geom)
                    if hit is not None:
                        axis, axis_point, _ = hit
                        delta = self.pos[small] - axis_point
                        norm = float(np.linalg.norm(delta))
                        normal = (delta / norm if norm > np.finfo(float).eps
                                  else np.array([1.0, 0.0, 0.0]))
                        self.mesh_axis[small] = axis
                        self.mesh_normal[small] = normal
                        self.pos[small] = axis_point + normal * (
                            geom["strand_radius"] + r_new)
                self.n_merge_mesh += 1
                self.n_merge_real += ms
                self._record_merge(before_s, before_l, r_new,
                                   int(self.side[small]), False, rs, rl,
                                   ids=[int(self.ids[small]), int(self.ids[large])],
                                   state="mesh-held")
                used.add(small); used.add(large)
                break
        if np.any(self.mult <= np.finfo(float).eps):
            self._filter(self.mult > np.finfo(float).eps)

    def _move_and_release_mesh(self, ns, dt, ctx):
        """Slide on strands and release by measured-angle force balance.

        With no measured contact-angle hysteresis we do not invent a tangential
        pinning coefficient. A held bubble follows liquid+buoyant slip along its
        current strand. It releases at a strand/coverage end, or when buoyancy
        plus Schiller--Naumann drag exceeds the Young--Dupre static adhesion
        estimate based on the measured PP bubble contact angle.
        """
        self._ensure_state_arrays()
        idx = np.nonzero(self.mesh_attached)[0]
        if len(idx) == 0:
            return
        geom = self.mesh_geometry()
        if geom is None:
            for i in idx:
                self._emit_event(
                    "mesh_release_edge",
                    id=int(self.ids[i]),
                    side=int(self.side[i]),
                    position_m=self.pos[i],
                    radius_m=float(self.r[i]),
                    reason="mesh_geometry_unavailable",
                )
            self.mesh_attached[idx] = False
            self.mesh_axis[idx] = 0
            self.mesh_normal[idx] = 0.0
            self.n_mesh_release_edge += len(idx)
            return
        p, r = self.pos[idx], self.r[idx]
        uf, vf, wf = ns.sample_velocity(p)
        liquid = np.stack([uf, vf, wf], axis=1)
        speed = np.linalg.norm(liquid, axis=1)
        rho, mu = float(ctx["rho_l"]), float(ctx["mu"])
        sigma, d_rho = float(ctx["sigma"]), float(ctx["d_rho"])
        Re = 2.0 * r * speed * rho / max(mu, np.finfo(float).tiny)
        Cd = np.zeros_like(Re)
        low = (Re > np.sqrt(np.finfo(float).eps)) & (Re < 1000.0)
        high = Re >= 1000.0
        Cd[low] = 24.0 / Re[low] * (1.0 + 0.15 * Re[low] ** 0.687)
        Cd[high] = 0.44
        drag = (0.5 * rho * Cd * np.pi * r * r * speed)[:, None] * liquid
        buoy = (d_rho * self._vol(r) * G)[:, None] * np.asarray(ns.up)[None, :]
        force = np.linalg.norm(drag + buoy, axis=1)

        theta_b = np.radians(180.0 - float(getattr(
            self.op, "mesh_contact_angle", 90.0)))
        contact_radius = np.minimum(geom["strand_radius"],
                                    r * abs(np.sin(theta_b)))
        work_adhesion = sigma * max(0.0, 1.0 + np.cos(theta_b))
        adhesion = 2.0 * np.pi * contact_radius * work_adhesion
        release = force >= adhesion

        # No hysteresis input => no invented static-friction force. A bubble may
        # translate only along the strand that it is actually touching.
        slip = terminal_velocity(r, d_rho, mu, rho)
        transport = liquid + slip[:, None] * np.asarray(ns.up)[None, :]
        held = ~release
        axis = self.mesh_axis[idx]
        move_y = held & (axis == 1)
        move_z = held & (axis == 2)
        p[move_y, 1] += transport[move_y, 1] * dt
        p[move_z, 2] += transport[move_z, 2] * dt
        edge = held & ((p[:, 1] < geom["y0"]) | (p[:, 1] > geom["y1"])
                       | (p[:, 2] < 0.0) | (p[:, 2] > self.g.Lz))
        p[:, 1] = np.clip(p[:, 1], 0.0, self.g.Ly)
        p[:, 2] = np.clip(p[:, 2], 0.0, self.g.Lz)
        self.pos[idx] = p

        force_idx, edge_idx = idx[release], idx[edge]
        if len(force_idx):
            for local in np.nonzero(release)[0]:
                i = int(idx[local])
                self._emit_event(
                    "mesh_release_force",
                    id=int(self.ids[i]),
                    side=int(self.side[i]),
                    position_m=self.pos[i],
                    radius_m=float(self.r[i]),
                    force_N=float(force[local]),
                    adhesion_N=float(adhesion[local]),
                    mesh_axis=int(self.mesh_axis[i]),
                )
            self.mesh_attached[force_idx] = False
            self.mesh_axis[force_idx] = 0
            self.mesh_normal[force_idx] = 0.0
            self.n_mesh_release_force += len(force_idx)
        if len(edge_idx):
            for local in np.nonzero(edge)[0]:
                i = int(idx[local])
                self._emit_event(
                    "mesh_release_edge",
                    id=int(self.ids[i]),
                    side=int(self.side[i]),
                    position_m=self.pos[i],
                    radius_m=float(self.r[i]),
                    mesh_axis=int(self.mesh_axis[i]),
                    reason="strand_or_coverage_edge",
                )
            self.mesh_attached[edge_idx] = False
            self.mesh_axis[edge_idx] = 0
            self.mesh_normal[edge_idx] = 0.0
            self.n_mesh_release_edge += len(edge_idx)

    # ----------------------------------------------------------- coalescence
    def p_merge(self):
        """Continuous electrolyte coalescence efficiency (0 < eta <= 1).

        The database's critical coalescence concentration is treated as the
        measured half-inhibition concentration, eta=c_crit/(c_crit+c), instead
        of the former nonphysical hard switch.  This is an explicit one-input
        closure: it adds no new fitted constant, but it is not an ion-resolved
        thin-film calculation.
        """
        p = self.params
        crit = ELECTROLYTES.get(getattr(self.op, "electrolyte", "KOH"), {}).get(
            "c_coalesce", getattr(p, "c_coalesce_crit", 0.3) if p else 0.3)
        crit = max(float(crit), np.finfo(float).tiny)
        concentration = max(0.0, float(getattr(self.op, "c_electrolyte", 0.0)))
        return crit / (crit + concentration)

    def _p_touch(self, r, mult):
        """P(at least one real neighbour within reach) for a Poisson site field.

        The real neighbours of a tracked bubble are its own `mult` siblings, at
        number density n = mult * N_SITES / A_face. For a 2-D Poisson field the
        chance one lies inside radius d is 1 - exp(-pi n d^2), with the contact
        reach d = 2 r sin(beta), the sum of two equal footprint radii.
        """
        sinb = abs(np.sin(np.radians(self.op.contact_angle)))
        n = mult * self.N_SITES / self._face_area()
        d = 2.0 * r * sinb
        return 1.0 - np.exp(-np.pi * n * d * d)

    def _coalesce_free(self, ns, dt, ctx):
        """Shima-style weighted pair collisions in each Eulerian flow cell.

        Random pairing represents every possible parcel pair through the exact
        combinatorial factor ``N_pair_all/N_pair_sampled``.  The collision
        kernel is geometric cross-section times physical approach speed and a
        Prince--Blanch film-drainage efficiency.  A collision changes the two
        existing weighted cohorts in place, so the tracked-particle count does
        not grow with the number of outer time steps.  Pair kinematics are
        evaluated as arrays per cell; only accepted collision events enter the
        Python bookkeeping loop.  This keeps the live solver responsive without
        changing the random-pair or weighted-collision equations.
        """
        self._ensure_state_arrays()
        free = np.nonzero((~self.attached) & (~self.mesh_attached)
                          & (self.mult > 0.0))[0]
        merge_efficiency = self.p_merge()
        if len(free) < 2 or merge_efficiency <= 0.0:
            return
        pos = self.pos[free]
        velocity = self.bubble_velocity(ns, ctx)[free]
        cells = np.clip((pos / self.g.h).astype(np.int64),
                        0, [self.g.nx - 1, self.g.ny - 1, self.g.nz - 1])
        buckets = {}
        for local, cell in enumerate(cells):
            key = (int(self.side[free[local]]), int(cell[0]), int(cell[1]), int(cell[2]))
            buckets.setdefault(key, []).append(local)

        # Assemble the random pairs per cell, then evaluate all cell batches in
        # one vector operation.  Most cells contain only a handful of parcels;
        # creating dozens of tiny NumPy arrays was slower than the old scalar
        # loop even though each individual formula was vectorised.
        local_i_parts, local_j_parts, factor_parts = [], [], []
        for members in buckets.values():
            count = len(members)
            sampled_pairs = count // 2
            if sampled_pairs == 0:
                continue
            shuffled = np.asarray(self.rng.permutation(members), dtype=np.int64)
            pair_factor = count * (count - 1) / (2.0 * sampled_pairs)
            local_i_parts.append(shuffled[:2 * sampled_pairs:2])
            local_j_parts.append(shuffled[1:2 * sampled_pairs:2])
            factor_parts.append(np.full(sampled_pairs, pair_factor))
        if not local_i_parts:
            return

        local_i = np.concatenate(local_i_parts)
        local_j = np.concatenate(local_j_parts)
        pair_factor = np.concatenate(factor_parts)
        pair_i, pair_j = free[local_i], free[local_j]
        mi, mj = self.mult[pair_i], self.mult[pair_j]
        ri, rj = self.r[pair_i], self.r[pair_j]
        relative = np.linalg.norm(
            velocity[local_i] - velocity[local_j], axis=1)
        yi, _ = self._wall_dist(self.pos[pair_i, 0], self.side[pair_i])
        yj, _ = self._wall_dist(self.pos[pair_j, 0], self.side[pair_j])
        shear = 0.5 * (self.shear_rate(yi) + self.shear_rate(yj))
        approach = relative + shear * (ri + rj)
        active = (mi > 0.0) & (mj > 0.0) & (approach > 0.0)
        if not active.any():
            return

        pair_i, pair_j = pair_i[active], pair_j[active]
        pair_factor = pair_factor[active]
        mi, mj = mi[active], mj[active]
        ri, rj = ri[active], rj[active]
        approach = approach[active]
        tiny = np.finfo(float).tiny
        reduced = 0.5 / (1.0 / np.maximum(ri, tiny)
                         + 1.0 / np.maximum(rj, tiny))
        t_drain = (
            np.sqrt(reduced ** 3 * float(ctx["rho_l"])
                    / (16.0 * float(ctx["sigma"])))
            * np.log(self.H0 / self.HF))
        t_contact = (ri + rj) / approach
        efficiency = np.exp(-t_drain / np.maximum(t_contact, tiny))
        kernel = np.pi * (ri + rj) ** 2 * approach * efficiency
        probability = (
            merge_efficiency * np.maximum(mi, mj) * kernel * float(dt)
            / self.g.cell_volume * pair_factor)
        gamma = np.floor(probability).astype(np.int64)
        gamma += (self.rng.random(len(gamma))
                  < probability - gamma).astype(np.int64)

        choose_i = mi <= mj
        small = np.where(choose_i, pair_i, pair_j)
        large = np.where(choose_i, pair_j, pair_i)
        m_small = np.where(choose_i, mi, mj)
        m_large = np.where(choose_i, mj, mi)
        max_gamma = np.floor(
            m_large / np.maximum(m_small, tiny)).astype(np.int64)
        gamma = np.minimum(gamma, max_gamma)
        r_small = self.r[small]
        r_large = self.r[large]
        r_new = (r_small ** 3 + gamma * r_large ** 3) ** (1.0 / 3.0)
        accepted = (gamma > 0) & (r_new <= self.r_conf())
        if not accepted.any():
            return

        small, large = small[accepted], large[accepted]
        m_small, m_large = m_small[accepted], m_large[accepted]
        gamma, r_small = gamma[accepted], r_small[accepted]
        r_large, r_new = r_large[accepted], r_new[accepted]
        before_small = self.pos[small].copy()
        before_large = self.pos[large].copy()
        v_small, v_large = self._vol(r_small), self._vol(r_large)
        self.pos[small] = (
            v_small[:, None] * before_small
            + (gamma * v_large)[:, None] * before_large
        ) / (v_small + gamma * v_large)[:, None]
        self.r[small] = r_new
        self.r_dep[small] = np.maximum(self.r_dep[small], r_new)
        self.mult[large] = np.maximum(0.0, m_large - gamma * m_small)
        merged_real = gamma * m_small
        self.n_merge_free += int(len(small))
        self.n_merge_real += float(merged_real.sum())
        for q in range(len(small)):
            self._record_merge(
                before_small[q], before_large[q], r_new[q],
                int(self.side[small[q]]), False,
                r_small[q], r_large[q],
                ids=[int(self.ids[small[q]]), int(self.ids[large[q]])],
                state="free")

        if len(small):
            self.W = self.mult * self._vol(self.r)
            self._filter(self.mult > np.finfo(float).eps)
            # Coalescence increases the receiving parcel radius after advection.
            # Re-seat that enlarged sphere against its electrode so the new
            # surface cannot overlap the catalyst plane for one outer step.
            free_now = (~self.attached) & (~self.mesh_attached)
            if free_now.any():
                idx = np.nonzero(free_now)[0]
                clearance = np.nextafter(self.r[idx], np.inf)
                y_w, nrm = self._wall_dist(self.pos[idx, 0], self.side[idx])
                inside = y_w < clearance
                if inside.any():
                    hit = idx[inside]
                    self.pos[hit, 0] += ((clearance - y_w)[inside]
                                         * nrm[inside])

    def _coalesce(self):
        """Merge wall bubbles that have grown into a neighbour.

        Bubbles do not burst in the liquid — they MERGE on contact and only
        burst at a free surface (here: the outlet vent). The neighbours live
        below the tracked resolution, so a merge is drawn against the INCREMENT
        in contact probability produced by this step's growth (dP), not against
        a per-step constant — that keeps the merge rate independent of dt.
        A merge fuses two real bubbles into one: mult halves, r grows 2^(1/3),
        and W = mult*V(r) is exactly unchanged.
        """
        att = self.attached & (self.mult >= 2.0)
        if not att.any():
            return
        p_new = self._p_touch(self.r[att], self.mult[att])
        dP = np.clip(p_new - self.p_touch[att], 0.0, 1.0)
        self.p_touch[att] = p_new
        r_cap = self.r_conf()
        grown = self.r[att] * 2.0 ** (1.0 / 3.0)
        hit = (self.rng.random(int(att.sum())) < dP * self.p_merge()) \
            & (grown <= r_cap)                     # a bridging pair cannot fuse
        if not hit.any():
            return
        idx = np.nonzero(att)[0][hit]
        event_pos = self.pos[idx].copy()
        event_radius = self.r[idx].copy()
        self.r[idx] = self.r[idx] * 2.0 ** (1.0 / 3.0)
        self.mult[idx] = self.mult[idx] * 0.5      # W = mult*V(r) preserved
        # halved neighbour density + bigger reach -> recompute, no cascade
        self.p_touch[idx] = self._p_touch(self.r[idx], self.mult[idx])
        self.n_merge += int(hit.sum())
        # a merged bubble that already exceeds its departure size leaves at the
        # merged (larger) radius — the coalescence-driven departure real cells show
        off = self._wall_off(self.r[idx])
        if self.elec_planes is not None:
            xc, xa = self.elec_planes
            self.pos[idx, 0] = np.where(self.side[idx] == 0, xc - off, xa + off)
        else:
            self.pos[idx, 0] = np.where(self.side[idx] == 0, off, self.g.Lx - off)
        for q, parcel_index in enumerate(idx):
            self._record_merge(event_pos[q], event_pos[q], self.r[parcel_index],
                               self.side[parcel_index], True,
                               event_radius[q], event_radius[q],
                               ids=[int(self.ids[parcel_index]),
                                    int(self.ids[parcel_index])],
                               state="electrode-attached")

    def _detach(self, ctx, j_A_m2):
        """Release attached bubbles that reached their departure radius."""
        if not self.attached.any():
            return
        go = self.attached & (self.r >= self.r_dep)
        if go.any():
            for i in np.nonzero(go)[0]:
                self._emit_event(
                    "detach",
                    id=int(self.ids[i]),
                    side=int(self.side[i]),
                    position_m=self.pos[i],
                    radius_m=float(self.r[i]),
                    departure_radius_m=float(self.r_dep[i]),
                    reason="radius_reached_departure_threshold",
                )
            self.attached[go] = False
        self._thin_free()

    def _thin_free(self):
        """Thin free risers while preserving number, area and gas volume.

        A volume-only rescale preserved ``sum(W)`` but changed ``sum(mult)`` and
        ``sum(mult*r**2)``.  Those are the real-bubble count and interfacial area,
        so thinning changed d32, drag and coalescence.  We now draw a fresh
        weighted subset and solve non-negative representative weights that
        preserve, independently on each electrode side, the 0th, 2nd and 3rd
        radius moments.  If the selected support cannot represent those moments
        without negative weights, thinning is skipped rather than corrupting the
        physics.
        """
        self._ensure_state_arrays()
        if self.record_mode:
            return
        free = np.nonzero((~self.attached) & (~self.mesh_attached))[0]
        sides = [s for s in (0, 1) if np.any(self.side[free] == s)]
        minimum_support = 3 * len(sides)
        target = max(int(self.FREE_TARGET), minimum_support)
        if len(free) <= target:
            return

        # Guarantee radius support on each gas side, then fill the remaining
        # slots by real-number weight.  The subsequent moment solve is exact;
        # this draw only controls the retained spatial sample.
        mandatory = []
        for side in sides:
            idx = free[self.side[free] == side]
            rr, mm = self.r[idx], np.maximum(self.mult[idx], 0.0)
            mean_r = float(np.sum(mm * rr) / max(mm.sum(), np.finfo(float).tiny))
            mandatory.extend((int(idx[np.argmin(rr)]), int(idx[np.argmax(rr)]),
                              int(idx[np.argmin(np.abs(rr - mean_r))])))
        mandatory = np.unique(np.asarray(mandatory, dtype=np.int64))
        remaining = np.setdiff1d(free, mandatory, assume_unique=False)
        n_fill = target - len(mandatory)
        if n_fill > 0:
            prob = np.maximum(self.mult[remaining], 0.0)
            prob = prob / prob.sum() if prob.sum() > 0.0 else None
            drawn = self.rng.choice(remaining, size=n_fill, replace=False, p=prob)
            kept = np.concatenate([mandatory, drawn])
        else:
            kept = mandatory[:target]

        r_scale = max(float(self.r[free].max()), np.finfo(float).tiny)
        x_all = self.r[free] / r_scale
        x_keep = self.r[kept] / r_scale
        rows, targets = [], []
        for side in sides:
            all_side = self.side[free] == side
            keep_side = self.side[kept] == side
            for power in (0, 2, 3):
                rows.append(keep_side.astype(float) * x_keep ** power)
                targets.append(float(np.sum(self.mult[free][all_side]
                                            * x_all[all_side] ** power)))
        A = np.vstack(rows)
        b = np.asarray(targets)

        # Closest-to-equal non-negative STATISTICAL weights under exact linear
        # moment constraints.  A lower bound of one rejected valid weighted
        # collisions and introduced severe time-step dependence.  Fractional
        # expected counts are therefore allowed and disclosed in diagnostics.
        lower = np.zeros(len(kept))
        shifted = b
        active = np.ones(len(kept), dtype=bool)
        solved = None
        while (int(active.sum()) >= len(b)
               and all(int(np.count_nonzero(active & (self.side[kept] == side))) >= 3
                       for side in sides)):
            A_act = A[:, active]
            w0 = np.zeros(int(active.sum()))
            active_sides = self.side[kept][active]
            for side in sides:
                sm = active_sides == side
                total_n = shifted[3 * sides.index(side)]
                if sm.any():
                    w0[sm] = total_n / sm.sum()
            residual = shifted - A_act @ w0
            gram = A_act @ A_act.T
            correction = A_act.T @ np.linalg.lstsq(gram, residual, rcond=None)[0]
            candidate = w0 + correction
            scale = max(1.0, float(np.max(np.abs(candidate))))
            if candidate.min(initial=0.0) >= -1e-12 * scale:
                solved = lower.copy()
                solved[active] += np.maximum(0.0, candidate)
                break
            active_indices = np.nonzero(active)[0]
            active[active_indices[int(np.argmin(candidate))]] = False

        if solved is None:
            self.thinning_skipped += 1
            return

        moment_scale = np.maximum(1.0, np.abs(b))
        error = float(np.max(np.abs(A @ solved - b) / moment_scale))
        self.thinning_moment_error = max(self.thinning_moment_error, error)
        if error > 1e-9:
            self.thinning_skipped += 1
            return

        self.mult[kept] = solved
        self.W[kept] = solved * self._vol(self.r[kept])
        live = self.attached | self.mesh_attached
        live[kept] = True
        self._filter(live)

    def bubble_velocity(self, ns, ctx):
        """Instantaneous representative-bubble velocity [m/s].

        Attached bubbles are stationary. Free bubbles use the solved liquid
        velocity plus Schiller--Naumann terminal slip and the published
        Tomiyama/Antal wall-normal force balance. Artificial sinusoidal wobble
        and random crawl are intentionally absent from the physical trajectory.
        """
        self._ensure_state_arrays()
        velocity = np.zeros((len(self.r), 3), dtype=np.float64)
        free = (~self.attached) & (~self.mesh_attached)
        if not free.any():
            return velocity
        p = self.pos[free]
        r = self.r[free]
        uf, vf, wf = ns.sample_velocity(p)
        slip = terminal_velocity(r, ctx["d_rho"], ctx["mu"], ctx["rho_l"])
        side = self.side[free]
        y_w, nrm = self._wall_dist(p[:, 0], side)
        vn = self.wall_normal_velocity(r, slip, y_w, ctx)
        velocity[free, 0] = uf + slip * ns.up[0] + vn * nrm
        velocity[free, 1] = vf + slip * ns.up[1]
        velocity[free, 2] = wf + slip * ns.up[2]
        return velocity

    def trace_kinematics(self, ns, ctx):
        """Liquid, buoyant-slip and effective velocities for video/audit data."""
        self._ensure_state_arrays()
        n = len(self.r)
        liquid = np.zeros((n, 3), dtype=np.float64)
        slip_vector = np.zeros((n, 3), dtype=np.float64)
        effective = self.bubble_velocity(ns, ctx)
        if n == 0:
            return liquid, slip_vector, effective
        uf, vf, wf = ns.sample_velocity(self.pos)
        liquid[:, 0] = uf
        liquid[:, 1] = vf
        liquid[:, 2] = wf
        moving = ~self.attached
        if moving.any():
            slip = terminal_velocity(
                self.r[moving], ctx["d_rho"], ctx["mu"], ctx["rho_l"])
            slip_vector[moving] = slip[:, None] * np.asarray(ns.up)[None, :]
        held = self.mesh_attached
        if held.any():
            transport = liquid[held] + slip_vector[held]
            axis = self.mesh_axis[held]
            projected = np.zeros_like(transport)
            projected[axis == 1, 1] = transport[axis == 1, 1]
            projected[axis == 2, 2] = transport[axis == 2, 2]
            effective[held] = projected
        return liquid, slip_vector, effective

    def _advect(self, ns, dt, ctx):
        """Advect free bubbles with solved flow, slip and wall-normal drift.

        Vent bubbles that reach the configured outlet. Attached bubbles stay
        put; no display wobble or random crawl enters the physical trajectory.
        """
        self._ensure_state_arrays()
        if len(self.r) == 0:
            return
        free = (~self.attached) & (~self.mesh_attached)
        if free.any():
            p = self.pos[free]
            r_f = self.r[free]
            velocity = self.bubble_velocity(ns, ctx)[free]
            # WALL-NORMAL force balance (Tomiyama lift vs Antal wall lubrication).
            # Lubrication repels a bubble at contact while lift draws it back
            # from farther out, giving a stable near-wall stand-off just above r.
            side_f = self.side[free]
            d = velocity * dt
            # axis-wise obstacle collision, SUBSTEPPED so a fast bubble can
            # never tunnel through a land in one step (the displacement is cut
            # into <= half-cell moves; an endpoint-only check let jet-riding
            # bubbles jump whole rib bands). Blocked components are cancelled,
            # the others survive -> bubbles SLIDE along rib walls to the gaps.
            max_disp = float(np.abs(d).max()) if len(d) else 0.0
            n_sub = max(1, int(np.ceil(max_disp / (0.5 * self.g.h))))
            ds = d / n_sub
            y_top = self.g.Ly - (self.r[free] + 0.2 * self.g.h)
            for _ in range(n_sub):
                for ax in range(3):
                    cand = p.copy()
                    cand[:, ax] += ds[:, ax]
                    blocked = self._in_solid(ns, cand)
                    if ax == 1 and self.vent_line is not None:
                        # the closed part of the top face is PLATE, not an exit:
                        # gas that reaches it is trapped and must find the port
                        blocked |= (cand[:, 1] > y_top) & ~self._at_top_vent(cand[:, 2])
                    p[~blocked, ax] = cand[~blocked, ax]
            # the bubble surface cannot enter the electrode: its centre stops at
            # one radius from the catalyst plane (where the wall force diverges)
            y_w, nrm = self._wall_dist(p[:, 0], side_f)
            # Use the next representable outward radius.  Subtracting a radius
            # from an electrode-plane coordinate can otherwise round the final
            # clearance a few ulps below r, which looks like a tiny penetration
            # in downstream geometry checks.
            clearance = np.nextafter(r_f, np.inf)
            inside = y_w < clearance
            if inside.any():
                p[inside, 0] += (clearance - y_w)[inside] * nrm[inside]
            self.pos[free] = p
        # reflect off solid walls; vent free bubbles past the outlet
        m = self.r + 0.2 * self.g.h
        self.pos = self.g.clamp_points(self.pos, m)
        free_now = (~self.attached) & (~self.mesh_attached)
        y, z = self.pos[:, 1], self.pos[:, 2]
        vented = free_now & (y > (self.g.Ly - m)) & self._at_top_vent(z)
        if self.vent_line is not None and self.vent_face in ("left", "right"):
            # A SIDE port: gas that reaches that wall row leaves there. The z
            # coordinate is CLAMPED to the wall (unlike y, whose top is open), so
            # a bubble sits exactly ON the margin — test with >=, not >, or the
            # side vent can never fire and the cell fills with gas forever.
            at_lo = z <= m * (1.0 + 1e-9)
            at_hi = z >= (self.g.Lz - m) * (1.0 - 1e-9)
            vented |= free_now & at_lo & self._at_side_vent("left", y)
            vented |= free_now & at_hi & self._at_side_vent("right", y)
        if vented.any():
            for i in np.nonzero(vented)[0]:
                self._emit_event(
                    "vent",
                    id=int(self.ids[i]),
                    side=int(self.side[i]),
                    position_m=self.pos[i],
                    radius_m=float(self.r[i]),
                    represented_volume_m3=float(self.W[i]),
                )
            self.vented_cum += float(self.W[vented].sum())
            keep = ~vented
            self._filter(keep)

    def _filter(self, keep):
        self._ensure_state_arrays()
        self.pos = self.pos[keep]; self.r = self.r[keep]; self.W = self.W[keep]
        self.mult = self.mult[keep]
        self.side = self.side[keep]; self.attached = self.attached[keep]
        self.mesh_attached = self.mesh_attached[keep]
        self.mesh_axis = self.mesh_axis[keep]
        self.mesh_normal = self.mesh_normal[keep]
        self.r_dep = self.r_dep[keep]; self.phase = self.phase[keep]
        self.p_touch = self.p_touch[keep]
        self.ids = self.ids[keep]

    # --------------------------------------------------------------- deposit
    def interphase_fields(self, ns, ctx):
        """Deposit void, Sauter diameter and gas velocity on flow cells.

        ``d32 = 6 alpha_g / a_i`` follows directly from dispersed-sphere volume
        and interfacial area. Deposits include parcel multiplicity, so thinning
        changes sampling noise but not phase volume or area.
        """
        deposited_fields = np.zeros((5,) + self.g.shape, dtype=np.float64)
        gas, area = deposited_fields[0], deposited_fields[1]
        momentum = deposited_fields[2:]
        if len(self.r):
            inv_cell = 1.0 / self.g.cell_volume
            void_weight = self.W * inv_cell
            area_weight = self.mult * (4.0 * np.pi * self.r * self.r) * inv_cell
            velocity = self.bubble_velocity(ns, ctx)
            fluid = ~ns.solid
            deposited = self.g.deposit27_many(
                deposited_fields, self.pos,
                np.vstack((void_weight, area_weight,
                           void_weight[None, :] * velocity.T)),
                fluid)
            self.deposition_unresolved_volume = max(
                0.0, float(void_weight.sum()) - float(deposited[0])
            ) * self.g.cell_volume
        else:
            self.deposition_unresolved_volume = 0.0
        self.alpha_raw_max = float(gas.max()) if gas.size else 0.0
        self.alpha_overfilled_cells = int(np.count_nonzero(gas > 1.0))
        # A phase fraction cannot exceed one.  Scale gas volume, interfacial
        # area and gas momentum by the SAME local factor before deriving d32 and
        # velocity.  Clipping alpha alone made the returned alpha, d32 and drag
        # describe different phase inventories.
        alpha_cap = 1.0 - np.sqrt(np.finfo(float).eps)
        scale = np.ones_like(gas)
        over = gas > alpha_cap
        scale[over] = alpha_cap / gas[over]
        self.deposition_clipped_volume = float(
            np.sum(gas[over] - alpha_cap) * self.g.cell_volume)
        gas *= scale
        area *= scale
        momentum *= scale[None, ...]
        gas_velocity = np.zeros_like(momentum)
        occupied = gas > np.finfo(float).tiny
        for axis in range(3):
            gas_velocity[axis, occupied] = momentum[axis, occupied] / gas[occupied]
        diameter = np.zeros_like(gas)
        surfaced = area > np.finfo(float).tiny
        diameter[surfaced] = 6.0 * gas[surfaced] / area[surfaced]
        return gas, gas_velocity, diameter

    def deposit_void(self, solid=None):
        """Scatter bubble gas volume -> grid void fraction (3x3x3 smear)."""
        gas = self.g.field()
        if len(self.r):
            valid = None if solid is None else ~np.asarray(solid, dtype=bool)
            self.g.deposit27(gas, self.pos, self.W / self.g.cell_volume, valid)
        return np.minimum(gas, 1.0 - np.sqrt(np.finfo(float).eps))

    # ------------------------------------------------------------ diagnostics
    def resident_gas(self):
        return float(self.W.sum()) if len(self.W) else 0.0

    def holdup(self, fluid_cells=None):
        """Resident gas divided by liquid-domain volume.

        ``fluid_cells`` lets the cell engine exclude ribs/core. The no-argument
        form remains for standalone boxes where every grid cell is fluid.
        """
        n_cells = self.g.n if fluid_cells is None else int(fluid_cells)
        total_vol = n_cells * self.g.cell_volume
        return self.resident_gas() / total_vol if total_vol else 0.0

    def pending_gas(self):
        """Unresolved/incubating gas carried between nucleation passes [m^3]."""
        return float(sum(self._pending))

    def coverage(self, side):
        """Fraction of the face shadowed by attached-bubble footprints (Poisson
        union, kernel Surface.coverage closure). Each tracked bubble stamps
        `mult` real footprints, so theta is the REAL physical coverage."""
        m = self.attached & (self.side == side)
        if not m.any():
            return 0.0
        sinb = abs(np.sin(np.radians(self.op.contact_angle)))
        foot = self.mult[m] * np.pi * (self.r[m] * sinb) ** 2
        return float(min(0.95, 1.0 - np.exp(-foot.sum() / self._face_area())))

    def near_wall_mask(self, side, slab_cells=2, *, layer_m=None):
        """Bubbles within a physical layer of this side's electrode surface.

        ``layer_m`` is preferred for scalar electrochemistry because the
        Bruggeman near-layer thickness is a physical model input and must not
        silently become ``slab_cells * h`` when the flow grid changes.  The
        cell-count form remains for display/binning callers.
        """
        slab = float(layer_m) if layer_m is not None else slab_cells * self.g.h
        slab = max(slab, np.finfo(float).tiny)
        x = self.pos[:, 0]
        if self.elec_planes is not None:
            xc, xa = self.elec_planes
            return (np.abs(x - xc) < slab) if side == 0 else (np.abs(x - xa) < slab)
        return (x < slab) if side == 0 else (x > self.g.Lx - slab)

    def void_near_wall(self, side, slab_cells=2, *, layer_m=None):
        """Gas volume fraction in the near-electrode layer (feeds the kernel
        Bruggeman void resistance, like Surface.void_fraction)."""
        if len(self.r) == 0:
            return 0.0
        thickness = float(layer_m) if layer_m is not None else slab_cells * self.g.h
        thickness = max(thickness, np.finfo(float).tiny)
        m = self.near_wall_mask(side, slab_cells, layer_m=thickness)
        layer_vol = self._face_area() * thickness
        return float(min(0.6, self.W[m].sum() / layer_vol))

    def size_stats(self):
        """Multiplicity-weighted number mean/std of bubble radius [m]."""
        if len(self.r) == 0:
            return 0.0, 0.0
        weights = np.maximum(0.0, self.mult)
        total = float(weights.sum())
        if total <= 0.0:
            return 0.0, 0.0
        mean = float(np.sum(weights * self.r) / total)
        var = float(np.sum(weights * (self.r - mean) ** 2) / total)
        return mean, var ** 0.5

    def gas_closure_error(self):
        if self.produced_cum <= 0:
            return 0.0
        return abs(self.produced_cum - (self.resident_gas() + self.pending_gas()
                                        + self.vented_cum)) \
            / self.produced_cum

    def snapshot_flat(self):
        """Flat [x, y, z, r, side, state, id]*N in metres, grid frame.

        state: 0 free, 1 catalyst-attached, 2 mesh-held.

        The stable per-bubble id lets the browser MATCH bubbles across
        snapshots and interpolate their motion at 60 fps (same fix as the 2-D
        app's flow2d ids — without it the poll cadence shows as stutter)."""
        self._ensure_state_arrays()
        if len(self.r) == 0:
            return []
        out = np.empty((len(self.r), 7))
        out[:, 0:3] = self.pos
        out[:, 3] = self.r
        out[:, 4] = self.side
        out[:, 5] = self.attached.astype(float) + 2.0 * self.mesh_attached.astype(float)
        out[:, 6] = self.ids
        return out.ravel().tolist()
