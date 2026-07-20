"""The electrode surface: a population of bubbles that nucleate, grow,
coalesce, detach and rise on a representative patch.

All quantities are intensive on the patch (coverage, void fraction), so the
patch stands in for the whole electrode and the electrochemistry works in
current *density*. The patch holds a tractable, statistically representative
number of bubbles (tens to low hundreds).
"""
import math

from .bubble import Bubble
from . import forces
from ...constants import G
from ...properties import ELECTROLYTES
from ..transport import supersaturation as _supersaturation


class Surface:
    def __init__(self, op, params, rng):
        self.op = op
        self.p = params
        self.rng = rng
        self.bubbles: list[Bubble] = []
        self.A_patch = params.patch_w * params.patch_h
        self._next_id = 0          # stable per-bubble ids for clients (no physics role)
        self.c_dissolved = 0.0     # near-electrode dissolved-gas concentration [mol/m^3]
        self._pool_seeded = False  # gas-saturated initial state set once (no phantom re-seed)

    # ------------------------------------------------------------------ geometry
    def footprint_radius(self, b: Bubble) -> float:
        """Contact-line (footprint) radius = r * sin(contact angle).

        Only the contact patch blocks active sites; the surrounding wetted
        electrode stays active. For a very non-wetting surface (angle -> 180 deg)
        the bubble beads up and the footprint shrinks again.
        """
        return b.r * abs(math.sin(math.radians(self.op.contact_angle)))

    def coverage(self) -> float:
        """Fraction of electrode area shadowed by attached-bubble footprints.

        Poisson union estimate theta = 1 - exp(-sum(pi rf^2)/A): it recovers the
        low-density sum (1-e^-x ~ x) but correctly SATURATES when footprints
        overlap, instead of the old linear sum/A that double-counted overlaps and
        could exceed reality (matches the Vogt / face2d 1-exp closure)."""
        s2 = 0.0
        for b in self.bubbles:
            if b.attached:
                rf = self.footprint_radius(b)
                s2 += math.pi * rf * rf
        return min(0.95, 1.0 - math.exp(-s2 / self.A_patch))

    def void_fraction(self) -> float:
        """Gas volume fraction within the near-electrode layer (feeds Bruggeman)."""
        vol = 0.0
        layer_vol = self.A_patch * self.p.near_layer
        for b in self.bubbles:
            if b.attached or b.y < self.p.near_layer:
                vol += b.volume()
        return min(0.6, vol / layer_vol)

    def site_count(self) -> int:
        """Active nucleation sites. Hydrophobic surfaces trap more gas -> more sites."""
        f = 0.5 + self.op.contact_angle / 90.0    # ~0.5 (very wetting) .. ~1.5 (90 deg)
        return int(self.p.site_density * f * self.A_patch)

    # ------------------------------------------------------------------ dynamics
    def grow(self, Q_to_bubbles, dt):
        """Distribute the captured gas volume rate among attached bubbles ~ r^2."""
        att = [b for b in self.bubbles if b.attached]
        if not att or Q_to_bubbles <= 0.0:
            return
        weights = [b.r * b.r for b in att]
        W = sum(weights)
        if W <= 0.0:
            return
        for b, w in zip(att, weights):
            v = b.volume() + Q_to_bubbles * (w / W) * dt
            b.r = (3.0 * v / (4.0 * math.pi)) ** (1.0 / 3.0)

    def grow_from_supersaturation(self, c_sat, D, M, rho_g, dt):
        """Diffusion-limited (Epstein-Plesset) growth of attached bubbles from the
        local dissolved-gas supersaturation; RETURNS the moles captured so the
        caller can debit the dissolved pool (closing the gas mass balance).

            dr/dt = (D / r) (c_dis - c_sat) (M / rho_g)   (Epstein & Plesset 1950)

        Growth is thus driven BY the supersaturation it consumes -- the physical
        coupling the old fixed f_to_bubble split lacked (it double-counted gas)."""
        if self.c_dissolved <= c_sat or c_sat <= 0.0:
            return 0.0
        excess = self.c_dissolved - c_sat
        dn = 0.0
        for b in self.bubbles:
            if b.attached and b.r > 0.0:
                dr = (D / b.r) * excess * (M / rho_g) * dt
                if dr > 0.0:
                    v0 = b.volume()
                    b.r += dr
                    dn += (b.volume() - v0) * rho_g / M     # moles of gas captured
        return dn

    def update_supersaturation(self, gas_in_rate, c_sat, k_m, dt, uptake_mol=0.0):
        """Evolve the near-electrode dissolved-gas pool; return S = c_dissolved/c_sat.

            d c_dis/dt = [ gas_in_rate - k_m (c_dis - c_sat) A_patch ] / V_layer
                         - uptake_mol / V_layer

        `gas_in_rate` [mol/s] is the evolved gas entering solution (now the FULL
        Faradaic rate); `k_m` transports the excess to the bulk; `uptake_mol` is
        the gas captured this step by bubble growth (grow_from_supersaturation),
        subtracted so a gas atom is counted once. Pressure/temperature enter via
        c_sat (Henry), so they modulate nucleation in supersaturation mode.
        """
        if c_sat <= 0.0:
            return 0.0
        if not self._pool_seeded:           # seed the gas-saturated start ONCE; never
            self.c_dissolved = c_sat        # re-inject c_sat after a legitimate drain
            self._pool_seeded = True        # (that would break the gas mass balance)
        V_layer = self.A_patch * self.p.near_layer
        loss = k_m * max(0.0, self.c_dissolved - c_sat) * self.A_patch
        self.c_dissolved = max(0.0, self.c_dissolved
                               + (gas_in_rate - loss) / V_layer * dt - uptake_mol / V_layer)
        return _supersaturation(self.c_dissolved, c_sat)   # S = c_dissolved / c_sat

    def nucleate(self, j, dt, supersaturation=None):
        """Seed new bubbles on free sites.

        Empirical mode (`supersaturation` None): rate ~ current density (original,
        byte-identical). Supersaturation mode: classical-nucleation-theory-lite
            rate = k_nuc_ss * exp(-B_nuc / ln(S)^2) * free      (only for S > 1).
        """
        n_att = sum(1 for b in self.bubbles if b.attached)
        free = max(0, self.site_count() - n_att)
        if free <= 0:
            return
        if supersaturation is None:
            if j <= 0.0:
                return
            rate = self.p.k_nuc * (j / self.p.j_ref) * free       # [1/s]
        else:
            if supersaturation <= 1.0:
                return
            rate = (self.p.k_nuc_ss
                    * math.exp(-self.p.B_nuc / (math.log(supersaturation) ** 2)) * free)
        expected = rate * dt
        n_new = int(expected)
        if self.rng.random() < (expected - n_new):
            n_new += 1
        for _ in range(n_new):
            x = self.rng.random() * self.p.patch_w
            spread = self.p.detach_spread
            factor = 1.0 + self.rng.uniform(-spread, spread)
            self._next_id += 1
            self.bubbles.append(Bubble(x=x, y=0.0, r=self.p.r_nuc, attached=True,
                                       detach_factor=factor, id=self._next_id))

    def coalesce(self):
        """Merge overlapping attached bubbles unless the electrolyte inhibits it.

        Above a critical concentration, dissolved ions suppress bubble
        coalescence (the well-known salting-out / coalescence-inhibition effect).
        """
        # coalesce-inhibition threshold is electrolyte-specific (salting-out differs
        # by ion); fall back to the Params default. KOH default == 0.3 == prior value.
        crit = ELECTROLYTES.get(getattr(self.op, "electrolyte", "KOH"),
                                {}).get("c_coalesce", self.p.c_coalesce_crit)
        if self.op.c_electrolyte > crit:
            return
        att = [b for b in self.bubbles if b.attached and not b.dead]
        sa = abs(math.sin(math.radians(self.op.contact_angle)))   # constant; hoist out of O(n^2)
        for i in range(len(att)):
            a = att[i]
            if a.dead:
                continue
            for k in range(i + 1, len(att)):
                c = att[k]
                if c.dead:
                    continue
                # Sum of the two projected contact-footprint radii.  The old
                # 0.8 overlap multiplier was an undocumented fitted constant.
                reach = a.r * sa + c.r * sa
                # cheap reject before the sqrt: |dx| or |dy| beyond reach => no overlap
                # (bit-identical: brute force's hypot test would also fail, no rng drawn)
                dx, dy = a.x - c.x, a.y - c.y
                if dx >= reach or dx <= -reach or dy >= reach or dy <= -reach:
                    continue
                if math.hypot(dx, dy) < reach:
                    v = a.volume() + c.volume()
                    a.r = (3.0 * v / (4.0 * math.pi)) ** (1.0 / 3.0)
                    a.x = 0.5 * (a.x + c.x)
                    c.dead = True
        if any(b.dead for b in self.bubbles):
            self.bubbles = [b for b in self.bubbles if not b.dead]

    def detach(self, props, j):
        """Release every attached bubble that has reached the departure radius."""
        r_d = forces.departure_radius(self.op, props, j)
        for b in self.bubbles:
            if b.attached and b.r >= r_d * b.detach_factor:
                b.attached = False
        return r_d

    @staticmethod
    def _terminal_velocity(r, d_rho, mu, rho_l):
        """Bubble terminal rise velocity [m/s] from a Re-aware drag balance.

        (4/3) pi r^3 d_rho g = 1/2 Cd rho_l U^2 pi r^2  ->  U = sqrt(8 d_rho g r /
        (3 Cd rho_l)), with the Schiller-Naumann drag Cd = 24/Re (1 + 0.15 Re^0.687)
        (rigid/contaminated interface, the usual case in electrolyte). Reduces to
        Stokes at Re<<1 and self-limits at Re~1-50 (sub-mm bubbles), so no
        arbitrary 0.3 m/s cap is needed. A few damped fixed-point iterations."""
        U = (2.0 / 9.0) * d_rho * G * r * r / mu          # Stokes start
        for _ in range(50):
            Re = max(1e-9, 2.0 * r * U * rho_l / mu)
            Cd = (24.0 / Re) * (1.0 + 0.15 * Re ** 0.687)
            U_new = math.sqrt(max(0.0, (8.0 / 3.0) * d_rho * G * r / (Cd * rho_l)))
            U_next = 0.5 * (U + U_new)
            if abs(U_next - U) <= 1e-4 * U_next:         # converge (12-iter was ~3-5% high)
                return U_next
            U = U_next
        return U

    def advect(self, dt, props):
        """Rise detached bubbles (buoyancy) and drift them with the flow; cull strays."""
        mu = props["mu"]
        d_rho = props["d_rho"]
        rho_l = props["rho_l"]
        kept = []
        for b in self.bubbles:
            if not b.attached:
                v_rise = self._terminal_velocity(b.r, d_rho, mu, rho_l)
                b.y += v_rise * dt
                b.x += self.op.u_flow * dt
                if b.y < 1.5 * self.p.patch_h and b.x < 1.5 * self.p.patch_w:
                    kept.append(b)
            else:
                kept.append(b)
        self.bubbles = kept
