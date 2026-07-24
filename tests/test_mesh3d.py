import math

import numpy as np

from bubblesim.config import Params
from bubblesim3d.cell3d import CellSim3D
from bubblesim3d.grid import Grid3D
from bubblesim3d.params3d import (DESIGNER_DEFAULTS, MESH_CATALOG,
                                 cell_config_from_designer,
                                 operating_from_designer)
from bubblesim3d.parcels import Parcels


def mesh_parcels(concentration=1.0, mesh_id="pp_040x053", mesh_mode="physical"):
    designer = dict(DESIGNER_DEFAULTS)
    designer.update(mesh_id=mesh_id, mesh_mode=mesh_mode,
                    c_mol=concentration, mesh_cover=1.0, mesh_pos="outlet")
    op = operating_from_designer(designer)
    grid = Grid3D(6, 6, 6, 1.0e-3)
    return Parcels(grid, op, np.random.default_rng(4), params=Params(),
                   elec_planes=(1.0e-3, 5.0e-3), channel_depth=1.0e-3)


def set_parcels(p, positions, radii, *, attached, mesh_attached, mult=None):
    n = len(radii)
    p.pos = np.asarray(positions, dtype=float)
    p.r = np.asarray(radii, dtype=float)
    p.mult = np.ones(n) if mult is None else np.asarray(mult, dtype=float)
    p.W = p.mult * p._vol(p.r)
    p.side = np.ones(n, dtype=np.int8)
    p.attached = np.asarray(attached, dtype=bool)
    p.mesh_attached = np.asarray(mesh_attached, dtype=bool)
    p.mesh_axis = np.where(p.mesh_attached, 1, 0).astype(np.int8)
    p.r_dep = np.full(n, 5.0e-4)
    p.phase = np.zeros(n)
    p.p_touch = np.zeros(n)
    p.ids = np.arange(1, n + 1, dtype=np.int64)


def test_live_operating_carries_catalog_mesh_geometry():
    p = mesh_parcels()
    geom = p.mesh_geometry()
    assert geom is not None
    assert geom["id"] == "pp_040x053"
    assert math.isclose(geom["hole_z"], 1.016e-3)
    assert math.isclose(geom["hole_y"], 1.346e-3)
    assert math.isclose(geom["strand_radius"], 0.483e-3 / 2)
    assert math.isclose(geom["pitch_z"], 1.016e-3 / math.sqrt(0.5))


def test_every_mesh2_catalog_size_reaches_the_live_3d_snapshot():
    snapshots = []
    for spec in MESH_CATALOG:
        snap = mesh_parcels(mesh_id=spec["id"], mesh_mode="hydrophobic").mesh_snapshot()
        assert snap is not None
        assert snap["id"] == spec["id"]
        assert snap["mode"] == "hydrophobic"
        assert math.isclose(snap["hole_z"], spec["hole_x_mm"], abs_tol=1e-6)
        assert math.isclose(snap["hole_y"], spec["hole_y_mm"], abs_tol=1e-6)
        assert math.isclose(2 * snap["strand_radius"], spec["t_mm"], abs_tol=1e-6)
        snapshots.append((snap["pitch_y"], snap["pitch_z"], snap["strand_radius"]))
    assert len(set(snapshots)) == len(MESH_CATALOG)


def test_mesh2_does_not_change_live_cfd_solid_or_inlet_geometry():
    pristine = dict(DESIGNER_DEFAULTS)
    mesh2 = {**pristine, "mesh_id": "pp_094x094", "mesh_mode": "hydrophobic"}
    cfg0, cfg2 = cell_config_from_designer(pristine), cell_config_from_designer(mesh2)
    sim0 = CellSim3D(operating_from_designer(pristine), Params(), cfg0.grid_dims(),
                     cfg0.h, cap=20, cfg=cfg0)
    sim2 = CellSim3D(operating_from_designer(mesh2), Params(), cfg2.grid_dims(),
                     cfg2.h, cap=20, cfg=cfg2)
    assert np.array_equal(sim0.ns.solid, sim2.ns.solid)
    assert np.array_equal(sim0.ns.inlet, sim2.ns.inlet)
    assert np.array_equal(sim0.ns.outlet, sim2.ns.outlet)
    assert sim0.inlet_area == sim2.inlet_area


def test_mesh_capture_requires_contact_and_conserves_gas():
    p = mesh_parcels()
    r = 0.10e-3
    # First bubble is directly over z=0 strand; second sits near the centre of
    # the rectangular aperture and is too small to touch any strand.
    set_parcels(
        p,
        [[p._wall_x(1, r), 3.0e-3, 0.0],
         [p._wall_x(1, r), 3.0e-3, 0.72e-3]],
        [r, 0.02e-3], attached=[True, True], mesh_attached=[False, False],
    )
    gas_before = p.resident_gas()
    p._capture_on_mesh()
    assert p.mesh_attached.tolist() == [True, False]
    assert p.attached.tolist() == [False, True]
    assert p.snapshot_flat()[5] == 2.0
    assert math.isclose(p.resident_gas(), gas_before, rel_tol=0, abs_tol=1e-24)


def test_mesh_contact_merge_conserves_represented_volume():
    p = mesh_parcels()
    p.op.c_electrolyte = 0.0  # eta=1: isolate contact/volume mechanics
    r = 0.08e-3
    geom = p.mesh_geometry()
    x = geom["x_axis"] + geom["strand_radius"] + r
    set_parcels(p, [[x, 2.00e-3, 0.0], [x, 2.10e-3, 0.0]], [r, r],
                attached=[False, False], mesh_attached=[True, True], mult=[10, 10])
    gas_before = p.resident_gas()
    p._coalesce_mesh()
    assert len(p.r) == 1
    assert p.n_merge_mesh == 1
    assert math.isclose(p.resident_gas(), gas_before, rel_tol=2e-15)
    assert math.isclose(p.r[0], r * 2 ** (1 / 3), rel_tol=2e-15)


def test_mesh_cohort_split_allows_fractional_expected_weight():
    """A valid weighted collision is not discarded just to keep mult >= 1."""
    p = mesh_parcels(concentration=0.0)
    p.op.c_electrolyte = 0.0  # eta=1: isolate weighted cohort mechanics
    r = 0.08e-3
    geom = p.mesh_geometry()
    x = geom["x_axis"] + geom["strand_radius"] + r
    set_parcels(p, [[x, 2.00e-3, 0.0], [x, 2.10e-3, 0.0]], [r, r],
                attached=[False, False], mesh_attached=[True, True],
                mult=[1.0, 1.5])
    gas_before = p.resident_gas()
    p._coalesce_mesh()
    assert p.n_merge_mesh == 1
    assert np.allclose(np.sort(p.mult), [0.5, 1.0])
    assert math.isclose(p.resident_gas(), gas_before, rel_tol=2e-15)


def test_koh_coalescence_efficiency_is_continuous_not_hard_zero():
    one_molar = mesh_parcels(1.0).p_merge()
    six_molar = mesh_parcels(6.0).p_merge()
    assert math.isclose(one_molar, 0.3 / 1.3)
    assert math.isclose(six_molar, 0.3 / 6.3)
    assert 0.0 < six_molar < one_molar < 1.0


class UniformFlow:
    def __init__(self, velocity):
        self.velocity = np.asarray(velocity, dtype=float)
        self.up = np.array([0.0, 1.0, 0.0])

    def sample_velocity(self, positions):
        n = len(positions)
        return tuple(np.full(n, value) for value in self.velocity)


def test_mesh_release_uses_force_balance_without_release_coefficient():
    p = mesh_parcels()
    geom = p.mesh_geometry()
    r = 0.08e-3
    x = geom["x_axis"] + geom["strand_radius"] + r
    set_parcels(p, [[x, 3.0e-3, 0.0]], [r], attached=[False],
                mesh_attached=[True])
    ctx = {"rho_l": 1000.0, "mu": 1.0e-3, "sigma": 0.072,
           "d_rho": 999.0}
    p._move_and_release_mesh(UniformFlow([0.0, 50.0, 0.0]), 0.0, ctx)
    assert not p.mesh_attached[0]
    assert p.n_mesh_release_force == 1


def test_mesh_strand_end_releases_a_sliding_bubble():
    p = mesh_parcels()
    geom = p.mesh_geometry()
    r = 0.08e-3
    x = geom["x_axis"] + geom["strand_radius"] + r
    set_parcels(p, [[x, geom["y1"] - 1e-9, 0.0]], [r], attached=[False],
                mesh_attached=[True])
    ctx = {"rho_l": 1000.0, "mu": 1.0e-3, "sigma": 0.072,
           "d_rho": 999.0}
    p._move_and_release_mesh(UniformFlow([0.0, 0.0, 0.0]), 1.0, ctx)
    assert not p.mesh_attached[0]
    assert p.n_mesh_release_edge == 1
