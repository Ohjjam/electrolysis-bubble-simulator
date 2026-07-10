"""Face-field 2.5-D solver (model="face2d") -- the bottleneck colour map.

The electrode FACE (width x, height y) is divided into nx*ny cells. Bubbles
generated lower down and upstream RISE (buoyancy, +y) and DRIFT (cross-flow, +x),
so the near-wall gas coverage ACCUMULATES with height and downstream distance.
Since the electrode is equipotential, the local current redistributes -- cells
that are bubble-blanketed (top / downstream) carry LESS current, clear cells
carry MORE. That redistribution is the bottleneck map the user asked for (like a
CFD surface field).

Honest scope: this is a multi-segment electrode-network reduction (standard in
electrochemical engineering), NOT a Navier-Stokes/VOF CFD. It captures the
face-direction current & coverage distribution and where the cell starves, but
not real vortices or exact bubble trajectories.

Method: the scalar operating point (V, mean j, overpotential split) comes from
the two-electrode balance at the MEAN coverage -- so catalyst inputs, electrolyte
and CA/CP all carry through. The coverage field then redistributes the current at
the common overpotential:  j_ij = j_mean * (1 - theta_ij) / mean(1 - theta).
By construction mean(j_field) == j_mean (charge conserved).

numpy only (solver boundary; the kernel stays stdlib).
"""
import numpy as np

from .base import ElectroState
from .zerod import ZeroDTwoElectrodeSolver


class _Stub:
    """Surface stand-in carrying a representative coverage / void for the scalar solve."""
    def __init__(self, theta, eps):
        self._t, self._e = theta, eps
    def coverage(self):
        return self._t
    def void_fraction(self):
        return self._e


def coverage_field(j, op, nx, ny, theta_cap=0.85):
    """theta(x, y) over the face from rising/drifting bubble accumulation.

        theta = theta_cap * (1 - exp(-(by*hy + bx*hx)))

    hy = 0..1 bottom->top, hx = 0..1 upstream->downstream. The vertical
    accumulation `by` grows with current density (more gas) and electrode height
    (longer rise path) and is reduced by cross-flow sweeping the wall; the flow
    also adds a downstream accumulation `bx`.
    """
    H = max(1e-3, getattr(op, "face_height_cm", 10.0) * 1e-2)     # electrode height [m]
    u = max(0.0, op.u_flow)
    sweep = 1.0 + 6.0 * u                                         # flow clears the wall
    jn = max(0.0, j) / 1.0e4
    by = 3.0 * jn * (H / 0.1) / sweep                            # vertical accumulation
    bx = 2.0 * u * jn                                            # downstream accumulation
    hy = (np.arange(ny) + 0.5) / ny
    hx = (np.arange(nx) + 0.5) / nx
    HY, HX = np.meshgrid(hy, hx, indexing="ij")                  # shape (ny, nx)
    return theta_cap * (1.0 - np.exp(-(by * HY + bx * HX)))


class Face2DSolver:
    """Pseudo-2D face-field solver (see module docstring)."""

    def __init__(self, nx=6, ny=12):
        self.nx, self.ny = nx, ny

    def solve(self, op, context, surfaces) -> ElectroState:
        base = ZeroDTwoElectrodeSolver(n_outer=40, n_inner=28)
        eps0 = surfaces[0].void_fraction()
        cp = getattr(op, "mode", "CA") == "CP"
        # iterate coverage-field <-> scalar current (the field shape converges fast)
        th = coverage_field(op.j_set if cp else 4000.0, op, self.nx, self.ny)
        st = None
        for _ in range(3):
            st = base.solve(op, context, [_Stub(float(th.mean()), eps0)])
            th = coverage_field(st.j, op, self.nx, self.ny)

        omt = 1.0 - th
        jf = st.j * omt / max(1e-6, float(omt.mean()))           # redistribute at common eta
        ov = dict(st.overpotentials)
        ov["j_spread"] = float(jf.max() / max(1e-9, jf.min()))   # max/min current ratio
        fields = dict(st.fields)
        fields.update({
            "theta_field": th.tolist(), "j_field": jf.tolist(),
            "nx": self.nx, "ny": self.ny,
            "theta_bot": float(th[0].mean()), "theta_top": float(th[-1].mean()),
            "j_bot": float(jf[0].mean()), "j_top": float(jf[-1].mean()),
            "face_height_cm": float(getattr(op, "face_height_cm", 10.0)),
        })
        return ElectroState(j=st.j, overpotentials=ov, fields=fields,
                            j_field=jf, V=st.V)
