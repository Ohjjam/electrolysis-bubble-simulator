"""Voxelize the P1 designer's flow field into the cell-scale grid (Track A).

Turns the designer geometry (flow-field type, channel/land widths, channel
count) into a solid-obstacle mask on the Grid3D: the ribs/lands that press
against each electrode block electrolyte flow, while the channels between them
carry it. Feeding that mask to NS3D makes the flow (and therefore the bubble
sweep and the electrode-face current map) rib-correlated — the "rib shadowing"
the user wants to see.

Layout (see grid.py): x through-plane (electrode faces at x=0 / x=Lx), y flow
/height, z width. Ribs sit in the near-electrode x-layers of both faces:
  * serpentine / straight -> passes run along z, stacked in y -> horizontal
    land bands across y (with an open turn gap at alternating ends)
  * parallel / interdigitated -> channels run along y -> vertical land bands
    across z

Honest scope: a blocky obstacle mask at the grid resolution, not a CAD-exact
flow field — enough to steer the flow around lands and localise coverage.
"""
import numpy as np

from .grid import Grid3D
from .params3d import Cell3DConfig


def _land_bands_y(cfg: Cell3DConfig, ny):
    """Fractional y-centres [0,1] of land bands for serpentine/straight."""
    n = max(1, int(round(cfg.n_ch)))
    pitch_f = cfg.w_ch_mm + cfg.w_land_mm
    land_frac = cfg.w_land_mm / pitch_f
    centres = (np.arange(n + 1)) / n
    half = 0.5 * land_frac / max(1, n) * n     # land half-width in fractional y
    return centres, half


def _overlap(n_out, n_in):
    """(n_out, n_in) fractional-overlap matrix; each row sums to 1."""
    edges = np.linspace(0.0, float(n_in), n_out + 1)
    W = np.zeros((n_out, n_in))
    for o in range(n_out):
        lo, hi = edges[o], edges[o + 1]
        for i in range(int(np.floor(lo)), min(int(np.ceil(hi)), n_in)):
            W[o, i] = max(0.0, min(hi, i + 1.0) - max(lo, float(i)))
        tot = W[o].sum()
        if tot > 0:
            W[o] /= tot
    return W


def _resample_mask(mask, ny, nz):
    """AREA-weighted resample of a (M,N) bool mask onto the (ny,nz) face.

    Nearest-neighbour (the old rule) simply SKIPS input rows when downsampling:
    32 drawn rows onto a 25-cell grid never sample 7 of them, so a one-cell rib
    drawn on 22% of the rows vanished from the physics entirely — you drew a rib
    and nothing happened. Here each output cell takes the fraction of its
    footprint that is land and becomes land above 50%, so a drawn rib always
    survives and the land fraction is preserved.
    """
    my, mz = mask.shape
    frac = _overlap(ny, my) @ mask.astype(float) @ _overlap(nz, mz).T
    return frac >= 0.5


def _port(nz, centre, width, open_row):
    """(nz,) bool port of fractional `width` centred at fractional `centre`.

    Restricted to cells the plate actually leaves open in that row; if the port
    lands entirely on a rib it snaps to the nearest open cell, because a plate
    whose inlet is blind has no flow at all.
    """
    zc = (np.arange(nz) + 0.5) / nz
    half = max(0.5 / nz, 0.5 * float(width))
    m = (np.abs(zc - float(centre)) <= half) & open_row
    if m.any():
        return m
    if not open_row.any():
        return np.ones(nz, dtype=bool)          # fully landed row: degenerate
    k = np.argmin(np.abs(np.nonzero(open_row)[0] / max(nz - 1, 1) - centre))
    m = np.zeros(nz, dtype=bool)
    m[np.nonzero(open_row)[0][k]] = True
    return m


def _edge(open2d, line, face):
    """Boolean (ny,nz) of the open port cells on `face`."""
    m = np.zeros_like(open2d)
    if face == "bottom":
        m[0] = open2d[0] & line
    elif face == "top":
        m[-1] = open2d[-1] & line
    elif face == "left":
        m[:, 0] = open2d[:, 0] & line
    else:
        m[:, -1] = open2d[:, -1] & line
    return m


def flow_connects(open2d, in_line, in_face, out_line, out_face):
    """Is there an open channel path from the inlet port to the outlet port?

    A plate whose channel never reaches the exit has NO flow: the projection
    cannot conserve mass (it sees an inflow and no outflow), the divergence
    stalls two orders of magnitude above tolerance, and every derived number is
    meaningless. The interdigitated preset is exactly this — real interdigitated
    plates push the liquid THROUGH the porous transport layer, and this model
    makes the core solid — so the condition has to be detectable, not silent.
    """
    reach = _edge(open2d, in_line, in_face)
    tgt = _edge(open2d, out_line, out_face)
    if not reach.any() or not tgt.any():
        return False
    for _ in range(open2d.size):
        nb = reach.copy()
        nb[1:] |= reach[:-1]; nb[:-1] |= reach[1:]
        nb[:, 1:] |= reach[:, :-1]; nb[:, :-1] |= reach[:, 1:]
        nb &= open2d
        if (nb & tgt).any():
            return True
        if nb.sum() == reach.sum():
            break
        reach = nb
    return bool((reach & tgt).any())


def voxelize(cfg: Cell3DConfig, grid: Grid3D):
    """Return (solid, face_c, face_a):

        solid  : (nx,ny,nz) bool  — land/rib obstacle cells (both near faces)
        face_c : (ny,nz)   bool  — active cathode-face cells (x=0 side, not landed)
        face_a : (ny,nz)   bool  — active anode-face cells   (x=Lx side)

    A cell is a land if it lies in the near-electrode x-layers AND its (y,z)
    falls on a land band. Face-active cells are the complement on that face.
    """
    nx, ny, nz = grid.shape
    solid = np.zeros(grid.shape, dtype=bool)
    # channel layers: the outer n_lay cells of each face carry the flow
    # channels (rib pattern; n_lay tracks the designer's channel depth via
    # cfg.layer_counts). Everything BETWEEN them (PTL + membrane core) is
    # solid — in a real zero-gap cell the liquid only flows in the channels.
    n_lay = cfg.layer_counts()[0]
    n_lay = max(1, min(n_lay, (nx - 1) // 2))            # never swallow the core
    xc = np.arange(nx)
    near = (xc < n_lay) | (xc >= nx - n_lay)             # (nx,) channel layers

    pitch_f = cfg.w_ch_mm + cfg.w_land_mm
    land_frac = float(np.clip(cfg.w_land_mm / pitch_f, 0.05, 0.95))
    n = max(1, int(round(cfg.n_ch)))
    ff = cfg.ff

    def _band_indices(n_cells, n_div, first, last):
        """Rib bands of constant thickness on an INTEGER pitch.

        `grid_dims` snaps the flow axis so `n_cells` is a whole number of passes.
        With a fractional pitch (25 rows / 8 passes = 3.125) the ribs came out
        uniform but the CHANNELS between them alternated 1 and 2 cells — the
        uneven flow paths in the cell map. On an integer pitch both are uniform.

        Thickness rounds HALF-DOWN: at pitch 3 a 50/50 plate is not
        representable, and a thinner rib keeps the channel open rather than
        choking it. The achieved widths are reported by `rib_channel_mm()`.
        """
        pitch = max(2, n_cells // n_div)
        thick = int(np.floor(land_frac * pitch + 0.5 - 1e-9))
        thick = max(1, min(pitch - 1, thick))
        rows = np.zeros(n_cells, dtype=bool)
        owner = np.full(n_cells, -1, dtype=int)          # which divider made this row
        for k in range(first, last + 1):
            c = k * pitch                                # divider position [cells]
            j0 = c - (thick - 1) // 2                    # centred, ties toward +
            for j in range(j0, j0 + thick):
                if 0 <= j < n_cells:
                    rows[j] = True
                    owner[j] = k
        return rows, owner

    land2d = np.zeros((ny, nz), dtype=bool)              # (y,z) land footprint
    if ff == "custom" and cfg.land_mask is not None:
        # USER-DRAWN plate: the painted mask is the flow field. It is authored at
        # its own resolution (fractional coords) and resampled to the grid with
        # nearest-neighbour, so the drawing survives a grid change.
        land2d = _resample_mask(np.asarray(cfg.land_mask, dtype=bool), ny, nz)
        if land2d.all():
            # a fully-ribbed plate has no channel: the projection would have no
            # fluid cells and nothing could nucleate. Keep one column open so the
            # cell stays a cell (the editor shows what the engine actually runs).
            land2d[:, nz // 2] = False
    elif ff in ("par", "inter"):
        # vertical land bands across z: n channels -> n+1 dividers (0..n)
        is_land, _owner = _band_indices(nz, n, 0, n)
        # guarantee every channel keeps >=1 open column even when a wide land
        # at a coarse grid would swallow it (the channel must stay a channel)
        for c in range(n):
            col = min(nz - 1, int((c + 0.5) / n * nz))
            is_land[col] = False
        band = np.broadcast_to(is_land[None, :], (ny, nz)).copy()
        if ff == "inter":                                # dead-end alternate channels
            yc = (np.arange(ny) + 0.5) / ny
            zc = (np.arange(nz) + 0.5) / nz
            chan_idx = np.floor(zc * n).astype(int)
            for k in range(nz):
                if chan_idx[k] % 2 == 0:
                    band[yc > 0.86, k] = True            # even channels: closed at top
                else:
                    band[yc < 0.14, k] = True            # odd channels: closed at bottom
        land2d = band
    else:
        # serpentine / straight: horizontal land bands across y WITH a turn gap
        # at alternating ends, so the channel is one connected snaking path
        # (matches the drawn plate) — flow and bubbles must traverse each pass
        # and turn at the gap instead of leaking straight up.
        # uniform-thickness rib bands; `k_near` is the divider each row belongs
        # to, so the turn gap alternates sides pass by pass
        is_land_row, k_near = _band_indices(ny, n, 1, n - 1)
        # turn-gap width ~ one channel width of the drawn plate
        gap_frac = float(np.clip(cfg.w_ch_mm / max(1e-6, cfg.W_cm * 10.0),
                                 0.06, 0.30))
        n_gap = max(1, int(round(gap_frac * nz)))
        zc_idx = np.arange(nz)
        land2d = np.zeros((ny, nz), dtype=bool)
        for j in np.nonzero(is_land_row)[0]:
            k = k_near[j]
            if k % 2 == 0:                               # even boundary: gap at z-high
                open_z = zc_idx >= nz - n_gap
            else:                                        # odd boundary: gap at z-low
                open_z = zc_idx < n_gap
            land2d[j, ~open_z] = True

    solid[near, :, :] = land2d[None, :, :]
    # interior core (PTL + membrane): no free liquid path through the cell
    if nx > 2 * n_lay:
        solid[n_lay:nx - n_lay, :, :] = True
    face_c = ~land2d
    face_a = ~land2d
    return solid, face_c, face_a


def inlet_mask(cfg: Cell3DConfig, grid: Grid3D, land2d):
    """(nz,) bool — bottom-row columns that act as the pump INLET port.

    A real serpentine is fed through a PORT at the start of the first pass, so
    the channel velocity equals the pump velocity everywhere along the snake.
    Feeding the whole bottom face instead (the old behaviour) multiplies the
    velocity at every 2-cell turn gap by (inlet area / gap area) ~ 10x and
    produces multi-m/s jets that fling bubbles over the ribs.

    `cfg.in_w > 0` places an EXPLICIT port of that fractional width at `in_z`
    (the user's choice). `in_w == 0` keeps each preset's own inlet:
      serpentine: a port at the end OPPOSITE the first turn gap, so the flow
        traverses the whole first pass;
      parallel / interdigitated: every open channel column (uniform manifold);
      custom: every open column of the bottom row.
    """
    nz = grid.nz
    open_row = ~land2d[0]
    if cfg.in_w and cfg.in_w > 0:
        return _port(nz, cfg.in_z, cfg.in_w, open_row)
    if cfg.ff in ("par", "inter", "custom"):
        return open_row if open_row.any() else np.ones(nz, dtype=bool)
    gap_frac = float(np.clip(cfg.w_ch_mm / max(1e-6, cfg.W_cm * 10.0), 0.06, 0.30))
    n_gap = max(1, int(round(gap_frac * nz)))
    mask = np.zeros(nz, dtype=bool)
    # first interior boundary k=1 is odd -> its gap is at z-low, so the inlet
    # port is at z-high (flow enters right, runs the pass leftward, turns up)
    mask[nz - n_gap:] = True
    return mask & open_row if (mask & open_row).any() else mask


def port_edges(cfg: Cell3DConfig, grid: Grid3D, land2d):
    """Resolve both ports onto their chosen edges.

    Returns (in_face, in_line, out_face, out_line) where each *_line is a bool
    array over the edge's own axis: z (nz,) for bottom/top, y (ny,) for
    left/right. The port is intersected with the cells the PLATE leaves open on
    that edge, so a port never opens onto a rib.
    """
    ny, nz = land2d.shape
    open_edge = {"bottom": ~land2d[0], "top": ~land2d[-1],
                 "left": ~land2d[:, 0], "right": ~land2d[:, -1]}

    inf = cfg.in_face if cfg.in_face in open_edge else "bottom"
    outf = cfg.out_face if cfg.out_face in open_edge else "top"
    n_in = nz if inf in ("bottom", "top") else ny
    n_out = nz if outf in ("bottom", "top") else ny

    if cfg.in_w and cfg.in_w > 0:
        in_line = _port(n_in, cfg.in_z, cfg.in_w, open_edge[inf])
    elif inf == "bottom":
        in_line = inlet_mask(cfg, grid, land2d)          # the preset's own inlet
    else:
        in_line = open_edge[inf].copy()                  # whole edge manifold
    if not in_line.any():
        in_line = np.ones(n_in, dtype=bool)

    if cfg.out_w and cfg.out_w > 0:
        if outf == "top" and cfg.out_w >= 1.0:
            out_line = np.ones(n_out, dtype=bool)        # whole top vents (legacy)
        else:
            out_line = _port(n_out, cfg.out_z, cfg.out_w, open_edge[outf])
    elif outf == "top":
        out_line = outlet_mask(cfg, grid, land2d)        # auto: the preset's own exit
    else:
        out_line = open_edge[outf].copy()                # auto side manifold
    if inf == outf:                                      # never feed and vent a cell
        out_line = out_line & ~in_line
        if not out_line.any():
            out_line = ~in_line & open_edge[outf]
    return inf, in_line, outf, out_line


def outlet_mask(cfg: Cell3DConfig, grid: Grid3D, land2d):
    """(nz,) bool — top-row columns that VENT (Dirichlet p=0 in the projection).

    `out_w == 1` opens the whole top face. A value in (0,1) is an explicit exit
    port at `out_z`, and the rest of the top becomes a wall — the exit position
    a design lever. `out_w == 0` is AUTO, mirroring `inlet_mask`:
      serpentine / straight: a channel-width port at the LAST pass's far end, so
        the snake really leaves through one exit instead of venting its whole
        top (which let the last pass short-circuit straight up everywhere);
      parallel / interdigitated / custom: every open top column (uniform
        manifold — those channels run to the top across the whole width).
    """
    nz = grid.nz
    open_row = ~land2d[-1]
    if cfg.out_w and cfg.out_w >= 1.0:
        return np.ones(nz, dtype=bool)
    if cfg.out_w and cfg.out_w > 0:
        return _port(nz, cfg.out_z, cfg.out_w, open_row)
    if cfg.ff in ("par", "inter", "custom"):
        return open_row if open_row.any() else np.ones(nz, dtype=bool)
    # serpentine / straight exit port. The inlet enters the first pass at its
    # z-high end; each interior rib flips the turn-gap side, so the final pass
    # (above rib n-1) exits at the end opposite its own entry gap: z-high when
    # (n-1) is odd (n even), z-low otherwise.
    n = max(1, int(round(cfg.n_ch)))
    gap_frac = float(np.clip(cfg.w_ch_mm / max(1e-6, cfg.W_cm * 10.0), 0.06, 0.30))
    n_gap = max(1, int(round(gap_frac * nz)))
    mask = np.zeros(nz, dtype=bool)
    if (n - 1) % 2 == 1:                                 # exit at z-high (right)
        mask[nz - n_gap:] = True
    else:                                                # exit at z-low (left)
        mask[:n_gap] = True
    out = mask & open_row
    return out if out.any() else mask
