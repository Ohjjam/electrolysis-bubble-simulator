"""3-D simulator app server (Track A live + Track B playback).

    python server3d_app.py      (opens http://127.0.0.1:8766 automatically)

Separate from server_app.py (:8765) ON PURPOSE: the deployed 2-D live app and
its Pyodide build pipeline stay untouched; this server needs numpy and the
results/ filesystem (batch playback), which don't belong in that bundle.
Same architecture: LiveSim-style daemon stepping thread + stdlib HTTP.

Endpoints:
    GET  /                 the UI (web3d/app3d.html)
    GET  /web3d/...        static assets (vendored three.js etc.)
    GET  /api3d/state      JSON snapshot of the live cell-scale sim
    POST /api3d/op         {key: value, ...} live parameter updates
    POST /api3d/reset      rebuild the live sim (keeps settings)
    GET  /api3d/runs       list Track B batch runs under results/
    POST /api3d/shutdown   local-only clean stop
"""
import json
import math
import os
import ipaddress
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bubblesim import Params, Simulator
from bubblesim.config import ElectrodeParams
from bubblesim.kernel.meshlayer import operating_mesh_factors
from bubblesim.solvers.channel import ChannelSolver
from bubblesim3d.params3d import (DESIGNER_DEFAULTS, MESH_CATALOG,
                                  cell_config_from_designer, mesh_spec,
                                  operating_from_designer, sweep_operating)
from bubblesim3d.cell3d import CellSim3D

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web3d"
PAGE = WEB / "app3d.html"          # 3-D WebGL render view
PAGE_2D = WEB / "app2d.html"       # flat Canvas-2D panel view (app.html style)
RESULTS = ROOT / "results"

MIME = {".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json",
        ".bin": "application/octet-stream"}


class LiveSim3D:
    """Live Track A (cell-scale 3-D) state + thread-safe control surface.

    Mirrors server_app.LiveSim: a daemon thread advances CellSim3D in
    wall-clock blocks under a lock; the HTTP handlers read snapshots and push
    parameter updates. Geometry edits rebuild the domain; operating levers
    mutate the running sim live.
    """

    NUM_LIMITS = {
        "W_cm": (0.2, 100.0), "H_cm": (0.2, 200.0), "L_flow_cm": (0.1, 1000.0),
        "n_ch": (1, 200), "w_ch_mm": (0.05, 20.0), "d_ch_mm": (0.05, 20.0),
        "w_land_mm": (0.05, 20.0), "t_mem_um": (1.0, 1000.0),
        "t_ptl_um": (5.0, 3000.0),
        "in_z": (0.0, 1.0), "in_w": (0.0, 1.0),
        "out_z": (0.0, 1.0), "out_w": (0.0, 1.0),
        "j": (0.0, 10.0), "V_cell": (0.0, 5.0), "c_mol": (0.01, 20.0),
        "j0_cathode": (1e-12, 1e5), "j0_anode": (1e-12, 1e2),
        "r_mem": (0.0, 1e-3), "fritz_scale": (0.005, 2.0),
        "dep_grad_um": (1.0, 1e6), "u_flow": (0.0, 5.0),
        "tilt": (0.0, 90.0), "B": (0.0, 20.0), "E": (0.0, 50.0),
        # saturation_pressure currently uses the 1--100 C Antoine range.
        "theta": (1.0, 179.0), "T": (0.0, 100.0), "Pbar": (0.1, 200.0),
        "drag_K": (0.0, 1000.0), "alpha_a": (0.1, 2.0),
        "gap_mm": (0.05, 10.0), "C_dl_anode": (1e-3, 100.0),
        "C_dl_cathode": (1e-3, 100.0), "dry_cathode": (0.0, 1.0),
        "n_drag": (0.0, 10.0), "D_w_mem": (1e-12, 1e-7),
        "h_mm": (0.4, 3.0), "mesh_cover": (0.0, 1.0),
        "mesh_theta": (1.0, 179.0), "void_frac": (0.0, 1.0),
    }
    ENUM_VALUES = {
        "ff": {"serp", "par", "inter", "custom", "straight"},
        "mode": {"CP", "CA"}, "electrolyte": {"KOH", "H2SO4", "PB"},
        "in_face": {"bottom", "left", "right"},
        "out_face": {"top", "left", "right"},
        "mesh_pos": {"inlet", "middle", "outlet"},
    }

    DT = 3.0e-3              # sim step [s] (semi-Lagrangian is unconditionally stable)
    BLOCK = 0.012            # wall-clock chunk per loop [s]: small -> lock freed
                             # often (snapshots stay fresh) + frequent frames
    PROJ_ITERS = 80       # CAP; CellSim3D.PROJ_TOL stops the solve early (~52 avg)
    IDLE_PAUSE = 45.0        # [s] no /api3d/state poll for this long -> stop
                             # stepping so an unwatched sim doesn't peg a CPU
                             # core (a viewer's poll wakes it within one loop)

    def __init__(self):
        self.lock = threading.Lock()
        self.designer = dict(DESIGNER_DEFAULTS)
        # Model closures such as fritz_scale are copied from DESIGNER_DEFAULTS
        # by _apply_params instead of being hidden in this constructor.
        self.params = Params()
        self.speed = 1.0
        self.paused = False
        self.last_poll = 0.0     # perf_counter of last /api3d/state poll
                                 # (0 -> starts idle; no CPU until a viewer)
        self.speed_actual = 0.0
        self._carry = 0.0        # fractional sim steps carried between blocks
        self._build()

    @staticmethod
    def _f(d, k, fallback):
        """float(designer[k]) that can never raise. A bare float() here used to
        blow up on a None/garbage value that `update` had ALREADY committed to
        self.designer — after which every later /api3d/op AND /api3d/reset raised
        too, bricking the live sim until the process was restarted (the browser
        swallows the error, so the UI just went dead)."""
        try:
            v = float(d.get(k, fallback))
        except (TypeError, ValueError):
            return float(fallback)
        return v if math.isfinite(v) else float(fallback)

    def _apply_params(self, d=None, params=None):
        """Push catalyst j0 + membrane resistance from the designer into Params
        (these live on Params, not Operating — like server_app._apply_catalyst)."""
        d = self.designer if d is None else d
        p = self.params if params is None else params
        p.cathode.j0_ref = max(1e-9, self._f(d, "j0_cathode", 130.0))
        p.anode.j0_ref = max(1e-12, self._f(d, "j0_anode", 1.3e-7))
        p.anode.alpha_a = min(2.0, max(0.1, self._f(d, "alpha_a", 1.0)))
        p.r_membrane_area = max(0.0, self._f(d, "r_mem", 3.2e-6))
        p.fritz_scale = self._f(d, "fritz_scale", 0.08)
        p.dep_gradient_length = self._f(d, "dep_grad_um", 100.0) * 1e-6
        # Double-layer capacitance is used by the EIS path only. The live CP
        # state is algebraic and has no hidden RC relaxation.
        p.anode.C_dl = max(1e-3, self._f(d, "C_dl_anode", 0.2))
        p.cathode.C_dl = max(1e-3, self._f(d, "C_dl_cathode", 0.2))
        return p

    def _construct(self, designer):
        params = self._apply_params(designer, Params())
        cfg = cell_config_from_designer(designer)
        op = operating_from_designer(designer)
        sim = CellSim3D(op, params, cfg.grid_dims(), h=cfg.h,
                        cap=cfg.cap_parcels, tilt=cfg.tilt, seed=0, cfg=cfg)
        sim.ns.drag_K = float(designer["drag_K"])
        return params, cfg, sim

    def _build(self):
        """(Re)create the cell sim from the current designer state."""
        self.params, self.cfg, self.sim = self._construct(self.designer)

    GEOM_KEYS = {"W_cm", "H_cm", "ff", "n_ch", "w_ch_mm", "d_ch_mm",
                 "w_land_mm", "t_ptl_um", "t_mem_um",
                 # ports + the user-drawn plate: all rebuild the voxel domain
                 "in_z", "in_w", "out_z", "out_w", "mask",
                 "in_face", "out_face",
                 "h_mm", "dry_cathode"}     # hydraulic boundary also rebuilds

    @staticmethod
    def _clean(k, v):
        """Value accepted for designer key `k`, or None to REJECT it.

        Validation happens BEFORE the value is stored. It used to be stored first
        and coerced later, so one bad value (e.g. `{"j0_cathode": null}` — and
        note JSON.stringify turns any NaN into null) poisoned self.designer
        permanently: every later update AND reset then raised. A saved experiment
        could persist the poison across restarts.
        """
        ref = DESIGNER_DEFAULTS[k]
        if k in LiveSim3D.ENUM_VALUES:
            return v if isinstance(v, str) and v in LiveSim3D.ENUM_VALUES[k] else None
        if k == "mesh_id":
            valid = {""} | {m["id"] for m in MESH_CATALOG}
            return v if isinstance(v, str) and v in valid else None
        if k == "mask":
            if not isinstance(v, str) or len(v) > 1_000_000:
                return None
            from bubblesim3d.params3d import decode_mask
            return v if (v == "" or decode_mask(v) is not None) else None
        if isinstance(ref, str):
            return v if isinstance(v, str) else None
        # numeric key: accept anything float() understands, but it must be FINITE.
        # (The seg toggles send "0"/"1" strings; float() takes those, and _flag
        # then reads the number correctly.)
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(f):
            return None
        lo, hi = LiveSim3D.NUM_LIMITS.get(k, (-1e12, 1e12))
        return f if lo <= f <= hi else None

    def update(self, data: dict):
        with self.lock:
            candidate = dict(self.designer)
            rebuild = False
            accepted, rejected = {}, {}
            for k, v in data.items():
                if k == "speed":
                    # down to 0.01x: true slow motion ("high-speed camera")
                    try:
                        s = float(v)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(s):
                        self.speed = max(0.01, min(5.0, s))
                        accepted[k] = self.speed
                    else:
                        rejected[k] = "finite number required"
                elif k == "paused":
                    self.paused = bool(v)
                    accepted[k] = self.paused
                elif k in DESIGNER_DEFAULTS:
                    cv = self._clean(k, v)
                    if cv is None:              # garbage: drop it, keep the sim alive
                        rejected[k] = "invalid value or outside supported range"
                        continue
                    if candidate.get(k) == cv:
                        continue            # unchanged: re-applying an experiment
                                            # must not trigger a pointless rebuild
                    candidate[k] = cv
                    accepted[k] = cv
                    if k in self.GEOM_KEYS:
                        rebuild = True
                else:
                    rejected[k] = "unknown key"
            # A drawn mask is authoritative only for ff="custom". Keeping a
            # stale mask beside serp/par/inter makes the UI say "serpentine"
            # while the solver and 3-D ribs still use an old drawing. Enforce
            # the invariant server-side as well as in both front-ends so cached
            # browsers and saved/legacy state cannot recreate that mismatch.
            if candidate.get("ff") != "custom" and candidate.get("mask"):
                candidate["mask"] = ""
                accepted["mask"] = ""
                rebuild = True
            if rebuild:
                # Build first, commit second: a failed geometry never poisons the
                # live designer or replaces the last valid simulation.
                params, cfg, sim = self._construct(candidate)
                self.designer = candidate
                self.params, self.cfg, self.sim = params, cfg, sim
            else:                                   # operating levers: live
                op = operating_from_designer(candidate)
                self.designer = candidate
                self._apply_params()                # catalyst / membrane R
                self.sim.set_operating(op, tilt=float(self.designer.get("tilt", 0.0)))
                self.sim.ns.drag_K = float(self.designer["drag_K"])
            return {"ok": 1, "accepted": accepted, "rejected": rejected}

    def reset(self):
        with self.lock:
            self._build()

    def _advance(self, budget):
        with self.lock:
            # accumulate FRACTIONAL steps so very low speeds actually slow the
            # sim (the old max(1, round(...)) floored the rate at ~0.25x —
            # slow-motion below that silently didn't work)
            nf = budget * self.speed / self.DT + self._carry
            n = int(nf)
            self._carry = nf - n
            for _ in range(n):
                self.sim.step(self.DT, proj_iters=self.PROJ_ITERS)
        return n * self.DT

    def run_forever(self):
        while True:
            start = time.perf_counter()
            # auto-pause when unwatched: if no client polled /api3d/state within
            # IDLE_PAUSE seconds, skip stepping (frees the CPU; the next poll
            # wakes it within one loop). Manual pause is still honored too.
            idle = (start - self.last_poll) > self.IDLE_PAUSE
            if self.paused or idle:
                self.speed_actual *= 0.8
                time.sleep(0.1 if idle else 0.06)
                continue
            adv = self._advance(self.BLOCK)
            elapsed = time.perf_counter() - start
            time.sleep(max(0.003, self.BLOCK - elapsed))
            total = time.perf_counter() - start
            self.speed_actual = 0.8 * self.speed_actual + 0.2 * (adv / max(total, 1e-9))

    def snapshot(self, faces=False) -> dict:
        # faces (the electrode current maps) are heavy at high resolution and
        # evolve slowly -> the client requests them only every few polls
        with self.lock:
            snap = self.sim.snapshot(with_faces=faces)
            snap.update({
                "phase": "P1",
                "paused": self.paused,
                "speed": self.speed,
                "speed_actual": round(self.speed_actual, 3),
                "designer": self.designer,
                "op": {"j_set": self.sim.op.j_set, "T": self.sim.op.T,
                       "P": self.sim.op.P, "u_flow": self.sim.op.u_flow,
                       "tilt": self.sim.tilt},
                "vslice": self.sim.velocity_slice(0.5),
            })
            return snap


# ---------------------------------------------------------------- j-V sweep
# The experiment tab's polarization curves: the 1-D channel bottleneck model
# (bubblesim.solvers.channel) run point-by-point in CP mode with the designer's
# calibrated kinetics. Stateless w.r.t. the live 3-D sim; cached by settings.
SWEEP_J = [10, 20, 50, 100, 200, 300, 400, 500, 625, 750, 875,
           1000, 1250, 1500, 2000, 2250]                 # mA/cm^2
_sweep_cache = {}

_SWEEP_KEYS = ("W_cm", "H_cm", "ff", "n_ch", "w_ch_mm", "d_ch_mm", "u_flow",
               "electrolyte", "c_mol", "T", "Pbar", "theta",
               "j0_cathode", "j0_anode", "alpha_a", "r_mem", "gap_mm", "void_frac",
               "mesh_id", "mesh_cover", "mesh_pos", "mesh_theta", "fritz_scale",
               # dry cathode (anolyte-only AEM) membrane water transport
               "dry_cathode", "n_drag", "D_w_mem", "t_mem_um")


def _sweep_params(d: dict) -> Params:
    return Params(
        fritz_scale=max(0.005, float(d.get("fritz_scale", 0.08))),
        anode=ElectrodeParams("OER", j0_ref=max(1e-12, float(d.get("j0_anode", 1.3e-7))),
                              alpha_a=min(2.0, max(0.1, float(d.get("alpha_a", 1.0)))),
                              Ea_j0=50.0e3),
        cathode=ElectrodeParams("HER", j0_ref=max(1e-9, float(d.get("j0_cathode", 130.0))),
                                Ea_j0=30.0e3),
        r_membrane_area=max(0.0, float(d.get("r_mem", 3.2e-6))))


def _sweep_one(d: dict, with_mesh: bool):
    """One polarization curve (channel model). with_mesh=False strips the mesh."""
    d = dict(d)
    if not with_mesh:
        d["mesh_id"] = ""
    solver = ChannelSolver()
    params = _sweep_params(d)
    # j_used = the current the solver ACTUALLY delivered. With a dry cathode the
    # water-supply wall clamps j below the requested value, and plotting V at the
    # requested abscissa drew the curve at the wrong x (and flat past the wall).
    # The chart/CSV must use j_used, and points where it fell short are simply
    # UNREACHABLE for this cell.
    out = {"V": [], "theta_out": [], "eps_out": [], "j_used": [], "reachable": []}
    st = None
    for j in SWEEP_J:
        op = sweep_operating(d, j)
        sim = Simulator(op=op, params=params)
        st = solver.solve(op, sim.props(), sim.surfaces)
        j_used = float(st.j) / 10.0                      # A/m^2 -> mA/cm^2
        out["V"].append(round(float(st.V), 4))
        out["j_used"].append(round(j_used, 1))
        out["reachable"].append(bool(j_used >= 0.999 * j))
        out["theta_out"].append(round(st.fields["theta_out"], 4))
        out["eps_out"].append(round(st.fields["eps_out"], 4))
    ov = st.overpotentials                                # split at the last (max) j
    out["split_jmax"] = {k: round(float(v), 4) for k, v in ov.items()
                         if isinstance(v, (int, float))}
    out["prof_jmax"] = st.fields.get("path_prof")
    out["mesh_warn"] = st.fields.get("mesh_warn", "")
    out["mesh_on"] = bool(st.fields.get("mesh_on", False))
    out["mesh_physics"] = {k.removeprefix("mesh_"): st.fields[k]
                           for k in ("mesh_bubble_d_mm", "mesh_contact_prob",
                                     "mesh_wetting_drive", "mesh_capture_eff",
                                     "mesh_obstruction", "mesh_u_boost",
                                     "mesh_dp_ratio", "mesh_blocking_fraction",
                                     "mesh_electrode_angle", "mesh_contact_angle")
                           if k in st.fields}
    return out


def sweep_polarization(designer: dict, overrides: dict) -> dict:
    d = {k: designer.get(k, DESIGNER_DEFAULTS.get(k)) for k in _SWEEP_KEYS}
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            if k not in _SWEEP_KEYS:
                continue
            # drop non-finite numbers (json.loads accepts NaN/Infinity by default,
            # which would poison the sweep or crash _sweep_params); keep the
            # designer value in that case. Strings/segs pass through untouched.
            if isinstance(v, float) and not math.isfinite(v):
                continue
            d[k] = v
    key = json.dumps(d, sort_keys=True)
    if key in _sweep_cache:
        return _sweep_cache[key]
    res = {"j": SWEEP_J, "pristine": _sweep_one(d, False)}
    # dry-cathode water-supply ceiling: the current the membrane can keep fed.
    # 0 when the term is off. Reported so the tab can say "you are at X% of it".
    from bubblesim.kernel import watertransport as _wt
    _op0 = sweep_operating(d, SWEEP_J[-1])
    _kw, _jw = _wt.dry_cathode_terms(_op0, float(d.get("t_mem_um", 50.0)) * 1e-6)
    res["water"] = {"k_w": round(_kw, 5),
                    "j_lim_water_mAcm2": round(_jw / 10.0, 1)}   # A/m^2 -> mA/cm^2
    ms = mesh_spec(str(d.get("mesh_id", "")))
    if ms is not None:
        res["mesh"] = _sweep_one(d, True)
        res["mesh_info"] = dict(ms)
        res["mesh_info"].update(res["mesh"].get("mesh_physics", {}))
        res["mesh_info"]["warn"] = res["mesh"].get("mesh_warn", "")
    else:
        res["mesh"] = None
        res["mesh_info"] = None
    res["settings"] = d
    if len(_sweep_cache) > 40:                            # tiny LRU-ish reset
        _sweep_cache.clear()
    _sweep_cache[key] = res
    return res


def mesh_catalog_status(designer: dict) -> list:
    """Catalog + mountability at the CURRENT channel depth (fits badges)."""
    out = []
    for ms in MESH_CATALOG:
        d = dict(designer)
        d["mesh_id"] = ms["id"]
        op = sweep_operating(d, 1000.0)
        sim = Simulator(op=op, params=_sweep_params(d))
        f = operating_mesh_factors(op, sim.props(), op.j_set)
        e = dict(ms)
        e.update({"fits": f["fits"], "warn": f["warn"],
                  "bubble_d_mm": round(f["bubble_d_mm"], 4),
                  "contact_prob": round(f["contact_prob"], 3),
                  "wetting_drive": round(f["wetting_drive"], 3),
                  "capture_eff": round(f["capture_eff"], 3),
                  "u_boost": round(f["u_boost"], 2),
                  "dp_ratio": round(f["dp_ratio"], 2)})
        out.append(e)
    return out


def list_runs() -> list:
    """Track B batch runs: finished (results/<run>/manifest.json) + active jobs."""
    runs = []
    if RESULTS.is_dir():
        for d in RESULTS.iterdir():
            man = d / "manifest.json"
            if d.is_dir() and man.is_file():
                try:
                    m = json.loads(man.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                runs.append({"run": d.name,
                             "frames": m.get("frames", 0),
                             "grid": m.get("grid", 0),
                             "substrate": m.get("substrate", "?"),
                             "created": m.get("created", ""),
                             "status": "done"})
    with JOBS_LOCK:
        active = {name: dict(info) for name, info in JOBS.items()
                  if info["status"] != "done"}
    for name, info in active.items():
        if not any(r["run"] == name for r in runs):
            runs.append({"run": name, "frames": info.get("frames", 0),
                         "grid": info.get("grid", 0),
                         "substrate": info.get("substrate", "?"),
                         "created": "", "status": info["status"],
                         "progress": info.get("progress", 0)})
    runs.sort(key=lambda r: r["run"], reverse=True)
    return runs


JOBS = {}                       # name -> {status, progress, ...}
JOBS_LOCK = threading.Lock()


# ----------------------- user-saved experiments (designer snapshots) --------
# Each experiment = a full designer dict (flow field incl. hand-drawn mask,
# dimensions, operating point, catalysts) + name/note. Persisted to a JSON file
# next to the server so saved conditions survive restarts and travel with the
# cloud deploy. The UI shows one tab per experiment.
EXP_FILE = ROOT / "experiments.json"
EXP_LOCK = threading.Lock()
# which saved experiment the running sim was last set to. In-memory on purpose:
# a server restart rebuilds the sim from defaults, so "no active experiment" is
# then the truth. Both pages read it (GET) so a choice made in one page shows
# up in the other's selector.
ACTIVE_EXP = None


def _exp_load() -> list:
    """Saved experiments, with malformed entries dropped.

    Entries are indexed as ex["id"] / ex["designer"] all over; a hand-edited or
    truncated file used to raise KeyError/TypeError deep inside a handler.
    """
    try:
        data = json.loads(EXP_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for ex in data:
        if not isinstance(ex, dict) or not isinstance(ex.get("id"), str):
            continue
        ex.setdefault("name", ex["id"])
        ex.setdefault("note", "")
        ex.setdefault("created", "")
        if not isinstance(ex.get("designer"), dict):
            ex["designer"] = {}
        out.append(ex)
    return out


def _clean_designer(d) -> dict:
    """Only known designer keys, only values the live sim can actually take."""
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, v in d.items():
        if k not in DESIGNER_DEFAULTS:
            continue
        cv = LiveSim3D._clean(k, v)
        if cv is not None:
            out[k] = cv
    return out


def _exp_save(lst: list):
    EXP_FILE.write_text(json.dumps(lst, ensure_ascii=False, indent=1),
                        encoding="utf-8")


def experiments_api(data: dict) -> dict:
    """save / update / delete / apply a named experiment; returns list+active."""
    global ACTIVE_EXP
    action = str(data.get("action", ""))
    if action == "apply":
        # set the running sim to this experiment's saved designer, and remember
        # it as the active one (both pages' selectors show it)
        with EXP_LOCK:
            lst = _exp_load()
            eid = data.get("id") or None
            if eid is None:                          # "no experiment": just clear
                ACTIVE_EXP = None
                return {"ok": 1, "active": None, "list": lst}
            hit = next((ex for ex in lst if ex["id"] == eid), None)
            if hit is None:
                return {"error": "experiment not found"}
            ACTIVE_EXP = eid
            designer = _clean_designer(hit.get("designer"))
        # LIVE.update outside EXP_LOCK: a geometry change rebuilds the voxel
        # domain for seconds and must not block the other page's list fetch
        LIVE.update(designer)
        return {"ok": 1, "active": eid, "list": lst}
    with EXP_LOCK:
        lst = _exp_load()
        if action == "save":
            name = str(data.get("name", "")).strip()
            if not name:
                return {"error": "name required"}
            ex = {"id": "exp%d" % int(time.time() * 1000),
                  "name": name[:60],
                  "note": str(data.get("note", ""))[:300],
                  "created": time.strftime("%Y-%m-%d %H:%M"),
                  "designer": _clean_designer(data.get("designer"))}
            lst.append(ex)
            _exp_save(lst)
            return {"ok": 1, "id": ex["id"], "list": lst}
        if action == "update":
            for ex in lst:
                if ex["id"] == data.get("id"):
                    if "name" in data and str(data["name"]).strip():
                        ex["name"] = str(data["name"]).strip()[:60]
                    if "note" in data:
                        ex["note"] = str(data["note"])[:300]
                    if "designer" in data:
                        ex["designer"] = _clean_designer(data["designer"])
                    _exp_save(lst)
                    return {"ok": 1, "id": ex["id"], "list": lst}
            return {"error": "experiment not found"}
        if action == "delete":
            kept = [ex for ex in lst if ex["id"] != data.get("id")]
            if len(kept) == len(lst):
                return {"error": "experiment not found"}
            if ACTIVE_EXP == data.get("id"):
                ACTIVE_EXP = None
            _exp_save(kept)
            return {"ok": 1, "active": ACTIVE_EXP, "list": kept}
    return {"error": "unknown action"}


# -------------------------- natural-language AI designer -------------------
# API keys never enter a browser bundle, saved experiment, file, or response.
# OPENAI_API_KEY is preferred; the optional UI key is process-memory only and
# disappears when the local simulator server stops.
AI_LOCK = threading.Lock()
AI_PROVIDER = "openai"
AI_PROVIDER_MODELS = {
    "openai": ("gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol"),
    "google": ("gemini-3.1-flash-lite", "gemini-3.5-flash",
               "gemini-3.1-pro-preview"),
    "anthropic": ("claude-haiku-4-5", "claude-sonnet-5",
                  "claude-opus-4-8", "claude-fable-5"),
    # OpenRouter also accepts a validated custom model slug. These presets cover
    # the free router and a few broadly useful low-cost/provider choices.
    "openrouter": ("openrouter/free", "google/gemini-3.1-flash-lite",
                   "openai/gpt-5.4-nano", "anthropic/claude-sonnet-5"),
}
AI_ENV_KEYS = {
    "openai": ("OPENAI_API_KEY",),
    "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
}
AI_SESSION_KEYS = {provider: "" for provider in AI_PROVIDER_MODELS}
AI_MODELS = {provider: models[0] for provider, models in AI_PROVIDER_MODELS.items()}

AI_FLOW_KEYS = {"ff", "mask", "in_face", "out_face"}
AI_NUMERIC_KEYS = {
    k for k, v in DESIGNER_DEFAULTS.items()
    if not isinstance(v, str)
} | {"speed"}
AI_ENUM_KEYS = {
    k for k in LiveSim3D.ENUM_VALUES
    if k not in AI_FLOW_KEYS
} | {"mesh_id"}

# These are inputs to or closures inside this simulator, not universal physical
# constants. The UI labels them so natural-language editing does not turn a
# fitted number into an apparently fundamental property.
AI_MODEL_PARAMETERS = {
    "j0_cathode", "j0_anode", "alpha_a", "r_mem",
    "fritz_scale", "dep_grad_um", "drag_K", "gap_mm",
    "C_dl_anode", "C_dl_cathode", "n_drag", "D_w_mem",
    "void_frac",
}

AI_SETTING_NOTES = {
    "W_cm": "electrode width [cm]", "H_cm": "electrode height [cm]",
    "L_flow_cm": "effective flow-path length [cm]",
    "n_ch": "number of channels", "w_ch_mm": "channel width [mm]",
    "d_ch_mm": "channel depth [mm]", "w_land_mm": "rib width [mm]",
    "t_mem_um": "membrane thickness [um]", "t_ptl_um": "PTL thickness [um]",
    "in_z": "inlet position fraction", "in_w": "inlet width fraction; 0=auto",
    "out_z": "outlet position fraction", "out_w": "outlet width fraction; 0=auto",
    "mode": "CP=current controlled, CA=voltage controlled",
    "j": "current density [A/cm2] in CP", "V_cell": "cell voltage [V] in CA",
    "electrolyte": "electrolyte family", "c_mol": "electrolyte concentration [mol/L]",
    "j0_cathode": "HER exchange-current model/material parameter [A/m2]",
    "j0_anode": "apparent OER exchange-current fitted parameter [A/m2]",
    "alpha_a": "OER anodic transfer coefficient model parameter",
    "r_mem": "area membrane/contact resistance, often fitted [ohm m2]",
    "fritz_scale": "bubble departure-size closure/calibration factor",
    "dep_grad_um": "DEP proxy gradient length, model closure [um]",
    "u_flow": "mean channel liquid velocity [m/s]",
    "tilt": "cell tilt from vertical [deg]", "B": "magnetic field [T]",
    "E": "reference electric field for DEP proxy [MV/m]",
    "theta": "electrode water contact angle [deg]",
    "T": "temperature [degC]", "Pbar": "pressure [bar]",
    "drag_K": "bubble-to-flow blocking closure [1/s per void]",
    "gap_mm": "electrolyte path-length convention paired with fitted resistance [mm]",
    "C_dl_anode": "anode double-layer capacitance model input [F/m2]",
    "C_dl_cathode": "cathode double-layer capacitance model input [F/m2]",
    "dry_cathode": "0=both sides wetted, 1=anolyte-only dry cathode",
    "n_drag": "electro-osmotic water drag model/material parameter",
    "D_w_mem": "membrane water diffusivity model/material parameter [m2/s]",
    "h_mm": "live 3D voxel size [mm]; smaller is slower",
    "mesh_cover": "fraction of path covered by mesh",
    "mesh_theta": "mesh water contact angle [deg]",
    "void_frac": "calibrated fraction of electrolyte path obstructed by channel void",
    "speed": "visual simulation time scale; does not change polarization physics",
    "mesh_id": "mesh catalog identifier; empty string means no mesh",
    "mesh_pos": "partial mesh position",
}


def _valid_ai_model(provider, model):
    if provider not in AI_PROVIDER_MODELS or not isinstance(model, str):
        return False
    if model in AI_PROVIDER_MODELS[provider]:
        return True
    if provider == "openrouter":
        return (1 <= len(model) <= 160
                and model.count("/") == 1
                and not model.startswith(("/", "http:", "https:"))
                and not model.endswith("/")
                and all(ch.isalnum() or ch in "._:/-" for ch in model))
    return False


def _ai_environment_key(provider):
    for name in AI_ENV_KEYS.get(provider, ()):
        key = os.environ.get(name, "").strip()
        if key:
            return key, name
    return "", ""


def _ai_key_status(provider=None):
    provider = provider if provider in AI_PROVIDER_MODELS else AI_PROVIDER
    env_key, env_name = _ai_environment_key(provider)
    if env_key:
        source, configured = "environment", True
    else:
        with AI_LOCK:
            configured = bool(AI_SESSION_KEYS[provider])
        source = "session" if configured else "none"
    with AI_LOCK:
        model = AI_MODELS[provider]
    return {"configured": configured, "source": source, "provider": provider,
            "environment_name": env_name, "model": model,
            "local_only": True, "key_persisted": False}


def _ai_get_key(provider):
    key, _name = _ai_environment_key(provider)
    if key:
        return key
    with AI_LOCK:
        return AI_SESSION_KEYS[provider]


def _ai_set_session(data):
    global AI_PROVIDER
    provider = str(data.get("provider", AI_PROVIDER))
    if provider not in AI_PROVIDER_MODELS:
        return {"error": "unsupported provider"}
    with AI_LOCK:
        current_model = AI_MODELS[provider]
    model = str(data.get("model", current_model))
    if not _valid_ai_model(provider, model):
        return {"error": "unsupported model"}
    key_present = "key" in data
    key = str(data.get("key", "")).strip() if key_present else None
    if key and (len(key) < 20 or any(ch.isspace() for ch in key)):
        return {"error": "invalid API key format"}
    with AI_LOCK:
        AI_PROVIDER = provider
        AI_MODELS[provider] = model
        if data.get("clear"):
            AI_SESSION_KEYS[provider] = ""
        elif key_present:
            AI_SESSION_KEYS[provider] = key or ""
    return {"ok": 1, **_ai_key_status(provider)}


def _ai_schema():
    numeric = sorted(AI_NUMERIC_KEYS)
    enums = sorted(AI_ENUM_KEYS)

    def change_schema(keys, value_type):
        return {
            "type": "object", "additionalProperties": False,
            "properties": {
                "key": {"type": "string", "enum": keys},
                "value": {"type": value_type},
                "reason": {"type": "string"},
            },
            "required": ["key", "value", "reason"],
        }

    test_schema = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "objective": {"type": "string"},
            "numeric_changes": {
                "type": "array", "maxItems": 16,
                "items": change_schema(numeric, "number"),
            },
            "enum_changes": {
                "type": "array", "maxItems": 8,
                "items": change_schema(enums, "string"),
            },
        },
        "required": ["name", "objective", "numeric_changes", "enum_changes"],
    }
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "numeric_changes": {
                "type": "array", "maxItems": 24,
                "items": change_schema(numeric, "number"),
            },
            "enum_changes": {
                "type": "array", "maxItems": 12,
                "items": change_schema(enums, "string"),
            },
            "flow": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "action": {"type": "string",
                               "enum": ["keep", "template", "custom"]},
                    "template": {"type": "string",
                                 "enum": ["serp", "par", "straight"]},
                    "ny": {"type": "integer", "minimum": 0, "maximum": 64},
                    "nz": {"type": "integer", "minimum": 0, "maximum": 64},
                    "rows": {"type": "array", "maxItems": 64,
                             "items": {"type": "string"}},
                    "in_face": {"type": "string",
                                "enum": ["bottom", "left", "right"]},
                    "out_face": {"type": "string",
                                 "enum": ["top", "left", "right"]},
                    "reason": {"type": "string"},
                },
                "required": ["action", "template", "ny", "nz", "rows",
                             "in_face", "out_face", "reason"],
            },
            "tests": {"type": "array", "maxItems": 3, "items": test_schema},
            "warnings": {"type": "array", "maxItems": 8,
                         "items": {"type": "string"}},
        },
        "required": ["summary", "numeric_changes", "enum_changes",
                     "flow", "tests", "warnings"],
    }


def _ai_context(current, speed):
    settings = {}
    for key in sorted(AI_NUMERIC_KEYS | AI_ENUM_KEYS):
        if key == "speed":
            value = speed
            limits = [0.01, 5.0]
        else:
            value = current.get(key, DESIGNER_DEFAULTS.get(key))
            limits = list(LiveSim3D.NUM_LIMITS[key]) if key in LiveSim3D.NUM_LIMITS else None
        item = {"current": value, "note": AI_SETTING_NOTES.get(key, "")}
        if limits:
            item["range"] = limits
        if key in AI_ENUM_KEYS:
            if key == "mesh_id":
                item["allowed"] = [""] + [m["id"] for m in MESH_CATALOG]
            else:
                item["allowed"] = sorted(LiveSim3D.ENUM_VALUES[key])
        item["classification"] = "model_or_fitted" if key in AI_MODEL_PARAMETERS else "physical_or_operating"
        settings[key] = item
    return settings


def _ai_instructions(language):
    answer_language = "English" if language == "en" else "Korean"
    return f"""
You design safe, reviewable inputs for an electrochemical bubble simulator.
Return the requested JSON schema only, written in {answer_language}.

Hard constraints:
- Never output code, formulas to execute, shell commands, or new parameter keys.
- The model has surface reactions and channel-scale 3D flow. It does NOT model
  penetration/infiltration through porous electrodes or through-plane PTL flow.
- Never select or imitate an interdigitated flow field because it requires the
  unsupported through-PTL path. Use serpentine, parallel, straight, or a custom
  connected surface channel.
- For a custom flow, rows[0] is the bottom/inlet edge and "0" means open channel,
  "1" means solid rib. The open cells must connect inlet edge to outlet edge.
- Treat entries classified model_or_fitted as model/material/fitted parameters,
  never as universal physical constants. Warn before changing them.
- Do not claim a proposed setting was tested. The local server performs the
  geometry and reduced-order polarization tests after your plan is returned.
- Keep changes minimal. Use tests for at most three meaningful alternative
  scalar configurations. Custom mask performance is not resolved by the 1-D
  polarization test; only connectivity and 3-D geometry build are checked.
""".strip()


def _openai_output_text(payload):
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    chunks = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for part in item.get("content", []):
            if isinstance(part, dict) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
            elif isinstance(part, dict) and part.get("type") == "refusal":
                raise ValueError(str(part.get("refusal") or "model refused request"))
    if not chunks:
        raise ValueError("OpenAI response did not contain structured output")
    return "".join(chunks)


def _ai_request_input(prompt, current, speed):
    return json.dumps({
        "request": prompt,
        "current_flow": {
            "template": current.get("ff"),
            "in_face": current.get("in_face"),
            "out_face": current.get("out_face"),
            "has_custom_mask": bool(current.get("mask")),
        },
        "settings": _ai_context(current, speed),
    }, ensure_ascii=False)


def _http_ai_json(provider_name, url, body, headers):
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", "replace")
        try:
            message = json.loads(detail).get("error", {}).get("message", detail)
        except json.JSONDecodeError:
            message = detail
        raise RuntimeError(f"{provider_name} API {exc.code}: {message[:600]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{provider_name} API connection failed: {exc.reason}") from exc


def _call_openai_plan(key, prompt, current, speed, language, model):
    body = {
        "model": model,
        "reasoning": {"effort": "low"},
        "instructions": _ai_instructions(language),
        "input": _ai_request_input(prompt, current, speed),
        "max_output_tokens": 5000,
        "text": {"format": {
            "type": "json_schema",
            "name": "bubble_simulator_design_plan",
            "strict": True,
            "schema": _ai_schema(),
        }},
    }
    payload = _http_ai_json(
        "OpenAI", "https://api.openai.com/v1/responses", body,
        {"Authorization": f"Bearer {key}"})
    return json.loads(_openai_output_text(payload))


def _call_anthropic_plan(key, prompt, current, speed, language, model):
    body = {
        "model": model,
        "max_tokens": 5000,
        "system": _ai_instructions(language),
        "messages": [{"role": "user",
                      "content": _ai_request_input(prompt, current, speed)}],
        "output_config": {"format": {
            "type": "json_schema", "schema": _ai_schema(),
        }},
    }
    payload = _http_ai_json(
        "Anthropic", "https://api.anthropic.com/v1/messages", body,
        {"x-api-key": key, "anthropic-version": "2023-06-01"})
    if payload.get("stop_reason") == "refusal":
        raise ValueError("Anthropic model refused request")
    text = "".join(part.get("text", "") for part in payload.get("content", [])
                   if isinstance(part, dict) and part.get("type") == "text")
    if not text:
        raise ValueError("Anthropic response did not contain structured output")
    return json.loads(text)


def _call_google_plan(key, prompt, current, speed, language, model):
    from urllib.parse import quote
    body = {
        "systemInstruction": {"parts": [{"text": _ai_instructions(language)}]},
        "contents": [{"role": "user", "parts": [
            {"text": _ai_request_input(prompt, current, speed)}
        ]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": _ai_schema(),
            "maxOutputTokens": 5000,
            "temperature": 0.2,
        },
    }
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{quote(model, safe='.-')}:generateContent?key={quote(key, safe='')}")
    payload = _http_ai_json("Google Gemini", url, body, {})
    candidates = payload.get("candidates", [])
    if not candidates:
        reason = payload.get("promptFeedback", {}).get("blockReason", "no candidate")
        raise ValueError(f"Gemini response unavailable: {reason}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    if not text:
        raise ValueError("Gemini response did not contain structured output")
    return json.loads(text)


def _call_openrouter_plan(key, prompt, current, speed, language, model):
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _ai_instructions(language)},
            {"role": "user", "content": _ai_request_input(prompt, current, speed)},
        ],
        "max_tokens": 5000,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "bubble_simulator_design_plan",
                "strict": True, "schema": _ai_schema(),
            },
        },
        "provider": {"require_parameters": True},
    }
    payload = _http_ai_json(
        "OpenRouter", "https://openrouter.ai/api/v1/chat/completions", body,
        {"Authorization": f"Bearer {key}",
         "HTTP-Referer": "http://localhost:8766",
         "X-Title": "Bubble Simulator"})
    choices = payload.get("choices", [])
    if not choices:
        raise ValueError("OpenRouter response did not contain a choice")
    message = choices[0].get("message", {})
    if message.get("refusal"):
        raise ValueError(str(message["refusal"]))
    content = message.get("content", "")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content
                          if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise ValueError("OpenRouter response did not contain structured output")
    return json.loads(content)


def _call_ai_plan(provider, prompt, current, speed, language, model):
    key = _ai_get_key(provider)
    if not key:
        raise PermissionError(f"{provider} API key is not configured")
    calls = {
        "openai": _call_openai_plan,
        "google": _call_google_plan,
        "anthropic": _call_anthropic_plan,
        "openrouter": _call_openrouter_plan,
    }
    return calls[provider](key, prompt, current, speed, language, model)


def _flow_rows_connect(rows, in_face, out_face):
    ny, nz = len(rows), len(rows[0])
    opened = [[cell == "0" for cell in row] for row in rows]

    def edge(face):
        if face == "bottom":
            return [(0, k) for k in range(nz)]
        if face == "top":
            return [(ny - 1, k) for k in range(nz)]
        if face == "left":
            return [(j, 0) for j in range(ny)]
        return [(j, nz - 1) for j in range(ny)]

    seeds = [(j, k) for j, k in edge(in_face) if opened[j][k]]
    targets = {(j, k) for j, k in edge(out_face) if opened[j][k]}
    if not seeds or not targets:
        return False
    seen, stack = set(seeds), list(seeds)
    while stack:
        j, k = stack.pop()
        if (j, k) in targets:
            return True
        for jj, kk in ((j - 1, k), (j + 1, k), (j, k - 1), (j, k + 1)):
            if (0 <= jj < ny and 0 <= kk < nz and opened[jj][kk]
                    and (jj, kk) not in seen):
                seen.add((jj, kk))
                stack.append((jj, kk))
    return False


def _normalize_ai_changes(numeric, enums, current, speed):
    apply, details, warnings = {}, [], []
    working = dict(current)
    working["speed"] = speed
    for item in numeric if isinstance(numeric, list) else []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if key not in AI_NUMERIC_KEYS:
            warnings.append(f"ignored unsupported numeric key: {key}")
            continue
        value = item.get("value")
        if key == "speed":
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = None
            clean = value if value is not None and math.isfinite(value) and 0.01 <= value <= 5.0 else None
        else:
            clean = LiveSim3D._clean(key, value)
        if key == "dry_cathode" and clean not in (0.0, 1.0):
            clean = None
        if clean is None:
            warnings.append(f"ignored invalid value for {key}")
            continue
        if working.get(key) == clean:
            continue
        working[key] = clean
        apply[key] = clean
        details.append({
            "key": key, "value": clean,
            "reason": str(item.get("reason", ""))[:300],
            "classification": "model_or_fitted" if key in AI_MODEL_PARAMETERS else "physical_or_operating",
        })
    for item in enums if isinstance(enums, list) else []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if key not in AI_ENUM_KEYS:
            warnings.append(f"ignored unsupported enum key: {key}")
            continue
        clean = LiveSim3D._clean(key, item.get("value"))
        if clean is None:
            warnings.append(f"ignored invalid value for {key}")
            continue
        if working.get(key) == clean:
            continue
        working[key] = clean
        apply[key] = clean
        details.append({
            "key": key, "value": clean,
            "reason": str(item.get("reason", ""))[:300],
            "classification": "model_or_fitted" if key in AI_MODEL_PARAMETERS else "physical_or_operating",
        })
    return apply, details, warnings


def normalize_ai_plan(raw, current, speed):
    if not isinstance(raw, dict):
        raise ValueError("AI plan must be a JSON object")
    apply, details, warnings = _normalize_ai_changes(
        raw.get("numeric_changes"), raw.get("enum_changes"), current, speed)
    flow_raw = raw.get("flow") if isinstance(raw.get("flow"), dict) else {}
    action = str(flow_raw.get("action", "keep"))
    flow = {
        "action": "keep", "template": str(current.get("ff", "serp")),
        "ny": 0, "nz": 0, "rows": [],
        "in_face": str(current.get("in_face", "bottom")),
        "out_face": str(current.get("out_face", "top")),
        "reason": str(flow_raw.get("reason", ""))[:500],
        "connected": None,
    }
    if action == "template":
        template = str(flow_raw.get("template", ""))
        inf, outf = str(flow_raw.get("in_face", "bottom")), str(flow_raw.get("out_face", "top"))
        if template not in {"serp", "par", "straight"}:
            warnings.append("unsupported flow template ignored; through-PTL interdigitated flow is disabled")
        elif inf not in {"bottom", "left", "right"} or outf not in {"top", "left", "right"} or inf == outf:
            warnings.append("invalid or overlapping flow ports; flow change ignored")
        else:
            flow.update({"action": "template", "template": template,
                         "in_face": inf, "out_face": outf, "connected": True})
            apply.update({"ff": template, "mask": "", "in_face": inf, "out_face": outf})
    elif action == "custom":
        try:
            ny, nz = int(flow_raw.get("ny", 0)), int(flow_raw.get("nz", 0))
        except (TypeError, ValueError):
            ny, nz = 0, 0
        rows = flow_raw.get("rows")
        inf, outf = str(flow_raw.get("in_face", "")), str(flow_raw.get("out_face", ""))
        valid_shape = (4 <= ny <= 64 and 4 <= nz <= 64 and isinstance(rows, list)
                       and len(rows) == ny and all(isinstance(r, str) and len(r) == nz
                                                  and set(r) <= {"0", "1"} for r in rows))
        if not valid_shape:
            warnings.append("custom flow grid is invalid; flow change ignored")
        elif inf not in {"bottom", "left", "right"} or outf not in {"top", "left", "right"} or inf == outf:
            warnings.append("custom flow ports are invalid or overlap; flow change ignored")
        elif not any("0" in row for row in rows):
            warnings.append("custom flow has no open channel; flow change ignored")
        elif not _flow_rows_connect(rows, inf, outf):
            warnings.append("custom flow has no connected inlet-to-outlet path; flow change ignored")
        else:
            from bubblesim3d.params3d import encode_mask
            import numpy as np
            mask = np.array([[cell == "1" for cell in row] for row in rows], dtype=bool)
            flow.update({"action": "custom", "template": "custom",
                         "ny": ny, "nz": nz, "rows": rows,
                         "in_face": inf, "out_face": outf, "connected": True})
            apply.update({"ff": "custom", "mask": encode_mask(mask),
                          "in_face": inf, "out_face": outf})
    elif action != "keep":
        warnings.append("unknown flow action ignored")

    tests = []
    for test in raw.get("tests", []) if isinstance(raw.get("tests"), list) else []:
        if not isinstance(test, dict):
            continue
        changes, test_details, test_warnings = _normalize_ai_changes(
            test.get("numeric_changes"), test.get("enum_changes"), current, speed)
        tests.append({
            "name": str(test.get("name", "candidate"))[:80],
            "objective": str(test.get("objective", ""))[:300],
            "apply": changes, "changes": test_details,
            "warnings": test_warnings,
        })
    warnings.extend(str(w)[:500] for w in raw.get("warnings", [])
                    if isinstance(w, str))
    if any(d["classification"] == "model_or_fitted" for d in details):
        warnings.append("Model/material/fitted parameters are being changed; verify them against experiment or literature.")
    return {
        "summary": str(raw.get("summary", ""))[:1200],
        "changes": details, "flow": flow, "tests": tests[:3],
        "warnings": list(dict.fromkeys(warnings))[:12],
        "apply": apply,
    }


def _ai_sweep_metrics(designer):
    result = sweep_polarization(designer, {})
    curve = result["pristine"]

    def at(requested):
        index = min(range(len(SWEEP_J)), key=lambda i: abs(SWEEP_J[i] - requested))
        if not curve["reachable"][index]:
            return {"j_mAcm2": SWEEP_J[index], "reachable": False, "V": None,
                    "theta_out": None, "eps_out": None}
        return {"j_mAcm2": SWEEP_J[index], "reachable": True,
                "V": curve["V"][index],
                "theta_out": curve["theta_out"][index],
                "eps_out": curve["eps_out"][index]}

    reachable = [j for j, ok in zip(SWEEP_J, curve["reachable"]) if ok]
    return {
        "at_1Acm2": at(1000), "at_2Acm2": at(2000),
        "reachable_points": sum(bool(v) for v in curve["reachable"]),
        "max_reachable_mAcm2": max(reachable) if reachable else 0,
        "water_limit_mAcm2": result["water"]["j_lim_water_mAcm2"],
    }


def evaluate_ai_plan(plan, current):
    if not isinstance(plan, dict) or not isinstance(plan.get("apply"), dict):
        raise ValueError("missing normalized AI plan")
    base = dict(current)
    primary = dict(base)
    primary.update({k: v for k, v in plan["apply"].items()
                    if k in DESIGNER_DEFAULTS})
    geometry = {"ok": True}
    try:
        _params, cfg, sim = LIVE._construct(primary)
        geometry["grid"] = list(sim.grid.shape)
        geometry["effective_h_mm"] = round(float(cfg.h) * 1000.0, 4)
        del sim, cfg, _params
    except Exception as exc:
        geometry = {"ok": False, "error": str(exc)[:500]}

    baseline_metrics = _ai_sweep_metrics(base)
    primary_metrics = _ai_sweep_metrics(primary)
    candidates = [{
        "name": "current", "objective": "baseline",
        "metrics": baseline_metrics,
    }, {
        "name": "AI plan", "objective": plan.get("summary", ""),
        "metrics": primary_metrics, "geometry": geometry,
    }]
    for test in plan.get("tests", [])[:3]:
        candidate = dict(base)
        candidate.update({k: v for k, v in test.get("apply", {}).items()
                          if k in DESIGNER_DEFAULTS})
        candidates.append({
            "name": test.get("name", "candidate"),
            "objective": test.get("objective", ""),
            "metrics": _ai_sweep_metrics(candidate),
        })
    b1 = baseline_metrics["at_1Acm2"]["V"]
    p1 = primary_metrics["at_1Acm2"]["V"]
    delta = round(p1 - b1, 4) if b1 is not None and p1 is not None else None
    warnings = [
        "Polarization comparison uses the 1-D reduced-order channel model.",
        "A custom flow mask is connectivity/build-tested, but its detailed topology is not resolved in the 1-D performance comparison.",
    ]
    if not geometry["ok"]:
        warnings.append("The proposed 3-D geometry did not build and must not be applied.")
    return {"ok": 1, "candidates": candidates, "delta_V_at_1Acm2": delta,
            "warnings": warnings}


def _validate_ai_apply(data):
    if not isinstance(data, dict):
        raise ValueError("apply must be an object")
    allowed = AI_NUMERIC_KEYS | AI_ENUM_KEYS | AI_FLOW_KEYS
    out = {}
    for key, value in data.items():
        if key not in allowed:
            raise ValueError(f"unsupported key: {key}")
        if key == "speed":
            try:
                clean = float(value)
            except (TypeError, ValueError):
                clean = None
            if clean is None or not math.isfinite(clean) or not 0.01 <= clean <= 5.0:
                raise ValueError("invalid speed")
        else:
            clean = LiveSim3D._clean(key, value)
            if clean is None:
                raise ValueError(f"invalid value for {key}")
        out[key] = clean
    if out.get("ff") == "inter":
        raise ValueError("interdigitated flow requires unsupported through-PTL transport")
    if out.get("ff") == "custom":
        from bubblesim3d.params3d import decode_mask
        mask = decode_mask(out.get("mask", ""))
        if mask is None:
            raise ValueError("custom flow requires a valid mask")
        rows = ["".join("1" if cell else "0" for cell in row) for row in mask]
        inf = out.get("in_face", "bottom")
        outf = out.get("out_face", "top")
        if inf == outf or not _flow_rows_connect(rows, inf, outf):
            raise ValueError("custom flow does not connect inlet to outlet")
    return out


def start_batch(spec: dict):
    """Launch a Track B batch run in a daemon thread. Returns the run name."""
    from bubblesim3d.params3d import Pore3DConfig
    from bubblesim3d import runner

    sub = str(spec.get("substrate", "ni_foam"))
    grid = max(16, min(160, int(spec.get("grid", 48))))
    j = max(0.01, min(10.0, float(spec.get("j", 0.8))))
    frames = max(1, min(500, int(spec.get("frames", 60))))
    stamp = time.strftime("%Y%m%d_%H%M%S")
    name = f"{sub}_{grid}_{stamp}"
    out_dir = RESULTS / name
    with JOBS_LOCK:
        # keep JOBS bounded — a long-lived server would otherwise hold every
        # finished run's status forever. results/ on disk is the source of truth
        # (list_runs), so drop the oldest finished entries, keep running ones.
        if len(JOBS) > 40:
            done = [k for k, v in JOBS.items() if v.get("status") in ("done", "error")]
            for k in done[:-20]:
                JOBS.pop(k, None)
        JOBS[name] = {"status": "running", "progress": 0, "frames": frames,
                      "grid": grid, "substrate": sub}

    def _worker():
        try:
            cfg = Pore3DConfig(substrate=sub, n=grid, j_A_cm2=j, frames=frames)
            runner.run(cfg, out_dir, frames, created=stamp)
            with JOBS_LOCK:
                JOBS[name]["status"] = "done"
        except Exception as e:                       # surface, don't crash server
            with JOBS_LOCK:
                JOBS[name]["status"] = "error"
                JOBS[name]["error"] = str(e)

    threading.Thread(target=_worker, daemon=True).start()
    return name


LIVE = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # cap how long a single request may hold a worker thread. Without it a client
    # that opens a connection and dribbles (or never finishes) the body leaves
    # rfile.read(length) blocked forever, tying up a thread (slow-loris).
    timeout = 20

    def log_message(self, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path):
        if not path.is_file():
            return self._json({"error": "not found"}, 404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",
                         MIME.get(path.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        # no-cache: a deploy replaces these files in place (no versioned names),
        # so a plain refresh must always fetch the current HTML/JS — without
        # this, browsers heuristically reuse the old page and a fresh deploy
        # "doesn't show up". (Vendored three.js is big but changes ~never, and
        # no-cache still allows conditional reuse; correctness wins here.)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _is_local_request(self):
        # A LAN visitor must never be able to spend the host's API key. Proxy
        # headers are rejected even if the immediate peer happens to be local.
        if self.headers.get("Cf-Connecting-Ip") or self.headers.get("X-Forwarded-For"):
            return False
        try:
            address = ipaddress.ip_address(str(self.client_address[0]).split("%", 1)[0])
            if getattr(address, "ipv4_mapped", None):
                address = address.ipv4_mapped
            return address.is_loopback
        except ValueError:
            return False

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p in ("/", "/app", "/app3d", "/app3d.html"):
            return self._file(PAGE)
        if p in ("/2d", "/app2d", "/app2d.html"):
            return self._file(PAGE_2D)
        if p.startswith("/web3d/"):
            # static assets; resolve inside web3d/ only (no traversal)
            target = (WEB / p[len("/web3d/"):]).resolve()
            if WEB.resolve() not in target.parents and target != WEB.resolve():
                return self._json({"error": "forbidden"}, 403)
            return self._file(target)
        if p == "/api3d/state":
            LIVE.last_poll = time.perf_counter()   # a viewer is here -> keep running
            q = self._query(self.path)
            return self._json(LIVE.snapshot(faces=q.get("faces") == "1"))
        if p == "/api3d/runs":
            return self._json({"runs": list_runs()})
        if p == "/api3d/eis":
            with LIVE.lock:
                try:
                    return self._json(LIVE.sim.eis())
                except Exception as e:
                    return self._json({"error": str(e)}, 500)
        if p == "/api3d/experiments":
            with EXP_LOCK:
                return self._json({"list": _exp_load(), "active": ACTIVE_EXP})
        if p == "/api3d/ai/status":
            if not self._is_local_request():
                return self._json({"error": "AI endpoints are local-only"}, 403)
            provider = self._query(self.path).get("provider")
            return self._json(_ai_key_status(provider))
        if p == "/api3d/meshes":
            with LIVE.lock:
                dsn = dict(LIVE.designer)
            # The experiment panel owns two explicit contact-angle inputs.  Use
            # them for the preview without mutating the live simulator state;
            # otherwise a freshly opened panel can show the live default (60°)
            # next to an experiment input that says 110°.
            q = self._query(self.path)
            for k in ("theta", "mesh_theta"):
                if k not in q:
                    continue
                try:
                    v = float(q[k])
                    if math.isfinite(v):
                        dsn[k] = min(179.0, max(1.0, v))
                except (TypeError, ValueError):
                    pass
            return self._json({"catalog": mesh_catalog_status(dsn)})
        if p == "/api3d/manifest":
            return self._run_json(self.path, "manifest.json")
        if p == "/api3d/scaffold":
            return self._scaffold(self.path)
        if p == "/api3d/frame":
            return self._frame(self.path)
        return self._json({"error": "not found"}, 404)

    # ------------------------------------------------------ Track B playback
    @staticmethod
    def _query(path):
        from urllib.parse import parse_qs, urlparse
        return {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}

    def _run_dir(self, path):
        q = self._query(path)
        name = q.get("run", "")
        d = (RESULTS / name).resolve()
        if RESULTS.resolve() not in d.parents or not d.is_dir():
            return None
        return d

    def _run_json(self, path, fname):
        d = self._run_dir(path)
        f = d / fname if d else None
        if not f or not f.is_file():
            return self._json({"error": "run not found"}, 404)
        return self._file(f)

    def _scaffold(self, path):
        d = self._run_dir(path)
        if not d or not (d / "scaffold.npz").is_file():
            return self._json({"error": "scaffold not found"}, 404)
        from bubblesim3d import snapshots
        return self._json(snapshots.scaffold_blob(d))

    def _frame(self, path):
        d = self._run_dir(path)
        q = self._query(path)
        try:
            i = int(q.get("i", "1"))
        except ValueError:
            return self._json({"error": "bad i"}, 400)
        from bubblesim3d import snapshots
        if not d or not snapshots.frame_path(d, i).is_file():
            return self._json({"error": "frame not found"}, 404)
        return self._json(snapshots.frame_blob(d, i))

    MAX_BODY = 8 << 20            # 8 MB: a hand-drawn plate mask is the big one

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return self._json({"error": "bad length"}, 400)
        if length < 0 or length > self.MAX_BODY:
            return self._json({"error": "body too large"}, 413)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._json({"error": "bad json"}, 400)
        # every handler below indexes the body like a dict. A bare list/string/
        # null used to reach them and raise AttributeError INSIDE the handler,
        # which drops the connection with no response at all (curl sees 000) —
        # and this server is publicly deployed, so any scanner triggers it.
        if not isinstance(data, dict):
            return self._json({"error": "body must be a JSON object"}, 400)
        if self.path == "/api3d/op":
            try:
                res = LIVE.update(data)
            except Exception as e:
                return self._json({"error": str(e)}, 400)
            return self._json(res, 400 if res.get("rejected") and not res.get("accepted") else 200)
        if self.path == "/api3d/experiments":
            res = experiments_api(data)
            return self._json(res, 400 if "error" in res else 200)
        if self.path == "/api3d/sweep":
            with LIVE.lock:
                dsn = dict(LIVE.designer)
            try:
                return self._json(sweep_polarization(dsn, data))
            except Exception as e:
                return self._json({"error": str(e)}, 500)
        if self.path.startswith("/api3d/ai/"):
            if not self._is_local_request():
                return self._json({"error": "AI endpoints are local-only"}, 403)
            if self.path == "/api3d/ai/key":
                res = _ai_set_session(data)
                return self._json(res, 400 if "error" in res else 200)
            if self.path == "/api3d/ai/plan":
                prompt = str(data.get("prompt", "")).strip()
                if not prompt:
                    return self._json({"error": "prompt required"}, 400)
                if len(prompt) > 5000:
                    return self._json({"error": "prompt too long"}, 413)
                language = "en" if data.get("language") == "en" else "ko"
                provider = str(data.get("provider", AI_PROVIDER))
                if provider not in AI_PROVIDER_MODELS:
                    return self._json({"error": "unsupported provider"}, 400)
                with AI_LOCK:
                    default_model = AI_MODELS[provider]
                model = str(data.get("model", default_model))
                if not _valid_ai_model(provider, model):
                    return self._json({"error": "unsupported model"}, 400)
                with LIVE.lock:
                    current, speed = dict(LIVE.designer), float(LIVE.speed)
                started = time.perf_counter()
                try:
                    raw = _call_ai_plan(provider, prompt, current, speed, language, model)
                    plan = normalize_ai_plan(raw, current, speed)
                except PermissionError as e:
                    return self._json({"error": str(e)}, 401)
                except (ValueError, RuntimeError) as e:
                    return self._json({"error": str(e)}, 502)
                return self._json({"ok": 1, "provider": provider, "model": model,
                                   "elapsed_s": round(time.perf_counter() - started, 2),
                                   "plan": plan})
            if self.path == "/api3d/ai/evaluate":
                with LIVE.lock:
                    current = dict(LIVE.designer)
                try:
                    return self._json(evaluate_ai_plan(data.get("plan"), current))
                except Exception as e:
                    return self._json({"error": str(e)}, 400)
            if self.path == "/api3d/ai/apply":
                try:
                    changes = _validate_ai_apply(data.get("apply"))
                    res = LIVE.update(changes)
                except Exception as e:
                    return self._json({"error": str(e)}, 400)
                return self._json({"ok": 1, "result": res})
            return self._json({"error": "not found"}, 404)
        if self.path == "/api3d/reset":
            LIVE.reset()
            return self._json({"ok": 1})
        if self.path == "/api3d/run":
            try:
                name = start_batch(data)
            except Exception as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"ok": 1, "run": name})
        if self.path == "/api3d/shutdown":
            if self.headers.get("Cf-Connecting-Ip") or self.headers.get("X-Forwarded-For"):
                return self._json({"error": "shutdown is local-only"}, 403)
            self._json({"ok": 1, "bye": 1})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        return self._json({"error": "not found"}, 404)


def _already_running(port):
    """True if OUR 3-D app already answers on this port (then just open it)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api3d/state", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="Bubble 3D app server")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--view", default="2d", choices=["2d", "3d"],
                    help="which page to open in the browser")
    args = ap.parse_args(argv)
    base = f"http://localhost:{args.port}/"
    url = base + ("2d" if args.view == "2d" else "")

    # fixed port = stable link. If it's already serving, just open the page.
    if _already_running(args.port):
        print(f"  already running:  {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return

    global LIVE
    LIVE = LiveSim3D()
    threading.Thread(target=LIVE.run_forever, daemon=True).start()

    try:
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        raise SystemExit(f"port {args.port} is busy ({e}); pass --port") from e

    print("  Bubble 3D app  (Track A live / Track B playback)")
    print(f"    2D panel view : {base}2d")
    print(f"    3D render view: {base}")
    print("  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        with open(ROOT / "server3d_error.log", "a", encoding="utf-8") as fh:
            fh.write(traceback.format_exc() + "\n")
        raise
