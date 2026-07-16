"""Regression tests for the 3-D model audit fixes."""
import math

from bubblesim import Params
from bubblesim.kernel.sources import faradaic_gas_rate
from bubblesim3d.cell3d import CellSim3D
from bubblesim3d.params3d import (DESIGNER_DEFAULTS, cell_config_from_designer,
                                  operating_from_designer)
from server3d_app import LiveSim3D


def _cell(**overrides):
    d = dict(DESIGNER_DEFAULTS); d.update(overrides)
    cfg = cell_config_from_designer(d)
    op = operating_from_designer(d)
    p = Params(fritz_scale=d["fritz_scale"])
    return CellSim3D(op, p, cfg.grid_dims(), h=cfg.h, cfg=cfg), cfg, op


def test_oer_stoichiometry_is_applied_once_in_cell_gas_total():
    sim, _, op = _cell()
    j = sim.cell_current_A_m2()
    A = sim.grid.Ly * sim.grid.Lz
    kw = dict(wet=True, water_activity=sim.ctx["water_activity"])
    expected = (faradaic_gas_rate(j, "HER", op.T, op.P, A, **kw)
                + faradaic_gas_rate(j, "OER", op.T, op.P, A, **kw))
    actual = sim.gas_liquid()[0]
    assert math.isclose(actual, expected, rel_tol=1e-12)


def test_wet_product_gas_volume_exceeds_dry_volume():
    dry = faradaic_gas_rate(1e4, "HER", 333.15, 1e5, 1e-4)
    wet = faradaic_gas_rate(1e4, "HER", 333.15, 1e5, 1e-4,
                            wet=True, water_activity=0.76)
    assert wet > dry


def test_live_grid_cap_coarsens_resolution_not_cell_size():
    d = {**DESIGNER_DEFAULTS, "W_cm": 20.0, "H_cm": 30.0, "h_mm": 0.4}
    cfg = cell_config_from_designer(d)
    nx, ny, nz = cfg.grid_dims()
    assert nx * ny * nz <= cfg.max_cells
    assert cfg.h > cfg.h_requested
    assert math.isclose(ny * cfg.h, 0.30, rel_tol=0.12)
    assert math.isclose(nz * cfg.h, 0.20, rel_tol=0.12)


def test_physical_pump_flow_is_conserved_on_voxel_inlet():
    sim, cfg, op = _cell()
    expected_total = op.u_flow * cfg.channel_area_m2() * 2
    assert math.isclose(sim.gas_liquid()[1], expected_total, rel_tol=1e-12)
    assert math.isclose(sim.ns.u_in * sim.inlet_area_voxel,
                        expected_total, rel_tol=1e-12)


def test_server_rejects_invalid_geometry_transactionally():
    live = LiveSim3D()
    old = dict(live.designer)
    sim_id = id(live.sim)
    result = live.update({"w_ch_mm": -1, "w_land_mm": 1, "T": -273.15})
    assert set(result["rejected"]) == {"w_ch_mm", "T"}
    assert live.designer["w_ch_mm"] == old["w_ch_mm"]
    assert live.designer["T"] == old["T"]
    assert id(live.sim) == sim_id


def test_live_and_sweep_property_fidelity_match():
    assert operating_from_designer(DESIGNER_DEFAULTS).high_fidelity is True


def test_non_custom_flow_clears_a_stale_drawn_mask():
    live = LiveSim3D()
    live.designer["mask"] = "2,2:0000"  # legacy/inconsistent state
    result = live.update({"j": float(live.designer["j"]) + 0.01})
    assert result["accepted"]["mask"] == ""
    assert live.designer["ff"] != "custom"
    assert live.designer["mask"] == ""
