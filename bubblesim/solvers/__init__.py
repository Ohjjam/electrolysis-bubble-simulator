"""Spatial solvers — the ~30 % of the physics that differs by fidelity.

Each solver implements `Solver.solve(op, context, surfaces) -> ElectroState`
over the same shared kernel. `SOLVERS` maps an `Operating.model` string to its
solver class; `get_solver(name)` resolves it.
"""
from .base import Solver, ElectroState
from .zerod import ZeroDSolver, ZeroDTwoElectrodeSolver


def _oned():
    from .oned import OneDGapSolver     # deferred: numpy only when requested
    return OneDGapSolver()


def _porous():
    from .porous import PorousSolver    # deferred: numpy only when requested
    return PorousSolver()


def _face2d():
    from .face2d import Face2DSolver    # deferred: numpy only when requested
    return Face2DSolver()


def _channel():
    from .channel import ChannelSolver  # deferred: numpy only when requested
    return ChannelSolver()


# model-name -> solver factory/class. `Operating.model` selects from here.
SOLVERS = {
    "lumped": ZeroDSolver,
    "two_electrode": ZeroDTwoElectrodeSolver,
    "oned": _oned,
    "porous": _porous,
    "face2d": _face2d,
    "channel": _channel,
}


def get_solver(name):
    """Instantiate the solver registered under `name` (defaults to lumped)."""
    cls = SOLVERS.get(name, ZeroDSolver)
    return cls()


__all__ = ["Solver", "ElectroState", "ZeroDSolver", "ZeroDTwoElectrodeSolver",
           "SOLVERS", "get_solver"]
