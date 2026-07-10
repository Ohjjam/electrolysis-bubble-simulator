"""Track B microstructure generation + snapshot I/O tests.

  * generated porosity matches the target (foam floored for connectivity)
  * specific area is positive and finite
  * BOTH phases percolate (electrolyte pore path + electronic solid path)
  * flat_plate reduces to a solid slab
  * scaffold / frame snapshots round-trip; bit packing is exact
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim3d.params3d import Pore3DConfig
from bubblesim3d.microstructure import generate, microstructure_stats, _min_solid_frac
from bubblesim3d import snapshots


# ------------------------------------------------------- microstructure
def test_porosity_matches_target():
    """Paper/mesh hit target porosity exactly; foam is floored for connectivity."""
    for sub, tol in (("carbon_paper", 0.02), ("ni_mesh", 0.02)):
        cfg = Pore3DConfig(substrate=sub, n=48, seed=0)
        solid, meta = generate(cfg)
        st = microstructure_stats(solid, meta["h_um"] * 1e-6)
        assert abs(st["porosity"] - meta["eps_target"]) < tol
        assert abs(st["porosity"] - meta["eps_achieved"]) < 1e-3


def test_foam_floored_but_connected():
    """High-porosity foam is floored at the resolution limit yet stays connected."""
    cfg = Pore3DConfig(substrate="ni_foam", n=64, seed=0)
    solid, meta = generate(cfg)
    st = microstructure_stats(solid, meta["h_um"] * 1e-6)
    assert meta["eps_achieved"] <= meta["eps_target"]         # floored
    assert st["percolates_y"] and st["solid_percolates"]      # both phases connect


def test_both_phases_percolate():
    for sub in ("ni_foam", "carbon_paper", "ni_mesh"):
        cfg = Pore3DConfig(substrate=sub, n=48, seed=1)
        solid, meta = generate(cfg)
        st = microstructure_stats(solid, meta["h_um"] * 1e-6)
        assert st["percolates_y"], f"{sub} pore path blocked"
        assert st["solid_percolates"], f"{sub} electronic path broken"


def test_specific_area_positive():
    cfg = Pore3DConfig(substrate="ni_foam", n=48, seed=0)
    solid, meta = generate(cfg)
    st = microstructure_stats(solid, meta["h_um"] * 1e-6)
    assert st["specific_area"] > 0 and np.isfinite(st["specific_area"])


def test_finer_grid_recovers_porosity():
    """A finer grid lets the foam approach its true (higher) porosity."""
    e64 = generate(Pore3DConfig(substrate="ni_foam", n=64, seed=2))[1]["eps_achieved"]
    e128 = generate(Pore3DConfig(substrate="ni_foam", n=128, seed=2))[1]["eps_achieved"]
    assert e128 > e64                                        # thinner struts possible


def test_flat_plate_is_slab():
    cfg = Pore3DConfig(substrate="flat_plate", n=32, seed=0)
    solid, meta = generate(cfg)
    assert abs(solid.mean() - 0.5) < 0.02                    # half solid slab


def test_min_solid_frac_scales_with_resolution():
    assert _min_solid_frac(64) > _min_solid_frac(128)        # finer -> thinner ok


# ------------------------------------------------------------ snapshots
def test_bit_pack_roundtrip():
    rng = np.random.default_rng(0)
    mask = rng.random((16, 12, 20)) < 0.3
    shape, b64 = snapshots.pack_bool(mask)
    back = snapshots.unpack_bool(shape, b64)
    assert np.array_equal(mask, back)


def test_scaffold_frame_roundtrip(tmp_path):
    solid = generate(Pore3DConfig(substrate="ni_mesh", n=24, seed=0))[0]
    meta = {"substrate": "ni_mesh", "n": 24}
    snapshots.save_scaffold(tmp_path, solid, meta)
    back, m = snapshots.load_scaffold(tmp_path)
    assert np.array_equal(solid, back) and m["substrate"] == "ni_mesh"
    # a frame with gas + surface current
    gas = np.zeros_like(solid); gas[5:8, 5:8, 5:8] = True
    jsurf = np.arange(10, dtype=np.float32)
    snapshots.save_frame(tmp_path, 1, gas, {"coverage": 0.1, "holdup": 0.02},
                         surf_current=jsurf)
    fr = snapshots.load_frame(tmp_path, 1)
    assert np.array_equal(fr["gas"], gas)
    assert fr["scalars"]["coverage"] == 0.1
    assert np.allclose(fr["jsurf"], jsurf)


def test_scaffold_blob(tmp_path):
    solid = generate(Pore3DConfig(substrate="ni_foam", n=24, seed=0))[0]
    snapshots.save_scaffold(tmp_path, solid, {"metal": "Ni"})
    blob = snapshots.scaffold_blob(tmp_path)
    back = snapshots.unpack_bool(blob["shape"], blob["solid_b64"])
    assert np.array_equal(solid, back) and blob["meta"]["metal"] == "Ni"


if __name__ == "__main__":
    import tempfile
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            if "tmp_path" in fn.__code__.co_varnames:
                with tempfile.TemporaryDirectory() as d:
                    from pathlib import Path
                    fn(Path(d))
            else:
                fn()
            print("ok", name)
