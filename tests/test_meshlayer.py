"""Mesh-interlayer mapping (kernel.meshlayer) + channel-solver integration.

The mesh model is a GEOMETRY -> bubble-knob mapping fixed a priori (blind
prediction protocol); these tests pin its structure and the no-mesh identity:

  * neutral factors when there is no mesh (t=0) -- legacy bit-identical path
  * physical trends: denser/finer mesh wicks more, thicker mesh boosts local
    velocity and blocking penalty, mesh thicker than the channel cannot mount
  * channel integration: mesh lowers the CP cell voltage at gas-choked high j,
    and covering the OUTLET half (where gas accumulates) beats the inlet half
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params, Simulator                     # noqa: E402
from bubblesim.config import ElectrodeParams                           # noqa: E402
from bubblesim.kernel.meshlayer import mesh_factors, path_mask         # noqa: E402
from bubblesim.solvers.channel import ChannelSolver                    # noqa: E402

_SOLVER = ChannelSolver()

# the measured PP mesh (hole 1.016x1.346 mm -> 1.18 mean, 50% open, 0.483 mm)
MESH = dict(mesh_hole_mm=1.18, mesh_open=0.5, mesh_t_mm=0.483)


def _channel_op(j_macm2, **kw):
    return Operating(model="channel", mode="CP", j_set=j_macm2 * 10.0,
                     track_both=True, electrolyte="KOH", c_electrolyte=1.0,
                     T=338.15, gap_mm=0.5, high_fidelity=True, A_cm2=4.84,
                     u_flow=0.08, channel_type="serpentine", n_pass=13,
                     cell_width_cm=2.2, face_height_cm=2.2, chan_depth_mm=0.9,
                     channel_void_ohmic=True, void_ohmic_frac=0.82, **kw)


def _solve(op):
    sim = Simulator(op=op, params=Params(
        anode=ElectrodeParams("OER", j0_ref=7.94e-4, alpha_a=1.14, Ea_j0=50.0e3),
        cathode=ElectrodeParams("HER", j0_ref=3000.0, Ea_j0=30.0e3),
        r_membrane_area=9.6e-6))
    return _SOLVER.solve(op, sim.props(), sim.surfaces)


def test_no_mesh_is_neutral():
    f = mesh_factors(0.0, 1.0, 0.0, 0.9)
    assert f["fits"] and f["u_boost"] == 1.0 and f["theta_factor"] == 1.0
    assert f["retention_factor"] == 1.0 and f["theta_add"] == 0.0


def test_mesh_thicker_than_channel_cannot_mount():
    f = mesh_factors(2.4, 0.45, 2.03, 0.9)          # 0.094" mesh in a 0.9 mm channel
    assert not f["fits"] and "cannot mount" in f["warn"]


def test_wick_trends():
    base = mesh_factors(1.18, 0.5, 0.483, 0.9)
    denser = mesh_factors(1.18, 0.3, 0.483, 0.9)     # more strand -> more wick
    coarser = mesh_factors(4.0, 0.5, 0.483, 0.9)     # bigger holes -> less wick
    assert denser["wick"] > base["wick"] > coarser["wick"]
    assert base["theta_factor"] < 1.0 and base["retention_factor"] < 1.0
    assert base["theta_add"] > 0.0


def test_encroachment_boost_and_cap():
    thin = mesh_factors(1.18, 0.5, 0.2, 0.9)
    thick = mesh_factors(1.18, 0.5, 0.7, 0.9)
    assert 1.0 < thin["u_boost"] < thick["u_boost"]
    near = mesh_factors(1.18, 0.5, 0.88, 0.9)        # nearly fills the channel
    assert near["u_boost"] <= 4.0 and near["warn"]
    assert thick["theta_add"] > thin["theta_add"]    # thicker blocks more liquid


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
