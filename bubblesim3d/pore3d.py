"""PoreSim3D — the pore-scale offline engine (Track B).

Ties the pieces together on a fixed voxel scaffold:
  current3d      -> where the reaction runs (penetration + gas redistribution)
  gastransport3d -> Faradaic gas rate + nucleation weighting (kernel physics)
  poregrowth     -> voxel-filling bubble growth + venting (gas conservation)

Each advance() = one snapshot frame: re-solve the current distribution on the
still-open pore, evolve the dissolved-gas-driven bubble growth, vent escaping
gas. The runner writes the gas mask + surface current + scalars per frame.

Reduced-model, honest scope (documented per module): linearized single-phase
current, voxel-filling (not VOF) bubbles. What it captures faithfully: reaction
penetration into a real 3-D scaffold, gas->current blocking feedback, and gas
mass conservation (produced = resident + vented).
"""
import numpy as np

from .current3d import Current3D, penetration_cells
from . import gastransport3d as gt
from .poregrowth import PoreGrowth
from bubblesim import Params
from bubblesim.config import Operating
from bubblesim.kernel.context import build_context
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
                            T=333.15)
        self.eff = morph.effective_electrode(cfg.substrate, cfg.nanostructure)
        # geometric footprint of the representative volume (one face) [m^2]
        self.footprint = (self.n * self.h) ** 2
        self.total_current = cfg.j_A_cm2 * 1e4 * self.footprint      # [A]
        # reaction penetration -> current distribution solver. The raw depth can
        # be sub-voxel for very high-area electrodes (extreme surface-skin
        # reaction) or exceed the sample (full utilization); clamp to [n/8, 4n]
        # cells so the solved distribution shows a resolvable penetration
        # gradient across the representative volume (documented modeling choice).
        lam = penetration_cells(self.op, self.params, self.eff, self.h)
        self.lam_cells = float(np.clip(lam, self.n / 8.0, 4.0 * self.n))
        self.cur = Current3D(solid, self.lam_cells, access_axis=1)
        self.cur.solve(iters=150)
        self.growth = PoreGrowth(solid, escape_axis=1,
                                 escape_factor=self.eff["escape_factor"])
        self.dt = cfg.dt_s
        self.frame = 0
        self._surf_current = self.cur.surface_current(self.total_current)
        # gas volume rate for the imposed current (Faraday + ideal gas) [m^3/s]
        self.gas_rate = gt.total_gas_rate(self.total_current, self.electrode,
                                          self.op.T, self.op.P)

    # ----------------------------------------------------------------- step
    def advance(self):
        """Advance one frame: re-solve current on open pore, grow + vent gas."""
        blocked = self.growth.gas
        # re-solve the reaction distribution as gas blocks pores (redistribution)
        if self.frame % 4 == 0:                    # potential varies slowly
            self.cur.solve(blocked=blocked, iters=60)
        self._surf_current = self.cur.surface_current(self.total_current, blocked=blocked)
        nucw = gt.nucleation_weight(self._surf_current, self.eff["nuc_site_mult"])
        dV = self.gas_rate * self.dt
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
            "lam_cells": round(self.lam_cells, 2),
            "j_A_cm2": self.cfg.j_A_cm2,
        }

    def gas_closure_error(self):
        """|produced - (resident + vented)| / produced — should be ~0."""
        g = self.growth
        resident = float(g.gas.sum()) * self.v_voxel
        if g.produced_cum <= 0:
            return 0.0
        return abs(g.produced_cum - (resident + g.vented_cum)) / g.produced_cum
