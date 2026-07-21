"""Regression tests for the 3-D model audit fixes."""
import math
from pathlib import Path

from bubblesim import Params
from bubblesim.kernel.bubbles.forces import departure_radius
from bubblesim.kernel.context import build_context
from bubblesim.kernel.sources import faradaic_gas_rate
from bubblesim3d.cell3d import CellSim3D
from bubblesim3d.params3d import (DESIGNER_DEFAULTS, cell_config_from_designer,
                                  operating_from_designer)
from server3d_app import LiveSim3D, mesh_catalog_status


APP3D_HTML = Path(__file__).parents[1] / "web3d" / "app3d.html"


def _cell(**overrides):
    d = dict(DESIGNER_DEFAULTS); d.update(overrides)
    cfg = cell_config_from_designer(d)
    op = operating_from_designer(d)
    p = Params(r_departure_ref=0.5e-6 * d["departure_diameter_um"])
    return CellSim3D(op, p, cfg.grid_dims(), h=cfg.h, cfg=cfg), cfg, op


def test_measured_zero_flow_departure_size_overrides_fritz_scaling():
    d = {**DESIGNER_DEFAULTS, "u_flow": 0.0, "B": 0.0, "E": 0.0,
         "departure_diameter_um": 300.0}
    op = operating_from_designer(d)
    p = Params(fritz_scale=1.9, r_departure_ref=150.0e-6)
    ctx = build_context(op, p)
    assert math.isclose(departure_radius(op, ctx, 5000.0), 150.0e-6,
                        rel_tol=2e-3)


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


def test_3d_display_supports_dense_tracers_and_large_bubble_scales():
    html = APP3D_HTML.read_text(encoding="utf-8")
    assert "const TR_N = 5000" in html
    assert 'max:5000, step:100' in html
    assert 'v:"both", local:1' in html
    assert 'v:5000, lo:0, hi:5000' in html
    assert '["16","×16"]' in html
    assert "maxDisplayScale: 16" in html


def test_analysis_spectrum_is_visual_only_and_can_show_raw_voxels():
    html = APP3D_HTML.read_text(encoding="utf-8")
    assert 'id="analysisSmooth"' in html
    assert "tex.userData.analysisScale = scale" in html
    assert "if (analysisSmooth)" in html
    assert "sourceGrid: analysisData" in html
    assert "textureSize: faceTexC" in html


def test_mesh2_ui_exposes_hydrophobic_only_mode():
    html = APP3D_HTML.read_text(encoding="utf-8")
    assert 'id="exMeshMode"' in html
    assert 'data-v="hydrophobic"' in html
    assert "mesh_mode: expMeshMode()" in html
    assert '"mesh_mode","dry_cathode"' in html
    assert "두께의 유체역학 효과 제외" in html


def test_mesh2_catalog_does_not_reject_mesh_thicker_than_channel():
    base = {**DESIGNER_DEFAULTS, "d_ch_mm": 0.9, "theta": 60,
            "mesh_theta": 150}
    physical = {m["id"]: m for m in mesh_catalog_status(base)}
    mesh2 = {m["id"]: m for m in mesh_catalog_status(
        {**base, "mesh_mode": "hydrophobic"})}
    assert not physical["pp_094x094"]["fits"]
    assert mesh2["pp_094x094"]["fits"]
    assert mesh2["pp_094x094"]["hydraulic_mode"] == "hydrophobic_only"
    assert mesh2["pp_094x094"]["obstruction"] == 0.0
    assert mesh2["pp_094x094"]["u_boost"] == 1.0
    assert mesh2["pp_094x094"]["dp_ratio"] == 1.0


def test_quantitative_color_modes_have_viewport_legends():
    html = APP3D_HTML.read_text(encoding="utf-8")
    assert 'id="fieldLegendStack"' in html
    assert 'id="analysisLegend"' in html
    assert 'id="bubbleVelocityLegend"' in html
    assert 'symbol:"|u<sub>b</sub>|"' in html
    assert "window.__colorLegendInfo" in html
    assert "velLegend" not in html
