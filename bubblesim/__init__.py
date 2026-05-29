"""bubblesim — a physically-grounded simulator for bubble dynamics on
gas-evolving electrodes (HER / OER water electrolysis) and their feedback
onto the current.

Quick start:

    from bubblesim import Simulator, Operating
    sim = Simulator(Operating(V_cell=2.0, contact_angle=60, u_flow=0.0))
    history = sim.run(t_end=2.0, dt=2e-4)
    print(history["j"][-1], history["theta"][-1])
"""
from .config import Operating, Params
from .simulator import Simulator
from . import properties, electrochem, forces, sweeps

__all__ = ["Operating", "Params", "Simulator",
           "properties", "electrochem", "forces", "sweeps"]
