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
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bubblesim import Params, Simulator
from bubblesim.config import ElectrodeParams
from bubblesim.kernel.meshlayer import mesh_factors
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
        # fritz_scale calibrated to ELECTROLYSIS departure sizes: the Fritz
        # boiling correlation over-predicts badly for water electrolysis (a
        # documented kernel limitation). 0.08 puts the departure radius at
        # ~120 um (theta=60deg, stagnant) — the 50-300 um diameter range
        # reported for H2/O2 on Ni in KOH; contact angle and flow still
        # modulate it through the kernel force balance.
        self.params = Params(fritz_scale=0.08)
        self.speed = 1.0
        self.paused = False
        self.last_poll = 0.0     # perf_counter of last /api3d/state poll
                                 # (0 -> starts idle; no CPU until a viewer)
        self.speed_actual = 0.0
        self._carry = 0.0        # fractional sim steps carried between blocks
        self._build()

    def _apply_params(self):
        """Push catalyst j0 + membrane resistance from the designer into Params
        (these live on Params, not Operating — like server_app._apply_catalyst)."""
        d = self.designer
        self.params.cathode.j0_ref = max(1e-9, float(d.get("j0_cathode", 130.0)))
        self.params.anode.j0_ref = max(1e-12, float(d.get("j0_anode", 1.3e-7)))
        self.params.anode.alpha_a = min(2.0, max(0.1, float(d.get("alpha_a", 1.0))))
        self.params.r_membrane_area = max(0.0, float(d.get("r_mem", 3.2e-6)))

    def _build(self):
        """(Re)create the cell sim from the current designer state."""
        self._apply_params()
        self.cfg = cell_config_from_designer(self.designer)
        op = operating_from_designer(self.designer)
        self.sim = CellSim3D(op, self.params, self.cfg.grid_dims(),
                             h=self.cfg.h, cap=self.cfg.cap_parcels,
                             tilt=self.cfg.tilt, seed=0, cfg=self.cfg)
        self.sim.ns.drag_K = max(0.0, float(self.designer.get("drag_K", 60.0)))

    GEOM_KEYS = {"W_cm", "H_cm", "ff", "n_ch", "w_ch_mm", "d_ch_mm",
                 "w_land_mm", "t_ptl_um", "eps_ptl", "t_mem_um",
                 # ports + the user-drawn plate: all rebuild the voxel domain
                 "in_z", "in_w", "out_z", "out_w", "mask",
                 "in_face", "out_face",
                 "h_mm"}                    # voxel size: resolution rebuild

    def update(self, data: dict):
        with self.lock:
            rebuild = False
            for k, v in data.items():
                if k == "speed":
                    # down to 0.01x: true slow motion ("high-speed camera")
                    self.speed = max(0.01, min(5.0, float(v)))
                elif k == "paused":
                    self.paused = bool(v)
                elif k in DESIGNER_DEFAULTS:
                    self.designer[k] = v
                    if k in self.GEOM_KEYS:
                        rebuild = True
            if rebuild:
                self._build()
            else:                                   # operating levers: live
                self._apply_params()                # catalyst / membrane R
                op = operating_from_designer(self.designer)
                self.sim.set_operating(op, tilt=float(self.designer.get("tilt", 0.0)))
                self.sim.ns.drag_K = max(0.0, float(self.designer.get("drag_K", 60.0)))

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

_SWEEP_KEYS = ("W_cm", "H_cm", "ff", "n_ch", "d_ch_mm", "u_flow", "electrolyte",
               "c_mol", "T", "Pbar", "theta", "j0_cathode", "j0_anode",
               "alpha_a", "r_mem", "gap_mm", "void_frac",
               "mesh_id", "mesh_cover", "mesh_pos")


def _sweep_params(d: dict) -> Params:
    return Params(
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
    out = {"V": [], "theta_out": [], "eps_out": []}
    st = None
    for j in SWEEP_J:
        op = sweep_operating(d, j)
        sim = Simulator(op=op, params=params)
        st = solver.solve(op, sim.props(), sim.surfaces)
        out["V"].append(round(float(st.V), 4))
        out["theta_out"].append(round(st.fields["theta_out"], 4))
        out["eps_out"].append(round(st.fields["eps_out"], 4))
    ov = st.overpotentials                                # split at the last (max) j
    out["split_jmax"] = {k: round(float(v), 4) for k, v in ov.items()
                         if isinstance(v, (int, float))}
    out["prof_jmax"] = st.fields.get("path_prof")
    out["mesh_warn"] = st.fields.get("mesh_warn", "")
    out["mesh_on"] = bool(st.fields.get("mesh_on", False))
    return out


def sweep_polarization(designer: dict, overrides: dict) -> dict:
    d = {k: designer.get(k, DESIGNER_DEFAULTS.get(k)) for k in _SWEEP_KEYS}
    for k, v in (overrides or {}).items():
        if k in _SWEEP_KEYS:
            d[k] = v
    key = json.dumps(d, sort_keys=True)
    if key in _sweep_cache:
        return _sweep_cache[key]
    res = {"j": SWEEP_J, "pristine": _sweep_one(d, False)}
    ms = mesh_spec(str(d.get("mesh_id", "")))
    if ms is not None:
        res["mesh"] = _sweep_one(d, True)
        res["mesh_info"] = dict(ms)
        res["mesh_info"].update(mesh_factors(
            ms["hole_mm"], ms["open"], ms["t_mm"],
            max(0.05, float(d.get("d_ch_mm", 1.0)))))
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
    d_ch = max(0.05, float(designer.get("d_ch_mm", DESIGNER_DEFAULTS["d_ch_mm"])))
    out = []
    for ms in MESH_CATALOG:
        f = mesh_factors(ms["hole_mm"], ms["open"], ms["t_mm"], d_ch)
        e = dict(ms)
        e.update({"fits": f["fits"], "warn": f["warn"], "wick": round(f["wick"], 3),
                  "u_boost": round(f["u_boost"], 2)})
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
        self.end_headers()
        self.wfile.write(body)

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
        if p == "/api3d/meshes":
            with LIVE.lock:
                dsn = dict(LIVE.designer)
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

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        if self.path == "/api3d/op":
            LIVE.update(data)
            return self._json({"ok": 1})
        if self.path == "/api3d/sweep":
            with LIVE.lock:
                dsn = dict(LIVE.designer)
            try:
                return self._json(sweep_polarization(dsn, data))
            except Exception as e:
                return self._json({"error": str(e)}, 500)
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
