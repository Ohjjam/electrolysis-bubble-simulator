"""Dry-cathode (anolyte-only AEM) membrane water transport.

The cathode of the measured cell gets NO liquid feed: every electron needs a
water molecule that crossed the membrane. Back-diffusion supplies it;
electro-osmotic drag (OH- travelling cathode -> anode) steals from it. That
gives a water-supply limiting current and a starvation overpotential.

Guards: off-by-default is bit-identical, the drag direction is a LOSS (a bigger
n_drag lowers the limit), a thinner membrane helps, and the penalty only bites
near the water limit.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Operating, Params
from bubblesim.constants import F
from bubblesim.kernel.context import build_context
from bubblesim.kernel import watertransport as wt
from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver


class _Stub:
    def __init__(self, theta=0.0, eps=0.0):
        self._t, self._e = theta, eps

    def coverage(self):
        return self._t

    def void_fraction(self):
        return self._e


def _op(**kw):
    op = Operating(model="two_electrode", track_both=True, mode="CP", T=338.15,
                   electrolyte="KOH", c_electrolyte=1.0, gap_mm=0.5)
    for k, v in kw.items():
        setattr(op, k, v)
    return op


def _params():
    p = Params()
    p.anode.j0_ref = 7.94e-4
    p.anode.alpha_a = 1.14
    p.cathode.j0_ref = 3000.0
    p.r_membrane_area = 9.6e-6
    return p


def _solve(op):
    ctx = build_context(op, _params())
    st = ZeroDTwoElectrodeSolver(n_outer=60, n_inner=48).solve(
        op, ctx, [_Stub(), _Stub()])
    return ctx, st


# ----------------------------------------------------------------- kernel math
def test_permeance_and_limit_follow_the_water_balance():
    """j_lim_water = F k_w / (1 + n_drag): the cathode must be fed the water HER
    consumes (1/e-) AND the water the OH- current drags away (n_drag/e-)."""
    k_w = wt.water_permeance(50e-6, D_w=1.0e-9, c_w=4.0e4)
    assert k_w == 1.0e-9 * 4.0e4 / 50e-6                    # = 0.8 mol/m^2/s
    j_lim = wt.water_limiting_current(k_w, n_drag=2.5)
    assert abs(j_lim - F * k_w / 3.5) < 1e-6
    assert 1.0e4 < j_lim < 4.0e4                            # ~2 A/cm^2 scale


def test_drag_starves_the_cathode_and_thin_membranes_help():
    k_w = wt.water_permeance(50e-6)
    # drag is a LOSS (AEM: OH- goes cathode -> anode): more drag = lower limit
    assert (wt.water_limiting_current(k_w, n_drag=4.0)
            < wt.water_limiting_current(k_w, n_drag=1.0))
    # a thinner membrane delivers more water
    assert (wt.water_permeance(20e-6) > wt.water_permeance(80e-6))


def test_eta_water_is_zero_below_the_limit_and_grows_into_it():
    j_lim = 2.0e4
    assert wt.eta_water(0.0, j_lim, 338.15) == 0.0
    small = wt.eta_water(0.05 * j_lim, j_lim, 338.15)
    big = wt.eta_water(0.9 * j_lim, j_lim, 338.15)
    assert 0.0 < small < 0.01                       # negligible far from the wall
    assert big > 5 * small                          # and it bites near it
    assert wt.eta_water(j_lim, j_lim, 338.15) < 1.0  # saturates, never diverges


# ----------------------------------------------------- solver / context wiring
def test_off_by_default_is_bit_identical():
    """The golden contract: an unflagged cell must not move by one bit."""
    _, wet = _solve(_op(j_set=1.0e4))
    ctx, _ = _solve(_op(j_set=1.0e4))
    assert ctx["j_lim_water"] == 0.0
    assert ctx["water_permeance"] == 0.0
    assert wet.overpotentials["eta_water"] == 0.0
    dry = _solve(_op(j_set=1.0e4, dry_cathode=True))[1]
    assert dry.V > wet.V                            # enabling it costs voltage
    assert dry.overpotentials["eta_water"] > 0.0


def test_dry_cathode_penalty_grows_with_current():
    """Water starvation is a HIGH-current failure: negligible at low j, large as
    the cell approaches the water-supply limit."""
    lo_w = _solve(_op(j_set=1.0e3, dry_cathode=True))[1]
    lo_d = _solve(_op(j_set=1.0e3))[1]
    hi_w = _solve(_op(j_set=2.0e4, dry_cathode=True))[1]
    hi_d = _solve(_op(j_set=2.0e4))[1]
    d_lo = lo_w.V - lo_d.V
    d_hi = hi_w.V - hi_d.V
    assert 0.0 <= d_lo < 0.02                       # ~ nothing at 0.1 A/cm^2
    # at 2 A/cm^2 the default membrane runs at ~91% of its water limit -> ~70 mV
    assert 0.04 < d_hi < 0.25                       # real, and not runaway
    assert d_hi > 5 * max(d_lo, 1e-6)


def test_thinner_membrane_recovers_the_dry_cathode():
    """A thinner membrane passes more water back -> less starvation. This is the
    real design lever the term exposes."""
    thick = _solve(_op(j_set=1.8e4, dry_cathode=True, t_mem_um=80.0))[1]
    thin = _solve(_op(j_set=1.8e4, dry_cathode=True, t_mem_um=20.0))[1]
    assert thin.V < thick.V
    assert thin.overpotentials["eta_water"] < thick.overpotentials["eta_water"]


def test_water_limit_caps_the_current_in_CA_mode():
    """In CA (potentiostatic) the water supply is a hard ceiling on j."""
    op = _op(mode="CA", V_cell=2.6, dry_cathode=True, D_w_mem=2.0e-10)  # poor supply
    ctx, st = _solve(op)
    assert ctx["j_lim_water"] > 0.0
    assert st.j <= ctx["j_lim_water"] * 0.9951
    wet = _solve(_op(mode="CA", V_cell=2.6))[1]
    assert st.j < wet.j                             # starvation cuts the current
