"""Track B surface-only current + pore gas growth tests.

  * surface current integrates to the imposed total (charge conservation)
  * gas is conserved: produced == resident + vented at every step
  * gas blocking redistributes current (blocked surface carries none)
  * higher current -> more gas / coverage
  * escape venting removes gas that reaches the separator face
  * a full runner frame set round-trips through snapshots
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim3d.params3d import Pore3DConfig
from bubblesim3d.microstructure import generate
from bubblesim3d.current3d import SurfaceCurrent3D, _surface_faces_mask
from bubblesim3d.poregrowth import PoreGrowth
from bubblesim3d.pore3d import PoreSim3D
from bubblesim3d import snapshots, runner


def _sim(sub="ni_foam", n=32, j=0.8, seed=0):
    cfg = Pore3DConfig(substrate=sub, n=n, j_A_cm2=j, dt_s=2e-3, seed=seed)
    solid, meta = generate(cfg)
    return PoreSim3D(cfg, solid, meta), cfg, solid, meta


# --------------------------------------------------------- current solve
def test_surface_current_conserves_total():
    sim, cfg, solid, meta = _sim()
    sc = sim.cur.surface_current(sim.total_current)
    assert abs(sc.sum() - sim.total_current) < 1e-9 * sim.total_current + 1e-15
    # current only on reacting surface voxels
    assert not (sc[~sim.cur.surf] > 0).any()


def test_current_redistributes_when_blocked():
    """Blocking (gas-covering) surface voxels moves their current elsewhere; the
    total is preserved and blocked voxels carry none."""
    sim, cfg, solid, meta = _sim()
    surf = sim.cur.surf
    idx = np.argwhere(surf)
    blocked = np.zeros_like(solid)
    for p in idx[: len(idx) // 3]:              # block a third of the surface
        blocked[tuple(p)] = True
    sc = sim.cur.surface_current(sim.total_current, blocked=blocked)
    assert abs(sc.sum() - sim.total_current) < 1e-6 * sim.total_current
    assert not (sc[blocked] > 0).any()          # blocked surface carries no current


def test_reaction_is_external_surface_only():
    """A second solid interface behind the first must never receive current."""
    solid = np.zeros((8, 8, 8), dtype=bool)
    solid[:, 3, :] = True
    solid[:, 6, :] = True
    cur = SurfaceCurrent3D(solid, access_axis=1)
    assert cur.surf[:, 2, :].all()
    assert not cur.surf[:, 5, :].any()
    assert not cur.surf[:, 6:, :].any()


# -------------------------------------------------------- gas conservation
def test_gas_conserved_every_step():
    """produced == resident + vented, exact to within one voxel (the only
    discretization error — gas is placed in whole voxels, never leaked)."""
    sim, cfg, solid, meta = _sim(n=32, j=1.0)
    for _ in range(50):
        sim.advance()
        g = sim.growth
        resident = float(g.gas.sum()) * sim.v_voxel
        residual = abs(g.produced_cum - (resident + g.vented_cum))
        assert residual <= sim.v_voxel + 1e-18     # closed to <1 voxel
    s = sim.scalars()
    assert s["produced"] > 0 and s["vented"] >= 0
    # once many voxels are involved the relative error is tiny
    assert sim.gas_closure_error() < 1e-2


def test_higher_current_more_gas():
    lo, _, _, _ = _sim(j=0.3, seed=1)
    hi, _, _, _ = _sim(j=1.5, seed=1)
    for _ in range(40):
        lo.advance(); hi.advance()
    assert hi.scalars()["produced"] > lo.scalars()["produced"]
    assert hi.growth.gas.sum() >= lo.growth.gas.sum()


def test_venting_removes_escaping_gas():
    """Gas that reaches the separator face vents (open foam escape_factor~1)."""
    solid = generate(Pore3DConfig(substrate="ni_mesh", n=24, seed=0))[0]
    g = PoreGrowth(solid, escape_axis=1, escape_factor=1.0)
    v_voxel = 1.0
    # nucleation weight favouring the escape face so gas quickly reaches it
    w = np.zeros_like(solid, dtype=float)
    w[:, 0, :] = 1.0                               # separator-face surface
    for _ in range(60):
        g.grow(50.0, v_voxel, w / max(1, w.sum()))
    assert g.vented_cum > 0                         # some gas escaped
    assert abs(g.produced_cum - (g.gas.sum() * v_voxel + g.vented_cum)) < 1e-6 * g.produced_cum


# ------------------------------------------------------- surface mask
def test_surface_mask_is_pore_touching_solid():
    solid = generate(Pore3DConfig(substrate="ni_foam", n=24, seed=0))[0]
    surf = _surface_faces_mask(solid)
    assert not (surf & solid).any()                # surface voxels are pores...
    assert surf.sum() > 0                           # ...that touch solid
    # only one externally visible interface is selected along each access ray
    assert (surf.sum(axis=1) <= 1).all()


# ------------------------------------------------------------ runner
def test_runner_frames_roundtrip(tmp_path):
    cfg = Pore3DConfig(substrate="ni_mesh", n=24, j_A_cm2=0.8, dt_s=2e-3, frames=6)
    manifest = runner.run(cfg, tmp_path, frames=6, created="test")
    assert manifest["frames"] == 6
    # every frame reads back with a gas mask + scalars
    for i in range(1, 7):
        blob = snapshots.frame_blob(tmp_path, i)
        gas = snapshots.unpack_bool(blob["shape"], blob["gas_b64"])
        assert gas.shape == (24, 24, 24)
        assert "coverage" in blob["scalars"]
    # scaffold blob loads
    sc = snapshots.scaffold_blob(tmp_path)
    assert tuple(sc["shape"]) == (24, 24, 24)


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            if "tmp_path" in fn.__code__.co_varnames:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print("ok", name)
