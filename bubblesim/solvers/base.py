"""The fidelity-agnostic solver interface.

Every spatial fidelity (0D lumped, 0D two-electrode, 1D gap, 2D) implements the
same `Solver.solve(op, context, surfaces) -> ElectroState`. The bubble model
consumes only `ElectroState.j` (the area-averaged current density), so swapping
the solver leaves the Lagrangian bubble dynamics untouched — and because every
solver returns the same scalar, cross-fidelity agreement is a one-line check.

`j_field` carries the along-electrode current distribution j(y) once a 2D solver
exists (current is non-uniform as bubbles accumulate up the electrode); it stays
None for 0D/1D where the face is uniform. `fields` holds 1D/2D profiles
(z, phi, c, eps(z)) for plotting.
"""
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class ElectroState:
    """Result of one electrochemical solve, independent of fidelity."""
    j: float                                  # area-averaged current density [A/m^2]
    overpotentials: dict = field(default_factory=dict)
    j_field: Optional[Any] = None             # 2D+: j(y) over the electrode face; None = uniform
    fields: dict = field(default_factory=dict)  # 1D/2D: {"z":..., "phi":..., "c":..., "eps":...}
    V: Optional[float] = None                 # galvanostatic (CP) result: the cell voltage that
                                              # drives j. None in CA mode (V is the input there).


@runtime_checkable
class Solver(Protocol):
    def solve(self, op, context: dict, surfaces) -> ElectroState:
        """Given the operating point, the property context and the bubble
        surface(s) (1 = primary electrode; 2 = both electrodes), return the
        electrochemical state. `surfaces` is a list of `Surface`."""
        ...
