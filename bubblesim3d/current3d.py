"""Surface-only current placement for the pore-scale playback track.

This module deliberately does NOT solve porous-electrode reaction penetration.
The represented cell architecture only permits reaction on the externally
exposed electrode face.  Current is therefore distributed over the first
solid|liquid interface seen from the access face and redistributed over the
remaining exposed sites when gas blocks part of that face.

No screened-Poisson equation, penetration length, roughness-factor utilization,
or internal-pore reaction is present here.
"""
import numpy as np


def _surface_faces_mask(solid, access_axis=1):
    """Reacting pore voxels on the first exposed interface from one face.

    For each ray normal to the electrode, mark the last liquid voxel immediately
    before the first solid voxel.  Anything behind that first solid is internal
    and cannot react in the surface-only architecture.
    """
    s = np.moveaxis(np.asarray(solid, dtype=bool), access_axis, 0)
    pore = ~s
    out = np.zeros_like(s)
    clear_from_face = np.ones(s.shape[1:], dtype=bool)
    for i in range(s.shape[0] - 1):
        out[i] = clear_from_face & pore[i] & s[i + 1]
        clear_from_face &= pore[i]
    return np.moveaxis(out, 0, access_axis)


class SurfaceCurrent3D:
    """Uniform CP current on the unblocked external reacting surface."""

    def __init__(self, solid, access_axis=1):
        self.solid = np.asarray(solid, dtype=bool)
        self.axis = access_axis
        self.surf = _surface_faces_mask(self.solid, access_axis)
        self._n_surface = int(self.surf.sum())
        if self._n_surface == 0:
            raise ValueError("no externally exposed reacting surface in scaffold")

    def active_mask(self, blocked=None):
        active = self.surf.copy()
        if blocked is not None:
            active &= ~np.asarray(blocked, dtype=bool)
        return active

    def active_fraction(self, blocked=None):
        return float(self.active_mask(blocked).sum() / self._n_surface)

    def surface_current(self, total_current_A, blocked=None):
        """Per-surface-voxel current [A], summing to imposed CP current.

        When the whole external face is blocked, delivered current is zero; the
        model reports that state instead of silently placing reaction internally.
        """
        active = self.active_mask(blocked)
        n_active = int(active.sum())
        out = np.zeros(self.solid.shape, dtype=float)
        if n_active > 0 and total_current_A > 0.0:
            out[active] = float(total_current_A) / n_active
        return out


# Compatibility name for old analysis imports.  The implementation is now
# surface-only; keeping the alias does not retain any penetration physics.
Current3D = SurfaceCurrent3D
