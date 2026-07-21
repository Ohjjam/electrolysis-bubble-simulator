"""Contact-angle/geometry mesh model + channel-solver integration tests."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params, Simulator                     # noqa: E402
from bubblesim.config import ElectrodeParams                           # noqa: E402
from bubblesim.kernel.meshlayer import mesh_factors, path_mask         # noqa: E402
from bubblesim.solvers.channel import ChannelSolver                    # noqa: E402

_SOLVER = ChannelSolver()

# the measured PP mesh (hole 1.016x1.346 mm -> 1.18 mean, 50% open, 0.483 mm)
MESH = dict(mesh_hole_mm=1.181, mesh_hole_x_mm=1.016,
            mesh_hole_y_mm=1.346, mesh_open=0.5, mesh_t_mm=0.483,
            contact_angle=34.9, mesh_contact_angle=78.8)


def _channel_op(j_macm2, **kw):
    return Operating(model="channel", mode="CP", j_set=j_macm2 * 10.0,
                     track_both=True, electrolyte="KOH", c_electrolyte=1.0,
                     T=338.15, gap_mm=0.5, high_fidelity=True, A_cm2=4.84,
                     u_flow=0.08, channel_type="serpentine", n_pass=13,
                     cell_width_cm=2.2, face_height_cm=2.2, chan_depth_mm=0.9,
                     channel_void_ohmic=True, void_ohmic_frac=0.82, **kw)


def _solve(op):
    sim = Simulator(op=op, params=Params(fritz_scale=0.08,
        anode=ElectrodeParams("OER", j0_ref=7.94e-4, alpha_a=1.14, Ea_j0=50.0e3),
        cathode=ElectrodeParams("HER", j0_ref=3000.0, Ea_j0=30.0e3),
        r_membrane_area=9.6e-6))
    return _SOLVER.solve(op, sim.props(), sim.surfaces)


def test_no_mesh_is_neutral():
    f = mesh_factors(0.0, 1.0, 0.0, 0.9)
    assert f["fits"] and f["u_boost"] == 1.0 and f["theta_factor"] == 1.0
    assert f["retention_factor"] == 1.0 and f["blocking_fraction"] == 0.0


def test_mesh_thicker_than_channel_cannot_mount():
    f = mesh_factors(2.4, 0.45, 2.03, 0.9)          # 0.094" mesh in a 0.9 mm channel
    assert not f["fits"] and f["warn"]


def test_mesh2_ignores_hydraulic_thickness_but_keeps_surface_transfer():
    common = dict(open_frac=0.45, d_ch_mm=0.9, bubble_d_mm=0.23,
                  electrode_angle_deg=34.9, mesh_angle_deg=78.8, hydraulic=False)
    thin = mesh_factors(2.4, t_mm=0.2, **common)
    thick = mesh_factors(2.4, t_mm=2.03, **common)
    for result in (thin, thick):
        assert result["fits"]
        assert result["hydraulic_mode"] == "hydrophobic_only"
        assert result["obstruction"] == 0.0
        assert result["flow_open_frac"] == result["retention_factor"] == 1.0
        assert result["u_boost"] == result["dp_ratio"] == 1.0
        assert result["capture_eff"] > 0.0 and result["theta_factor"] < 1.0
    assert thin["capture_eff"] == thick["capture_eff"]
    assert thin["theta_factor"] == thick["theta_factor"]


def test_contact_probability_is_smooth_and_finer_is_higher():
    kw = dict(open_frac=0.5, t_mm=0.483, d_ch_mm=0.9,
              bubble_d_mm=0.23, electrode_angle_deg=34.9, mesh_angle_deg=78.8)
    fine = mesh_factors(0.5, **kw)
    base = mesh_factors(1.18, **kw)
    coarse = mesh_factors(4.0, **kw)
    assert 0.0 < coarse["contact_prob"] < base["contact_prob"] < fine["contact_prob"] < 1.0
    assert fine["capture_eff"] > base["capture_eff"] > coarse["capture_eff"]
    dense = mesh_factors(1.18, 0.3, 0.483, 0.9, bubble_d_mm=0.23)
    sparse = mesh_factors(1.18, 0.7, 0.483, 0.9, bubble_d_mm=0.23)
    assert dense["contact_prob"] > sparse["contact_prob"]


def test_measured_gas_bubble_angles_drive_transfer_toward_pp_mesh():
    # Measured submerged gas-bubble angles are converted to water-side angles:
    # catalyst/NF 145.1 -> 34.9 deg; bare PP 101.2 -> 78.8 deg.
    driven = mesh_factors(1.18, 0.5, 0.483, 0.9, bubble_d_mm=0.23,
                          electrode_angle_deg=34.9, mesh_angle_deg=78.8)
    assert 0.34 < driven["wetting_drive"] < 0.35
    assert driven["theta_factor"] < 1.0


def test_wetting_transfer_reverses_when_bubble_angles_are_reversed():
    no_drive = mesh_factors(1.18, 0.5, 0.483, 0.9, bubble_d_mm=0.23,
                            electrode_angle_deg=78.8, mesh_angle_deg=34.9)
    assert no_drive["wetting_drive"] == 0.0
    assert no_drive["capture_eff"] == 0.0


def test_solid_volume_boost_and_pressure_ratio():
    thin = mesh_factors(1.18, 0.5, 0.2, 0.9, bubble_d_mm=0.23)
    thick = mesh_factors(1.18, 0.5, 0.7, 0.9, bubble_d_mm=0.23)
    assert 1.0 < thin["u_boost"] < thick["u_boost"]
    near = mesh_factors(1.18, 0.1, 0.88, 0.9, bubble_d_mm=0.23)
    assert near["dp_ratio"] > thick["dp_ratio"] > thin["dp_ratio"]
    assert near["warn"]
    assert thick["blocking_fraction"] == thin["blocking_fraction"] == 0.0
    assert thick["active_area_blocking_mode"] == "not_modelled"


def test_path_mask_placement():
    m = 100
    assert sum(path_mask(m, 0.0, "outlet")) == 0
    assert sum(path_mask(m, 1.0, "inlet")) == m
    half_in = path_mask(m, 0.5, "inlet")
    half_out = path_mask(m, 0.5, "outlet")
    mid = path_mask(m, 0.5, "middle")
    assert half_in[0] and not half_in[-1]
    assert half_out[-1] and not half_out[0]
    assert mid[m // 2] and not mid[0] and not mid[-1]
    assert sum(half_in) == sum(half_out) == sum(mid) == 50


def test_channel_defaults_have_no_mesh_fields():
    st = _solve(_channel_op(1000))
    assert "mesh_on" not in st.fields
    assert "path_prof" in st.fields                  # add-only diagnostics present


def test_mesh_lowers_voltage_at_high_current():
    a = _solve(_channel_op(2250))
    b = _solve(_channel_op(2250, mesh_cover=1.0, **MESH))
    assert b.V < a.V - 0.02, f"mesh should relieve the choke: {a.V:.3f} -> {b.V:.3f}"
    assert b.fields["theta_out"] < a.fields["theta_out"]
    assert b.fields["mesh_on"] and b.fields["mesh_mask_frac"] > 0.99


def test_outlet_half_beats_inlet_half():
    """Gas accumulates downstream, so covering the outlet half must help more."""
    inlet = _solve(_channel_op(2250, mesh_cover=0.5, mesh_pos="inlet", **MESH))
    outlet = _solve(_channel_op(2250, mesh_cover=0.5, mesh_pos="outlet", **MESH))
    assert outlet.V < inlet.V, (
        f"outlet-half {outlet.V:.3f} should beat inlet-half {inlet.V:.3f}")


def test_unfit_mesh_changes_nothing():
    a = _solve(_channel_op(1500))
    b = _solve(_channel_op(1500, mesh_cover=1.0,
                           mesh_hole_mm=2.4, mesh_open=0.45, mesh_t_mm=2.03))
    assert abs(a.V - b.V) < 1e-12 and "mesh_on" not in b.fields


def test_mesh2_channel_keeps_thick_mesh_active_without_flow_boost():
    mesh2 = dict(mesh_hole_mm=2.4, mesh_open=0.45, mesh_t_mm=2.03,
                 mesh_contact_angle=78.8, mesh_cover=1.0,
                 mesh_mode="hydrophobic", contact_angle=34.9)
    st = _solve(_channel_op(1500, **mesh2))
    assert st.fields["mesh_on"]
    assert st.fields["mesh_mode"] == "hydrophobic"
    assert st.fields["mesh_hydraulic_mode"] == "hydrophobic_only"
    assert st.fields["mesh_obstruction"] == 0.0
    assert st.fields["mesh_u_boost"] == st.fields["mesh_dp_ratio"] == 1.0
    assert st.fields["mesh_capture_eff"] > 0.0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1; print(f"  FAIL  {fn.__name__}  {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
