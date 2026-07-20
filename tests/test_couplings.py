"""Track-1 coupling tests (A-F): the previously-dangling physics nodes, now wired.

A  supersaturation-driven nucleation (Henry -> dissolved pool -> S -> CNT-lite)
B  Vogt bubble self-stirring (j-dependent limiting-current enhancement)
C  Nernst pressure term in E_rev(P)
D  double-layer capacitance scales with active area, C_dl(1-theta)
E  activity-corrected concentration order in j0
F  electrolyte-specific coalescence threshold

Defaults are chosen so existing golden/characterization values are unchanged
(P=1 bar -> +0 ; activity ratio 1 at c_ref ; nucleation="empirical").

Run with:  python -m pytest tests/ -q   (or: python tests/test_couplings.py)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params, Simulator                 # noqa: E402
from bubblesim import properties as prop                            # noqa: E402
from bubblesim.kernel import transport as tr                        # noqa: E402
from bubblesim.kernel import chemistry as chem                      # noqa: E402
from bubblesim.kernel import impedance as imp                       # noqa: E402
from bubblesim.kernel.context import build_context                  # noqa: E402
from bubblesim.kernel.bubbles.population import Surface             # noqa: E402
import random                                                       # noqa: E402


# ============================================================ C  E_rev(P)
def test_erev_pressure_zero_at_reference():
    """1 bar reference gives exactly the old T-only value (ln(1)=0 -> golden-safe)."""
    assert prop.reversible_voltage(333.15, 1.0e5) == 1.229 - 0.9e-3 * (333.15 - 298.15)


def test_erev_rises_with_pressure():
    """Pressurized operation raises the reversible voltage (Nernst gas term)."""
    e1 = prop.reversible_voltage(333.15, 1.0e5)
    e10 = prop.reversible_voltage(333.15, 10.0e5)
    assert e10 > e1
    # analytic: (RT/2F)*1.5*ln(10)
    from bubblesim.constants import F, R_GAS
    assert math.isclose(e10 - e1, (R_GAS * 333.15) / (2 * F) * 1.5 * math.log(10.0), rel_tol=1e-9)


# ============================================================ B  Vogt
def test_vogt_enhancement():
    assert tr.vogt_enhancement(0.0, 1e4, 0.6) == 1.0
    assert tr.vogt_enhancement(1e4, 1e4, 0.6) > 1.0
    assert tr.vogt_enhancement(4e4, 1e4, 0.6) > tr.vogt_enhancement(1e4, 1e4, 0.6)
    assert tr.vogt_enhancement(1e4, 1e4, 0.0) == 1.0   # disabled


def test_vogt_raises_achievable_current():
    """With Vogt on, the CP transport limit (hence clamp) is above the base."""
    from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver

    class Flat:
        def coverage(self): return 0.0
        def void_fraction(self): return 0.0
    op = Operating(mode="CP", j_set=1.0e9, model="two_electrode")
    j_vogt = ZeroDTwoElectrodeSolver().solve(op, build_context(op, Params()), [Flat()]).j
    p0 = Params(); p0.k_vogt = 0.0
    j_base = ZeroDTwoElectrodeSolver().solve(op, build_context(op, p0), [Flat()]).j
    assert j_vogt > j_base


# ============================================================ E  activity -> j0
def test_activity_neutral_at_reference():
    """At c = c_ref the activity ratio is 1, so j0 is unchanged (golden-safe)."""
    d_ref = build_context(Operating(c_electrolyte=6.0), Params())
    j0_plain = prop.j0_arrhenius(Params().anode.j0_ref, Params().anode.Ea_j0,
                                 333.15, 6.0, Params().anode.gamma_c)
    assert math.isclose(d_ref["j0_anode"], j0_plain, rel_tol=1e-12)


def test_activity_shifts_j0_off_reference():
    """Isolate the activity factor itself (not the incidental c-dependence):
    context j0 differs from the plain (c/c_ref)^gamma value by exactly
    (activity(c)/activity(c_ref))^gamma off-reference."""
    c = 1.0
    d = build_context(Operating(c_electrolyte=c), Params())
    a = Params().cathode
    plain = prop.j0_arrhenius(a.j0_ref, a.Ea_j0, 333.15, c, a.gamma_c)  # no activity args
    assert not math.isclose(d["j0_cathode"], plain, rel_tol=1e-6)       # activity moved it
    act = chem.davies_activity(chem.ionic_strength(c, "KOH"))
    act_ref = chem.davies_activity(chem.ionic_strength(6.0, "KOH"))
    assert math.isclose(d["j0_cathode"] / plain, (act / act_ref) ** a.gamma_c, rel_tol=1e-9)


# ============================================================ D  C_dl(1-theta)
def test_cdl_coverage_keeps_apex_frequency_grows_diameter():
    """Coverage raises R_ct (semicircle diameter) but, with C_dl(1-theta), the
    apex frequency stays ~constant (the RC time constant is intensive)."""
    j0, T = 1.0, 333.15
    def spectrum(theta):
        omt = 1.0 - theta
        R_ct = imp.r_ct_bv(omt * j0, 0.5, 0.5, 0.2, T)
        C = 0.2 * omt
        freqs = [10 ** (k / 10.0) for k in range(-20, 41)]
        Z = imp.cell_impedance(freqs, 0.0, [{"R_ct": R_ct, "C_dl": C}])
        apex = freqs[max(range(len(Z)), key=lambda i: -Z[i].imag)]
        return R_ct, apex
    Rct0, f0 = spectrum(0.0)
    Rct1, f1 = spectrum(0.5)
    assert Rct1 > Rct0                                  # bigger semicircle when covered
    assert abs(math.log10(f1 / f0)) < 0.06             # apex frequency ~ unchanged


# ============================================================ F  coalescence
def test_coalescence_threshold_is_electrolyte_specific():
    """At 0.15 M, KOH is below its CCC and H2SO4 is above its CCC."""
    from bubblesim.kernel.bubbles.bubble import Bubble

    def merges(electrolyte):
        op = Operating(electrolyte=electrolyte, c_electrolyte=0.15, contact_angle=90.0)
        merged = 0
        for seed in range(40):
            s = Surface(op, Params(), random.Random(seed))
            # two overlapping attached bubbles
            s.bubbles = [Bubble(x=1e-3, y=0.0, r=2e-4, id=1),
                         Bubble(x=1.05e-3, y=0.0, r=2e-4, id=2)]
            s.coalesce()
            if len(s.bubbles) == 1:
                merged += 1
        return merged
    assert merges("KOH") > merges("H2SO4")


# ============================================================ A  supersaturation
def test_dissolved_pool_and_supersaturation():
    """S rises with gas input and falls with a higher saturation concentration
    (=higher pressure): the chain P -> c_sat -> S that drives nucleation."""
    op, p = Operating(), Params()
    s = Surface(op, p, random.Random(0))
    # inject gas for a while at fixed c_sat
    for _ in range(200):
        S = s.update_supersaturation(gas_in_rate=1e-6, c_sat=1.3, k_m=5e-6, dt=1e-3)
    assert S > 1.0
    # higher c_sat (higher P) -> lower S for the same gas input
    s2 = Surface(op, p, random.Random(0))
    for _ in range(200):
        S2 = s2.update_supersaturation(gas_in_rate=1e-6, c_sat=13.0, k_m=5e-6, dt=1e-3)
    assert S2 < S


def test_nucleation_modes():
    """Empirical mode unchanged by the new arg; supersaturation mode fires only
    above S=1 and rises with S."""
    op, p = Operating(contact_angle=90.0), Params()

    def count(mode_kwargs, n=300):
        s = Surface(op, p, random.Random(1))
        for _ in range(n):
            s.nucleate(3000.0, 1e-3, **mode_kwargs)
        return sum(1 for b in s.bubbles if b.attached)

    # empirical: nucleate(j,dt) == nucleate(j,dt,supersaturation=None)
    s_a = Surface(op, p, random.Random(7)); s_a.nucleate(3000.0, 1e-3)
    s_b = Surface(op, p, random.Random(7)); s_b.nucleate(3000.0, 1e-3, supersaturation=None)
    assert len(s_a.bubbles) == len(s_b.bubbles)
    # supersaturation: none below 1, some above, more at higher S
    assert count({"supersaturation": 0.5}) == 0
    assert count({"supersaturation": 5.0}) > 0
    assert count({"supersaturation": 50.0}) >= count({"supersaturation": 2.0})


def test_simulator_supersaturation_differs_from_empirical():
    """Supersaturation nucleation drives a coupled run AND yields a different
    bubble trajectory than the empirical default (the mode is load-bearing, not a
    no-op that a broken dispatch would silently pass)."""
    from dataclasses import replace as _replace
    base = Operating(V_cell=2.2)
    h_emp = Simulator(base, seed=0).run(t_end=0.5, dt=5e-4)
    h_ss = Simulator(_replace(base, nucleation="supersaturation"), seed=0).run(t_end=0.5, dt=5e-4)
    assert max(h_ss["n_bub"]) > 0 and h_ss["j"][-1] > 0.0
    assert h_ss["n_bub"] != h_emp["n_bub"]


def test_pressure_suppresses_nucleation_end_to_end():
    """Full chain op.P -> c_sat (Henry) -> S -> nucleation: higher pressure raises
    c_sat, lowers supersaturation, so fewer bubbles nucleate. Guards against a
    regression that decouples pressure from c_sat_gas."""
    from dataclasses import replace as _replace
    base = Operating(V_cell=2.2, nucleation="supersaturation")
    n_lo = max(Simulator(base, seed=0).run(t_end=0.5, dt=5e-4)["n_bub"])
    n_hi = max(Simulator(_replace(base, P=2.0e6), seed=0).run(t_end=0.5, dt=5e-4)["n_bub"])
    assert n_hi < n_lo


# ============================================================ B  Vogt robustness/ceiling
class _Flat:
    def coverage(self): return 0.0
    def void_fraction(self): return 0.0


def test_vogt_zero_jref_no_crash():
    """j_ref_vogt=0 (a plausible 'disable' value) must not crash the solver."""
    from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver
    p = Params(); p.j_ref_vogt = 0.0
    op = Operating(mode="CP", j_set=2000.0, model="two_electrode")
    st = ZeroDTwoElectrodeSolver().solve(op, build_context(op, p), [_Flat()])
    assert st.j > 0.0 and math.isfinite(st.V)


def test_ca_current_never_exceeds_vogt_ceiling():
    """Even at very high V the CA solve cannot report j above the exact
    self-consistent Vogt ceiling (regression for the under-converged fixed point)."""
    from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver
    p = Params()
    ctx = build_context(Operating(V_cell=10.0, model="two_electrode"), p)
    ceiling = tr.vogt_limit(ctx["j_lim_transport"], p.j_ref_vogt, p.k_vogt)
    st = ZeroDTwoElectrodeSolver().solve(Operating(V_cell=10.0, model="two_electrode"), ctx, [_Flat()])
    assert st.j <= ceiling * 1.0001


def test_vogt_raises_ca_achievable_current():
    """In the transport-stressed regime, Vogt on yields higher CA current than off
    (locks Vogt into the implicit solve, not only the clamp)."""
    from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver
    op = Operating(V_cell=4.0, model="two_electrode")
    j_on = ZeroDTwoElectrodeSolver().solve(op, build_context(op, Params()), [_Flat()]).j
    p0 = Params(); p0.k_vogt = 0.0
    j_off = ZeroDTwoElectrodeSolver().solve(op, build_context(op, p0), [_Flat()]).j
    assert j_on > j_off


# ============================================================ D  transient at coverage
def test_cdl_transient_faster_under_coverage():
    """C_dl*(1-theta) in the transient: at fixed cell current R_ct is ~theta-
    independent, so coverage shrinks the double-layer area and the CP relaxation is
    FASTER at higher coverage. Measured via the per-step decay factor exp(-dt/tau)
    (independent of the step magnitude) -- a mutation guard for the (1-theta)
    factor at dynamic.py. Both electrodes are covered so neither tau dominates."""
    from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver
    from bubblesim.solvers.dynamic import DoubleLayerWrapper

    class Cov:
        def __init__(self, th): self.th = th
        def coverage(self): return self.th
        def void_fraction(self): return 0.0

    def decay_factor(theta, dt=1e-3):
        p = Params(); p.anode.C_dl = p.cathode.C_dl = 200.0   # big C -> partial relaxation
        op = Operating(mode="CP", j_set=1000.0, model="two_electrode", track_both=True)
        ctx, surf = build_context(op, p), [Cov(theta), Cov(theta)]
        w = DoubleLayerWrapper(ZeroDTwoElectrodeSolver(), p, dt)
        w.solve(op, ctx, surf)                 # init eta = ss(1000)
        op.j_set = 5000.0                       # current step
        V_ss = ZeroDTwoElectrodeSolver().solve(op, ctx, surf).V
        gaps = [abs(w.solve(op, ctx, surf).V - V_ss) for _ in range(8)]
        return gaps[-1] / gaps[-2]              # exp(-dt/tau): smaller = faster
    assert decay_factor(0.5) < decay_factor(0.0)


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
