"""Regression tests for the 3-D model audit fixes."""
import math
from pathlib import Path

from bubblesim import Operating, Params
from bubblesim.constants import F, R_GAS
from bubblesim.kernel.bubbles.forces import departure_radius
from bubblesim.kernel.context import build_context
from bubblesim.kernel.sources import faradaic_gas_rate
from bubblesim3d.cell3d import CellSim3D
from bubblesim3d.params3d import (DESIGNER_DEFAULTS, cell_config_from_designer,
                                  operating_from_designer)
from server3d_app import LiveSim3D, mesh_catalog_status


APP3D_HTML = Path(__file__).parents[1] / "web3d" / "app3d.html"
VISUALS3D_JS = Path(__file__).parents[1] / "web3d" / "visuals3d.js"
RUN3D_BAT = Path(__file__).parents[1] / "run3d.bat"


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
    # Independent hand-calculation oracle: do not call the production helper
    # for the expected value, or an internal z error would pass both sides.
    p_gas = op.P - sim.ctx["p_water"]
    expected = (sim.params.eta_faraday * j * A / F
                * R_GAS * op.T / p_gas * (1.0 / 2.0 + 1.0 / 4.0))
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


def test_resolved_channel_velocity_and_flow_are_consistent():
    sim, cfg, op = _cell()
    expected_total = op.u_flow * sim.inlet_area_voxel
    assert math.isclose(sim.gas_liquid()[1], expected_total, rel_tol=1e-12)
    assert math.isclose(sim.ns.u_in * sim.inlet_area_voxel,
                        expected_total, rel_tol=1e-12)
    assert math.isclose(sim.ns.u_in, op.u_flow, rel_tol=1e-12)
    assert math.isclose(sim.inlet_area_requested,
                        cfg.channel_area_m2() * 2, rel_tol=1e-12)


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


def test_experiment_contact_angle_does_not_leak_into_shared_default():
    assert Operating().contact_angle == 60.0
    assert operating_from_designer(DESIGNER_DEFAULTS).contact_angle == 34.9


def test_non_custom_flow_clears_a_stale_drawn_mask():
    live = LiveSim3D()
    live.designer["mask"] = "2,2:0000"  # legacy/inconsistent state
    result = live.update({"j": float(live.designer["j"]) + 0.01})
    assert result["accepted"]["mask"] == ""
    assert live.designer["ff"] != "custom"
    assert live.designer["mask"] == ""


def test_any_changed_condition_starts_a_fresh_run_but_ui_controls_do_not():
    live = LiveSim3D()
    initial_run = live.run_id
    old_sim = live.sim
    live.sim.t = 3.5
    live._carry = 0.75
    live.speed_actual = 0.8

    changed = live.update({"j": float(live.designer["j"]) + 0.01})
    assert changed["run_id"] == initial_run + 1
    assert live.run_id == initial_run + 1
    assert live.sim is not old_sim
    assert live.sim.t == 0.0
    assert live._carry == 0.0
    assert live.speed_actual == 0.0

    current_run = live.run_id
    same_sim = live.sim
    controls = live.update({"speed": 2.0, "paused": True})
    assert controls["run_id"] == current_run
    assert controls["paused"] is True
    assert live.sim is same_sim


def test_reset_reports_new_run_preserves_conditions_and_pauses_at_zero():
    live = LiveSim3D()
    live.update({"j": float(live.designer["j"]) + 0.01, "paused": False})
    current_j = live.designer["j"]
    previous_run = live.run_id
    previous_sim = live.sim
    live.sim.t = 2.0

    result = live.reset()
    assert result == {"ok": 1, "run_id": previous_run + 1, "paused": True}
    assert live.run_id == previous_run + 1
    assert live.paused is True
    assert live.sim is not previous_sim
    assert live.sim.t == 0.0
    assert live.designer["j"] == current_j


def test_3d_page_has_run_controls_and_clears_visual_pools_on_new_run():
    html = APP3D_HTML.read_text(encoding="utf-8")
    assert 'id="simRunBar"' in html
    assert 'id="bStageReset"' in html
    assert 'id="bStageStart"' in html
    assert 'id="bStageStop"' in html
    assert "function clearLiveVisualState()" in html
    assert "observeRunResult(st);" in html
    assert "tracers.length = 0; tracerHandoffs.length = 0" in html
    assert "gas3dCur = null; vel3dCur = null" in html


def test_3d_display_uses_exact_detach_paths_without_random_replication():
    html = APP3D_HTML.read_text(encoding="utf-8")
    assert "const TR_N = 5000" in html
    assert 'max:5000, step:100' in html
    assert 'v:"both", local:1' in html
    assert 'v:600, lo:0, hi:5000' in html
    assert 'source:"exact-detach-events"' in html
    assert "function ingestLifecycleEvents(st)" in html
    assert "function _trSeed()" not in html
    assert "availableDistributionCount = Math.min(eligibleFree, serverFreeTarget)" in html
    assert '["16","×16"]' in html
    assert "maxDisplayScale: 16" in html


def test_live_snapshot_filters_exact_detach_events_by_sequence():
    live = LiveSim3D()
    live.sim.parcels.lifecycle_events = [
        {"seq": 4, "type": "nucleate"},
        {"seq": 5, "type": "detach", "id": 11},
        {"seq": 6, "type": "detach", "id": 12},
    ]
    initial = live.snapshot(event_after=0)["lifecycle"]
    assert initial == {"latest_seq": 6, "events": []}
    feed = live.snapshot(event_after=5)["lifecycle"]
    assert feed["latest_seq"] == 6
    assert feed["events"] == [{"seq": 6, "type": "detach", "id": 12}]


def test_live_advance_yields_after_one_slow_step():
    live = LiveSim3D()
    calls = []
    live.sim.step = lambda dt, proj_iters: calls.append((dt, proj_iters))
    live.MAX_LOCK_SECONDS = 0.0
    advanced = live._advance(10 * live.DT)
    assert advanced == live.DT
    assert calls == [(live.DT, live.PROJ_ITERS)]
    assert 0.0 <= live._carry < 1.0


def test_live_advance_keeps_the_requested_batch_when_steps_are_fast():
    live = LiveSim3D()
    calls = []
    live.sim.step = lambda dt, proj_iters: calls.append((dt, proj_iters))
    live.MAX_LOCK_SECONDS = 1.0
    advanced = live._advance(live.BLOCK)
    assert advanced == 4 * live.DT
    assert len(calls) == 4


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
    assert "mesh2_zero_thickness" in html
    assert "new THREE.PlaneGeometry" in html
    assert "expSyncMeshPreview" in html
    assert "hydraulicThicknessMm: mesh2 ? 0" in html
    assert "m.id === wanted && m.fits" in html


def test_mesh_experiment_defaults_to_measured_gas_bubble_angles():
    html = APP3D_HTML.read_text(encoding="utf-8")
    assert 'value="145.1"' in html
    assert 'value="101.2"' in html
    assert "EXP_BUBBLE_ANGLE_E = 145.1" in html
    assert "EXP_BUBBLE_ANGLE_M = 101.2" in html
    assert "waterE: Number((180 - bubbleE).toFixed(3))" in html
    assert "waterM: Number((180 - bubbleM).toFixed(3))" in html
    assert "theta: 34.9, mesh_theta: 78.8" in html


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


def test_component_layers_distinguish_outer_plates_from_real_electrodes():
    html = APP3D_HTML.read_text(encoding="utf-8")
    assert 'data-layer="plateC"' in html
    assert 'data-layer="plateA"' in html
    assert 'data-layer="electrodeC"' in html
    assert 'data-layer="electrodeA"' in html
    assert "음극측 셀 외판" in html
    assert "양극측 셀 외판" in html
    assert "음극 전극/PTL" in html
    assert "양극 전극/NF" in html
    assert 'data-layer="cathode"' not in html
    assert 'data-layer="anode"' not in html
    assert 'data-layer="ptl"' not in html


def test_render_only_visual_upgrade_contract_is_present():
    html = APP3D_HTML.read_text(encoding="utf-8")
    helpers = VISUALS3D_JS.read_text(encoding="utf-8")
    assert "new THREE.ExtrudeGeometry" in helpers
    assert "roundedBoxGeometry" in html
    assert 'data-v="assembly"' in html
    assert 'data-v="internal" class="on"' in html
    assert 'data-v="analysis"' in html
    assert 'let visualPreset = "internal"' in html
    assert 'setAnalysisMode(next === "analysis" ? "j_c" : "off")' in html
    assert "new THREE.CylinderGeometry" in html
    assert "const instAttached = new THREE.InstancedMesh" in html
    assert "freeBubbleTransform" in html
    assert "material.onBeforeCompile" in html


def test_dense_snapshot_fields_are_independently_selectable():
    sim, _, _ = _cell()
    base = sim.snapshot(with_faces=False)
    assert not {"faces", "land2d", "ports", "gas3d", "vel3d"} & base.keys()

    geometry = sim.snapshot(with_faces=False, with_geometry=True)
    assert "land2d" in geometry and "ports" in geometry
    assert "faces" not in geometry and "gas3d" not in geometry and "vel3d" not in geometry

    velocity = sim.snapshot(with_faces=False, with_velocity=True)
    assert "vel3d" in velocity and "gas3d" not in velocity and "faces" not in velocity

    legacy = sim.snapshot(with_faces=True)
    assert {"faces", "land2d", "ports", "gas3d", "vel3d"} <= legacy.keys()

    live = LiveSim3D()
    surfaces = live.snapshot(surfaces=True)
    assert "faces" in surfaces
    assert not {"land2d", "ports", "gas3d", "vel3d"} & surfaces.keys()


def test_run3d_launcher_has_portable_python_fallbacks():
    launcher = RUN3D_BAT.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in launcher
    assert "py -3.14" in launcher
    assert "%LOCALAPPDATA%\\Python" in launcher
    assert "server3d_app.py --view 3d %*" in launcher
    assert "C:\\Users\\user" not in launcher
