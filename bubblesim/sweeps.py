"""Parameter sweeps: polarization curves and one-factor sensitivity studies.

These are the "research-grade" outputs — they run the coupled model to a
quasi-steady state and report time-averaged observables, so you can ask
*which lever moves the current the most*.
"""
import statistics
from dataclasses import replace

from .config import Operating
from .simulator import Simulator


def steady_means(op: Operating, t_end=1.5, dt=2e-4, settle=0.6, seed=0,
                 params=None) -> dict:
    """Run one operating point and average observables after the settle time."""
    sim = Simulator(op=op, params=params, seed=seed)
    sim.run(t_end, dt)
    h = sim.history

    def avg(key):
        vals = [v for t, v in zip(h["t"], h[key]) if t >= settle]
        return statistics.fmean(vals) if vals else float("nan")

    return {
        "j": avg("j"), "I": avg("I"), "theta": avg("theta"),
        "eps": avg("eps"), "r_d": avg("r_d"), "n_bub": avg("n_bub"),
        "eta_ohmic": avg("eta_ohmic"),
    }


def polarization(V_list, base_op: Operating = None, params=None, **kw) -> dict:
    """Polarization curve: mean current density vs applied voltage."""
    base_op = base_op or Operating()
    out = {"V": [], "j": [], "theta": [], "eps": []}
    for V in V_list:
        m = steady_means(replace(base_op, V_cell=V), params=params, **kw)
        out["V"].append(V)
        out["j"].append(m["j"])
        out["theta"].append(m["theta"])
        out["eps"].append(m["eps"])
    return out


def sweep(field: str, values, base_op: Operating = None, params=None, **kw) -> dict:
    """Sweep a single operating field; return mean observables vs that field."""
    base_op = base_op or Operating()
    out = {field: [], "j": [], "theta": [], "eps": [], "r_d": []}
    for val in values:
        m = steady_means(replace(base_op, **{field: val}), params=params, **kw)
        out[field].append(val)
        for k in ("j", "theta", "eps", "r_d"):
            out[k].append(m[k])
    return out
