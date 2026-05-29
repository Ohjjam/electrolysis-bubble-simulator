"""A single gas bubble on / near the electrode."""
from dataclasses import dataclass
import math


@dataclass
class Bubble:
    x: float            # position along electrode [m]
    y: float            # distance from electrode (buoyancy direction) [m]
    r: float            # bubble radius [m]
    attached: bool = True   # still pinned to the electrode?
    dead: bool = False      # flagged for removal (absorbed by coalescence)
    detach_factor: float = 1.0  # per-bubble departure threshold multiplier (surface heterogeneity)

    def volume(self) -> float:
        return (4.0 / 3.0) * math.pi * self.r ** 3
