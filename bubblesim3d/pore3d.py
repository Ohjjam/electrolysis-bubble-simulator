"""PoreSim3D — the pore-scale offline engine (Track B).

Ties the pieces together on a fixed voxel scaffold:
  current3d      -> surface-only reaction mask + gas-blocking redistribution
  gastransport3d -> Faradaic gas rate + nucleation weighting (kernel physics)
  poregrowth     -> voxel-filling bubble growth + venting (gas conservation)

Each advance() = one snapshot frame: redistribute imposed current over the
still-open external surface, grow gas from that surface, and vent escaping gas.

Reduced-model, honest scope (documented per module): uniform imposed current on
the unblocked external face, and voxel-filling (not VOF) bubbles. Internal-pore
reaction penetration is explicitly excluded for this cell architecture.
"""
import numpy as np

from .current3d import SurfaceCurrent3D
from . import gastransport3d as gt
from .poregrowth import PoreGrowth
from bubblesim import Params
from bubblesim.config import Operating
from bubblesim.kernel import morphology as morph


class PoreSim3D:
    def __init__(self, cfg, solid, meta, params=None):
        self.cfg = cfg
        self.solid = solid
        self.meta = meta
        self.params = params or Params()
        self.n = solid.shape[0]
        self.h = meta["h_um"] * 1e-6
        self.v_voxel = self.h ** 3
        self.electrode = cfg.electrode
        self.op = Operating(mode="CP", j_set=cfg.j_A_cm2 * 1e4,
                            electrode=cfg.electrode, model="two_electrode",
                            substrate=cfg.substrate, nanostructure=cfg.nanostructure,
                            T=333.15, high_fidelity=True)
        self.eff = morph.effective_electrode(cfg.substrate, cfg.nanostructure)
        # geometric footprint of the representative volume (one face) [m^2]
        self.footprint = (self.n * self.h) ** 2
        self.total_current = cfg.j_A_cm2 * 1e4 * self.footprint      # [A]
        self.cur = SurfaceCurrent3D(solid, access_axis=1)
        self.growth = PoreGrowth(solid, escape_axis=1,
                                 escape_factor=self.eff["escape_factor"],
                                 reactive_surface=self.cur.surf)
        self.dt = cfg.dt_s
        self.frame = 0
        self._surf_current = self.cur.surface_current(self.total_current)
        # gas volume rate for the imposed current (Faraday + ideal gas) [m^3/s]
        from bubblesim.kernel.context import build_context
        ctx = build_context(self.op, self.params)
        self.gas_rate = gt.total_gas_rate(
            self.total_current, self.electrode, self.op.T, self.op.P,
            eta_F=self.params.eta_faraday, wet=True,
            water_activity=ctx.get("water_activity", 1.0))

    # ----------------------------------------------------------------- step
    def advance(self):
        """Advance one frame: re-solve current on open pore, grow + vent gas."""
        blocked = self.growth.gas
        self._surf_current = self.cur.surface_current(self.total_current, blocked=blocked)
        nucw = gt.nucleation_weight(self._surf_current, self.eff["nuc_site_mult"])
        delivered = float(self._surf_current.sum()) / max(self.total_current, 1e-30)
        dV = self.gas_rate * delivered * self.dt
        self.growth.grow(dV, self.v_voxel, nucw)
        self.frame += 1

    # ------------------------------------------------------------ outputs
    def gas_mask(self):
        return self.growth.gas

    def surface_current(self):
        """Per-surface-voxel current density [A/cm^2] (for colouring)."""
        return self._surf_current / (self.h * self.h) / 1.0e4

    def scalars(self):
        g = self.growth
        return {
            "frame": self.frame,
            "t": round(self.frame * self.dt, 5),
            "coverage": round(g.coverage(), 4),
            "holdup": round(g.holdup(), 5),
            "vented": round(g.vented_cum, 12),
            "produced": round(g.produced_cum, 12),
            "resident": round(float(g.gas.sum()) * self.v_voxel, 12),
            "reaction_mode": "external_surface_only",
            "active_surface": round(self.cur.active_fraction(g.gas), 4),
            "current_limited": bool(self.cur.active_fraction(g.gas) <= 0.0),
            "j_A_cm2": self.cfg.j_A_cm2,
        }

    def gas_closure_error(self):
        """|produced - (resident + vented)| / produced — should be ~0."""
        g = self.growth
        resident = float(g.gas.sum()) * self.v_voxel
        if g.produced_cum <= 0:
            return 0.0
        return abs(g.produced_cum - (resident + g.vented_cum)) / g.produced_cum
