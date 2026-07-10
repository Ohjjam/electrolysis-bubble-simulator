"""In-browser (Pyodide) driver for the bubble simulator.

Replaces the HTTP server entirely: the page calls these functions directly
instead of fetching /api/* over a network. ONE physics path -- reuses
``LiveSim`` from :mod:`server_app`, including its ``_advance()`` stepping block.
No server, no tunnel, no per-frame round-trip => no lag.

The JS bootstrap (see build_web.py) wires the 4 endpoints to these calls:
    /api/op    -> op(json_str)
    /api/reset -> reset()
    /api/state -> state()      (returns a JSON string)
    /api/eis   -> eis()        (returns a JSON string)
and drives stepping from requestAnimationFrame via pump(now_seconds).
"""
import json

from server_app import LiveSim

LIVE = LiveSim()
_last = None          # performance.now()/1000 at the previous pump [s]


def op(body):
    """POST /api/op : live-update settings. ``body`` is a JSON string."""
    LIVE.update(json.loads(body) if body else {})


def reset():
    """POST /api/reset : restart the bubble population, keep settings."""
    LIVE.reset()


def pump(now_s):
    """Advance the sim by the real time elapsed since the last call.

    Driven from requestAnimationFrame (~60 Hz) so motion stays smooth and
    independent of how often the UI reads state(). ``now_s`` is the browser's
    performance.now() in seconds (the kernel never calls wall-clock itself).
    """
    global _last
    if LIVE.paused:
        LIVE.speed_actual *= 0.8
        _last = now_s
        return
    if _last is None:                 # first frame: just set the clock
        _last = now_s
        return
    raw = now_s - _last
    _last = now_s
    if raw <= 0:
        return
    # clamp long gaps (backgrounded tab) so we don't burst-step on return;
    # speed_actual uses the *real* gap so the "x real-time" readout stays honest
    n = LIVE._advance(min(raw, 0.05))
    inst = (n * LIVE.DT) / raw
    LIVE.speed_actual = 0.8 * LIVE.speed_actual + 0.2 * inst


def state():
    """GET /api/state -> JSON string (the same snapshot the server served)."""
    return json.dumps(LIVE.snapshot())


def eis():
    """GET /api/eis -> JSON string."""
    return json.dumps(LIVE.eis())
