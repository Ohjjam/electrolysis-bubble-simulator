"""A single gas bubble on / near the electrode.

Canonical coordinate frame (shared across all fidelities — see plan v2):

    x : electrode width   (horizontal, in-plane)
    y : electrode height  (vertical = buoyancy / rise, in-plane)
    z : electrode -> membrane normal (the gap direction; void eps(z) lives here)

NOTE (v1 carry-over): the current lumped/0D model is effectively a *horizontal*
electrode. The single off-electrode axis stored below as `y` is really the
gap-normal `z` — it is the direction `near_layer` measures and along which the
buoyant rise acts. The rename `y -> z` (and adding a true vertical buoyancy
axis for 2D) is deferred to the 1D/2D work (Phase 5); behavior is unchanged for
now, so the field is left named `y` to keep the move byte-for-byte equivalent.
"""
from dataclasses import dataclass
import math


@dataclass
class Bubble:
    x: float            # position along electrode width [m]
    y: float            # off-electrode distance [m]  (v1: gap-normal z; buoyant rise acts here)
    r: float            # bubble radius [m]
    attached: bool = True   # still pinned to the electrode?
    dead: bool = False      # flagged for removal (absorbed by coalescence)
    detach_factor: float = 1.0  # per-bubble departure threshold multiplier (surface heterogeneity)
    id: int = 0             # stable identity (lets clients interpolate motion between frames)

    def volume(self) -> float:
        return (4.0 / 3.0) * math.pi * self.r ** 3
