"""Confined-pore bubble growth by voxel filling (Track B).

Honest scope: NOT interface-tracking VOF. Gas produced at the reacting surface
fills the connected OPEN pore space voxel-by-voxel — nucleating at the highest
current / most-favoured sites, then growing outward into adjacent open pores
(the physical picture: a bubble grows until it meets a pore wall, then conforms
to and floods the connected pore channel). A gas cluster that reaches the escape
face (the accessible / separator side) vents and is removed. This conserves gas
by construction: produced = resident + vented at every step.

numpy-only; connectivity via array-shift flood fill (no scipy).
"""
import numpy as np


class PoreGrowth:
    def __init__(self, solid, escape_axis=1, escape_factor=1.0):
        self.solid = solid
        self.pore = ~solid
        self.gas = np.zeros(solid.shape, dtype=bool)
        self.axis = escape_axis                 # gas escapes toward this axis' far face
        self.escape_factor = float(escape_factor)
        self.produced_cum = 0.0                 # total gas volume evolved [m^3]
        self.vented_cum = 0.0
        self._rng = np.random.default_rng(0)

    # ------------------------------------------------------------- helpers
    def _dilate_into_pore(self, mask):
        """One-voxel 6-connected dilation restricted to open pore (not gas)."""
        open_pore = self.pore & (~self.gas)
        d = mask.copy()
        d[1:] |= mask[:-1]; d[:-1] |= mask[1:]
        d[:, 1:] |= mask[:, :-1]; d[:, :-1] |= mask[:, 1:]
        d[:, :, 1:] |= mask[:, :, :-1]; d[:, :, :-1] |= mask[:, :, 1:]
        return d & open_pore

    def _cluster_touching_escape(self):
        """Gas voxels connected (through gas) to the escape face.

        The escape face is index 0 of `axis` — the separator/channel side that
        the electrolyte faces (and where current3d drives the reaction), so gas
        vents out the front into the flow, not into the current collector."""
        reached = np.zeros_like(self.gas)
        sl = [slice(None)] * 3; sl[self.axis] = 0
        reached[tuple(sl)] = self.gas[tuple(sl)]
        # cap = total voxels: a tortuous gas cluster can be far longer than 4n
        # (the loop breaks on convergence, so the cap only guards pathology)
        for _ in range(self.gas.size):
            nb = reached.copy()
            nb[1:] |= reached[:-1]; nb[:-1] |= reached[1:]
            nb[:, 1:] |= reached[:, :-1]; nb[:, :-1] |= reached[:, 1:]
            nb[:, :, 1:] |= reached[:, :, :-1]; nb[:, :, :-1] |= reached[:, :, 1:]
            nb &= self.gas
            if nb.sum() == reached.sum():
                break
            reached = nb
        return reached

    # -------------------------------------------------------------- step
    def grow(self, gas_volume_added, v_voxel, nuc_weight):
        """Add `gas_volume_added` [m^3] of gas, seed by `nuc_weight` (per-voxel
        surface preference), grow into connected pore, then vent escaping gas."""
        self.produced_cum += gas_volume_added
        resident_target_vol = self.produced_cum - self.vented_cum
        target_voxels = int(round(resident_target_vol / v_voxel))
        cur = int(self.gas.sum())
        n_add = target_voxels - cur
        if n_add > 0:
            self._add_voxels(n_add, nuc_weight)
        # vent gas that has grown to the escape face
        escaping = self._cluster_touching_escape()
        n_vent = int(escaping.sum())
        if n_vent > 0:
            # escape_factor<1 (foams) traps some gas: only a fraction actually leaves
            keep_frac = 1.0 - self.escape_factor
            if keep_frac > 0:
                idx = np.argwhere(escaping)
                keep_n = int(round(keep_frac * len(idx)))
                if keep_n > 0:
                    sel = self._rng.choice(len(idx), size=len(idx) - keep_n, replace=False)
                    vent_mask = np.zeros_like(self.gas)
                    for q in sel:
                        vent_mask[tuple(idx[q])] = True
                    escaping = vent_mask
                    n_vent = int(escaping.sum())
            self.gas &= ~escaping
            self.vented_cum += n_vent * v_voxel

    def _add_voxels(self, n_add, nuc_weight):
        """Fill n_add open-pore voxels: nucleate at weighted surface sites, then
        grow existing gas outward."""
        open_pore = self.pore & (~self.gas)
        if not open_pore.any():
            return
        added = 0
        # 1) growth: dilate current gas into pore first (existing bubbles grow)
        if self.gas.any():
            frontier = self._dilate_into_pore(self.gas) & (~self.gas)
            fidx = np.argwhere(frontier)
            if len(fidx):
                take = min(n_add, len(fidx))
                # prefer frontier voxels near high nucleation weight
                order = np.argsort([-nuc_weight[tuple(p)] for p in fidx])
                for q in order[:take]:
                    self.gas[tuple(fidx[q])] = True
                added += take
        # 2) nucleation: seed remaining at the highest-weight surface voxels
        if added < n_add:
            w = nuc_weight * (open_pore & (~self.gas))
            if w.sum() > 0:
                order = np.argsort(w.ravel())[::-1]
                need = n_add - added
                picked = order[:need]
                coords = np.unravel_index(picked, self.gas.shape)
                # only keep those with positive weight
                keep = w.ravel()[picked] > 0
                self.gas[coords[0][keep], coords[1][keep], coords[2][keep]] = True
                added += int(keep.sum())
        # 3) fallback: if still short (weights exhausted), fill any open pore
        if added < n_add:
            rem = np.argwhere(self.pore & (~self.gas))
            if len(rem):
                take = min(n_add - added, len(rem))
                sel = self._rng.choice(len(rem), size=take, replace=False)
                for q in sel:
                    self.gas[tuple(rem[q])] = True

    # ------------------------------------------------------------ diagnostics
    def coverage(self):
        """Fraction of reacting-surface pore voxels that are gas-covered."""
        surf = self.pore & self._surface()
        if not surf.any():
            return 0.0
        return float((self.gas & self._surface()).sum() / max(1, surf.sum()))

    def _surface(self):
        s = self.solid
        t = np.zeros_like(s)
        t[:-1] |= s[1:]; t[1:] |= s[:-1]
        t[:, :-1] |= s[:, 1:]; t[:, 1:] |= s[:, :-1]
        t[:, :, :-1] |= s[:, :, 1:]; t[:, :, 1:] |= s[:, :, :-1]
        return t & self.pore

    def holdup(self):
        """Gas fraction of the pore space."""
        npore = int(self.pore.sum())
        return float(self.gas.sum() / npore) if npore else 0.0
