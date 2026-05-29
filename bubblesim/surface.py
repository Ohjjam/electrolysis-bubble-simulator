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
from .constants import G


class Surface:
    def __init__(self, op, params, rng):
        self.op = op
        self.p = params
        self.rng = rng
        self.bubbles: list[Bubble] = []
        self.A_patch = params.patch_w * params.patch_h

    # ------------------------------------------------------------------ geometry
    def footprint_radius(self, b: Bubble) -> float:
        """Contact-line (footprint) radius = r * sin(contact angle).

        Only the contact patch blocks active sites; the surrounding wetted
        electrode stays active. For a very non-wetting surface (angle -> 180 deg)
        the bubble beads up and the footprint shrinks again.
        """
        return b.r * abs(math.sin(math.radians(self.op.contact_angle)))

    def coverage(self) -> float:
        """Fraction of electrode area shadowed by attached-bubble footprints."""
        s2 = 0.0
        for b in self.bubbles:
            if b.attached:
                rf = self.footprint_radius(b)
                s2 += math.pi * rf * rf
        return min(0.95, s2 / self.A_patch)

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

    def nucleate(self, j, dt):
        """Seed new bubbles on free sites at a rate that scales with current density."""
        n_att = sum(1 for b in self.bubbles if b.attached)
        free = max(0, self.site_count() - n_att)
        if free <= 0 or j <= 0.0:
            return
        rate = self.p.k_nuc * (j / self.p.j_ref) * free       # [1/s]
        expected = rate * dt
        n_new = int(expected)
        if self.rng.random() < (expected - n_new):
            n_new += 1
        for _ in range(n_new):
            x = self.rng.random() * self.p.patch_w
            spread = self.p.detach_spread
            factor = 1.0 + self.rng.uniform(-spread, spread)
            self.bubbles.append(Bubble(x=x, y=0.0, r=self.p.r_nuc, attached=True,
                                       detach_factor=factor))

    def coalesce(self):
        """Merge overlapping attached bubbles unless the electrolyte inhibits it.

        Above a critical concentration, dissolved ions suppress bubble
        coalescence (the well-known salting-out / coalescence-inhibition effect).
        """
        if self.op.c_electrolyte > self.p.c_coalesce_crit:
            p_merge = self.p.p_merge_inhibited
        else:
            p_merge = self.p.p_merge_free
        att = [b for b in self.bubbles if b.attached and not b.dead]
        for i in range(len(att)):
            a = att[i]
            if a.dead:
                continue
            for k in range(i + 1, len(att)):
                c = att[k]
                if c.dead:
                    continue
                rfa = self.footprint_radius(a)
                rfc = self.footprint_radius(c)
                if math.hypot(a.x - c.x, a.y - c.y) < 0.8 * (rfa + rfc):
                    if self.rng.random() < p_merge:
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

    def advect(self, dt, props):
        """Rise detached bubbles (buoyancy) and drift them with the flow; cull strays."""
        mu = props["mu"]
        d_rho = props["d_rho"]
        kept = []
        for b in self.bubbles:
            if not b.attached:
                v_rise = min(2.0 * d_rho * G * b.r * b.r / (9.0 * mu), 0.3)  # Stokes, capped
                b.y += v_rise * dt
                b.x += self.op.u_flow * dt
                if b.y < 1.5 * self.p.patch_h and b.x < 1.5 * self.p.patch_w:
                    kept.append(b)
            else:
                kept.append(b)
        self.bubbles = kept
