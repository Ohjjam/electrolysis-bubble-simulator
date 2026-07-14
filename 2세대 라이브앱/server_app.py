"""Live multiphysics app: the real Python kernel behind a browser UI.

    python server_app.py        (opens http://127.0.0.1:8765 automatically)

ONE physics implementation — every number the browser shows is computed by the
`bubblesim` kernel in this process; the page only renders and sends slider
values back. Stdlib only (http.server + threading), no dependencies.

Endpoints:
    GET  /            the UI (app.html, served from this folder)
    GET  /api/state   JSON snapshot: scalars, overpotential split, pH, bubbles, traces
    POST /api/op      {key: value, ...} live-updates Operating / Params / catalyst
    POST /api/reset   restart the bubble population (keeps current settings)
"""
import json
import sys
import threading
import time
import webbrowser
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# this file lives in a subfolder; the bubblesim package is at the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bubblesim import Operating, Params, Simulator
from bubblesim.constants import F, R_GAS
from bubblesim.properties import ELECTROLYTES
from bubblesim.kernel import impedance as imp
from bubblesim.solvers import get_solver
from bubblesim.solvers.zerod import ZeroDTwoElectrodeSolver
from bubblesim.solvers.oned import OneDGapSolver
from bubblesim.solvers.dynamic import DoubleLayerWrapper
from bubblesim.solvers.porous import PorousSolver
from bubblesim.kernel import morphology as morph

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "app.html"


class CachedSolver:
    """Re-solve the implicit electrochemistry only every `every` steps.

    Between bubble events j varies slowly, so the UI does not need a fresh
    implicit solve at every dt — this buys the pure-Python loop real-time-ish
    speed without touching the kernel.
    """

    def __init__(self, inner, every):
        self.inner, self.every = inner, every
        self._n, self._state = 0, None

    def solve(self, op, context, surfaces):
        if self._state is None or self._n % self.every == 0:
            self._state = self.inner.solve(op, context, surfaces)
        self._n += 1
        return self._state


def make_solver(model, params, dt):
    if model == "two_electrode":
        # 32/28 bisection iters ~ micro-volt resolution; plenty for the UI
        inner = CachedSolver(ZeroDTwoElectrodeSolver(n_outer=32, n_inner=28), every=5)
    elif model == "oned":
        inner = CachedSolver(OneDGapSolver(n_cells=48, n_inner=28), every=5)
    elif model == "porous":
        # depth BVP is heavier -> fewer nodes + longer cache; no DL wrapper needed
        return CachedSolver(PorousSolver(n_outer=40, N=25), every=8)
    elif model == "face2d":
        from bubblesim.solvers.face2d import Face2DSolver
        return CachedSolver(Face2DSolver(), every=6)
    elif model == "channel":
        from bubblesim.solvers.channel import ChannelSolver
        return CachedSolver(ChannelSolver(), every=6)
    else:
        return CachedSolver(get_solver(model), every=2)
    # double-layer transient (CP relaxation) wraps the cached steady solve
    return DoubleLayerWrapper(inner, params, dt)


class LiveSim:
    """The running simulation + thread-safe control surface for the handlers."""

    DT = 1.0e-3          # UI time step [s] (coarser than batch runs; stable, fast)
    BLOCK = 0.012        # wall-clock chunk per loop [s]; small -> lock freed often
                         # so /api/state polls aren't blocked behind a long step run

    OP_FLOATS = {"V_cell", "j_set", "c_electrolyte", "T", "P", "contact_angle",
                 "u_flow", "B_field", "E_ext", "gap_mm"}
    PARAM_FLOATS = {"r_membrane_area", "r_contact_area", "hA_cool",
                    "T_ambient", "fritz_scale"}

    def __init__(self):
        self.lock = threading.Lock()
        self.speed = 1.0
        self.paused = False
        self.speed_actual = 0.0
        self.flow = None                 # cathode (H2) FlowChannel2D when model=="flow2d"
        self.flow_a = None               # anode (O2) FlowChannel2D
        # catalyst state, in real units the UI edits directly:
        #   spec_j0 [A/m^2] = material-specific exchange current density
        #   Rf [-]          = roughness factor (ECSA, real area / geometric area)
        # effective geometric j0_ref = spec_j0 * Rf
        self.spec_j0 = {"anode": 0.01, "cathode": 1.0}
        self.Rf = {"anode": 1.0, "cathode": 1.0}
        self.params = Params(fritz_scale=0.6, thermal_mass=5.0, hA_cool=0.3)
        self._apply_catalyst()
        self.sim = self._make_sim(Operating(mode="CP", j_set=2000.0, V_cell=2.3,
                                            model="two_electrode", track_both=True))

    def _make_sim(self, op):
        return Simulator(op, self.params, seed=0,
                         solver=make_solver(op.model, self.params, self.DT))

    def _apply_catalyst(self):
        self.params.anode.j0_ref = self.spec_j0["anode"] * self.Rf["anode"]
        self.params.cathode.j0_ref = self.spec_j0["cathode"] * self.Rf["cathode"]

    # ------------------------------------------------------------- control
    def update(self, data: dict):
        with self.lock:
            op = self.sim.op
            for k, v in data.items():
                if k in self.OP_FLOATS:
                    setattr(op, k, float(v))
                elif k in self.PARAM_FLOATS:
                    setattr(self.params, k, float(v))
                elif k == "electrode":
                    op.electrode = "OER" if v == "OER" else "HER"
                elif k == "electrolyte" and v in ELECTROLYTES:
                    op.electrolyte = v
                    # medium-specific coalescence-inhibition threshold
                    self.params.c_coalesce_crit = ELECTROLYTES[v]["c_coalesce"]
                elif k == "mode" and v in ("CA", "CP"):
                    op.mode = v
                elif k == "model" and v in ("lumped", "two_electrode", "oned", "porous", "face2d", "channel", "flow2d") \
                        and v != op.model:
                    op.model = v
                    if v == "flow2d":
                        from bubblesim.solvers.flow2d import FlowChannel2D
                        # floor the through-flow: a real cell always has at least buoyancy-driven
                        # natural convection, so the channel never goes fully stagnant (which would
                        # just pile every bubble at the top wall -> looks frozen)
                        u0 = max(0.02, op.u_flow)
                        self.flow = FlowChannel2D(u_in=u0, gas_factor=1.0, seed=0)
                        self.flow_a = FlowChannel2D(u_in=u0, gas_factor=0.5, seed=7)
                        # electrochem scalars (cell V, j, trace) still come from two-electrode
                        self.sim.solver = make_solver("two_electrode", self.params, self.DT)
                    else:
                        self.flow = self.flow_a = None
                        self.sim.solver = make_solver(v, self.params, self.DT)  # hot-swap
                elif k == "substrate" and v in morph.SUBSTRATES:
                    op.substrate = v
                elif k == "nanostructure" and v in morph.NANOSTRUCTURES:
                    op.nanostructure = v
                elif k == "cat_loading":
                    op.cat_loading = max(0.05, min(10.0, float(v)))
                elif k in ("rf_override", "Le_override_mm", "eps_override", "sigma_override"):
                    setattr(op, k, None if v is None else float(v))   # None clears the override
                elif k == "face_height_cm":
                    op.face_height_cm = max(0.2, min(100.0, float(v)))
                elif k in ("high_fidelity", "gas_feedback"):
                    setattr(op, k, bool(v))
                elif k == "channel_type" and v in ("serpentine", "parallel", "straight"):
                    op.channel_type = v
                elif k == "n_pass":
                    op.n_pass = max(1, min(12, int(float(v))))
                elif k == "cell_width_cm":
                    op.cell_width_cm = max(1.0, min(30.0, float(v)))
                elif k == "drill_inlet_gas":
                    op.drill_inlet_gas = max(0.0, min(2000.0, float(v)))
                elif k == "custom_path":                  # user-drawn flow path (design tool)
                    op.custom_path = v if (isinstance(v, list) and len(v) >= 2) else None
                elif k == "track_both":
                    if bool(v) != op.track_both:
                        op.track_both = bool(v)
                        self.sim = self._make_sim(replace(op))   # surface count changes
                elif k == "thermal":
                    op.thermal = bool(v)
                elif k == "speed":
                    self.speed = max(0.05, min(5.0, float(v)))
                elif k == "paused":
                    self.paused = bool(v)
                elif k in ("j0_anode", "j0_cathode"):           # specific j0 [A/m^2]
                    self.spec_j0[k.rsplit("_", 1)[1]] = max(1e-9, float(v))
                    self._apply_catalyst()
                elif k in ("Rf_anode", "Rf_cathode"):           # ECSA roughness [-]
                    self.Rf[k.rsplit("_", 1)[1]] = max(0.01, float(v))
                    self._apply_catalyst()
                elif k == "alpha_anode":
                    self.params.anode.alpha_a = max(0.05, min(3.0, float(v)))
                elif k == "alpha_cathode":
                    self.params.cathode.alpha_a = max(0.05, min(3.0, float(v)))
                elif k == "C_dl_anode":
                    self.params.anode.C_dl = max(1e-3, float(v))
                elif k == "C_dl_cathode":
                    self.params.cathode.C_dl = max(1e-3, float(v))

    def reset(self):
        with self.lock:
            self.sim = self._make_sim(replace(self.sim.op))   # keep settings, new bubbles

    # ------------------------------------------------------------- sim loop
    def _advance(self, budget):
        """Advance the sim by ~`budget`*speed seconds of sim time; return DT steps.

        One stepping block, factored out of run_forever so the server's run loop
        AND the in-browser Pyodide driver (sim_bridge) share ONE stepping path.
        """
        with self.lock:
            op = self.sim.op
            n = max(1, int(round(budget * self.speed / self.DT)))
            if op.model == "flow2d" and self.flow is not None:
                for _ in range(n):                        # electrochem scalars + V(t) trace
                    self.sim.step(self.DT)
                h = self.sim.history
                if len(h["t"]) > 40000:
                    for v in h.values():
                        del v[:20000]
                jd = max(0.0, (h["j"][-1] if h["t"] else 0.0)) * 1.0e4   # cell j [A/cm^2] -> A/m^2
                rdep = 1.0e-4 + 3.0e-4 * (op.contact_angle / 90.0)
                nf = max(1, min(14, int(round(budget * self.speed / 2.0e-3))))
                for fl in (self.flow, self.flow_a):       # both electrodes' 2-D channels
                    fl.u_in = max(0.02, op.u_flow)        # keep natural-convection through-flow
                    fl.inlet_gas = op.drill_inlet_gas
                    for _ in range(nf):
                        fl.step(2.0e-3, jd, rdep, op.contact_angle)
            else:
                for _ in range(n):
                    self.sim.step(self.DT)
                h = self.sim.history
                if len(h["t"]) > 40000:                   # bound memory
                    for v in h.values():
                        del v[:20000]
        return n

    def run_forever(self):
        while True:
            start = time.perf_counter()
            if self.paused:
                self.speed_actual *= 0.8
                time.sleep(0.06)
                continue
            n = self._advance(self.BLOCK)
            elapsed = time.perf_counter() - start
            # ALWAYS yield a few ms (even if a heavy block ran over BLOCK) so the
            # HTTP polling thread isn't GIL-starved -> snapshots stay fast/fresh
            time.sleep(max(0.003, self.BLOCK - elapsed))
            total = time.perf_counter() - start
            inst = (n * self.DT) / max(total, 1e-9)           # sim-seconds per wall-second
            self.speed_actual = 0.8 * self.speed_actual + 0.2 * inst

    # ------------------------------------------------------------- snapshot
    def snapshot(self) -> dict:
        with self.lock:
            sim, op = self.sim, self.sim.op
            h = sim.history
            st = sim.last_state
            n = len(h["t"])
            i0 = max(0, n - 4000)
            stride = max(1, (n - i0) // 400)
            _r = {"t": 4, "j": 5, "T": 3, "V": 5}
            trace = {k: [round(v, _r[k]) for v in h[k][i0::stride]]
                     for k in ("t", "j", "T", "V")}

            def pack(bubbles):
                # compact ints (micrometers): [id, x_um, y_um, r_um, attached]
                return [[b.id, int(b.x * 1e6), int(b.y * 1e6), int(b.r * 1e6),
                         1 if b.attached else 0] for b in bubbles]
            dual = len(sim.surfaces) > 1
            return {
                "t": h["t"][-1] if n else 0.0,
                "j": h["j"][-1] if n else 0.0,            # A/cm^2
                "T": op.T,
                "contact_angle": op.contact_angle,        # for sessile-cap rendering
                "theta": h["theta"][-1] if n else 0.0,    # cathode/primary
                "theta_a": h["theta_a"][-1] if n else 0.0,
                "eps": h["eps"][-1] if n else 0.0,
                "r_d": h["r_d"][-1] if n else 0.0,
                "n_bub": sum(len(s.bubbles) for s in sim.surfaces),
                "V_cell": op.V_cell,
                "V_now": h["V"][-1] if n else op.V_cell,
                "mode": op.mode,
                "j_set": op.j_set,
                "model": op.model,
                "electrode": op.electrode,
                "electrolyte": op.electrolyte,
                "track_both": dual,
                "thermal": op.thermal,
                "speed": self.speed,
                "speed_actual": round(self.speed_actual, 3),
                "paused": self.paused,
                "j0_eff": {"anode": self.params.anode.j0_ref,
                           "cathode": self.params.cathode.j0_ref},
                "ov": (st.overpotentials if st else {}),
                "ph": ({k: st.fields[k] for k in
                        ("pH_bulk", "pH_anode", "pH_cathode") if k in st.fields}
                       if st else {}),
                "profiles": ({k: st.fields[k] for k in
                              ("z_mm", "eps_c", "c_c", "eps_a", "c_a", "delta_mm")
                              if k in st.fields}
                             if st and "z_mm" in st.fields else None),
                # depth-resolved porous-electrode profiles (model="porous")
                "porous": ({k: st.fields[k] for k in
                            ("d_mm", "jloc_c", "eta_d_c", "jloc_a", "eta_d_a",
                             "util_c", "util_a", "pen_mm_c", "pen_mm_a", "L_e_mm",
                             "morph_name") if k in st.fields}
                           if st and "d_mm" in st.fields else None),
                "substrate": op.substrate,
                "nanostructure": op.nanostructure,
                "cat_loading": op.cat_loading,
                "morph_warn": (list(dict.fromkeys(
                    morph.morphology_warnings(op.substrate, op.nanostructure,
                                              op.electrolyte, "OER")
                    + morph.morphology_warnings(op.substrate, op.nanostructure,
                                                op.electrolyte, "HER")))
                    if op.model == "porous" else []),
                # 2-D face-field map (model="face2d")
                "face": ({k: st.fields[k] for k in
                          ("theta_field", "j_field", "nx", "ny", "theta_bot",
                           "theta_top", "j_bot", "j_top") if k in st.fields}
                         if st and "theta_field" in st.fields else None),
                "face_height_cm": op.face_height_cm,
                # flow-channel cell-design map (model="channel")
                "channel": ({k: st.fields[k] for k in
                             ("segments", "ctype", "n_pass", "theta_in", "theta_out",
                              "eps_out", "bn_frac", "eff_in", "eff_out", "up_frac", "inlet")
                             if k in st.fields}
                            if st and "segments" in st.fields else None),
                "channel_type": op.channel_type,
                "n_pass": op.n_pass,
                "cell_width_cm": op.cell_width_cm,
                # in-tool 2-D coupled CFD (model="flow2d") -- both electrodes
                "flow": (self.flow.snapshot() if op.model == "flow2d" and self.flow else None),
                "flow_a": (self.flow_a.snapshot() if op.model == "flow2d" and self.flow_a else None),
                "bubbles": pack(sim.surfaces[0].bubbles),
                "bubbles_a": (pack(sim.surfaces[1].bubbles) if dual else []),
                "trace": trace,
            }


    # ------------------------------------------------------------------ EIS
    def eis(self) -> dict:
        """Small-signal spectrum at the current operating point (analytic).

        Per electrode: R_ct from the BV slope at the present overpotential,
        C_dl from params; one shared finite-length Warburg split evenly between
        the electrodes (tau_d = delta^2/D from the boundary layer). R_s is the
        series resistance the solver reported (ohmic + membrane + contact).
        """
        with self.lock:
            sim, op = self.sim, self.sim.op
            ctx = sim.props()
            st = sim.last_state
            if st is None or op.model == "lumped":
                return {"error": "two_electrode/oned 모델에서 사용 가능"}
            ov = st.overpotentials
            j = max(st.j, 1e-3)
            T = op.T
            dual = op.track_both and len(sim.surfaces) > 1
            th_c = sim.surfaces[0].coverage()
            th_a = sim.surfaces[1].coverage() if dual else 0.0
            R_s = ov["eta_ohmic"] / j
            eta_a = ov.get("eta_act_anode", 0.0)
            eta_c = ov.get("eta_act_cathode", 0.0)
            Rct_a = imp.r_ct_bv(max(1e-3, 1 - th_a) * ctx["j0_anode"],
                                ctx["alpha_a_anode"], ctx["alpha_c_anode"], eta_a, T)
            Rct_c = imp.r_ct_bv(max(1e-3, 1 - th_c) * ctx["j0_cathode"],
                                ctx["alpha_a_cathode"], ctx["alpha_c_cathode"], eta_c, T)
            j_lim = (st.fields.get("j_lim_1d") or ctx["j_lim_transport"])
            z = ctx["z_primary"]
            R_d = (R_GAS * T / (z * F)) / max(j_lim - j, 1e-3)
            delta = min(ctx["delta_bl"], 0.8 * ctx["gap_m"])
            tau_d = delta * delta / ctx["D_carrier"]
            els = [
                {"R_ct": Rct_a, "C_dl": self.params.anode.C_dl * max(1e-3, 1.0 - th_a),
                 "R_d": 0.5 * R_d, "tau_d": tau_d},
                {"R_ct": Rct_c, "C_dl": self.params.cathode.C_dl * max(1e-3, 1.0 - th_c),
                 "R_d": 0.5 * R_d, "tau_d": tau_d},
            ]
            freqs = imp.log_freqs(1e-2, 1e4, 50)
            Z = imp.cell_impedance(freqs, R_s, els)
        return {
            "f": freqs,
            "re": [z_.real * 1e4 for z_ in Z],          # ohm*m^2 -> ohm*cm^2
            "im": [-z_.imag * 1e4 for z_ in Z],         # Nyquist: -Im
            "Rs": R_s * 1e4, "Rct_a": Rct_a * 1e4, "Rct_c": Rct_c * 1e4,
        }


LIVE = None   # set in main() / by tests


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"     # persistent connections: no TCP handshake per poll
                                      # (Content-Length is set on every response below)

    def log_message(self, *args):     # keep the console quiet
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/app", "/app.html"):
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            self._json(LIVE.snapshot())
        elif self.path == "/api/eis":
            self._json(LIVE.eis())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        if self.path == "/api/op":
            LIVE.update(data)
            self._json({"ok": 1})
        elif self.path == "/api/reset":
            LIVE.reset()
            self._json({"ok": 1})
        elif self.path == "/api/shutdown":
            # clean off-switch (used by server_stop.py / the desktop OFF button).
            # Tunnel visitors arrive via the local tunnel agent but carry proxy
            # headers (cloudflared: Cf-Connecting-Ip; ngrok: X-Forwarded-For) —
            # they may play with the sim, not kill it.
            if self.headers.get("Cf-Connecting-Ip") or self.headers.get("X-Forwarded-For"):
                return self._json({"error": "shutdown is local-only"}, 403)
            self._json({"ok": 1, "bye": 1})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._json({"error": "not found"}, 404)


def _already_running(port):
    """True if OUR app already answers on this port (then just open the link)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def _lan_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))           # no traffic sent; just picks the route
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def main(argv=None):
    import argparse
    import os
    import socket

    ap = argparse.ArgumentParser(description="Bubble multiphysics live app")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="0.0.0.0",
                    help="bind address (default 0.0.0.0 = reachable on the LAN; "
                         "the API only tweaks simulator settings)")
    ap.add_argument("--no-browser", action="store_true",
                    help="don't open a browser (for auto-start at logon)")
    args = ap.parse_args(argv)
    url = f"http://localhost:{args.port}/"

    # fixed port = stable link. If our app already serves it, just open the link.
    if _already_running(args.port):
        print(f"  already running:  {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return

    global LIVE
    LIVE = LiveSim()
    threading.Thread(target=LIVE.run_forever, daemon=True).start()

    try:
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        raise SystemExit(
            f"port {args.port} is held by another program ({e}); "
            f"free it or pass --port") from e

    host = socket.gethostname()
    ip = _lan_ip()
    print(f"  Bubble multiphysics app")
    print(f"    this computer : {url}")
    if ip:
        print(f"    same network  : http://{ip}:{args.port}/   (or http://{host}:{args.port}/)")
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
    except Exception:                        # headless (pythonw) crash -> log file
        import traceback
        with open(ROOT / "server_error.log", "a", encoding="utf-8") as fh:
            fh.write(traceback.format_exc() + "\n")
        raise
