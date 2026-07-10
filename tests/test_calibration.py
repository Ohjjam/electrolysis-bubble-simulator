"""Quantitative-calibration option (high_fidelity): Pitzer activity + Gilliam
conductivity for KOH, opt-in so the default (Davies + parabolic fit) stays
golden bit-identical.

Run with:  python -m pytest tests/ -q   (or: python tests/test_calibration.py)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params                          # noqa: E402
from bubblesim import properties as prop                         # noqa: E402
from bubblesim.kernel import chemistry as chem                   # noqa: E402
from bubblesim.kernel.context import build_context               # noqa: E402


def test_gilliam_koh_conductivity_reasonable():
    """6 M KOH at 25 C ~ 60 S/m (the well-known peak); rises with temperature."""
    k25 = prop.conductivity_koh_gilliam(6.0, 298.15)
    assert 55.0 < k25 < 72.0
    assert prop.conductivity_koh_gilliam(6.0, 353.15) > k25      # hotter -> higher
    assert prop.conductivity_koh_gilliam(0.0, 298.15) >= 0.1     # floored, finite


def test_pitzer_matches_known_dilute_and_beats_davies():
    """Pitzer reproduces g+-(~1 molal KOH) ~ 0.75 and, unlike Davies, stays
    physical (does not blow up) at electrolyzer concentration."""
    g1 = chem.pitzer_activity_koh(1.0)
    assert math.isclose(g1, 0.75, rel_tol=0.08)
    davies6 = chem.davies_activity(chem.ionic_strength(6.0, "KOH"))
    pitzer6 = chem.pitzer_activity_koh(6.0)
    assert davies6 > 3.0                              # Davies extrapolation blows up
    assert 0.5 < pitzer6 < davies6                    # Pitzer more physical
    for c in (0.5, 2.0, 6.0, 10.0):
        assert chem.pitzer_activity_koh(c) > 0.0 and math.isfinite(chem.pitzer_activity_koh(c))


def test_activity_for_default_is_davies():
    """high_fidelity=False reproduces the Davies activity exactly (golden-safe)."""
    for med in ("KOH", "H2SO4", "PB"):
        a = chem.activity_for(3.0, 333.15, med, high_fidelity=False)
        b = chem.davies_activity(chem.ionic_strength(3.0, med))
        assert a == b
    # high_fidelity only changes KOH
    assert chem.activity_for(6.0, 333.15, "KOH", high_fidelity=True) == chem.pitzer_activity_koh(6.0, 333.15)
    assert chem.activity_for(3.0, 333.15, "H2SO4", high_fidelity=True) == \
        chem.davies_activity(chem.ionic_strength(3.0, "H2SO4"))


def test_context_flag_default_bit_identical():
    """Default context kappa/activity equal the original correlations exactly."""
    op = Operating(electrolyte="KOH", c_electrolyte=6.0, T=333.15)
    ctx = build_context(op, Params())
    assert ctx["kappa"] == prop.conductivity_KOH(6.0, 333.15)
    assert ctx["activity_coeff"] == chem.davies_activity(chem.ionic_strength(6.0, "KOH"))


def test_context_high_fidelity_changes_props():
    """With the flag, KOH context uses Gilliam + Pitzer -> different finite numbers."""
    base = Operating(electrolyte="KOH", c_electrolyte=6.0, T=333.15)
    hf = Operating(electrolyte="KOH", c_electrolyte=6.0, T=333.15, high_fidelity=True)
    cb, ch = build_context(base, Params()), build_context(hf, Params())
    assert abs(ch["kappa"] - cb["kappa"]) > 1.0
    assert ch["kappa"] == prop.conductivity_koh_gilliam(6.0, 333.15)
    assert ch["activity_coeff"] != cb["activity_coeff"]
    assert math.isfinite(ch["kappa"]) and math.isfinite(ch["activity_coeff"])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1; print(f"  FAIL  {fn.__name__}  {e}")
        except Exception as e:
            failed += 1; print(f"  ERROR {fn.__name__}  {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
