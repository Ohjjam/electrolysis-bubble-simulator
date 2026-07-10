"""Double-layer transient dynamics: a stateful wrapper over any steady solver.

Under galvanostatic (CP) operation each electrode's overpotential obeys

    C_dl * d(eta)/dt = j_set - j_far(eta)

so after a setpoint change eta relaxes toward its steady value with the local
time constant  tau = R_ct(eta_ss) * C_dl  (the same product EIS measures as the
charge-transfer semicircle). Instead of integrating the stiff ODE explicitly,
each step applies the exact exponential update of the linearized system:

    eta <- eta_ss + (eta - eta_ss) * exp(-dt / tau)

which is unconditionally stable for any dt. During the transient the *faradaic*
current (which evolves gas) lags the imposed current — the difference charges
the double layer — so the wrapper reports j = faradaic mean and the relaxed V.

CA mode passes straight through (steady solve, as before). The wrapper needs
the integration dt at construction; keep it equal to the Simulator step.
"""
import math

from .base import ElectroState
from ..constants import F, R_GAS
from ..kernel.impedance import r_ct_bv
from ..kernel.kinetics import butler_volmer


class DoubleLayerWrapper:
    def __init__(self, inner, params, dt):
        self.inner = inner
        self.p = params
        self.dt = dt
        self.eta_a = None      # relaxed anodic overpotential state [V]
        self.eta_c = None

    def solve(self, op, context, surfaces) -> ElectroState:
        st = self.inner.solve(op, context, surfaces)
        if getattr(op, "mode", "CA") != "CP" or st.j <= 0.0:
            self.eta_a = self.eta_c = None     # reset state outside CP operation
            return st

        ov = st.overpotentials
        ss_a = ov.get("eta_act_anode", ov.get("eta_act", 0.0))
        ss_c = ov.get("eta_act_cathode", 0.0)
        if self.eta_a is None:
            self.eta_a, self.eta_c = ss_a, ss_c

        T = op.T
        dual = op.track_both and len(surfaces) > 1
        theta_c = surfaces[0].coverage()
        theta_a = surfaces[1].coverage() if dual else 0.0
        if not dual and op.electrode == "OER":
            theta_a, theta_c = theta_c, 0.0

        for which, ss in (("a", ss_a), ("c", ss_c)):
            j0 = context["j0_anode" if which == "a" else "j0_cathode"]
            aa = context["alpha_a_anode" if which == "a" else "alpha_a_cathode"]
            ac = context["alpha_c_anode" if which == "a" else "alpha_c_cathode"]
            omt = max(1e-3, 1.0 - (theta_a if which == "a" else theta_c))
            # bubble coverage removes double-layer area: C_eff = C_dl*(1-theta).
            # At fixed cell current R_ct is ~theta-independent, so tau = R_ct*C_eff
            # scales as (1-theta): coverage speeds DL relaxation / raises the EIS
            # apex frequency (the semicircle shifts; it is NOT intensive).
            C = (self.p.anode if which == "a" else self.p.cathode).C_dl * omt
            tau = r_ct_bv(omt * j0, aa, ac, ss, T) * C
            eta = self.eta_a if which == "a" else self.eta_c
            eta = ss + (eta - ss) * math.exp(-self.dt / max(tau, 1e-9))
            if which == "a":
                self.eta_a = eta
            else:
                self.eta_c = eta

        # faradaic currents at the relaxed overpotentials (gas generation lags)
        omt_a = max(1e-3, 1.0 - theta_a)
        omt_c = max(1e-3, 1.0 - theta_c)
        jf_a = omt_a * butler_volmer(context["j0_anode"],
                                     context["alpha_a_anode"], context["alpha_c_anode"],
                                     self.eta_a, T)
        jf_c = omt_c * butler_volmer(context["j0_cathode"],
                                     context["alpha_a_cathode"], context["alpha_c_cathode"],
                                     self.eta_c, T)
        j_far = max(0.0, 0.5 * (jf_a + jf_c))

        V = (st.V - ss_a - ss_c + self.eta_a + self.eta_c) if st.V is not None else None
        ov = dict(ov)
        ov["eta_act_anode"], ov["eta_act_cathode"] = self.eta_a, self.eta_c
        ov["eta_act"] = self.eta_a + self.eta_c
        return ElectroState(j=j_far, overpotentials=ov, fields=st.fields,
                            j_field=st.j_field, V=V)
