"""Dimension-agnostic physics kernel.

Everything here knows nothing about spatial discretization — it is the ~70 %
of the physics (thermodynamics, kinetics, properties, source terms, the
Lagrangian bubble model, and the bubble<->grid projection operators) shared by
every fidelity solver (0D / 1D / 2D). Spatial solvers live in `bubblesim.solvers`
and consume this kernel.
"""
