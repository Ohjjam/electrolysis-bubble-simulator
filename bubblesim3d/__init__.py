"""bubblesim3d — 3-D structure simulator built on the bubblesim kernel.

Two fidelity tracks share this package (and the frozen `bubblesim.kernel`
physics — kinetics, properties, chemistry, sources, forces are imported
read-only, never reimplemented):

  Track A (cell scale, ~mm voxels, interactive):
      flow-field plate (ribs/channels) + PTL + electrode faces on a uniform
      grid; incompressible Navier-Stokes (projection) + Lagrangian gas parcels
      + electrode-face current redistribution.  `CellSim3D`.

  Track B (pore scale, ~um voxels, offline batch):
      voxel microstructure used only as gas-access geometry. Electrochemical
      reaction is restricted to the first externally accessible catalyst
      surface; gas may subsequently occupy connected pores. No porous-electrode
      reaction penetration or internal secondary-current solve. `PoreSim3D`.

Honest scope: parcels are sub-grid (no resolved interfaces -> not VOF), and
pore growth is volume-filling (not interface-tracking). numpy is allowed here
(solver-layer rule, same as bubblesim/solvers); the kernel stays stdlib-pure.

This package NEVER modifies bubblesim state: no new context keys, no solver
registry entries — golden tests stay untouched by construction.
"""
from .grid import Grid3D
from .params3d import Cell3DConfig, Pore3DConfig, operating_from_designer

__all__ = ["Grid3D", "Cell3DConfig", "Pore3DConfig", "operating_from_designer"]
