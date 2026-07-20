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
                 Schiller-Naumann terminal velocity) with a gentle lateral
                 meander, and vents at the outlet

REPRESENTATIVE MULTIPLICITY (the honest answer to real bubble sizes): at real
electrolysis departure sizes (~50-300 um diameter) a working cell detaches
HUNDREDS OF THOUSANDS of bubbles per second — tracking each one is the
documented millions-of-bubbles wall. So each tracked bubble carries a
multiplicity `mult`: its RADIUS is a genuine single-bubble radius (drives
slip, detachment, the rendered size), while its GAS CONTENT is
W = mult * V(r) and its coverage footprint counts mult sites. `mult` for
attached bubbles = (real nucleation-site count from the kernel site density) /
(tracked slots), so coverage, gas totals and the ~10 ms growth-to-departure
cycle all come out at REAL physical values; free risers are adaptively thinned
(conservation kept exact by renormalising the survivors' W).

COALESCENCE: a bubble does not "pop" in the liquid — when two touch they MERGE
(and only burst at a free surface, which here is the outlet vent). Merging is
resolved statistically because the neighbours of a tracked bubble are its own
`mult` real siblings, below the tracked resolution: as a wall bubble swells, the
chance that a Poisson-distributed neighbour falls inside its new reach grows by
dP = P(reach_new) - P(reach_old), and a merge is drawn against dP * p_merge —
rate-consistent (independent of dt) rather than a per-step coin flip.
p_merge comes from the kernel: concentrated electrolytes (KOH above
ELECTROLYTES["KOH"]["c_coalesce"] = 0.3 M) inhibit coalescence (salting-out).
A merge halves `mult` and grows r by 2^(1/3): W = mult*V(r) is untouched.
Not resolved: coalescence inside the free rising swarm.

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
    produced (integral of j/nF) = resident (attached + free) + vented
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
        self.r_dep = z0()                 # per-bubble departure radius [m]
        self.phase = z0()                 # per-bubble meander phase
        self.p_touch = z0()               # P(a neighbour lies within reach) so far
        self.n_merge = 0                  # wall coalescence events (diagnostic)
        self.n_merge_free = 0             # swarm coalescence events (diagnostic)
        self.n_merge_real = 0.0           # represented real-bubble pair events
        self.merge_events = []            # bounded event stream for the renderer
        self._merge_seq = 0
        self.ids = np.zeros(0, dtype=np.int64)
        self._next_id = 1
        self._t = 0.0
        self.alpha_raw_max = 0.0
        self.alpha_overfilled_cells = 0
        self.produced_cum = 0.0
        self.vented_cum = 0.0
        self._pending = [0.0, 0.0]        # gas that found no home this pass

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _vol(r):
        return (4.0 / 3.0) * np.pi * r ** 3

    def _face_area(self):
        return self.g.Ly * self.g.Lz

    def _record_merge(self, a, b, radius, side, attached, radius_a=None, radius_b=None):
        self._merge_seq += 1
        self.merge_events.append({
            "seq": self._merge_seq, "t": float(self._t),
            "a": [float(v) for v in a], "b": [float(v) for v in b],
            "r": float(radius), "side": int(side),
            "ra": float(radius if radius_a is None else radius_a),
            "rb": float(radius if radius_b is None else radius_b),
            "attached": bool(attached),
        })
        if len(self.merge_events) > 128:
            del self.merge_events[:-128]

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

    def _sample_sites(self, side, want):
        """Random continuous (y,z) nucleation spots on the face, restricted to
        the OPEN channel (rejection-sampled against the land mask)."""
        ys = self.rng.uniform(0.04, 0.96, 3 * want) * self.g.Ly
        zs = self.rng.uniform(0.04, 0.96, 3 * want) * self.g.Lz
        if self.face_masks is not None and self.face_masks[side] is not None:
            mask = self.face_masks[side]
            jy = np.clip((ys / self.g.h).astype(int), 0, mask.shape[0] - 1)
            kz = np.clip((zs / self.g.h).astype(int), 0, mask.shape[1] - 1)
            ok = mask[jy, kz]
            ys, zs = ys[ok], zs[ok]
        return ys[:want], zs[:want]

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

    def step(self, ns, j_A_m2, dt, ctx):
        """One bubble-dynamics step: nucleate + grow, coalesce, detach, advect."""
        self._t += dt
        r_dep0 = max(2 * self.R_NUC,
                     self.departure_radius(ctx, max(1e-6, j_A_m2)))
        n_sub = self._wall_substeps(j_A_m2, dt, r_dep0, ctx)
        sdt = dt / n_sub
        for _ in range(n_sub):
            self._nucleate_and_grow(j_A_m2, sdt, ctx, r_dep0)
            self._coalesce()
            self._detach(ctx, j_A_m2)
        self._advect(ns, dt, ctx)
        self._coalesce_free(ns, dt, ctx)

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
            self.pos = np.vstack([self.pos] + new_pos)
            self.r = np.concatenate([self.r] + new_r)
            self.W = np.concatenate([self.W] + new_W)
            self.mult = np.concatenate([self.mult] + new_mult)
            self.side = np.concatenate([self.side] + new_side)
            self.attached = np.concatenate([self.attached] + new_att)
            self.r_dep = np.concatenate([self.r_dep] + new_dep)
            self.phase = np.concatenate([self.phase] + new_ph)
            self.p_touch = np.concatenate([self.p_touch] + new_touch)
            self.ids = np.concatenate([self.ids] + new_id)
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

    # ----------------------------------------------------------- coalescence
    def p_merge(self):
        """Whether the medium is below its measured coalescence threshold.

        This deliberately returns 0 or 1 instead of the former fitted 0.05/0.9
        probabilities. Collision frequency and film-drainage efficiency are
        calculated separately; the electrolyte database supplies only its
        empirical critical coalescence concentration.
        """
        p = self.params
        crit = ELECTROLYTES.get(getattr(self.op, "electrolyte", "KOH"), {}).get(
            "c_coalesce", getattr(p, "c_coalesce_crit", 0.3) if p else 0.3)
        return 0.0 if getattr(self.op, "c_electrolyte", 0.0) > crit else 1.0

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
        not grow with the number of outer time steps.
        """
        free = np.nonzero((~self.attached) & (self.mult > 0.0))[0]
        if len(free) < 2 or self.p_merge() <= 0.0:
            return
        pos = self.pos[free]
        velocity = self.bubble_velocity(ns, ctx)[free]
        cells = np.clip((pos / self.g.h).astype(np.int64),
                        0, [self.g.nx - 1, self.g.ny - 1, self.g.nz - 1])
        buckets = {}
        for local, cell in enumerate(cells):
            key = (int(self.side[free[local]]), int(cell[0]), int(cell[1]), int(cell[2]))
            buckets.setdefault(key, []).append(local)

        rho = float(ctx["rho_l"])
        sigma = float(ctx["sigma"])
        tiny = np.finfo(float).tiny
        changed = False
        for members in buckets.values():
            count = len(members)
            sampled_pairs = count // 2
            if sampled_pairs == 0:
                continue
            shuffled = self.rng.permutation(members)
            # Number of all unordered parcel pairs represented by each sampled
            # pair.  This is exact combinatorics, not an efficiency parameter.
            pair_factor = count * (count - 1) / (2.0 * sampled_pairs)
            for q in range(sampled_pairs):
                local_i, local_j = int(shuffled[2*q]), int(shuffled[2*q + 1])
                i, j = int(free[local_i]), int(free[local_j])
                mi, mj = float(self.mult[i]), float(self.mult[j])
                if mi <= 0.0 or mj <= 0.0:
                    continue
                ri, rj = float(self.r[i]), float(self.r[j])
                relative = float(np.linalg.norm(velocity[local_i] - velocity[local_j]))
                yi, _ = self._wall_dist(self.pos[[i], 0], self.side[[i]])
                yj, _ = self._wall_dist(self.pos[[j], 0], self.side[[j]])
                shear = 0.5 * (float(self.shear_rate(yi)[0])
                               + float(self.shear_rate(yj)[0]))
                approach = relative + shear * (ri + rj)
                if approach <= 0.0:
                    continue

                reduced = 0.5 / (1.0 / max(ri, tiny) + 1.0 / max(rj, tiny))
                t_drain = (np.sqrt(reduced ** 3 * rho / (16.0 * sigma))
                           * np.log(self.H0 / self.HF))
                t_contact = (ri + rj) / approach
                efficiency = float(np.exp(-t_drain / max(t_contact, tiny)))
                kernel = np.pi * (ri + rj) ** 2 * approach * efficiency
                probability = (max(mi, mj) * kernel * float(dt)
                               / self.g.cell_volume * pair_factor)
                gamma = int(np.floor(probability))
                if self.rng.random() < probability - gamma:
                    gamma += 1
                if gamma <= 0:
                    continue

                # The lower-multiplicity cohort receives gamma partner volumes;
                # the higher cohort loses exactly the corresponding real-bubble
                # count.  This is the super-droplet update and conserves gas.
                small, large = (i, j) if mi <= mj else (j, i)
                m_small, m_large = float(self.mult[small]), float(self.mult[large])
                max_gamma = int(np.floor(m_large / m_small))
                if max_gamma <= 0:
                    continue
                gamma = min(gamma, max_gamma)
                r_small, r_large = float(self.r[small]), float(self.r[large])
                r_new = (r_small ** 3 + gamma * r_large ** 3) ** (1.0 / 3.0)
                if r_new > self.r_conf():
                    continue
                before_small = self.pos[small].copy()
                before_large = self.pos[large].copy()
                v_small, v_large = self._vol(r_small), self._vol(r_large)
                self.pos[small] = ((v_small * before_small + gamma * v_large * before_large)
                                   / (v_small + gamma * v_large))
                self.r[small] = r_new
                self.r_dep[small] = max(float(self.r_dep[small]), r_new)
                self.mult[large] = max(0.0, m_large - gamma * m_small)
                merged_real = gamma * m_small
                self.n_merge_free += 1
                self.n_merge_real += merged_real
                self._record_merge(before_small, before_large, r_new,
                                   int(self.side[small]), False,
                                   r_small, r_large)
                changed = True

        if changed:
            self.W = self.mult * self._vol(self.r)
            self._filter(self.mult > np.finfo(float).eps)

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
                               event_radius[q], event_radius[q])

    def _detach(self, ctx, j_A_m2):
        """Release attached bubbles that reached their departure radius."""
        if not self.attached.any():
            return
        go = self.attached & (self.r >= self.r_dep)
        if go.any():
            self.attached[go] = False
        self._thin_free()

    def _thin_free(self):
        """Keep at most FREE_TARGET tracked risers.

        At real departure sizes a working cell frees ~1e5-1e9 bubbles/s, far
        beyond what can be tracked. A random subset survives and absorbs ALL the
        gas of the dropped ones (W and mult scaled by the same factor, so each
        survivor's single-bubble radius is untouched and it simply stands for
        more real bubbles). produced = resident + vented stays machine-exact.

        The subset MUST stay a fresh UNIFORM random draw each step: it is a
        Monte-Carlo sample of the real swarm, so `r[~attached].mean()` reads the
        true number-mean bubble radius. Keeping a "stable" subset instead (to
        stop the render churn) biased the sample toward the older, coalesced
        risers and inflated the mean radius 3-8x -- a physics error. The id
        churn is handled in the RENDERER (nearest-match continuity), not here.
        """
        free = np.nonzero(~self.attached)[0]
        if len(free) <= self.FREE_TARGET:
            return
        sel = self.rng.choice(len(free), size=self.FREE_TARGET, replace=False)
        kept = free[sel]
        w_total = float(self.W[free].sum())
        w_kept = float(self.W[kept].sum())
        if w_kept <= 0.0:
            return
        scale = w_total / w_kept
        self.W[kept] *= scale
        self.mult[kept] *= scale
        live = self.attached.copy()
        live[kept] = True
        self._filter(live)

    def bubble_velocity(self, ns, ctx):
        """Instantaneous representative-bubble velocity [m/s].

        Attached bubbles are stationary. Free bubbles use the solved liquid
        velocity plus Schiller--Naumann terminal slip and the published
        Tomiyama/Antal wall-normal force balance. Artificial sinusoidal wobble
        and random crawl are intentionally absent from the physical trajectory.
        """
        velocity = np.zeros((len(self.r), 3), dtype=np.float64)
        free = ~self.attached
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

    def _advect(self, ns, dt, ctx):
        """Rise the freed bubbles (flow + buoyant slip + lateral meander); vent
        those that reach the outlet. Attached bubbles stay put."""
        if len(self.r) == 0:
            return
        free = ~self.attached
        if free.any():
            p = self.pos[free]
            r_f = self.r[free]
            velocity = self.bubble_velocity(ns, ctx)[free]
            # gentle lateral meander (organic, not a straight column)
            # WALL-NORMAL force balance (Tomiyama lift vs Antal wall lubrication).
            # For these sizes the lift wins at every standoff >= r, so the drift
            # is inward and the bubbles stay pinned to the electrode — the model
            # now SAYS that instead of merely omitting the physics.
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
            # trapped-bubble crawl: a riser pinned under a land (rise blocked)
            # wanders slowly sideways until it finds the turn gap — the
            # contact-line wobble real trapped bubbles show, and it keeps the
            # dead corners from collecting permanent residents
            # the bubble surface cannot enter the electrode: its centre stops at
            # one radius from the catalyst plane (where the wall force diverges)
            y_w, nrm = self._wall_dist(p[:, 0], side_f)
            inside = y_w < r_f
            if inside.any():
                p[inside, 0] += (r_f - y_w)[inside] * nrm[inside]
            self.pos[free] = p
        # reflect off solid walls; vent free bubbles past the outlet
        m = self.r + 0.2 * self.g.h
        self.pos = self.g.clamp_points(self.pos, m)
        free_now = ~self.attached
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
            self.vented_cum += float(self.W[vented].sum())
            keep = ~vented
            self._filter(keep)

    def _filter(self, keep):
        self.pos = self.pos[keep]; self.r = self.r[keep]; self.W = self.W[keep]
        self.mult = self.mult[keep]
        self.side = self.side[keep]; self.attached = self.attached[keep]
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
        gas = self.g.field()
        area = self.g.field()
        momentum = np.zeros((3,) + self.g.shape, dtype=np.float64)
        if len(self.r):
            inv_cell = 1.0 / self.g.cell_volume
            void_weight = self.W * inv_cell
            area_weight = self.mult * (4.0 * np.pi * self.r * self.r) * inv_cell
            velocity = self.bubble_velocity(ns, ctx)
            self.g.deposit27(gas, self.pos, void_weight)
            self.g.deposit27(area, self.pos, area_weight)
            for axis in range(3):
                self.g.deposit27(momentum[axis], self.pos,
                                 void_weight * velocity[:, axis])
        gas_velocity = np.zeros_like(momentum)
        occupied = gas > np.finfo(float).tiny
        for axis in range(3):
            gas_velocity[axis, occupied] = momentum[axis, occupied] / gas[occupied]
        diameter = np.zeros_like(gas)
        surfaced = area > np.finfo(float).tiny
        diameter[surfaced] = 6.0 * gas[surfaced] / area[surfaced]
        self.alpha_raw_max = float(gas.max()) if gas.size else 0.0
        self.alpha_overfilled_cells = int(np.count_nonzero(gas > 1.0))
        # A phase fraction cannot exceed one. The epsilon-sized gap only keeps
        # alpha_l positive in the momentum equation; it is not a packing fit.
        gas = np.minimum(gas, 1.0 - np.sqrt(np.finfo(float).eps))
        return gas, gas_velocity, diameter

    def deposit_void(self):
        """Scatter bubble gas volume -> grid void fraction (3x3x3 smear)."""
        gas = self.g.field()
        if len(self.r):
            self.g.deposit27(gas, self.pos, self.W / self.g.cell_volume)
        return np.minimum(gas, 1.0 - np.sqrt(np.finfo(float).eps))

    # ------------------------------------------------------------ diagnostics
    def resident_gas(self):
        return float(self.W.sum()) if len(self.W) else 0.0

    def holdup(self):
        total_vol = self.g.n * self.g.cell_volume
        return self.resident_gas() / total_vol if total_vol else 0.0

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

    def near_wall_mask(self, side, slab_cells=2):
        """Bubbles within `slab_cells` of this side's ELECTRODE surface (the
        catalyst plane with elec_planes, else the outer wall)."""
        slab = slab_cells * self.g.h
        x = self.pos[:, 0]
        if self.elec_planes is not None:
            xc, xa = self.elec_planes
            return (np.abs(x - xc) < slab) if side == 0 else (np.abs(x - xa) < slab)
        return (x < slab) if side == 0 else (x > self.g.Lx - slab)

    def void_near_wall(self, side, slab_cells=2):
        """Gas volume fraction in the near-electrode layer (feeds the kernel
        Bruggeman void resistance, like Surface.void_fraction)."""
        if len(self.r) == 0:
            return 0.0
        m = self.near_wall_mask(side, slab_cells)
        layer_vol = self._face_area() * slab_cells * self.g.h
        return float(min(0.6, self.W[m].sum() / layer_vol))

    def size_stats(self):
        """(mean, std) bubble radius [m] — std>0 confirms a size distribution."""
        if len(self.r) == 0:
            return 0.0, 0.0
        return float(self.r.mean()), float(self.r.std())

    def gas_closure_error(self):
        if self.produced_cum <= 0:
            return 0.0
        return abs(self.produced_cum - (self.resident_gas() + self.vented_cum)) \
            / self.produced_cum

    def snapshot_flat(self):
        """Flat [x, y, z, r, side, attached, id]*N in metres, grid frame.

        The stable per-bubble id lets the browser MATCH bubbles across
        snapshots and interpolate their motion at 60 fps (same fix as the 2-D
        app's flow2d ids — without it the poll cadence shows as stutter)."""
        if len(self.r) == 0:
            return []
        out = np.empty((len(self.r), 7))
        out[:, 0:3] = self.pos
        out[:, 3] = self.r
        out[:, 4] = self.side
        out[:, 5] = self.attached.astype(float)
        out[:, 6] = self.ids
        return out.ravel().tolist()
