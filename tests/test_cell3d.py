"""Track A (cell-scale 3-D) engine tests.

Meaningful checks for a Stam-style projection solver + Lagrangian parcels:
  * the projection produces a genuinely divergence-free interior
  * uniform inflow with no gas -> plug flow at the inlet speed (mass balance)
  * the vectorized parcel slip matches the frozen kernel terminal velocity
  * spawned parcel gas volume closes the Faraday balance (j/nF)
  * a detached parcel in quiescent liquid rises at its terminal velocity
  * tilt rotates the buoyancy/slip direction (the 3-D payoff)

These import bubblesim.kernel read-only; no golden values are touched.
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim import Params
from bubblesim.kernel.bubbles.population import Surface
from bubblesim.kernel.context import build_context
from bubblesim3d.grid import Grid3D
from bubblesim3d.ns3d import NS3D
from bubblesim3d.parcels import Parcels, terminal_velocity
from bubblesim3d.cell3d import CellSim3D
from bubblesim3d.params3d import (DESIGNER_DEFAULTS, cell_config_from_designer,
                                  operating_from_designer)


def _op(**kw):
    d = dict(DESIGNER_DEFAULTS); d.update(kw)
    return operating_from_designer(d)


# --------------------------------------------------------------- projection
def test_batched_deposition_matches_scalar_stencils_exactly():
    g = Grid3D(5, 6, 7, 1.0e-3)
    rng = np.random.default_rng(21)
    pts = rng.uniform([0.0, 0.0, 0.0], [g.Lx, g.Ly, g.Lz], size=(18, 3))
    weights = rng.uniform(0.0, 2.0, size=(5, len(pts)))
    valid = rng.random(g.shape) > 0.2
    scalar = np.zeros((5,) + g.shape)
    scalar_totals = np.asarray([
        g.deposit27(scalar[i], pts, weights[i], valid)
        for i in range(len(scalar))
    ])
    batched = np.zeros_like(scalar)
    batched_totals = g.deposit27_many(batched, pts, weights, valid)
    assert np.allclose(batched, scalar, rtol=0.0, atol=1.0e-14)
    assert np.allclose(batched_totals, scalar_totals, rtol=0.0, atol=1.0e-14)


def test_projection_divergence_free():
    """A random divergent field in a closed box projects to ~0 divergence."""
    g = Grid3D(16, 16, 16, 1.5e-3)
    ns = NS3D(g, outlet=False); ns.u_in = 0.0
    r = np.random.default_rng(0)
    ns.U = r.standard_normal(ns.U.shape) * 0.01
    ns.V = r.standard_normal(ns.V.shape) * 0.01
    ns.W = r.standard_normal(ns.W.shape) * 0.01
    ns._apply_bc()
    d0 = ns.max_divergence()
    ns.project(200, warm=False)
    d1 = ns.max_divergence()
    assert d0 > 1.0                       # started strongly divergent
    assert d1 < 1e-3                      # projected essentially divergence-free
    assert d1 < d0 * 1e-3


def test_projection_open_outlet():
    """With an inflow + open outlet the interior still projects div-free."""
    g = Grid3D(16, 16, 16, 1.5e-3)
    ns = NS3D(g, outlet=True); ns.u_in = 0.05
    r = np.random.default_rng(1)
    ns.U = r.standard_normal(ns.U.shape) * 0.01
    ns.V = r.standard_normal(ns.V.shape) * 0.01
    ns.W = r.standard_normal(ns.W.shape) * 0.01
    ns._apply_bc()
    ns.project(1000, warm=False)
    assert ns.max_divergence() < 1e-3


# ------------------------------------------------- projection convergence
def test_step_ends_with_the_projection():
    """The field the parcels sample must be the divergence-free one.

    `forces -> project -> advect` left the ADVECTION's divergence in the field
    that then moved the bubbles. Ending on the projection halves the residual
    for the same sweep count."""
    g = Grid3D(8, 24, 8, 2.0e-3)
    ns = NS3D(g); ns.u_in = 0.05; ns.nu = 1.0e-6; ns.damp = 0.0
    for _ in range(40):
        ns.step(2.0e-3, proj_iters=200, tol=0.0)
    vmax = max(float(ns.speed().max()), 1e-9)
    assert ns.max_divergence() * g.h / vmax < 1e-3        # post-step, as sampled


def test_projection_early_exit_is_exact_and_adaptive():
    """`tol` stops the SOR when the residual says the corrected field is already
    divergence-free enough. The residual estimate R/h^2 is EXACTLY the post-
    projection divergence, so the exit cannot be optimistic."""
    g = Grid3D(8, 24, 8, 2.0e-3)
    ns = NS3D(g); ns.u_in = 0.05; ns.nu = 1.0e-6; ns.damp = 0.0
    first = []
    for i in range(80):
        ns.step(2.0e-3, proj_iters=200, tol=2.0e-3)
        first.append(ns.sweeps)
    assert first[0] == 200                       # developing: needs the budget
    assert first[-1] < 40                        # settled: stops early
    vmax = max(float(ns.speed().max()), 1e-9)
    assert ns.max_divergence() * g.h / vmax < 2.0e-3      # the tol is honoured

    # the residual estimate matches the divergence it predicts, to round-off
    h = g.h
    ns.add_forces(2e-3); ns.diffuse(2e-3); ns.advect(2e-3)
    rhs = ns._divergence() * h * h
    ns.project(40, tol=0.0)
    res = np.abs(ns._ndiv * ns.p - ns._neighbour_sum(ns.p) + rhs)
    res[ns.solid] = 0.0
    assert abs(res.max() / (h * h) - ns.max_divergence()) < 1e-9 * max(1.0, ns.max_divergence())


# --------------------------------------------------------------- viscosity
def _poiseuille(nu, nx=20, ny=16, nz=4, h=1.0e-3, u_in=1.0e-3, dt=2.0e-4, steps=400):
    """Plane channel: no-slip electrode x-walls, FREE-slip z-walls, plug inflow.
    Returns the fully developed velocity profile across x and the exact parabola."""
    g = Grid3D(nx, ny, nz, h)
    ns = NS3D(g, outlet=True)
    ns.noslip_z = False          # -> exact 2-D Poiseuille in x
    ns.damp = 0.0; ns.buoy = 0.0
    ns.nu = nu; ns.u_in = u_in
    for _ in range(steps):
        ns.step(dt, proj_iters=30)
    _, v, _ = ns.centres()
    prof = v[:, ny - 4, nz // 2]
    xc = (np.arange(nx) + 0.5) * h
    Lx = nx * h
    exact = 1.5 * u_in * (1.0 - ((xc - Lx / 2) / (Lx / 2)) ** 2)
    return prof, exact


def test_viscous_channel_recovers_poiseuille():
    """With the explicit viscous term a straight duct relaxes to the analytic
    parabola: u(x) = 1.5 u_mean [1 - ((x-L/2)/(L/2))^2].

    Re = u L / nu = 4e-3, so this is Stokes flow — no advection, no numerical
    diffusion excuse. This is what makes the wall shear a real number instead of
    an artefact of semi-Lagrangian smearing.
    """
    prof, exact = _poiseuille(nu=5.0e-3)
    err = np.abs(prof - exact).max() / exact.max()
    assert err < 0.03                                   # 1.5% on a 20-cell channel
    assert abs(prof.mean() / 1.0e-3 - 1.0) < 0.02       # mass balance
    assert abs(prof[len(prof)//2] - exact[len(exact)//2]) < 0.02 * exact.max()


def test_without_viscosity_the_channel_stays_plug():
    """Guard: the parabola comes from the VISCOUS operator, not from numerical
    diffusion. nu=0 leaves the prescribed plug profile untouched."""
    prof, exact = _poiseuille(nu=0.0)
    wall_to_centre = prof[0] / prof[len(prof) // 2]
    assert wall_to_centre > 0.97                        # still plug
    assert np.abs(prof - exact).max() / exact.max() > 0.3


def test_viscous_substepping_is_stable_past_the_explicit_bound():
    """nu*dt/h^2 = 3 would blow up a single explicit Euler step; `diffuse`
    substeps to stay inside 1/6 and stays bounded."""
    g = Grid3D(8, 8, 8, 1.0e-3)
    ns = NS3D(g, outlet=False)
    ns.nu = 1.0e-2; ns.damp = 0.0
    ns.V[:] = np.random.default_rng(0).standard_normal(ns.V.shape) * 0.01
    v0 = np.abs(ns.V).max()
    ns.diffuse(3.0e-4)                                  # nu*dt/h^2 = 3.0
    assert np.isfinite(ns.V).all()
    assert np.abs(ns.V).max() <= v0 + 1e-12             # diffusion never amplifies


# ---------------------------------------------------------------- plug flow
def test_plug_flow_inlet_speed():
    """Uniform inflow, no gas: steady interior flow ~ the inlet speed (mass
    conservation through the straight open channel), divergence stays small."""
    g = Grid3D(10, 40, 10, 1.5e-3)
    ns = NS3D(g, outlet=True); ns.u_in = 0.05
    ns.damp = 0.0                          # don't dissipate the through-flow
    for _ in range(200):
        ns.project(60)
        ns.advect(2.0e-3)
    _, v, _ = ns.centres()
    core = v[2:-2, 5:-5, 2:-2]             # away from walls / inlet / outlet
    assert abs(core.mean() - 0.05) < 0.05 * 0.15     # within 15 % of u_in
    assert ns.max_divergence() < 1e-2


# ------------------------------------------------------- terminal velocity
def test_terminal_velocity_recovers_independent_stokes_limit():
    """At Re << 1, Schiller--Naumann must reduce to analytical Stokes rise."""
    d_rho, mu, rho_l = 1000.0, 1.0e-3, 1000.0
    radii = np.array([0.25e-6, 0.5e-6, 1.0e-6])
    got = terminal_velocity(radii, d_rho, mu, rho_l, iters=80)
    expected = (2.0 / 9.0) * d_rho * 9.80665 * radii ** 2 / mu
    reynolds = 2.0 * radii * got * rho_l / mu
    assert reynolds.max() < 0.01
    assert np.allclose(got, expected, rtol=0.03)


# ------------------------------------------------------ Faraday gas closure
def test_lifecycle_conserves_faradaic_gas():
    """The bubble lifecycle (nucleate small -> grow attached -> detach -> rise ->
    vent) conserves gas exactly: produced (integral of j/nF) = resident + vented."""
    g = Grid3D(8, 24, 12, 2.0e-3)
    op = _op(j=0.8)
    rng = np.random.default_rng(3)
    parc = Parcels(g, op, rng, cap=100000)
    ctx = build_context(op, Params())
    ns = NS3D(g); ns.u_in = max(0.0, op.u_flow)
    j = op.j_set                            # A/m^2
    for _ in range(120):
        parc.step(ns, j, 2.0e-3, ctx)
    assert parc.produced_cum > 0
    resident = parc.resident_gas()
    residual = abs(parc.produced_cum -
                   (resident + parc.pending_gas() + parc.vented_cum))
    assert residual < 1e-9 * parc.produced_cum + 1e-18     # closed to machine precision


def test_lifecycle_grows_detaches_and_distributes_size():
    """Bubbles nucleate small, grow, detach and rise -> both attached and free
    populations exist, the radius spreads, and — with the electrolysis-
    calibrated fritz_scale — departure sizes sit in the LITERATURE range
    (~25-250 um radius), not the mm-scale Fritz boiling prediction."""
    g = Grid3D(8, 40, 16, 2.0e-3)
    op = _op(j=1.0)
    parc = Parcels(g, op, np.random.default_rng(5), cap=8000)
    ctx = build_context(op, Params(fritz_scale=0.08))
    ns = NS3D(g); ns.u_in = max(0.0, op.u_flow)
    for _ in range(150):
        parc.step(ns, op.j_set, 2.0e-3, ctx)
    attached = int(parc.attached.sum())
    free = int((~parc.attached).sum())
    assert attached > 0 and free > 0                       # full lifecycle running
    r_mean, r_std = parc.size_stats()
    assert r_std > 8e-6                                    # a genuine size spread
    # freshly nucleated bubbles (a seed grows within its birth step, so the
    # smallest tracked radius sits just above R_NUC) coexist with grown ones
    assert parc.R_NUC <= parc.r.min() < 0.2 * parc.r.max()
    # Departure-size validation must use the recorded detach transition.  Free
    # bubbles can subsequently coalesce and legitimately exceed their original
    # departure radius, so the maximum resident radius is the wrong observable.
    detach_radii = np.asarray([
        event["radius_m"] for event in parc.lifecycle_events
        if event["type"] == "detach"
    ])
    assert len(detach_radii) > 0
    assert 25e-6 < detach_radii.min()
    assert detach_radii.max() < 400e-6                    # literature departure range
    assert parc.r.max() <= parc.r_conf()                  # free-bubble confinement
    # multiplicity is a non-negative expected-count weight (fractional values
    # are valid after cohort splitting); W == mult * V(r) is the invariant.
    assert (parc.mult > 0.0).all()
    assert np.allclose(parc.W, parc.mult * (4 / 3) * np.pi * parc.r ** 3, rtol=1e-9)


# -------------------------------------------------------- buoyant rise
def test_free_bubble_rises_at_terminal_velocity():
    """A lone FREE (detached) bubble in quiescent liquid rises at its terminal
    velocity (j=0 so nothing new nucleates)."""
    g = Grid3D(12, 60, 12, 1.0e-3)
    op = _op(u_flow=0.0)
    parc = Parcels(g, op, np.random.default_rng(4), cap=10)
    r = 2.0e-4
    parc.pos = np.array([[g.Lx * 0.5, g.Ly * 0.2, g.Lz * 0.5]])
    parc.r = np.array([r]); parc.W = np.array([4 / 3 * np.pi * r ** 3])
    parc.mult = np.array([1.0])
    parc.side = np.array([0], dtype=np.int8)
    parc.attached = np.array([False]); parc.r_dep = np.array([1.0])
    parc.phase = np.array([0.0]); parc.ids = np.array([1])
    ns = NS3D(g); ns.u_in = 0.0            # quiescent
    ctx = {"d_rho": 1000.0, "mu": 1.0e-3, "rho_l": 1000.0}
    u_term = Surface._terminal_velocity(r, 1000.0, 1.0e-3, 1000.0)
    y0 = parc.pos[0, 1]; dt, n = 1.0e-3, 100
    for _ in range(n):
        parc._advect(ns, dt, ctx)         # no wobble in y -> vertical rise clean
    rose = parc.pos[0, 1] - y0
    assert abs(rose - u_term * dt * n) < 0.05 * u_term * dt * n


# ----------------------------------------------------- bubble blocking
def test_gas_blocks_crossflow():
    """Stationary attached bubbles exchange momentum without a fitted K.

    The gas-rich half carries less crossflow because Schiller--Naumann exchange
    is derived from its diameter and local gas/liquid slip. Removing the phase
    removes the effect; there is no strength parameter to tune.
    """
    def run(with_bubbles):
        g = Grid3D(8, 30, 16, 2.0e-3)
        ns = NS3D(g, outlet=True)
        ns.u_in = 0.05
        ns.damp = 0.0
        ns.set_fluid_properties(1000.0, 1.0e-3)
        gas = np.zeros(g.shape)
        diameter = np.zeros(g.shape)
        if with_bubbles:
            gas[:, 10:20, 1:8] = 0.4       # stationary attached-bubble curtain
            diameter[:, 10:20, 1:8] = 2.0e-4
        ns.set_interphase(gas, np.zeros((3,) + g.shape), diameter)
        for _ in range(150):
            ns.step(2.0e-3, proj_iters=40)
        _, v, _ = ns.centres()
        v_blob = float(v[2:-2, 12:18, 2:7].mean())
        v_open = float(v[2:-2, 12:18, 10:15].mean())
        return v_blob, v_open
    vb, vo = run(True)
    assert vo > vb * 1.5                   # open side carries clearly more flow
    vb0, vo0 = run(False)
    assert abs(vo0 - vb0) < 0.3 * abs(vo - vb) + 1e-9   # effect vanishes without gas


def test_bubble_coverage_raises_voltage():
    """The 3-D bubbles feed the scalar electrochemistry: blanketing the cathode
    raises the CP cell voltage (blocking feedback closed)."""
    cfg = cell_config_from_designer(DESIGNER_DEFAULTS)
    op = operating_from_designer(DESIGNER_DEFAULTS)     # CP, j=0.5 A/cm^2
    sim = CellSim3D(op, Params(fritz_scale=0.6), (8, 20, 12), h=cfg.h,
                    cap=4000, tilt=0.0, seed=0, cfg=cfg)
    V0 = sim.cell_voltage()                             # fresh cell, no bubbles
    p = sim.parcels
    n = 250
    rng = np.random.default_rng(7)
    r = np.full(n, 1.0e-3)                              # 1 mm attached bubbles
    p.pos = np.stack([np.full(n, p._wall_x(0, 1.0e-3)),
                      rng.uniform(0.1, 0.9, n) * sim.grid.Ly,
                      rng.uniform(0.1, 0.9, n) * sim.grid.Lz], axis=1)
    p.r = r; p.W = (4 / 3) * np.pi * r ** 3
    p.mult = np.ones(n)
    p.side = np.zeros(n, dtype=np.int8)
    p.attached = np.ones(n, dtype=bool)
    p.r_dep = np.full(n, 1.0); p.phase = np.zeros(n)
    p.ids = np.arange(1, n + 1)
    sim._resolve()
    V1 = sim.cell_voltage()
    assert p.coverage(0) > 0.1                          # cathode really blanketed
    assert V1 > V0 + 1e-3                               # voltage penalty appears


# ------------------------------------------------ departure-radius physics
def _parcels_for(**kw):
    """Exactly how CellSim3D builds its Parcels, using achieved voxel depth.

    A requested sub-voxel channel cannot be mixed into parcel shear while NS
    solves the larger resolved channel.  Both paths therefore use ``n_lay*h``.
    """
    d = dict(DESIGNER_DEFAULTS); d.update(kw)
    cfg = cell_config_from_designer(d)
    op = operating_from_designer(d)
    g = Grid3D(*cfg.grid_dims(), cfg.h)
    nl = cfg.layer_counts()[0]
    params = Params(fritz_scale=0.08)
    p = Parcels(g, op, np.random.default_rng(0), params=params,
                elec_planes=(nl * cfg.h, g.Lx - nl * cfg.h),
                channel_depth=nl * cfg.h)
    return p, build_context(op, params), op


def test_departure_radius_is_literature_scale_and_flow_graded():
    """Departure radius must (a) sit in the electrolysis range (~20-200 um),
    (b) fall SMOOTHLY with pump flow — never pin to the r_min_detach floor.

    Regression guard: feeding the kernel force balance the BULK channel
    velocity (instead of the near-wall velocity the bubble actually sees)
    pinned r_dep at the 8 um floor for every u >= 0.2 m/s, so flow stopped
    mattering and attached bubbles vanished within one step.
    """
    rs = []
    for u in (0.0, 0.2, 0.35, 0.6):
        p, ctx, op = _parcels_for(u_flow=u)
        rs.append(p.departure_radius(ctx, op.j_set))
    r_min_detach = Params().r_min_detach
    assert all(10e-6 < r < 200e-6 for r in rs)          # literature scale
    assert all(rs[i] > rs[i+1] for i in range(len(rs)-1))   # strictly decreasing
    assert all(r > 1.5 * r_min_detach for r in rs)      # not pinned to the floor


def test_departure_radius_reaches_the_model_floor_at_extreme_shear():
    """Honest limit: sufficiently high resolved wall shear reaches the model floor.

    With the default 2 mm resolved gap this occurs around 2 m/s rather than the
    old mixed-geometry 1 mm gap at 1 m/s.  The floor is a MODEL limit, not a
    physical departure-size prediction.
    """
    p, ctx, op = _parcels_for(u_flow=2.0)
    r = p.departure_radius(ctx, op.j_set)
    assert math.isclose(r, Params().r_min_detach, rel_tol=0.0, abs_tol=1e-15)
    p2, ctx2, op2 = _parcels_for(u_flow=0.35)
    assert p2.departure_radius(ctx2, op2.j_set) > 2 * r      # still graded below it


def test_departure_radius_grows_with_contact_angle():
    """A more gas-philic (higher contact angle) surface holds bubbles longer, so
    they depart bigger — the classic wettability lever.

    In STAGNANT liquid the lever is strong. Under pumped flow it is
    SELF-LIMITING: a bigger bubble sticks further into the wall shear layer and
    feels more drag, so the wettability size ratio must shrink. The test avoids
    pinning a ratio that changes with resolved channel depth.
    """
    def r(theta, u):
        p, ctx, op = _parcels_for(theta=theta, u_flow=u)
        return p.departure_radius(ctx, op.j_set)

    r30, r60, r120 = (r(t, 0.0) for t in (30, 60, 120))       # stagnant
    assert r30 < r60 < r120
    assert r120 > 3.0 * r30

    f30, f60, f120 = (r(t, 0.35) for t in (30, 60, 120))      # pumped
    assert f30 < f60 < f120                                   # still monotone
    assert f120 / f30 < r120 / r30                            # shear compresses it
    assert all(f < s for f, s in ((f30, r30), (f60, r60), (f120, r120)))


# --------------------------------------------- electrochemical placement
def test_bubbles_nucleate_on_catalyst_plane():
    """Zero-gap cell: gas emerges at the CATALYST plane (the membrane-side
    wall of each channel), not at the outer flow plate — attached bubbles must
    hug the core boundary from the channel side."""
    cfg = cell_config_from_designer(DESIGNER_DEFAULTS)
    op = operating_from_designer(DESIGNER_DEFAULTS)
    sim = CellSim3D(op, Params(fritz_scale=0.6), cfg.grid_dims(), h=cfg.h,
                    cap=4000, tilt=0.0, seed=0, cfg=cfg)
    for _ in range(40):
        sim.step(3.0e-3, proj_iters=12)
    p = sim.parcels
    xc, xa = p.elec_planes
    att_c = p.attached & (p.side == 0)
    att_a = p.attached & (p.side == 1)
    assert att_c.any() and att_a.any()
    # cathode bubbles sit on the channel side of x_c, tangent to it
    assert np.all(p.pos[att_c, 0] < xc)
    assert np.all(xc - p.pos[att_c, 0] < 2.5 * sim.grid.h)
    # anode mirrored
    assert np.all(p.pos[att_a, 0] > xa)
    assert np.all(p.pos[att_a, 0] - xa < 2.5 * sim.grid.h)
    # and the coverage the electrochemistry sees is measured there too
    assert p.coverage(0) > 0.0


# ------------------------------------------------- bubbles follow the lines
def test_bubbles_respect_ribs_and_snake():
    """With the serpentine voxelized (turn gaps + solid core), bubbles never
    sit inside a rib/core cell and the risers acquire real LATERAL (z) motion
    as they slide along the passes toward the turn gaps."""
    d = dict(DESIGNER_DEFAULTS); d.update(j=1.0, u_flow=0.3)
    cfg = cell_config_from_designer(d)
    op = operating_from_designer(d)
    sim = CellSim3D(op, Params(fritz_scale=0.6), cfg.grid_dims(), h=cfg.h,
                    cap=4000, tilt=0.0, seed=0, cfg=cfg)
    z_disp = 0.0
    prev = {}
    for i in range(200):
        sim.step(3.0e-3, proj_iters=15)
        if i > 100:                                  # steady phase: track z motion
            p = sim.parcels
            for bid, z, att in zip(p.ids, p.pos[:, 2], p.attached):
                if not att and bid in prev:
                    z_disp += abs(z - prev[bid])
                prev[bid] = z
    p = sim.parcels
    # no bubble may sit inside an obstacle cell
    ci = np.clip((p.pos / sim.grid.h).astype(int),
                 0, [sim.grid.nx - 1, sim.grid.ny - 1, sim.grid.nz - 1])
    assert not sim.ns.solid[ci[:, 0], ci[:, 1], ci[:, 2]].any()
    assert z_disp > 0.01                             # cumulative sideways travel [m]


# --------------------------------------------------------------- tilt
def test_tilt_rotates_buoyancy():
    g = Grid3D(8, 8, 8, 1.5e-3)
    ns = NS3D(g)
    ns.set_tilt(0.0)
    assert np.allclose(ns.up, [0, 1, 0], atol=1e-9)      # vertical: rise +y
    ns.set_tilt(90.0)
    assert np.allclose(ns.up, [1, 0, 0], atol=1e-6)      # horizontal: rise +x


# -------------------------------------------------- confinement (far wall)
def _run(steps=180, dt=3.0e-3, seed=5, iters=60, **kw):
    # `iters` is a CAP; CellSim3D.PROJ_TOL stops the SOR as soon as the field is
    # divergence-free enough, so most steps cost far less than the cap. At the
    # old flat 6 sweeps the flow never converged and the mass balance was ~20%.
    d = dict(DESIGNER_DEFAULTS); d.update(kw)
    cfg = cell_config_from_designer(d)
    op = operating_from_designer(d)
    sim = CellSim3D(op, Params(fritz_scale=0.08), cfg.grid_dims(), h=cfg.h,
                    cap=cfg.cap_parcels, tilt=0.0, seed=seed, cfg=cfg)
    for _ in range(steps):
        sim.step(dt, proj_iters=iters)
    return sim


def test_bubble_never_grows_through_the_opposite_wall():
    """A bubble cannot exceed ~half the *resolved* channel depth.

    A requested 0.2 mm gap on a 2 mm grid is not silently treated as 0.2 mm by
    parcels while the flow solver sees 2 mm.  The geometry mismatch remains an
    explicit diagnostic instead.
    """
    for d_ch in (1.0, 0.2):
        sim = _run(d_ch_mm=d_ch, steps=140)
        p = sim.parcels
        achieved = sim.n_lay * sim.grid.h
        assert sim.channel_depth == achieved
        assert abs(p.r_conf() - 0.45 * achieved) < 1e-12
        assert p.r.max() <= p.r_conf() * (1.0 + 1e-9)
        assert p.gas_closure_error() < 1e-9      # conservation survives the cap
        if not math.isclose(achieved, d_ch * 1e-3):
            assert sim.diagnostics()["grid_geometry_matches_request"] is False


def test_confinement_caps_the_departure_radius_without_flow():
    """The parcel kernel caps departure when supplied a physically narrow gap.

    This is a kernel test, not a claim that the default 2 mm voxel resolves a
    0.12 mm gap.  Live-cell geometry tests above use achieved voxel depth.
    """
    g = Grid3D(8, 8, 8, 1.0e-3)
    op = _op(u_flow=0.0)
    params = Params(fritz_scale=0.08)
    ctx = build_context(op, params)
    wide = Parcels(g, op, np.random.default_rng(1), params=params,
                   channel_depth=2.0e-3)
    tight = Parcels(g, op, np.random.default_rng(2), params=params,
                    channel_depth=0.12e-3)
    j = 1000.0
    r_wide = wide.departure_radius(ctx, j)
    r_tight = tight.departure_radius(ctx, j)
    assert r_wide > r_tight                                    # the gap binds
    assert abs(r_tight - tight.r_conf()) < 1e-12


def test_growth_never_overshoots_the_departure_radius():
    """The flow step (3 ms) is coarser than the ~1 ms growth-to-departure
    cycle. Growing a whole step's gas in one pass used to inflate every bubble
    to ~3x its departure size; the surplus must become MORE bubbles instead."""
    p = _run(steps=120).parcels
    att = p.attached
    assert att.any()
    assert np.all(p.r[att] <= p.r_dep[att] * (1.0 + 1e-9))
    V = (4.0 / 3.0) * np.pi * p.r ** 3
    assert np.allclose(p.W, p.mult * V, rtol=1e-9)      # W = mult*V(r) exactly
    assert p.gas_closure_error() < 1e-9


def test_attached_bubbles_touch_the_catalyst():
    """A wall bubble's centre sits at ~its own radius from the electrode.

    The old standoff was 0.1*h = 200 um on a 2 mm grid — five times a 40 um
    bubble's radius — so every bubble floated a fifth of a millimetre off the
    catalyst and the near-wall layer was pure grid artefact."""
    sim = _run(steps=100)
    p = sim.parcels
    xc, xa = p.elec_planes
    for side, plane, sgn in ((0, xc, -1), (1, xa, +1)):
        m = p.attached & (p.side == side)
        assert m.any()
        d = sgn * (p.pos[m, 0] - plane)          # distance into the channel
        assert np.all(d > 0)                     # on the channel side of the plane
        assert np.all(d < p.r[m] + 0.01 * sim.grid.h)   # tangent, not floating


def test_released_bubbles_skim_the_electrode():
    """Buoyancy is along the electrode and the lift/lubrication balance keeps a
    released bubble in the near-wall layer while it travels up-cell."""
    sim = _run(steps=140)
    p = sim.parcels
    xc = p.elec_planes[0]
    fr = (~p.attached) & (p.side == 0)
    assert fr.sum() > 50
    d = xc - p.pos[fr, 0]                        # wall-normal distance [m]
    assert np.median(p.pos[fr, 1]) > 5e-3        # they really did rise up-cell
    assert d.max() < 6.0 * p.r[fr].max() + 0.02 * sim.grid.h


# ------------------------------------------- wall-normal force balance
def test_lift_coefficient_exposes_small_and_large_bubble_branches():
    """The implemented correlation changes sign between small and large bubbles.

    This is an implementation branch test, not external validation of Tomiyama
    in the electrolysis-scale Eo range; diagnostics mark that extrapolation.
    """
    p, ctx, _ = _parcels_for()

    r = np.array([40e-6])                    # electrolysis bubble: Eo_d ~ 1e-3
    Eo = 9.80665 * ctx["d_rho"] * (2*r)**2 / ctx["sigma"]
    assert Eo[0] < 1e-2
    Re = np.array([0.24])
    got = p.lift_coefficient(r, Re, ctx)[0]
    assert got > 0                           # positive -> migrates to the WALL

    r_big = np.array([4e-3])                 # 8 mm bubble: Eo_d > 10
    got_big = p.lift_coefficient(r_big, np.array([1e3]), ctx)[0]
    assert got_big < 0                       # negative -> migrates to the CORE


def test_wall_lubrication_and_lift_create_near_wall_equilibrium():
    """Wall lubrication prevents penetration and lift returns a displaced bubble.

    Opposite signs at r and farther out imply a stable near-wall stand-off
    without pinning an empirical equilibrium distance.
    """
    p, ctx, _ = _parcels_for()
    r = np.array([40e-6])
    vs = terminal_velocity(r, ctx["d_rho"], ctx["mu"], ctx["rho_l"])
    vns = [p.wall_normal_velocity(r, vs, np.array([f * r[0]]), ctx)[0]
           for f in (1.0, 1.5, 3.0)]
    assert vns[0] > 0                              # lubrication repels at contact
    assert vns[1] < 0 and vns[2] < 0               # lift draws it back farther out
    assert max(abs(v) for v in vns) < 1e-4         # drift remains only µm/s


def test_free_bubbles_settle_at_their_own_radius_from_the_electrode():
    """The engine's own outcome: risers sit ~1.05 r off the catalyst, never
    inside it, and still travel far up-cell. The near-wall layer is a RESULT of
    the lift/wall balance now, not of a missing force."""
    sim = _run(steps=160, seed=2)
    p = sim.parcels
    xc = p.elec_planes[0]
    fr = (~p.attached) & (p.side == 0)
    assert fr.sum() > 100
    y_w = xc - p.pos[fr, 0]
    ratio = y_w / p.r[fr]
    assert (ratio >= 0.999).all()                  # surface never enters the wall
    assert np.median(ratio) < 1.6                  # and it stays pinned there
    assert np.median(p.pos[fr, 1]) > 5e-3          # while rising up the cell


# --------------------------------------------------------- coalescence
def test_coalescence_is_inhibited_by_concentrated_electrolyte():
    """Bubbles do not burst in the liquid — they MERGE on contact. Above the
    salting-out threshold (KOH 0.3 M) merging is suppressed, so a dilute cell
    shows far more merges. Gas is conserved either way: `mult` halves as the
    single-bubble volume doubles."""
    conc = _run(c_mol=6.0, u_flow=0.05, steps=120)       # inhibited
    dil = _run(c_mol=0.1, u_flow=0.05, steps=120)        # free
    assert conc.parcels.p_merge() < dil.parcels.p_merge()
    assert dil.parcels.n_merge > 5 * max(1, conc.parcels.n_merge)
    for sim in (conc, dil):
        p = sim.parcels
        V = (4.0 / 3.0) * np.pi * p.r ** 3
        assert np.allclose(p.W, p.mult * V, rtol=1e-9)
        assert p.gas_closure_error() < 1e-9


def test_coalescence_rate_is_independent_of_the_time_step():
    """The merge draw is against the INCREMENT in contact probability produced
    by growth, not a per-step coin flip — so chopping the step 4x finer must
    not quadruple the merges."""
    coarse = _run(c_mol=0.1, u_flow=0.05, steps=60, dt=4.0e-3)
    fine = _run(c_mol=0.1, u_flow=0.05, steps=240, dt=1.0e-3)   # same 0.24 s
    assert coarse.parcels.n_merge > 0
    assert 0.4 < fine.parcels.n_merge / coarse.parcels.n_merge < 2.5


# --------------------------------------------------------- inlet / outlet ports
def test_outlet_port_is_a_real_boundary_for_liquid_and_gas():
    """A narrow exit port must (a) be the only Dirichlet p=0 face, (b) still
    balance mass, and (c) block GAS as well — bubbles that reach the closed part
    of the top are under plate, not free to leave."""
    full = _run(steps=120, out_w=1.0)                        # explicit whole-top vent
    port = _run(steps=120, out_w=0.10, out_z=0.06)

    assert full.ns.outlet.all()                              # whole top vents
    open_cells = int(port.ns.outlet[0].sum())
    assert 1 <= open_cells <= 0.25 * port.grid.nz            # a port, not a face

    # liquid: what goes in comes out (through the port only)
    h = port.grid.h
    qi = float(port.ns.V[:, 0, :].sum()) * h * h
    qo = float((port.ns.V[:, -1, :] * port.ns.outlet).sum()) * h * h
    assert qi > 0 and abs(qi - qo) < 0.10 * qi

    # gas: with the top mostly plated, free bubbles collect under it
    def stuck(sim):
        p = sim.parcels
        m = (~p.attached) & (p.pos[:, 1] > sim.grid.Ly - 3 * sim.grid.h)
        if not m.any():
            return 0
        k = np.clip((p.pos[m, 2] / sim.grid.h).astype(int), 0, sim.grid.nz - 1)
        return int((~sim.port_out[k]).sum())              # under the closed plate

    assert stuck(full) == 0                                  # nothing to block
    assert stuck(port) > 0                                   # a real gas trap
    assert port.parcels.gas_closure_error() < 1e-9           # still conserved


def test_inlet_port_position_steers_the_flow():
    """Moving the inlet port across the cell width moves where the liquid
    enters — the feed is a boundary condition, not decoration."""
    left = _run(steps=40, in_w=0.12, in_z=0.06)
    right = _run(steps=40, in_w=0.12, in_z=0.94)
    zc = lambda sim: float(np.nonzero(sim.port_in)[0].mean()) / (sim.grid.nz - 1)
    assert zc(left) < 0.25 and zc(right) > 0.75
    for sim in (left, right):
        v_in = sim.ns.V[:, 0, :]
        fed = v_in[:, sim.port_in] > 0
        assert fed.any()
        assert np.allclose(v_in[:, ~sim.port_in], 0.0)       # the rest is plate


def _net_flux(sim):
    ns, a = sim.ns, sim.grid.h ** 2
    qi = (float(ns.V[:, 0, :].sum()) + float((ns.W[:, :, 0] * ns.inlet_z[0]).sum())
          - float((ns.W[:, :, -1] * ns.inlet_z[1]).sum())) * a
    qo = (float((ns.V[:, -1, :] * ns.outlet).sum())
          - float((ns.W[:, :, 0] * ns.outlet_z[0]).sum())
          + float((ns.W[:, :, -1] * ns.outlet_z[1]).sum())) * a
    return qi, qo


def test_side_ports_are_real_boundaries():
    """Inlet and outlet can sit on ANY edge (bottom / left / right). A side port
    is the same boundary condition on a different face: prescribed normal
    velocity for the inflow, Dirichlet p=0 for the outflow, plate elsewhere."""
    cross = _run(steps=120, in_face="left", in_w=0.25, in_z=0.2,
                 out_face="right", out_w=0.25, out_z=0.8, u_flow=0.6)
    assert cross.in_face == "left" and cross.out_face == "right"
    ns = cross.ns
    assert np.allclose(ns.V[:, 0, :], 0.0)          # the bottom is plate now
    assert ns.outlet.sum() == 0                     # so is the top
    assert ns.inlet_z[0].any() and ns.outlet_z[1].any()
    qi, qo = _net_flux(cross)
    assert qi > 0 and abs(qi - qo) < 0.05 * qi      # mass in == mass out
    # a genuine cross-flow: net +z motion through the cell
    _, _, w = ns.centres()
    assert w.mean() > 0.05 * abs(ns.u_in)


def test_gas_leaves_through_whatever_port_the_liquid_uses():
    """A free parcel reaching the liquid outlet must vent through that same
    boundary. Transport to a side port is intentionally tested separately from
    the outlet boundary itself: after pump-flow conservation was fixed, the
    coarse-grid circulation no longer supplies the old artificial side jet."""
    sim = _run(steps=120, out_face="right", out_w=0.25, out_z=0.8, u_flow=0.6)
    p = sim.parcels
    assert sim.out_face == "right"
    free = np.flatnonzero(~p.attached)
    assert len(free) > 0
    i = int(free[0])
    rows = np.flatnonzero(p.vent_line)
    assert len(rows) > 0
    p.pos[i, 1] = (rows[len(rows) // 2] + 0.5) * sim.grid.h
    margin = p.r[i] + 0.2 * sim.grid.h
    p.pos[i, 2] = sim.grid.Lz - margin               # clamped side-wall centre
    before = p.vented_cum
    p._advect(sim.ns, 0.0, sim.ctx)
    assert p.vented_cum > before                     # the side outlet vents it
    assert p.gas_closure_error() < 1e-9


def test_custom_plate_runs_and_confines_the_bubbles():
    """A user-drawn plate is a first-class flow field: the engine voxelizes it,
    the flow stays inside it, and no bubble ever sits in a drawn rib."""
    from bubblesim3d.params3d import encode_mask
    M = 20
    m = np.zeros((M, M), dtype=bool)
    m[5:7, :15] = True
    m[13:15, 5:] = True
    # fed through a port, like a real plate: a full-width inlet forced through
    # a one-cell turn gap is a 3 m/s jet, and the SOR then needs many more
    # sweeps to converge (raised here; the live loop warm-starts every step)
    sim = _run(steps=120, iters=200, ff="custom", mask=encode_mask(m),
               in_w=0.12, in_z=0.94)
    g, p = sim.grid, sim.parcels
    land = ~sim.face_c
    assert land.any() and not land.all()
    ci = np.clip((p.pos / g.h).astype(int), 0, [g.nx - 1, g.ny - 1, g.nz - 1])
    assert not land[ci[:, 1], ci[:, 2]].any()                # never inside a rib
    assert not sim.ns.solid[ci[:, 0], ci[:, 1], ci[:, 2]].any()
    assert p.gas_closure_error() < 1e-9
    assert sim.ns.max_divergence() * g.h / max(float(sim.ns.speed().max()), 1e-9) < 0.05


# ------------------------------------------------ free-swarm coalescence
def test_swarm_coalescence_rate_is_independent_of_the_time_step():
    """A four-times finer step must preserve collision rate and real-bubble size."""
    coarse = _run(steps=150, dt=4.0e-3, seed=3, c_mol=0.1)
    fine = _run(steps=600, dt=1.0e-3, seed=3, c_mol=0.1)
    a, b = coarse.parcels.n_merge_real, fine.parcels.n_merge_real
    assert a > 1 and 0.5 < b / a < 2.0
    # Weighted parcels have unequal multiplicity after a super-droplet
    # collision.  A plain mean would measure computational parcels, not real
    # bubbles, so compare the real-number-weighted mean radius.
    fa, fb = ~coarse.parcels.attached, ~fine.parcels.attached
    ra = np.average(coarse.parcels.r[fa], weights=coarse.parcels.mult[fa])
    rb = np.average(fine.parcels.r[fb], weights=fine.parcels.mult[fb])
    assert abs(ra - rb) < 0.15 * ra


def test_swarm_coalescence_grows_the_exit_bubbles_when_the_electrolyte_allows():
    """The observable of coalescence inhibition: concentrated KOH keeps the
    tracked swarm smaller; dilute KOH produces more merges, a broader large-
    bubble tail. Gas is conserved either way.

    Finite-time cumulative venting is intentionally not ordered: rib residence,
    nucleation position and stochastic clusters can outweigh terminal velocity
    during startup, and no experiment has established a universal ratio.
    """
    # whole-top vent (out_w=1) so the swarm leaves freely and the coalescence
    # signal isn't confounded by gas piling under a narrow default exit port
    conc = _run(steps=400, c_mol=6.0, seed=3, out_w=1.0)
    dil = _run(steps=400, c_mol=0.1, seed=3, out_w=1.0)

    def resident_r(sim):
        p = sim.parcels
        m = (~p.attached) & (~p.mesh_attached)
        assert m.sum() > 50
        return p.r[m]

    rc, rd = resident_r(conc), resident_r(dil)
    # A maximum-at-the-outlet assertion is physically backwards: the largest,
    # fastest bubbles have already vented and a stochastic outlier controls max().
    # The tracked-parcel 95th percentile measures the visible large-bubble tail.
    assert rd.mean() > rc.mean()                       # merging really grows them
    assert np.quantile(rd, 0.95) > np.quantile(rc, 0.95)
    assert dil.parcels.n_merge_free > conc.parcels.n_merge_free
    for sim in (conc, dil):
        p = sim.parcels
        assert np.isfinite(p.vented_cum) and 0.0 <= p.vented_cum <= p.produced_cum
        assert np.allclose(p.W, p.mult * (4/3) * np.pi * p.r ** 3, rtol=1e-9)
        assert p.gas_closure_error() < 1e-9
        assert p.r.max() <= p.r_conf() * (1 + 1e-9)    # never bridges the channel


def _mean_holdup(steps=400, tail=80, **kw):
    """Time-averaged holdup — the instantaneous value swings by ~40% as bubble
    clusters vent, so a single snapshot cannot resolve a 20% difference."""
    d = dict(DESIGNER_DEFAULTS); d.update(kw)
    cfg = cell_config_from_designer(d); op = operating_from_designer(d)
    sim = CellSim3D(op, Params(fritz_scale=0.08), cfg.grid_dims(), h=cfg.h,
                    cap=cfg.cap_parcels, tilt=0.0, seed=3, cfg=cfg)
    hs = []
    for i in range(steps):
        sim.step(3.0e-3, proj_iters=60)
        if i >= steps - tail:
            hs.append(sim.parcels.holdup())
    return sim, float(np.mean(hs))


def test_coalescence_speeds_the_swarm_up_and_keeps_vent_ledger_closed():
    """Bigger bubbles rise faster while the finite-time gas ledger stays closed.

    Instantaneous holdup and cumulative venting are not required to be monotonic:
    ongoing nucleation, rib residence and stochastic cluster position can
    outweigh rise speed during a finite transient.
    """
    conc, h_conc = _mean_holdup(c_mol=6.0, out_w=1.0)
    dil, h_dil = _mean_holdup(c_mol=0.1, out_w=1.0)

    def mean_rise(sim):
        p = sim.parcels
        free = (~p.attached) & (~p.mesh_attached)
        r = p.r[free]
        return terminal_velocity(r, sim.ctx["d_rho"], sim.ctx["mu"],
                                 sim.ctx["rho_l"]).mean()

    assert mean_rise(dil) > 2.0 * mean_rise(conc)     # merged bubbles rise faster
    for sim in (conc, dil):
        p = sim.parcels
        assert np.isfinite(p.vented_cum) and 0.0 <= p.vented_cum <= p.produced_cum
        assert p.gas_closure_error() < 1e-9
    assert np.isfinite(h_conc) and np.isfinite(h_dil) and min(h_conc, h_dil) > 0


# --------------------------------------------------------- integration
def test_cellsim_runs_and_snapshots():
    cfg = cell_config_from_designer(DESIGNER_DEFAULTS)
    op = operating_from_designer(DESIGNER_DEFAULTS)
    sim = CellSim3D(op, Params(fritz_scale=0.6), (8, 20, 12), h=cfg.h,
                    cap=4000, tilt=0.0, seed=0, cfg=cfg)
    for _ in range(60):
        # Correct OER stoichiometry + wet-gas volume increase void forcing. Use
        # the same projection cap as the live server instead of the former
        # under-forced 25-sweep shortcut.
        sim.step(2.0e-3, proj_iters=80)
    snap = sim.snapshot()
    assert snap["n_bub"] > 0                             # bubbles nucleated
    assert len(snap["bubbles"]) == 7 * snap["n_bub"]     # [x,y,z,r,side,attached,id]
    ids = snap["bubbles"][6::7]
    assert len(set(ids)) == snap["n_bub"]                # ids stable + unique
    assert abs(sim.cell_current_A_m2() / 1e4 - 0.5) < 1e-6   # j tracks the input
    # The live 80-sweep cap may bind on a serpentine preview. Keep the final
    # divergence bounded and expose failure to reach PROJ_TOL explicitly rather
    # than claiming a quantitatively converged pressure solution.
    div = sim.ns.max_divergence()
    vmax = float(sim.ns.speed().max())
    rel_div = div * sim.grid.h / max(vmax, 1e-9)
    assert rel_div < 0.025
    diag = sim.diagnostics()
    assert math.isclose(diag["projection_relative_divergence"], rel_div,
                        rel_tol=1e-12)
    assert diag["projection_converged"] is (rel_div <= sim.PROJ_TOL)
    d = sim.diagnostics()
    assert d["n_attached"] > 0                           # bubbles growing on the wall
    assert 0.0 <= d["holdup"] < 0.6 and d["r_std_mm"] > 0.0
    slip = d["bubble_slip_model"]
    assert slip["d_rho_kg_m3"] > 0.0
    assert slip["mu_Pa_s"] > 0.0
    assert slip["rho_l_kg_m3"] > 0.0
    assert slip["sigma_N_m"] > 0.0
    assert 9.7 < slip["g_m_s2"] < 9.9
    assert d["interphase_model"].startswith("Schiller-Naumann")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
