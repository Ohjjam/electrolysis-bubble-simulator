"""Flow-channel cell-design solver (model="channel").

A real flow field: electrolyte runs along a CHANNEL across the electrode
(serpentine / parallel / straight). Gas made under each segment is carried
DOWNSTREAM, so the void fraction -- and the coverage/bottleneck -- BUILDS UP
along the path: worst near the outlet and on long serpentine runs, eased by
higher flow or shorter (parallel) channels. You design the channel layout and
see where it clogs, like a CFD surface field.

Along-path two-phase accumulation:
    Vgas(s)/Q = (RT/P)/(zF u d_ch) * integral_0^s j ds   (cumulative gas / liquid flow)
    eps(s) = (Vgas/Q)/(1 + Vgas/Q),   theta(s) = min(0.92, eps)
    j(s) redistributes at the common potential: j ~ (1 - theta), mean pinned to
    the scalar operating current (from the two-electrode balance at mean theta).

Honest scope: a 1-D along-the-channel balance mapped onto the 2-D path, NOT a
Navier-Stokes/VOF CFD -- it captures downstream gas build-up and how the LAYOUT
(serpentine vs parallel, number of passes, flow) moves the bottleneck, not
vortices or exact menisci. numpy only.
"""
import numpy as np

from .base import ElectroState
from .zerod import ZeroDTwoElectrodeSolver
from ..constants import F, R_GAS
from ..properties import GAS
from ..kernel.meshlayer import operating_mesh_factors, path_mask

D_CHAN = 1.0e-3        # legacy channel depth [m] (op.chan_depth_mm overrides)
EPS_FILM = 0.70        # slug/annular flow transition void: below this a wall
                       # liquid film keeps the ionic path wet (zero-gap cell),
                       # so only the void EXCESS above it starves the path.
                       # ~0.7 is the packed-bubble/churn transition (literature
                       # anchor, fixed a priori -- not fitted).


class _Stub:
    def __init__(self, theta, eps):
        self._t, self._e = theta, eps
    def coverage(self):
        return self._t
    def void_fraction(self):
        return self._e


def channel_polylines(ctype, n_pass):
    """Flow-path polylines in [0,1]^2 (x = width, y = height); inlet first point."""
    if ctype == "straight":
        return [[(0.5, 0.04), (0.5, 0.96)]]
    if ctype == "parallel":
        return [[((i + 0.5) / n_pass, 0.04), ((i + 0.5) / n_pass, 0.96)]
                for i in range(n_pass)]
    wp = []                                              # serpentine snake
    for i in range(n_pass):
        y = (i + 0.5) / n_pass
        xs = (0.06, 0.94) if i % 2 == 0 else (0.94, 0.06)
        wp += [(xs[0], y), (xs[1], y)]
    return [wp]


def _resample(wp, m):
    pts = np.array(wp, dtype=float)
    seg = np.sqrt(((pts[1:] - pts[:-1]) ** 2).sum(1))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    s = np.linspace(0.0, cum[-1], m)
    return np.interp(s, cum, pts[:, 0]), np.interp(s, cum, pts[:, 1])


class ChannelSolver:
    """See module docstring. Returns a coloured segment list for the 2-D path."""

    def __init__(self, m_per=12):
        self.m_per = m_per

    def solve(self, op, context, surfaces) -> ElectroState:
        ctype = getattr(op, "channel_type", "serpentine")
        n_pass = max(1, int(getattr(op, "n_pass", 4)))
        W = max(0.01, getattr(op, "cell_width_cm", 5.0) * 1e-2)
        H = max(0.01, getattr(op, "face_height_cm", 10.0) * 1e-2)
        # This channel/mesh path represents the ANODE interlayer. Use OER's z=4
        # explicitly; context.z_primary defaults to HER in the full-cell object
        # and previously doubled the anode gas source. A tiny numerical floor is
        # used only to evaluate the zero-flow limiting state (holdup saturates).
        u = max(1.0e-6, op.u_flow)
        T, z = op.T, GAS["OER"]["z"]

        custom = getattr(op, "custom_path", None)
        if custom and len(custom) >= 2:                  # user-drawn flow path (design tool)
            pts = [(max(0.0, min(1.0, float(p[0]))), max(0.0, min(1.0, float(p[1])))) for p in custom]
            L_geom = max(1e-3, sum((((pts[i + 1][0] - pts[i][0]) * W) ** 2
                                    + ((pts[i + 1][1] - pts[i][1]) * H) ** 2) ** 0.5
                                   for i in range(len(pts) - 1)))
            m = max(8, min(140, int(round(L_geom / 0.0035))))   # ~3.5 mm resolution
            polys, ctype = [pts], "custom"
        elif ctype == "serpentine":
            L_geom, m = n_pass * W + H, max(8, self.m_per * n_pass)   # runs (W each) + vertical bends (H)
            polys = channel_polylines("serpentine", n_pass)
        else:                                            # straight / parallel: one short pass of height H
            L_geom, m = H, max(8, self.m_per)
            polys = channel_polylines(ctype, n_pass)
        requested_length = max(0.0, float(getattr(op, "flow_length_cm", 0.0))) * 1e-2
        Lscale = requested_length if requested_length > 0.0 else L_geom
        ds = Lscale / (m - 1)
        d_ch = max(0.05, float(getattr(op, "chan_depth_mm", 1.0))) * 1e-3
        # High-fidelity gas is reported wet, so the evolved dry gas expands
        # against its partial pressure rather than the total pressure.
        p_gas = float(context.get("p_dry_gas", op.P))
        KA = (R_GAS * T / p_gas) / (z * F * u * d_ch)    # Vgas/Q per (A/m) of cumulative j

        # --- bubble-management mesh interlayer (kernel.meshlayer) --------------
        # Mesh physics is evaluated from the calculated departure-bubble size,
        # opening geometry, electrode/mesh water contact angles, and the solid
        # volume occupying the channel.  No L_ref or empirical wick multiplier.
        mesh_cover = min(1.0, max(0.0, float(getattr(op, "mesh_cover", 0.0))))
        mf = operating_mesh_factors(op, context, max(1e-9, float(getattr(op, "j_set", 0.0))))
        mesh_on = (mf["fits"] and float(getattr(op, "mesh_hole_mm", 0.0)) > 0.0
                   and float(getattr(op, "mesh_t_mm", 0.0)) > 0.0 and mesh_cover > 0.0)
        mmask = (np.array(path_mask(m, mesh_cover, getattr(op, "mesh_pos", "outlet")))
                 if mesh_on else np.zeros(m, dtype=bool))
        # mesh acts LOCALLY: gas volume is conserved along the channel (it all
        # exits at the outlet), but under the mesh the bubbles ride the fast
        # core flow (slip up, slugs broken) -> the local HOLDUP that blankets
        # the wall drops. So the factor multiplies eps in covered segments,
        # never the production integral (that would delete gas downstream).
        # --- channel ORIENTATION vs gravity -----------------------------------
        # The cell stands in a vertical plane (y = height, gravity points down).
        # Where the drawn path runs UP, bubbles rise out of the channel WITH the
        # flow (self-purging -> less gas retained); where it runs DOWN, gas is
        # trapped against the flow (more retained); horizontal runs are between.
        # So the LAYOUT's geometry matters: a bottom->top (upward) flow path
        # clogs less than a downward or horizontal one. Retention stays >0, so
        # accumulation is still monotonic downstream (outlet >= inlet holds).
        xr0, yr0 = _resample(polys[0], m)
        dxp = np.diff(xr0) * W
        dyp = np.diff(yr0) * H
        vfrac = dyp / (np.sqrt(dxp * dxp + dyp * dyp) + 1e-12)        # +1 up .. -1 down
        ret = np.concatenate([[1.0], np.clip(1.0 - 0.5 * vfrac, 0.4, 1.6)])
        up_frac = float((vfrac > 0.3).mean())                        # share of path running upward

        base = ZeroDTwoElectrodeSolver(n_outer=40, n_inner=28)
        eps0 = surfaces[0].void_fraction()
        # channel_void_ohmic: let the path-mean bulk void raise the electrolyte
        # resistance in the scalar solve (real at gas-choking flow ratios).
        # Off (default) keeps the legacy behaviour: the stub carries eps0 only.
        void_ohmic = bool(getattr(op, "channel_void_ohmic", False))
        vfrac_ohm = min(1.0, max(0.0, float(getattr(op, "void_ohmic_frac", 1.0))))
        eps_mean = eps0
        theta = np.zeros(m)
        eps = np.zeros(m)
        st = None
        for _ in range(5):                               # theta <-> reaction <-> scalar
            st = base.solve(op, context, [_Stub(float(theta.mean()), eps_mean)])
            if mesh_on:
                # CP water limitation or CA operation can make delivered j differ
                # from the request; use the current that was actually solved.
                mf = operating_mesh_factors(op, context, st.j)
            hold_mesh = np.where(mmask, mf["retention_factor"], 1.0)
            th_amp = 0.9 * np.where(mmask, mf["theta_factor"], 1.0)
            omt = 1.0 - theta
            jprof = st.j * omt / max(1e-6, float(omt.mean()))     # redistribute at common eta
            cumj = np.cumsum(jprof * ret) * ds           # integral j ds [A/m], weighted by path orientation
            V = KA * cumj
            eps = (V / (1.0 + V)) * hold_mesh            # local wall holdup (mesh relieves in place)
            # coverage closure: surface coverage is a SATURATING function of the
            # bulk void, not theta=eps (bulk gas fraction != electrode blanketing).
            # theta = theta_max (1 - exp(-k eps)) keeps the downstream monotonicity
            # while decoupling coverage magnitude from void (Vogt & Balzer 2005).
            theta_bubble = th_amp * (1.0 - np.exp(-3.0 * eps))
            # Do not infer catalyst-area blockage from mesh solid volume.  That
            # needs spacing/compression/contact data that the geometry tab does
            # not contain.  Obstruction remains a hydraulic diagnostic.
            theta = np.minimum(0.92, theta_bubble)
            if void_ohmic:
                # threshold-excess void: the wall film survives to ~EPS_FILM,
                # beyond it the two-phase flow goes slug/annular and the liquid
                # supply (ionic path through the porous electrode) starves.
                eps_x = np.clip((eps - EPS_FILM) / (1.0 - EPS_FILM), 0.0, 1.0)
                eps_mean = vfrac_ohm * float(eps_x.mean())

        # local "voltage efficiency" = E_rev / (E_rev + overpotentials), where the
        # coverage penalty eta_cov = (RT/aF) ln(1/(1-theta)) grows at the bottleneck.
        # So the colour MEANS: blue = high % of the applied voltage usefully used,
        # red = low % (lost to the gas-blanketing bottleneck).
        ov = st.overpotentials
        E_rev = ov.get("E_rev", 1.23)
        eta_fixed = ov.get("eta_act", 0.0) + ov.get("eta_conc", 0.0) + ov.get("eta_ohmic", 0.0)
        fRT = R_GAS * T / F
        eta_cov = (fRT / 0.5) * np.log(1.0 / (1.0 - np.minimum(0.95, theta)))
        eff = E_rev / (E_rev + eta_fixed + eta_cov)        # 0..1, falls at the bottleneck

        # map the along-path profile onto the polyline(s) as coloured segments
        segs = []
        for poly in polys:
            xs, ys = _resample(poly, m)
            for i in range(m - 1):
                segs.append([round(float(xs[i]), 4), round(float(ys[i]), 4),
                             round(float(xs[i + 1]), 4), round(float(ys[i + 1]), 4),
                             round(float(jprof[i]), 1), round(float(eps[i]), 4),
                             round(float(theta[i]), 4), round(float(eff[i]), 4)])

        i_bn = int(np.argmax(theta))                     # worst (bottleneck) point
        ov = dict(st.overpotentials)
        ov["theta_out"] = float(theta[-1])
        ov["theta_in"] = float(theta[0])
        fields = dict(st.fields)
        fields.update({
            "segments": segs, "ctype": ctype, "n_pass": n_pass,
            "flow_length_m": float(Lscale),
            "flow_length_geometry_m": float(L_geom),
            "flow_length_source": ("designer" if requested_length > 0.0 else "layout"),
            "theta_in": float(theta[0]), "theta_out": float(theta[-1]),
            "eps_out": float(eps[-1]), "bn_frac": float(i_bn / max(1, m - 1)),
            "eff_in": float(eff[0]), "eff_out": float(eff[-1]),
            "up_frac": round(up_frac, 3),                # how much of the path runs upward (self-purging)
            "inlet": [round(float(polys[0][0][0]), 3), round(float(polys[0][0][1]), 3)],
            "channel_closure_status": "empirical; target-cell calibration required",
            "channel_closures": {
                "orientation_retention": "clip(1 - 0.5*vfrac, 0.4, 1.6)",
                "coverage_from_void": "0.9*(1-exp(-3*eps))",
                "film_threshold": float(EPS_FILM),
                "void_ohmic_fraction": float(vfrac_ohm),
            },
        })
        if mesh_on:                                      # add-only diagnostics
            fields.update({
                "mesh_on": True, "mesh_cover": mesh_cover,
                "mesh_pos": getattr(op, "mesh_pos", "outlet"),
                "mesh_mode": getattr(op, "mesh_mode", "physical"),
                "mesh_bubble_d_mm": round(mf["bubble_d_mm"], 4),
                "mesh_contact_prob": round(mf["contact_prob"], 4),
                "mesh_wetting_drive": round(mf["wetting_drive"], 4),
                "mesh_capture_eff": round(mf["capture_eff"], 4),
                "mesh_obstruction": round(mf["obstruction"], 4),
                "mesh_u_boost": round(mf["u_boost"], 2),
                "mesh_dp_ratio": round(mf["dp_ratio"], 2),
                "mesh_blocking_fraction": round(mf["blocking_fraction"], 4),
                "mesh_active_area_blocking_mode": mf["active_area_blocking_mode"],
                "mesh_electrode_angle": round(mf["electrode_angle_deg"], 1),
                "mesh_contact_angle": round(mf["mesh_angle_deg"], 1),
                "mesh_hydraulic_mode": mf["hydraulic_mode"],
                "mesh_warn": mf["warn"],
                "mesh_mask_frac": float(mmask.mean()),
            })
        # compact along-path profiles (<= 60 pts) for curve/analysis panels
        k = max(1, (m - 1) // 59)
        idx = list(range(0, m, k))
        if idx[-1] != m - 1:
            idx.append(m - 1)
        fields["path_prof"] = {
            "s": [round(i / (m - 1), 4) for i in idx],
            "theta": [round(float(theta[i]), 4) for i in idx],
            "eps": [round(float(eps[i]), 4) for i in idx],
            "j": [round(float(jprof[i]), 1) for i in idx],
            "mesh": [bool(mmask[i]) for i in idx],
        }
        return ElectroState(j=st.j, overpotentials=ov, fields=fields, V=st.V)
