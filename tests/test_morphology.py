"""Track 2 -- electrode morphology library (effective/homogenized properties).

Checks the physics contracts: flat plate reduces to a planar electrode; foams &
nanostructures raise area (R_f, a); Bruggeman lowers the effective conductivities;
the reaction penetration depth shrinks as the kinetics get faster; substrate x
electrolyte warnings fire where the chemistry would corrode.

Run with:  python -m pytest tests/ -q   (or: python tests/test_morphology.py)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim.kernel import morphology as morph                  # noqa: E402


def test_flat_plate_reduces_to_planar():
    """flat_plate + planar_film == an ordinary planar electrode."""
    e = morph.effective_electrode("flat_plate", "planar_film")
    assert e["R_f"] < 2.0                       # essentially no roughness
    assert e["eps_p"] == 0.0
    assert math.isclose(e["sigma_eff"], e["sigma_s"])   # (1-0)^1.5 = 1
    assert e["tau"] == 1.0
    assert morph.kappa_eff(60.0, e) == 60.0     # planar -> bulk electrolyte


def test_foam_and_nano_raise_area():
    """Foam scaffold and nanostructure both multiply the active area."""
    flat = morph.effective_electrode("flat_plate", "planar_film")["R_f"]
    foam = morph.effective_electrode("ni_foam", "planar_film")["R_f"]
    nano = morph.effective_electrode("flat_plate", "nanoparticle")["R_f"]
    both = morph.effective_electrode("ni_foam", "nanoparticle")["R_f"]
    assert foam > flat and nano > flat
    assert both > foam and both > nano
    # multiplicative: nanostructure coats the whole scaffold
    assert math.isclose(both, 30.0 * 80.0, rel_tol=1e-9)
    assert morph.effective_electrode("ni_foam", "nanoparticle")["a"] > 1e6  # m^2/m^3


def test_loading_scales_area_linearly():
    base = morph.effective_electrode("ni_foam", "nanowire", cat_loading=1.0)["R_f"]
    dbl = morph.effective_electrode("ni_foam", "nanowire", cat_loading=2.0)["R_f"]
    assert math.isclose(dbl, 2.0 * base, rel_tol=1e-9)


def test_bruggeman_lowers_effective_conductivities():
    """More porous matrix -> lower solid sigma_eff; pores -> lower kappa_eff."""
    foam = morph.effective_electrode("ni_foam", "planar_film")        # eps 0.95
    mesh = morph.effective_electrode("ni_mesh", "planar_film")        # eps 0.60
    assert foam["sigma_eff"] < foam["sigma_s"]
    assert foam["sigma_eff"] < mesh["sigma_eff"]                      # more porous, lower
    assert morph.kappa_eff(60.0, foam) < 60.0
    assert foam["tau"] > 1.0


def test_penetration_depth_shrinks_with_faster_kinetics():
    """Faster kinetics (larger dj/d_eta) -> shallower reaction zone."""
    e = morph.effective_electrode("ni_foam", "nanoparticle")
    deep = morph.penetration_depth(e, 60.0, dj_deta=1.0e2)
    shallow = morph.penetration_depth(e, 60.0, dj_deta=1.0e6)
    assert deep > shallow > 0.0
    assert all(math.isfinite(x) for x in (deep, shallow))


def test_warnings_fire_on_incompatible_chemistry():
    assert morph.morphology_warnings("ss_foam", "nanoparticle", "H2SO4", "OER")
    assert morph.morphology_warnings("ni_foam", "nanoparticle", "H2SO4", "HER")
    assert morph.morphology_warnings("carbon_paper", "nanoparticle", "KOH", "OER")
    assert not morph.morphology_warnings("ni_foam", "nanoparticle", "KOH", "HER")


def test_all_combos_finite_positive():
    for s in morph.SUBSTRATES:
        for n in morph.NANOSTRUCTURES:
            e = morph.effective_electrode(s, n)
            for k in ("R_f", "a", "L_e", "tau", "sigma_s", "sigma_eff",
                      "j0_mult", "C_dl_area", "nuc_site_mult", "escape_factor"):
                assert math.isfinite(e[k]) and e[k] > 0.0, (s, n, k, e[k])
            assert 0.0 <= e["eps_p"] < 1.0


def test_overrides_replace_preset_and_recompute():
    """Measured overrides win over presets; dependent quantities recompute."""
    base = morph.effective_electrode("ni_foam", "nanoparticle")
    ov = morph.effective_electrode("ni_foam", "nanoparticle",
                                   overrides={"R_f": 500.0, "L_e": 1.0e-3,
                                              "eps_p": 0.80, "sigma_s": 1.0e5})
    assert ov["R_f"] == 500.0
    assert math.isclose(ov["L_e"], 1.0e-3)
    assert math.isclose(ov["a"], 500.0 / 1.0e-3, rel_tol=1e-9)      # a = R_f/L_e
    assert ov["eps_p"] == 0.80 and ov["overridden"] is True
    assert math.isclose(ov["sigma_eff"], 1.0e5 * 0.20 ** 1.5, rel_tol=1e-9)
    assert ov["R_f"] != base["R_f"]
    # partial override leaves the rest from the preset
    p = morph.effective_electrode("ni_foam", "nanoparticle", overrides={"R_f": 999.0})
    assert p["R_f"] == 999.0 and p["eps_p"] == base["eps_p"]


def test_rf_helpers():
    assert math.isclose(morph.rf_from_bet(50.0, 1.0), 500.0)        # 50 m2/g x 1 mg/cm2 x10
    assert math.isclose(morph.rf_from_cdl(20.0, 0.40), 50.0)        # 20 / 0.40 F/m2
    assert morph.rf_from_bet(1e-4, 1e-4) >= 1.0                     # floored at 1


def test_presets_cover_all():
    p = morph.list_presets()
    assert len(p["substrates"]) == len(morph.SUBSTRATES)
    assert len(p["nanostructures"]) == len(morph.NANOSTRUCTURES)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}  {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {fn.__name__}  {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
