"""Back-compat shim. The lumped electrochemistry now lives in
`bubblesim.solvers.zerod` (the `ZeroDSolver` fidelity). These names are
re-exported so existing imports — `electrochem.solve_current_density`,
`electrochem.overpotentials` — and the tests keep working unchanged.
"""
from .solvers.zerod import solve_current_density, overpotentials  # noqa: F401

__all__ = ["solve_current_density", "overpotentials"]
