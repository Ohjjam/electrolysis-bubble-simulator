"""Configs for the two 3-D tracks + the P1 designer -> engine bridge.

The web3d designer (web3d/index.html, the `P{}` model) is the single source of
cell geometry. `operating_from_designer` / `cell_config_from_designer` map its
keys onto a `bubblesim.Operating` (so the frozen kernel context works
unchanged) plus the 3-D-only geometry numbers the voxelizer needs.
"""
from dataclasses import dataclass, field

from bubblesim.config import Operating


# designer keys we accept, with the same defaults as web3d/index.html CTRL[].
# Operating levers mirror the 2-D app so the full electrochemistry is drivable:
# mode (CA/CP), voltage/current, electrolyte + concentration, catalyst j0,
# membrane resistance, flow/fields/tilt/T/P.
DESIGNER_DEFAULTS = {
    "W_cm": 5.0, "H_cm": 5.0,
    "ff": "serp", "L_flow_cm": 40.0, "n_ch": 8,
    "w_ch_mm": 1.0, "d_ch_mm": 1.0, "w_land_mm": 1.0,
    "t_mem_um": 50.0,
    "t_ptl_um": 200.0,
    # --- flow-field ports (the plate breathes through holes, not whole faces) ---
    # in_w / out_w are port WIDTHS as a fraction of the cell width z.
    #   in_w  = 0  -> "auto": the preset's own inlet (serpentine start / every
    #                 parallel channel). Any value > 0 places an explicit port.
    #   out_w = 0  -> "auto": the preset's own outlet (serpentine EXIT port at
    #                 the snake's end / parallel manifold). out_w = 1 vents the
    #                 whole top face; any value in (0,1) is an explicit port.
    # in_face / out_face pick WHICH edge the port sits on:
    #   bottom = y=0 (with the flow), top = y=Ly, left = z=0, right = z=Lz.
    # in_z / out_z are the fractional position ALONG that edge.
    "in_face": "bottom", "out_face": "top",
    "in_z": 0.94, "in_w": 0.0, "out_z": 0.06, "out_w": 0.0,
    # --- user-drawn flow field: "" = use `ff`; otherwise an N*N string of
    # '0' (channel) / '1' (land) read row-major from y=0 (inlet) upward.
    "mask": "",
    # --- operating levers ---
    "mode": "CP",                # "CP" (fix current) | "CA" (fix voltage)
    "j": 0.5,                    # current density [A/cm^2]  (CP)
    "V_cell": 2.0,               # cell voltage [V]          (CA)
    "electrolyte": "KOH",        # KOH | H2SO4 | PB
    "c_mol": 6.0,                # electrolyte concentration [mol/L]
    "j0_cathode": 130.0,         # HER exchange current density [A/m^2]
    "j0_anode": 1.3e-7,          # OER exchange current density [A/m^2]
    "r_mem": 3.2e-6,             # area membrane resistance [ohm*m^2]
    # Measured system input: zero-flow single-bubble departure diameter.  This
    # replaces the former arbitrary Fritz multiplier (0.08) in the 3-D path.
    "departure_diameter_um": 244.0,
    "dep_grad_um": 100.0,        # DEP proxy gradient length [um]
    # 0.35 m/s: channel mean velocity. Pump flow is derived from the requested
    # physical channel cross-section, not from the coarse live voxel inlet.
    "u_flow": 0.35, "tilt": 0.0, "B": 0.0, "E": 0.0,
    # Measured catalyst/NF gas-bubble angle 145.1 deg -> water-side 34.9 deg.
    "theta": 34.9, "T": 60.0, "Pbar": 1.0,
    # --- electrode kinetics shape + electrolyte-path convention -------------
    "alpha_a": 1.0,              # OER anodic transfer coefficient (Tafel slope lever)
    "gap_mm": 2.0,               # electrode-to-membrane electrolyte gap CONVENTION [mm]
    "C_dl_anode": 0.2,           # anode double-layer capacitance [F/m^2] (EIS only)
    "C_dl_cathode": 0.2,         # cathode double-layer capacitance [F/m^2]
    # --- dry cathode (anolyte-only AEM): membrane water transport -------------
    # OFF by default: every existing cell keeps both electrodes liquid-wetted.
    "dry_cathode": 0,            # 1 = no liquid feed on the cathode side
    "n_drag": 2.5,               # electro-osmotic drag [mol H2O / mol OH-]
    "D_w_mem": 1.0e-9,           # water diffusivity in the membrane [m^2/s]
        # (measured/calibrated r_mem pairs with a gap value; keep them together)
    "h_mm": 2.0,                 # live-grid voxel size [mm] (smaller = finer channels, slower)
    # --- PP-mesh bubble-management interlayer (experiment tab; sweep only) --
    "mesh_id": "",               # MESH_CATALOG id ("" = no mesh)
    "mesh_cover": 1.0,           # fraction of the flow path covered (1 = full)
    "mesh_pos": "outlet",        # partial-cover anchor: inlet | middle | outlet
    # Water-side equivalent of measured PP gas-bubble angle 101.2 deg.
    "mesh_theta": 78.8,
    "mesh_mode": "physical",     # physical | hydrophobic (Mesh 2: no hydraulic thickness)
    "void_frac": 0.82,           # void_ohmic_frac for the polarization sweep
                                 # (fraction of the electrolyte path the channel
                                 # void obstructs; calibrated on the pristine cell)
}

# Polypropylene mesh catalog (industrial PP porous mesh line; hole = mean of
# the two opening dims, inches -> mm). Geometry only -- performance is
# PREDICTED from it, never fitted (blind protocol).
MESH_CATALOG = [
    {"id": "pp_015x015", "name": '0.015"×0.015" — 구멍 0.46 mm · 24% · t 0.76 mm',
     "hole_mm": 0.457, "hole_x_mm": 0.457, "hole_y_mm": 0.457,
     "open": 0.24, "t_mm": 0.762},
    {"id": "pp_025x030", "name": '0.025"×0.030" — 구멍 0.70 mm · 35% · t 0.36 mm',
     "hole_mm": 0.699, "hole_x_mm": 0.635, "hole_y_mm": 0.762,
     "open": 0.35, "t_mm": 0.356},
    {"id": "pp_030x037", "name": '0.030"×0.037" — 구멍 0.85 mm · 20% · t 0.91 mm',
     "hole_mm": 0.851, "hole_x_mm": 0.762, "hole_y_mm": 0.940,
     "open": 0.20, "t_mm": 0.914},
    {"id": "pp_040x053", "name": '0.040"×0.053" — 구멍 1.18 mm · 50% · t 0.48 mm (실측에 사용)',
     "hole_mm": 1.181, "hole_x_mm": 1.016, "hole_y_mm": 1.346,
     "open": 0.50, "t_mm": 0.483},
    {"id": "pp_085x115", "name": '0.085"×0.115" — 구멍 2.54 mm · 35% · t 1.75 mm',
     "hole_mm": 2.540, "hole_x_mm": 2.159, "hole_y_mm": 2.921,
     "open": 0.35, "t_mm": 1.753},
    {"id": "pp_094x094", "name": '0.094"×0.094" — 구멍 2.39 mm · 45% · t 2.03 mm',
     "hole_mm": 2.388, "hole_x_mm": 2.388, "hole_y_mm": 2.388,
     "open": 0.45, "t_mm": 2.032},
    {"id": "pp_120x175", "name": '0.120"×0.175" — 구멍 3.75 mm · 60% · t 0.89 mm',
     "hole_mm": 3.747, "hole_x_mm": 3.048, "hole_y_mm": 4.445,
     "open": 0.60, "t_mm": 0.889},
    {"id": "pp_145x175", "name": '0.145"×0.175" — 구멍 4.06 mm · 70% · t 0.89 mm',
     "hole_mm": 4.064, "hole_x_mm": 3.683, "hole_y_mm": 4.445,
     "open": 0.70, "t_mm": 0.889},
    {"id": "pp_3x3", "name": '3×3 strand/inch — 구멍 7.06 mm · 65% · t 2.29 mm',
     "hole_mm": 7.061, "hole_x_mm": 7.061, "hole_y_mm": 7.061,
     "open": 0.65, "t_mm": 2.286},
]


def mesh_spec(mesh_id):
    for mitem in MESH_CATALOG:
        if mitem["id"] == mesh_id:
            return mitem
    return None


_ELYTES = {"KOH", "H2SO4", "PB"}


def _num(d, k, cast=float):
    v = d.get(k, DESIGNER_DEFAULTS[k])
    try:
        return cast(v)
    except (TypeError, ValueError):
        return cast(DESIGNER_DEFAULTS[k])


def _flag(d, k):
    """Truthiness of a designer toggle. The UI's seg buttons send STRINGS, and
    bool("0") is True — so parse the string form explicitly or an "off" switch
    silently reads as on."""
    v = d.get(k, DESIGNER_DEFAULTS.get(k, 0))
    if isinstance(v, str):
        return v.strip().lower() not in ("", "0", "off", "false", "no")
    return bool(v)


def operating_from_designer(d: dict) -> Operating:
    """Designer dict -> kernel Operating (two-electrode, CA or CP)."""
    mode = "CA" if str(d.get("mode", "CP")).upper() == "CA" else "CP"
    med = d.get("electrolyte", "KOH")
    if med not in _ELYTES:
        med = "KOH"
    return Operating(
        mode=mode,
        j_set=max(0.0, _num(d, "j")) * 1.0e4,          # A/cm^2 -> A/m^2  (CP)
        V_cell=max(0.0, _num(d, "V_cell")),            # V               (CA)
        model="two_electrode",
        track_both=True,
        electrolyte=med,
        c_electrolyte=max(0.1, _num(d, "c_mol")),
        T=_num(d, "T") + 273.15,                        # degC -> K
        P=max(0.1, _num(d, "Pbar")) * 1.0e5,            # bar -> Pa
        contact_angle=_num(d, "theta"),
        mesh_contact_angle=_num(d, "mesh_theta"),
        u_flow=max(0.0, _num(d, "u_flow")),
        B_field=max(0.0, _num(d, "B")),
        E_ext=max(0.0, _num(d, "E")) * 1.0e6,           # MV/m -> V/m
        A_cm2=max(1e-3, _num(d, "W_cm") * _num(d, "H_cm")),
        gap_mm=max(0.05, _num(d, "gap_mm")),
        # dry cathode (anolyte-only AEM): the cathode is fed water ONLY through
        # the membrane. Off by default -> identical to before.
        dry_cathode=_flag(d, "dry_cathode"),
        n_drag=max(0.0, _num(d, "n_drag")),
        D_w_mem=max(0.0, _num(d, "D_w_mem")),
        t_mem_um=max(1.0, _num(d, "t_mem_um")),
        high_fidelity=True,
    )


def sweep_operating(d: dict, j_macm2: float) -> Operating:
    """Designer dict -> a CP channel-model Operating for the polarization
    sweep (the experiment tab's j-V curves). Maps the 3-D designer's flow
    field onto the 1-D channel solver and attaches the mesh interlayer."""
    op = operating_from_designer(d)
    op.mode = "CP"
    op.j_set = max(1.0, float(j_macm2)) * 10.0          # mA/cm^2 -> A/m^2
    op.model = "channel"
    ff = str(d.get("ff", "serp"))
    op.channel_type = "serpentine" if ff in ("serp", "custom") else "parallel"
    op.n_pass = max(1, _num(d, "n_ch", int))
    op.cell_width_cm = max(0.2, _num(d, "W_cm"))
    op.face_height_cm = max(0.2, _num(d, "H_cm"))
    op.chan_depth_mm = max(0.05, _num(d, "d_ch_mm"))
    op.u_flow = max(0.0, _num(d, "u_flow"))
    op.high_fidelity = True          # Gilliam/Pitzer properties: the calibrated
                                     # (j0, alpha_a, r_mem, void_frac) set pairs with these
    op.channel_void_ohmic = True
    op.void_ohmic_frac = min(1.0, max(0.0, _num(d, "void_frac")))
    ms = mesh_spec(str(d.get("mesh_id", "")))
    if ms is not None:
        op.mesh_hole_mm = ms["hole_mm"]
        op.mesh_hole_x_mm = ms.get("hole_x_mm", ms["hole_mm"])
        op.mesh_hole_y_mm = ms.get("hole_y_mm", ms["hole_mm"])
        op.mesh_open = ms["open"]
        op.mesh_t_mm = ms["t_mm"]
        op.mesh_contact_angle = _num(d, "mesh_theta")
        op.mesh_cover = min(1.0, max(0.0, _num(d, "mesh_cover")))
        op.mesh_pos = str(d.get("mesh_pos", "outlet"))
        op.mesh_mode = ("hydrophobic" if str(d.get("mesh_mode", "physical")) == "hydrophobic"
                        else "physical")
    return op


@dataclass
class Cell3DConfig:
    """Track A: cell-scale domain (flow field + gap between the two faces).

    The grid is derived from the designer's physical dims at voxel size `h`,
    capped so the live loop stays interactive. The through-plane extent is the
    channel depth + a free-electrolyte margin per side (zero-gap MEA: bubbles
    live in the channels, the membrane is the mid-plane).
    """
    # geometry (designer)
    W_cm: float = 5.0            # electrode width  -> z extent
    H_cm: float = 5.0            # electrode height -> y extent (flow, buoyancy)
    ff: str = "serp"             # flow-field type: serp | par | inter | custom
    n_ch: int = 8
    w_ch_mm: float = 1.0
    d_ch_mm: float = 1.0
    w_land_mm: float = 1.0
    t_ptl_um: float = 200.0
    t_mem_um: float = 50.0
    tilt: float = 0.0            # cell tilt [deg]: 0 vertical, 90 horizontal
    # ports: which edge, then fractional centre and width ALONG that edge
    in_face: str = "bottom"      # bottom | left | right
    out_face: str = "top"        # top | left | right
    in_z: float = 0.94
    in_w: float = 0.0            # 0 -> the preset's own inlet
    out_z: float = 0.06
    out_w: float = 0.0           # 0 -> the preset's own outlet (serp exit port);
                                 # 1 -> the whole top face vents
    # user-drawn land mask, (M, M) bool, y-major from the inlet row up.
    # Resampled to the grid; only used when ff == "custom".
    land_mask: object = None
    # numerics
    h: float = 2.0e-3            # voxel size [m] (live tier; parcels render as
                                 # spheres regardless, so a coarser flow grid
                                 # barely changes the visual but ~halves cost)
    h_requested: float = 0.0      # requested h before the live-cell safety cap
    max_cells: int = 60_000      # grid safety cap (live interactivity)
    cap_parcels: int = 6000

    def _layer_counts_at(self, h):
        """Channel/core layer counts at a candidate isotropic voxel size."""
        n_lay = max(1, min(4, int(round(self.d_ch_mm * 1e-3 / h + 0.49))))
        core_m = 2.0 * (self.t_ptl_um * 1e-6) + self.t_mem_um * 1e-6
        n_core = max(2, int(round(core_m / h + 0.49)))
        return n_lay, n_core

    def layer_counts(self):
        """(n_lay, n_core): channel-layer and core thickness in voxels.

        n_lay tracks the designer's CHANNEL DEPTH (so the slider genuinely
        deepens the computed channel); the core (PTL + membrane, solid — no
        free liquid path in a zero-gap cell) is at least 2 voxels so the
        membrane plane stays representable.
        """
        return self._layer_counts_at(self.h)

    def effective_h(self):
        """Coarsen h when needed while preserving the requested H/W extents.

        The former cap reduced ny/nz with h unchanged, silently turning a large
        or fine-resolution cell into a physically smaller cell.  Here the safety
        cap changes resolution, never the requested geometry.  A short binary
        search handles the through-plane layer-count discontinuities.
        """
        base = max(1e-6, self.h_requested or self.h)
        H, W = self.H_cm * 1e-2, self.W_cm * 1e-2

        def cells(h):
            n_lay, n_core = self._layer_counts_at(h)
            nx = 2 * n_lay + n_core
            ny = max(8, round(H / h))
            nz = max(6, round(W / h))
            return nx * ny * nz

        if cells(base) <= self.max_cells:
            return base
        lo, hi = base, base
        while cells(hi) > self.max_cells:
            hi *= 1.5
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            if cells(mid) > self.max_cells:
                lo = mid
            else:
                hi = mid
        return hi

    def n_passes(self, dim):
        """Channels the flow axis can actually hold (each needs >= 1 rib cell)."""
        return max(1, min(int(round(self.n_ch)), dim // 2))

    @staticmethod
    def _snap(dim, n):
        """Round the flow axis DOWN to a whole number of passes."""
        pitch = max(2, dim // n)
        return max(4, pitch * n)

    def grid_dims(self):
        """(nx, ny, nz) at voxel h. x is EXACT: 2 channel layers + core (the
        voxelizer and renderer share layer_counts, so the drawn cell is the
        computed domain). y: electrode height, z: width, capped for the live
        loop (the cap never touches x — layers must stay intact).

        The FLOW axis is snapped to a whole number of passes. With a fractional
        pitch (25 rows / 8 passes = 3.125) the ribs come out uniform but the
        channels between them alternate 1 and 2 cells — visibly uneven bands.
        Rounding the axis down to `pitch * n` makes both uniform. It costs at
        most one pitch of electrode height, and the renderer draws the grid, so
        what you see stays what is computed.
        """
        n_lay, n_core = self.layer_counts()
        nx = 2 * n_lay + n_core
        ny = max(8, round(self.H_cm * 1e-2 / self.h))
        nz = max(6, round(self.W_cm * 1e-2 / self.h))
        # snap BOTH in-plane axes, for EVERY flow field. If the snap depended on
        # `ff`, switching a preset over to the hand-drawn plate would change the
        # grid underneath the drawing and resample it — a 6 mm rib came back as
        # 8 mm. The grid must depend only on the cell size and the pass count.
        ny = self._snap(ny, self.n_passes(ny))
        nz = self._snap(nz, self.n_passes(nz))
        return nx, ny, nz

    def rib_channel_mm(self):
        """(pitch, rib, channel) in mm as the GRID actually resolves them.

        The pass pitch is the electrode length divided by `n_ch`; `w_ch_mm` and
        `w_land_mm` only set their RATIO. Both are then quantised to whole cells.
        Reporting the achieved widths is the only honest thing to do — asking for
        1 mm ribs on a 2 mm grid cannot give 1 mm ribs.
        """
        nx, ny, nz = self.grid_dims()
        dim = ny if self.ff in ("serp", "straight") else nz
        n = self.n_passes(dim)
        pitch = max(2, dim // n)
        frac = float(min(0.95, max(0.05, self.w_land_mm / (self.w_ch_mm + self.w_land_mm))))
        rib = max(1, min(pitch - 1, int(frac * pitch + 0.5 - 1e-9)))
        mm = self.h * 1e3
        return pitch * mm, rib * mm, (pitch - rib) * mm

    def channel_area_m2(self):
        """Requested physical channel cross-section of one liquid circuit."""
        paths = self.n_ch if self.ff in ("par", "inter") else 1
        return (max(0.0, self.w_ch_mm) * 1e-3
                * max(0.0, self.d_ch_mm) * 1e-3
                * max(1, int(round(paths))))


def cell_config_from_designer(d: dict) -> Cell3DConfig:
    cfg = Cell3DConfig(
        W_cm=_num(d, "W_cm"), H_cm=_num(d, "H_cm"),
        ff=str(d.get("ff", "serp")),
        n_ch=max(1, _num(d, "n_ch", int)),
        w_ch_mm=_num(d, "w_ch_mm"), d_ch_mm=_num(d, "d_ch_mm"),
        w_land_mm=_num(d, "w_land_mm"),
        t_ptl_um=_num(d, "t_ptl_um"),
        t_mem_um=_num(d, "t_mem_um"),
        tilt=_num(d, "tilt"),
        in_face=str(d.get("in_face", "bottom")),
        out_face=str(d.get("out_face", "top")),
        in_z=_num(d, "in_z"), in_w=_num(d, "in_w"),
        out_z=_num(d, "out_z"), out_w=_num(d, "out_w"),
        land_mask=decode_mask(d.get("mask", "")),
        # voxel size is a designer lever now (fine channels need h < w_ch);
        # clamped so the grid stays live-interactive
        h=min(3.0, max(0.4, _num(d, "h_mm"))) * 1e-3,
    )
    cfg.h_requested = cfg.h
    cfg.h = cfg.effective_h()
    return cfg


def decode_mask(txt):
    """'ny,nz:0101...' -> (ny, nz) bool array, or None. Row-major from y=0 up.

    The editor draws at the PHYSICS grid resolution, which is rectangular and
    changes with the electrode size, so the mask has to carry its own shape.
    A bare square bit-string (the old format) is still accepted.
    """
    if not txt:
        return None
    import numpy as _np
    t = str(txt)
    if ":" in t:
        hdr, bits = t.split(":", 1)
        try:
            ny, nz = (int(v) for v in hdr.split(","))
        except ValueError:
            return None
        bits = "".join(ch for ch in bits if ch in "01")
        if ny < 2 or nz < 2 or len(bits) != ny * nz:
            return None
        return _np.frombuffer(bits.encode(), dtype="S1").reshape(ny, nz) == b"1"
    bits = "".join(ch for ch in t if ch in "01")
    m = int(round(len(bits) ** 0.5))
    if m < 2 or m * m != len(bits):
        return None
    return _np.frombuffer(bits.encode(), dtype="S1").reshape(m, m) == b"1"


def encode_mask(arr):
    """(ny, nz) bool array -> 'ny,nz:0101...' (inverse of decode_mask)."""
    if arr is None:
        return ""
    import numpy as _np
    a = _np.asarray(arr, dtype=bool)
    ny, nz = a.shape
    return "%d,%d:" % (ny, nz) + "".join("1" if v else "0" for v in a.ravel())


@dataclass
class Pore3DConfig:
    """Track B: pore-scale representative volume of one porous electrode."""
    substrate: str = "ni_foam"          # bubblesim.kernel.morphology key
    nanostructure: str = "nanoparticle"
    electrode: str = "HER"              # which gas evolves in this volume
    n: int = 64                         # voxels per edge (64 default, 128 opt-in)
    h_um: float = 0.0                   # voxel size [um]; 0 = derive L_e / n
    j_A_cm2: float = 0.4                # imposed (galvanostatic) current density
    seed: int = 0
    frames: int = 200
    dt_s: float = 1.0e-3                # physics step between frames may subcycle
