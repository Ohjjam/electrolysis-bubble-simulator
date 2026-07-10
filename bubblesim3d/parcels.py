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


def terminal_velocity(r, d_rho, mu, rho_l, iters=20):
    """Vectorized bubble rise speed [m/s] (Schiller-Naumann drag balance).

    Identical scheme to population.Surface._terminal_velocity over an array of
    radii: Stokes seed, then damped fixed-point on Cd = 24/Re (1 + 0.15 Re^0.687).
    20 sweeps land within 3e-4 of the kernel over 1 um - 3 mm (40 gave 1e-4 for
    twice the cost, and this is called twice per bubble step).
    """
    r = np.asarray(r, dtype=np.float64)
    if r.size == 0:
        return r
    U = (2.0 / 9.0) * d_rho * G * r * r / mu
    for _ in range(iters):
        Re = np.maximum(1e-9, 2.0 * r * U * rho_l / mu)
        Cd = (24.0 / Re) * (1.0 + 0.15 * Re ** 0.687)
        U_new = np.sqrt(np.maximum(0.0, (8.0 / 3.0) * d_rho * G * r / (Cd * rho_l)))
        U = 0.5 * (U + U_new)
    return U


class Parcels:
    """Bubble population on the two electrode faces of a Grid3D.

    A tracked bubble is a real (representative) bubble with a full attached->
    detached lifecycle — NOT a fixed-volume computational parcel.
    """

    R_NUC = 2.0e-6          # nucleation seed radius [m] (~2 um). Must stay well
                            # BELOW the departure radius at every flow rate, or
                            # the 2*R_NUC detachment floor binds and every bubble
                            # leaves at the seed size (r_dep -> ~16 um at 1 m/s).
    DETACH_SPREAD = 0.35    # +/- per-bubble spread on the departure radius
    N_SITES = 140           # TRACKED attached slots per face (each represents
                            # `mult` real nucleation sites — see module docstring)
    FREE_TARGET = 1400      # tracked free risers to keep (adaptively thinned)
    WOBBLE = 0.35           # lateral meander amplitude of rising bubbles [-]

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
    EPS_MAX = 0.62            # random close packing: the near-wall layer cannot
                              # hold more gas than this, whatever the smearing says
    LAYER_CAP = 40.0          # max concentration factor h/(2 y_w) (see _n_local)

    CONF_FRAC = 0.45        # a bubble cannot exceed ~90% of the channel gap in
                            # diameter: beyond that it bridges the channel (slug
                            # flow) rather than growing as a free sphere

    def __init__(self, grid: Grid3D, op, rng, cap=6000, gas_factor_anode=0.5,
                 face_masks=None, elec_planes=None, params=None,
                 channel_depth=None, vent_face="top", vent_line=None):
        self.g = grid
        self.op = op
        self.params = params           # kernel Params (site density for mult)
        self.rng = rng
        self.cap = int(cap)
        self.gas_factor_anode = float(gas_factor_anode)
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
        self.ids = np.zeros(0, dtype=np.int64)
        self._next_id = 1
        self._t = 0.0
        self.produced_cum = 0.0
        self.vented_cum = 0.0
        self._pending = [0.0, 0.0]        # gas that found no home this pass

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _vol(r):
        return (4.0 / 3.0) * np.pi * r ** 3

    def _face_area(self):
        return self.g.Ly * self.g.Lz

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
    def _wall_substeps(self, j_A_m2, dt, r_dep):
        """Substeps needed to resolve the growth-to-departure cycle.

        At a real site density a bubble goes seed -> departure in ~1 ms, which
        is SHORTER than the flow time step (3 ms). Growing the whole step's gas
        in one pass inflates every bubble far past its departure radius before
        `_detach` can look at it, so the reported bubble size came out ~3x the
        physics. Cap each pass at SUB_FRAC of a full cycle's gas instead. Only
        the (tiny) wall arrays are touched per substep — the flow solve is not.
        """
        A = self._face_area()
        q = sum(faradaic_gas_rate(max(0.0, j_A_m2), el, self.op.T, self.op.P, A) * gf
                for el, gf in (("HER", 1.0), ("OER", self.gas_factor_anode)))
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
        n_sub = self._wall_substeps(j_A_m2, dt, r_dep0)
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
        for side, (electrode, gf) in enumerate([("HER", 1.0),
                                                ("OER", self.gas_factor_anode)]):
            Qdot = faradaic_gas_rate(max(0.0, j_A_m2), electrode, self.op.T,
                                     self.op.P, self._face_area()) * gf
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
        """Merge probability on contact, from the electrolyte (kernel rule).

        Above the salting-out threshold (KOH: 0.3 M) dissolved ions suppress
        film drainage, so touching bubbles bounce apart instead of merging.
        """
        p = self.params
        crit = ELECTROLYTES.get(getattr(self.op, "electrolyte", "KOH"), {}).get(
            "c_coalesce", getattr(p, "c_coalesce_crit", 0.3) if p else 0.3)
        inhib = getattr(p, "p_merge_inhibited", 0.05) if p else 0.05
        free = getattr(p, "p_merge_free", 0.9) if p else 0.9
        return inhib if getattr(self.op, "c_electrolyte", 0.0) > crit else free

    def _p_touch(self, r, mult):
        """P(at least one real neighbour within reach) for a Poisson site field.

        The real neighbours of a tracked bubble are its own `mult` siblings, at
        number density n = mult * N_SITES / A_face. For a 2-D Poisson field the
        chance one lies inside radius d is 1 - exp(-pi n d^2), with the contact
        reach d = 0.8 * 2 r sin(beta) (the kernel's overlap test).
        """
        sinb = abs(np.sin(np.radians(self.op.contact_angle)))
        n = mult * self.N_SITES / self._face_area()
        d = 1.6 * r * sinb
        return 1.0 - np.exp(-np.pi * n * d * d)

    def _n_local(self, ns, pos, r, y_w):
        """Real bubbles per m^3 around each free bubble.

        CLOSURE (stated because it is a closure, not a derivation): the void
        fraction `ns.gas` is smeared over 2 mm cells, but the free bubbles live
        in a ~2*y_w thick sheet against the electrode. Concentrating the cell
        average into that sheet gives the density the bubbles actually see:
            eps_layer = min(eps_cell * h / (2 y_w), EPS_MAX)
            n         = eps_layer / V(r)
        Without the concentration factor the collision rate is ~25x too low; with
        no cap it exceeds close packing. Both bounds are documented, not tuned.
        """
        g = self.g
        ci = np.clip((pos / g.h).astype(np.int64), 0, [g.nx - 1, g.ny - 1, g.nz - 1])
        eps_cell = ns.gas[ci[:, 0], ci[:, 1], ci[:, 2]]
        conc = np.minimum(self.LAYER_CAP, g.h / np.maximum(2.0 * y_w, 1e-9))
        eps_layer = np.minimum(self.EPS_MAX, eps_cell * conc)
        return eps_layer / np.maximum(self._vol(r), 1e-30)

    def _coalesce_free(self, ns, dt, ctx):
        """Coalescence inside the rising swarm (Prince & Blanch collision kernel).

        Collision frequency per bubble  w = n * S * dv
            S  = (pi/4)(d_i + d_j)^2 = 4 pi r^2   (equal-size neighbours)
            dv = shear across the standoff spread + the slip difference the
                 departure-size spread produces
        Coalescence efficiency (film drainage)
            lambda = exp(-t_drain / t_contact)
            t_drain   = sqrt(r_ij^3 rho / (16 sigma)) ln(h0/hf),  r_ij = r/4
            t_contact ~ 1/gamma_dot   (the laminar analogue of Prince-Blanch's
                        turbulent r^(2/3)/eps^(1/3); this cell is laminar,
                        Re ~ 4e2, so no dissipation rate is available)
        and the electrolyte's salting-out inhibition multiplies it. The draw is
        against 1 - exp(-rate*dt), so the merge count does not depend on dt.

        A merge fuses two real bubbles: mult halves, r grows 2^(1/3), W is
        untouched. Bridging pairs (r beyond the channel gap) cannot fuse.
        """
        free = np.nonzero((~self.attached) & (self.mult >= 2.0))[0]
        if len(free) == 0 or self.op.u_flow <= 0:
            return
        r = self.r[free]
        pos = self.pos[free]
        y_w, _ = self._wall_dist(pos[:, 0], self.side[free])
        y_w = np.maximum(y_w, r)
        v_s = terminal_velocity(r, ctx["d_rho"], ctx["mu"], ctx["rho_l"])
        gdot = self.shear_rate(y_w)

        n = self._n_local(ns, pos, r, y_w)
        dv = gdot * self.DETACH_SPREAD * y_w + 2.0 * self.DETACH_SPREAD * v_s
        S = 4.0 * np.pi * r * r
        omega = n * S * dv                                   # collisions / s

        rho, sig = float(ctx["rho_l"]), float(ctx.get("sigma", 0.072))
        r_ij = 0.25 * r
        t_drain = np.sqrt(r_ij ** 3 * rho / (16.0 * sig)) * np.log(self.H0 / self.HF)
        t_contact = 1.0 / np.maximum(gdot, v_s / np.maximum(r, 1e-12))
        lam = np.exp(-t_drain / np.maximum(t_contact, 1e-12))

        rate = omega * lam * self.p_merge()
        hit = self.rng.random(len(free)) < -np.expm1(-rate * dt)   # 1-exp(-rate dt)
        grown = r * 2.0 ** (1.0 / 3.0)
        hit &= grown <= self.r_conf()                        # a bridging pair cannot fuse
        if not hit.any():
            return
        idx = free[hit]
        self.r[idx] = self.r[idx] * 2.0 ** (1.0 / 3.0)
        self.mult[idx] = self.mult[idx] * 0.5                # W = mult*V(r) preserved
        self.n_merge_free += int(hit.sum())
        # a merged bubble is 26% bigger: its surface would now poke INTO the
        # electrode it was skimming, so nudge the centre back out to one radius
        d, nrm = self._wall_dist(self.pos[idx, 0], self.side[idx])
        short = d < self.r[idx]
        if short.any():
            sel = idx[short]
            self.pos[sel, 0] += (self.r[idx] - d)[short] * nrm[short]

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

    def _advect(self, ns, dt, ctx):
        """Rise the freed bubbles (flow + buoyant slip + lateral meander); vent
        those that reach the outlet. Attached bubbles stay put."""
        if len(self.r) == 0:
            return
        free = ~self.attached
        if free.any():
            p = self.pos[free]
            r_f = self.r[free]
            uf, vf, wf = ns.sample_velocity(p)
            vs = terminal_velocity(r_f, ctx["d_rho"], ctx["mu"], ctx["rho_l"])
            up = ns.up
            # gentle lateral meander (organic, not a straight column)
            mw = self.WOBBLE * vs * np.sin(6.0 * p[:, 1] / self.g.Ly * np.pi
                                           + self.phase[free])
            # WALL-NORMAL force balance (Tomiyama lift vs Antal wall lubrication).
            # For these sizes the lift wins at every standoff >= r, so the drift
            # is inward and the bubbles stay pinned to the electrode — the model
            # now SAYS that instead of merely omitting the physics.
            side_f = self.side[free]
            y_w, nrm = self._wall_dist(p[:, 0], side_f)
            vn = self.wall_normal_velocity(r_f, vs, y_w, ctx)
            d = np.stack([(uf + vs * up[0] + vn * nrm) * dt,
                          (vf + vs * up[1]) * dt,
                          (wf + vs * up[2] + mw) * dt], axis=1)
            # axis-wise obstacle collision, SUBSTEPPED so a fast bubble can
            # never tunnel through a land in one step (the displacement is cut
            # into <= half-cell moves; an endpoint-only check let jet-riding
            # bubbles jump whole rib bands). Blocked components are cancelled,
            # the others survive -> bubbles SLIDE along rib walls to the gaps.
            max_disp = float(np.abs(d).max()) if len(d) else 0.0
            n_sub = max(1, int(np.ceil(max_disp / (0.5 * self.g.h))))
            ds = d / n_sub
            rise_blocked = np.zeros(len(p), dtype=bool)
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
                    if ax == 1:
                        rise_blocked |= blocked
            # trapped-bubble crawl: a riser pinned under a land (rise blocked)
            # wanders slowly sideways until it finds the turn gap — the
            # contact-line wobble real trapped bubbles show, and it keeps the
            # dead corners from collecting permanent residents
            if rise_blocked.any():
                cand = p.copy()
                crawl = 0.4 * vs * dt * self.rng.choice([-1.0, 1.0], size=len(p))
                cand[:, 2] += crawl
                ok = rise_blocked & (~self._in_solid(ns, cand))
                p[ok, 2] = cand[ok, 2]
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
    def deposit_void(self):
        """Scatter bubble gas volume -> grid void fraction (3x3x3 smear)."""
        gas = self.g.field()
        if len(self.r):
            self.g.deposit27(gas, self.pos, self.W / self.g.cell_volume)
        return np.minimum(gas, 0.8)

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
