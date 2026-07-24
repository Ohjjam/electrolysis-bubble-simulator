"""Track A geometry voxelization + face current redistribution tests.

  * designer flow-field -> solid land mask has the right orientation & fraction
  * obstacles don't break the divergence-free projection
  * face current redistribution conserves charge (mean over active cells)
  * porosity->planar limit: no ribs -> ~uniform current
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bubblesim3d.grid import Grid3D
from bubblesim3d.ns3d import NS3D
from bubblesim3d.geometry import voxelize
from bubblesim3d.faceredist import face_coverage, redistribute, face_maps
from bubblesim3d.params3d import Cell3DConfig, cell_config_from_designer, DESIGNER_DEFAULTS


def _grid():
    return Grid3D(6, 24, 24, 2.0e-3)


# -------------------------------------------------------------- voxelize
def _percolates_2d(open_mask):
    """Flood-fill: does the open channel connect bottom row -> top row?
    Iteration cap = total cells (a serpentine path is ~ny*nz long, far more
    than a straight-line 4*ny)."""
    ny, nz = open_mask.shape
    reach = np.zeros_like(open_mask)
    reach[0] = open_mask[0]
    for _ in range(open_mask.size):
        nb = reach.copy()
        nb[1:] |= reach[:-1]; nb[:-1] |= reach[1:]
        nb[:, 1:] |= reach[:, :-1]; nb[:, :-1] |= reach[:, 1:]
        nb &= open_mask
        if nb.sum() == reach.sum():
            break
        reach = nb
        if reach[-1].any():
            return True
    return bool(reach[-1].any())


def test_serpentine_is_connected_snake():
    """Serpentine lands are horizontal bands WITH a turn gap at alternating
    ends -> one connected snaking channel from inlet to outlet."""
    cfg = Cell3DConfig(ff="serp", n_ch=6, w_ch_mm=1.0, w_land_mm=1.0)
    g = _grid()
    solid, fc, fa = voxelize(cfg, g)
    assert solid.shape == g.shape
    assert solid.any() and not solid.all()
    land2d = ~fc
    # every land row leaves a gap (not full-width) and gaps sit at an end
    gap_sides = []
    for j in range(land2d.shape[0]):
        row = land2d[j]
        if not row.any():
            continue
        assert not row.all(), "land row must keep its turn gap open"
        open_cols = np.nonzero(~row)[0]
        side = 0 if open_cols.max() < land2d.shape[1] / 2 else 1
        # gap is contiguous at one end
        assert open_cols.min() == 0 or open_cols.max() == land2d.shape[1] - 1
        if not gap_sides or gap_sides[-1] != side:
            gap_sides.append(side)
    assert len(gap_sides) >= 3                        # several passes
    assert all(gap_sides[i] != gap_sides[i + 1] for i in range(len(gap_sides) - 1)), \
        "turn gaps must alternate ends (snake)"
    # the open channel percolates inlet -> outlet through the gaps
    assert _percolates_2d(fc)


def test_interior_core_is_solid():
    """The cell interior (PTL + membrane core) carries no free liquid path —
    flow is confined to the two channel layers (zero-gap cell)."""
    cfg = Cell3DConfig(ff="serp", n_ch=6)
    g = _grid()
    solid, fc, fa = voxelize(cfg, g)
    n_lay = max(1, min(cfg.layer_counts()[0], (g.nx - 1) // 2))
    assert solid[n_lay:g.nx - n_lay, :, :].all()


def _band_widths(line):
    """Consecutive-run lengths of a 1-D boolean mask."""
    idx = np.nonzero(line)[0]
    if not len(idx):
        return []
    out, cur = [], 1
    for a, b in zip(idx[:-1], idx[1:]):
        if b == a + 1:
            cur += 1
        else:
            out.append((cur, a - cur + 1)); cur = 1
    out.append((cur, idx[-1] - cur + 1))
    return out


def test_rib_bands_have_uniform_thickness():
    """Every interior rib is the SAME number of cells thick.

    Thresholding cell centres against the land half-width (the old rule) rounds
    differently at each divider, so on a coarse grid some ribs came out 1 cell
    thick, some 2 and some vanished — the visibly uneven bands in the cell view.
    Bands touching a domain edge are half-bands by construction (they are the
    outer walls), so they are excluded.
    """
    g = _grid()
    for ff, axis, n_cells in (("serp", 1, g.ny), ("par", 0, g.nz)):
        for w_land in (0.4, 1.0, 2.0, 3.0):
            cfg = Cell3DConfig(ff=ff, n_ch=6, w_ch_mm=1.0, w_land_mm=w_land)
            line = (~voxelize(cfg, g)[1]).any(axis=axis)   # collapse constant axis
            bands = [w for w, start in _band_widths(line)
                     if start > 0 and start + w < n_cells]
            assert len(bands) >= 3 and len(set(bands)) == 1, \
                (ff, w_land, _band_widths(line))


def test_channels_between_ribs_are_uniform_too():
    """Not just the ribs — the CHANNELS between them must be one thickness.

    With a fractional pass pitch (25 rows / 8 passes = 3.125) the ribs came out
    uniform at 2 cells but the channels alternated 1 and 2 cells: visibly uneven
    flow paths. `grid_dims` now snaps the flow axis to a whole number of passes.
    Bands touching a domain edge are half-bands (the plate wall), so excluded.
    """
    for h_mm in (2.0, 1.0):
        for ff, axis in (("serp", 1), ("par", 0)):
            for n in (2, 4, 6, 8, 12):
                cfg = cell_config_from_designer(
                    {**DESIGNER_DEFAULTS, "ff": ff, "n_ch": n, "h_mm": h_mm})
                nx, ny, nz = cfg.grid_dims()
                g = Grid3D(nx, ny, nz, cfg.h)
                line = (~voxelize(cfg, g)[1]).any(axis=axis)
                L = len(line)
                runs = _band_widths(line)                       # (width, start) of LAND
                inner_ribs = [w for w, st_ in runs if st_ > 0 and st_ + w < L]
                assert len(set(inner_ribs)) <= 1, (ff, n, h_mm, inner_ribs)

                gaps = _band_widths(~line)                      # and the CHANNELS
                inner_ch = [w for w, st_ in gaps if st_ > 0 and st_ + w < L]
                assert len(set(inner_ch)) <= 1, (ff, n, h_mm, inner_ch)


def test_reported_widths_match_the_grid():
    """The pass pitch is H/n_ch (the width sliders only set the ratio) and both
    get quantised to whole cells. `rib_channel_mm()` must report what the grid
    really built, so the UI can say it instead of leaving the user puzzled."""
    cfg = cell_config_from_designer({**DESIGNER_DEFAULTS, "ff": "serp",
                                     "n_ch": 8, "h_mm": 2.0})
    nx, ny, nz = cfg.grid_dims()
    g = Grid3D(nx, ny, nz, cfg.h)
    line = (~voxelize(cfg, g)[1]).any(axis=1)
    L = len(line)
    pitch, rib, chan = cfg.rib_channel_mm()

    ribs = [w for w, st_ in _band_widths(line) if st_ > 0 and st_ + w < L]
    chans = [w for w, st_ in _band_widths(~line) if st_ > 0 and st_ + w < L]
    assert abs(ribs[0] * cfg.h * 1e3 - rib) < 1e-9
    assert abs(chans[0] * cfg.h * 1e3 - chan) < 1e-9
    assert abs(pitch - (rib + chan)) < 1e-9
    assert ny % cfg.n_passes(ny) == 0                   # whole number of passes


def test_grid_does_not_move_when_the_flow_field_changes():
    """Switching a preset over to the hand-drawn plate must not resize the grid.

    It used to: `grid_dims` snapped only for serp/par, so ff='custom' fell back
    to the unsnapped 25 rows. The editor's 24-row drawing was then resampled onto
    25 rows and a 6 mm rib came back as 8 mm — you clicked a template and got a
    different plate. The grid may depend on the cell size and the pass count, and
    on nothing else.
    """
    base = cell_config_from_designer(DESIGNER_DEFAULTS).grid_dims()
    for ff in ("serp", "par", "inter", "custom", "straight"):
        got = cell_config_from_designer({**DESIGNER_DEFAULTS, "ff": ff}).grid_dims()
        assert got == base, (ff, got, base)
    # and the drawn plate survives that switch bit-for-bit (identity resample)
    from bubblesim3d.params3d import encode_mask
    nx, ny, nz = base
    m = np.zeros((ny, nz), bool)
    m[5:8, :nz-3] = True
    cfg = cell_config_from_designer({**DESIGNER_DEFAULTS, "ff": "custom",
                                     "mask": encode_mask(m)})
    land = ~voxelize(cfg, Grid3D(*cfg.grid_dims(), cfg.h))[1]
    assert np.array_equal(land, m)


def test_parallel_bands_span_y():
    """Parallel lands are vertical bands (constant over y, vary over z)."""
    cfg = Cell3DConfig(ff="par", n_ch=6, w_ch_mm=1.0, w_land_mm=1.0)
    g = _grid()
    solid, fc, fa = voxelize(cfg, g)
    land2d = ~fc
    assert np.all(land2d == land2d[:1, :])            # constant across y


def test_land_fraction_tracks_widths():
    """Wider lands -> more solid in the channel layers."""
    g = _grid()
    cfg_thick = Cell3DConfig(ff="par", n_ch=6, w_ch_mm=0.5, w_land_mm=3.0)
    thin = voxelize(Cell3DConfig(ff="par", n_ch=6, w_ch_mm=3.0, w_land_mm=0.5), g)[0]
    thick = voxelize(cfg_thick, g)[0]
    assert thick.sum() > thin.sum()
    # the channel layers themselves keep open (non-land) cells
    n_lay = max(1, min(cfg_thick.layer_counts()[0], (g.nx - 1) // 2))
    assert not thick[:n_lay].all() and not thick[g.nx - n_lay:].all()


# ------------------------------------------------------------ ports / custom
def test_inlet_port_follows_its_position_and_width():
    """in_w > 0 places an explicit inlet port at in_z; in_w == 0 keeps the
    preset's own inlet (serpentine: the end opposite the first turn gap)."""
    from bubblesim3d.geometry import inlet_mask, outlet_mask
    g = _grid()
    auto = Cell3DConfig(ff="serp", n_ch=6)
    land = ~voxelize(auto, g)[1]
    k_auto = np.nonzero(inlet_mask(auto, g, land))[0]
    assert k_auto.max() == g.nz - 1                    # preset: at the z-high end

    left = Cell3DConfig(ff="serp", n_ch=6, in_w=0.12, in_z=0.06)
    right = Cell3DConfig(ff="serp", n_ch=6, in_w=0.12, in_z=0.94)
    kl = np.nonzero(inlet_mask(left, g, land))[0]
    kr = np.nonzero(inlet_mask(right, g, land))[0]
    assert kl.mean() < 0.25 * g.nz < 0.75 * g.nz < kr.mean()
    assert 1 <= len(kl) <= 0.25 * g.nz                # a port, not the whole face


def test_outlet_port_closes_the_rest_of_the_top():
    """out_w == 1 vents the whole top; a value in (0,1) is an explicit port and
    the rest of the top row becomes plate; out_w == 0 is the AUTO exit port."""
    from bubblesim3d.geometry import outlet_mask
    g = _grid()
    full = Cell3DConfig(ff="serp", n_ch=6, out_w=1.0)
    land = ~voxelize(full, g)[1]
    assert outlet_mask(full, g, land).all()

    port = Cell3DConfig(ff="serp", n_ch=6, out_w=0.10, out_z=0.06)
    m = outlet_mask(port, g, land)
    assert 1 <= m.sum() <= 0.25 * g.nz
    assert np.nonzero(m)[0].mean() < 0.25 * g.nz      # sits at the z-low end
    # a port can never close completely: an incompressible inflow needs an exit
    shut = Cell3DConfig(ff="serp", n_ch=6, out_w=0.0, out_z=0.5)
    assert outlet_mask(shut, g, land).sum() >= 1


def test_serpentine_auto_outlet_is_a_port_at_the_snake_end():
    """out_w == 0 (the default) puts a channel-width EXIT port at the last
    pass's far end, mirroring the inlet — not a whole-top vent. The inlet sits
    at the z-high end of the first pass; the exit alternates with n's parity."""
    from bubblesim3d.geometry import inlet_mask, outlet_mask
    g = _grid()
    for n, exit_high in ((6, True), (7, False), (8, True), (9, False)):
        cfg = Cell3DConfig(ff="serp", n_ch=n, out_w=0.0)
        land = ~voxelize(cfg, g)[1]
        ins = np.nonzero(inlet_mask(cfg, g, land))[0]
        outs = np.nonzero(outlet_mask(cfg, g, land))[0]
        assert 1 <= len(outs) <= 0.25 * g.nz, n        # a port, not the whole face
        assert ins.mean() > 0.75 * g.nz, n             # inlet at the z-high end
        end_high = bool(outs.mean() > 0.5 * g.nz)
        assert end_high == exit_high, (n, outs.tolist())   # exit end tracks parity


def test_custom_mask_becomes_the_flow_field():
    """A user-drawn mask is the plate: it resamples onto the grid, survives a
    grid change, and round-trips through the string encoding."""
    from bubblesim3d.params3d import decode_mask, encode_mask
    M = 20
    m = np.zeros((M, M), dtype=bool)
    m[5:7, :15] = True                                # rib with a gap at z-high
    m[13:15, 5:] = True                               # rib with a gap at z-low
    txt = encode_mask(m)
    assert np.array_equal(decode_mask(txt), m)        # round-trip

    cfg = Cell3DConfig(ff="custom", land_mask=m)
    for g in (_grid(), Grid3D(6, 40, 40, 1.2e-3)):    # two different grids
        solid, fc, fa = voxelize(cfg, g)
        land = ~fc
        assert land.shape == (g.ny, g.nz)
        assert abs(land.mean() - m.mean()) < 0.05     # the drawing is preserved
        assert _percolates_2d(~land)                  # still one connected channel


def test_resampling_never_deletes_a_drawn_rib():
    """A rib drawn on ANY row must reach the physics grid.

    Nearest-neighbour resampling of 32 drawn rows onto 25 grid rows never samples
    7 of them (rows 2, 6, 11, 15, 20, 25, 29), so a one-cell rib drawn on 22% of
    the canvas silently vanished — you drew and nothing happened. Area-weighted
    coverage keeps every rib that is at least half a cell thick, and the editor
    now draws AT the grid resolution so the common case is the identity.
    """
    from bubblesim3d.geometry import _resample_mask

    # identity: what the editor actually sends (drawn on the physics grid)
    for j in range(25):
        m = np.zeros((25, 25), bool); m[j, :] = True
        assert _resample_mask(m, 25, 25)[j].all(), f"row {j} lost at identity"

    # a coarser grid may thin a sub-cell rib, but a 2-cell rib always survives
    for j in range(0, 30, 2):
        m = np.zeros((32, 32), bool); m[j:j+2, :] = True
        assert _resample_mask(m, 25, 25).any(), f"2-cell rib at {j} vanished"

    # and the land fraction is preserved, unlike nearest-neighbour
    rng = np.random.default_rng(0)
    for f in (0.2, 0.5):
        m = rng.random((32, 32)) < f
        assert abs(_resample_mask(m, 24, 24).mean() - f) < 0.06


def test_mask_string_carries_its_shape():
    """The grid is rectangular and changes size, so the mask encodes ny,nz."""
    from bubblesim3d.params3d import decode_mask, encode_mask
    m = np.zeros((18, 31), bool); m[7, 3:20] = True
    txt = encode_mask(m)
    assert txt.startswith("18,31:")
    assert np.array_equal(decode_mask(txt), m)
    assert decode_mask("0" * 1024).shape == (32, 32)      # legacy square form
    assert decode_mask("5,5:0101") is None                # wrong bit count
    assert decode_mask("") is None


def test_dead_plates_are_detected():
    """A plate with no inlet->outlet channel cannot conserve mass, so it must be
    detectable rather than silently simulated.

    The interdigitated preset IS such a plate in this model: real interdigitated
    flow fields push the liquid through the porous transport layer, and here the
    core is solid. Measured on the default cell: Qin = 1.1e-5, Qout = 0,
    divergence 0.30 (150x the tolerance), SOR pinned at its cap every step.
    """
    from bubblesim3d.geometry import flow_connects, port_edges
    g = _grid()
    for ff, expect in (("serp", True), ("par", True), ("inter", False)):
        cfg = Cell3DConfig(ff=ff, n_ch=6)
        land = ~voxelize(cfg, g)[1]
        inf, in_line, outf, out_line = port_edges(cfg, g, land)
        assert flow_connects(~land, in_line, inf, out_line, outf) is expect, ff

    # a hand-drawn plate that seals the cell is caught too
    m = np.zeros((20, 20), bool); m[9:11, :] = True          # full-width rib, no gap
    cfg = Cell3DConfig(ff="custom", land_mask=m)
    land = ~voxelize(cfg, g)[1]
    inf, in_line, outf, out_line = port_edges(cfg, g, land)
    assert not flow_connects(~land, in_line, inf, out_line, outf)

    # ... and one with a gap is fine
    m[9:11, :3] = False
    cfg = Cell3DConfig(ff="custom", land_mask=m)
    land = ~voxelize(cfg, g)[1]
    inf, in_line, outf, out_line = port_edges(cfg, g, land)
    assert flow_connects(~land, in_line, inf, out_line, outf)


def test_custom_mask_degenerate_drawings_stay_solvable():
    """An empty drawing is an open duct; a fully-ribbed one still keeps one
    channel — otherwise the projection has no fluid cells and nothing nucleates."""
    g = _grid()
    empty = ~voxelize(Cell3DConfig(ff="custom",
                                   land_mask=np.zeros((16, 16), bool)), g)[1]
    assert not empty.any()

    full = ~voxelize(Cell3DConfig(ff="custom",
                                  land_mask=np.ones((16, 16), bool)), g)[1]
    assert full.any() and not full.all()
    assert _percolates_2d(~full)


def test_custom_mask_ignored_without_a_drawing():
    """ff='custom' with no mask falls back to the serpentine bands, not a
    fully-open (and physically meaningless) empty plate."""
    g = _grid()
    land = ~voxelize(Cell3DConfig(ff="custom", n_ch=6), g)[1]
    assert land.any()


def test_designer_config_voxelizes():
    cfg = cell_config_from_designer(DESIGNER_DEFAULTS)
    g = Grid3D(*cfg.grid_dims(), cfg.h)
    solid, fc, fa = voxelize(cfg, g)
    assert 0 < solid.mean() < 0.9


# --------------------------------------------------- obstacles + projection
def test_projection_divergence_free_with_obstacles():
    # parallel flow field: short straight channels, so the cold SOR solve
    # converges in reasonable iterations (a serpentine is one LONG narrow
    # path — pressure information must travel its whole length, which the
    # warm-started live loop handles incrementally but a cold test cannot)
    g = _grid()
    cfg = Cell3DConfig(ff="par", n_ch=6)
    solid = voxelize(cfg, g)[0]
    ns = NS3D(g, outlet=True)
    ns.set_solid(solid)
    ns.u_in = 0.05
    r = np.random.default_rng(0)
    ns.U = r.standard_normal(ns.U.shape) * 0.01
    ns.V = r.standard_normal(ns.V.shape) * 0.01
    ns.W = r.standard_normal(ns.W.shape) * 0.01
    ns._apply_bc()
    # obstacle geometry adds many internal Neumann walls -> SOR converges more
    # slowly, but the projection is exact (drives fluid divergence to ~0)
    ns.project(2000, warm=False)
    # divergence is measured on FLUID cells (solid cells are excluded from flow)
    div = np.abs(ns._divergence())
    assert div[~ns.solid].max() < 1e-2
    # no flow penetrates a land: blocked faces stay zero
    assert np.abs(ns.U[ns._Ublock]).max() < 1e-12
    assert np.abs(ns.V[ns._Vblock]).max() < 1e-12


# --------------------------------------------------- current redistribution
def test_redistribute_conserves_charge():
    ny, nz = 10, 10
    theta = np.random.default_rng(1).uniform(0, 0.6, (ny, nz))
    jf = redistribute(0.4, theta)
    assert abs(jf.mean() - 0.4) < 1e-9                # mean current preserved
    # more coverage -> less local current (monotone)
    assert jf[np.unravel_index(theta.argmax(), theta.shape)] < \
           jf[np.unravel_index(theta.argmin(), theta.shape)]


def test_redistribute_active_mask_conserves_full_face_charge():
    ny, nz = 8, 8
    theta = np.zeros((ny, nz))
    active = np.ones((ny, nz), dtype=bool)
    active[:, 0] = False                              # a land column
    jf = redistribute(0.5, theta, active)
    assert abs(jf.mean() - 0.5) < 1e-9                # full-face integral conserved
    assert np.all(jf[~active] == 0.0)
    assert jf[active].mean() > 0.5                    # active area carries land current


def test_uniform_when_no_coverage():
    """No bubbles -> uniform current (planar limit)."""
    ny, nz = 12, 12
    jf = redistribute(0.4, np.zeros((ny, nz)))
    assert np.allclose(jf, 0.4)


def test_face_maps_export_coverage_for_3d_analysis():
    class EmptyParcels:
        r = np.array([])

    g = Grid3D(4, 3, 4, 1e-3)
    active = np.ones((g.ny, g.nz), dtype=bool)
    active[:, 0] = False
    maps = face_maps(EmptyParcels(), g, 5000.0, 60.0, active, active, res=2)
    cathode = maps["cathode"]
    assert len(cathode["theta"]) == cathode["ny"] * cathode["nz"]
    theta = np.array(cathode["theta"]).reshape(cathode["ny"], cathode["nz"])
    assert (theta[:, :2] == -1).all()                 # rib/land stays neutral
    assert (theta[:, 2:] == 0).all()                  # open face, no bubbles


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
