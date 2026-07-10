"""Snapshot I/O for the pore-scale batch track (Track B).

A run lives in results/<run>/:
    manifest.json     run metadata (substrate, grid, dt, frame count, units)
    scaffold.npz      the solid mask (bit-packed) — written once, shared
    frame_00001.npz   per-frame gas mask (bit-packed) + optional fields + scalars
    ...

Gas/solid masks are stored with numpy.packbits (1 bit/voxel); the dissolved-gas
field is float16. This keeps a 64^3 run to tens of MB. The server decodes frames
to a compact browser blob (base64 bit masks) so the page never parses .npz.

numpy + stdlib only.
"""
import base64
import json
from pathlib import Path

import numpy as np


# ----------------------------------------------------------- bit packing
def pack_bool(mask):
    """(shape, base64 packed bits) for a boolean array."""
    a = np.ascontiguousarray(mask, dtype=bool)
    packed = np.packbits(a.ravel())
    return list(a.shape), base64.b64encode(packed.tobytes()).decode("ascii")


def unpack_bool(shape, b64):
    n = int(np.prod(shape))
    packed = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
    bits = np.unpackbits(packed, count=n)
    return bits.reshape(shape).astype(bool)


# --------------------------------------------------------------- writers
def save_manifest(run_dir, manifest):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")


def save_scaffold(run_dir, solid, meta):
    """Write the shared scaffold once (bit-packed solid mask + metadata)."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(run_dir / "scaffold.npz",
                        packed=np.packbits(np.ascontiguousarray(solid, bool).ravel()),
                        shape=np.array(solid.shape, dtype=np.int32),
                        meta=json.dumps(meta))


def load_scaffold(run_dir):
    d = np.load(Path(run_dir) / "scaffold.npz", allow_pickle=False)
    shape = tuple(int(x) for x in d["shape"])
    n = int(np.prod(shape))
    solid = np.unpackbits(d["packed"], count=n).reshape(shape).astype(bool)
    meta = json.loads(str(d["meta"])) if "meta" in d else {}
    return solid, meta


def frame_path(run_dir, i):
    return Path(run_dir) / f"frame_{i:05d}.npz"


def save_frame(run_dir, i, gas_mask, scalars, c_field=None, surf_current=None):
    """One time-step: bit-packed gas mask + scalars (+ optional dissolved field
    and per-surface-voxel current)."""
    payload = dict(
        packed_gas=np.packbits(np.ascontiguousarray(gas_mask, bool).ravel()),
        shape=np.array(gas_mask.shape, dtype=np.int32),
        scalars=json.dumps(scalars),
    )
    if c_field is not None:
        payload["c"] = c_field.astype(np.float16)
    if surf_current is not None:
        payload["jsurf"] = surf_current.astype(np.float32)
    np.savez_compressed(frame_path(run_dir, i), **payload)


def load_frame(run_dir, i):
    d = np.load(frame_path(run_dir, i), allow_pickle=False)
    shape = tuple(int(x) for x in d["shape"])
    n = int(np.prod(shape))
    gas = np.unpackbits(d["packed_gas"], count=n).reshape(shape).astype(bool)
    scalars = json.loads(str(d["scalars"]))
    out = {"gas": gas, "scalars": scalars}
    if "c" in d:
        out["c"] = d["c"].astype(np.float32)
    if "jsurf" in d:
        out["jsurf"] = d["jsurf"]
    return out


# ------------------------------------------------------- browser blobs
def scaffold_blob(run_dir):
    """Compact JSON for the renderer: bit-packed solid mask + metadata."""
    solid, meta = load_scaffold(run_dir)
    shape, b64 = pack_bool(solid)
    return {"shape": shape, "solid_b64": b64, "meta": meta}


def frame_blob(run_dir, i):
    """Compact JSON for one playback frame: bit-packed gas mask + scalars.

    The full surface-current field stays in the .npz for offline analysis; the
    browser only needs the gas mask (the animated visual) and the scalars."""
    fr = load_frame(run_dir, i)
    shape, b64 = pack_bool(fr["gas"])
    return {"i": i, "shape": shape, "gas_b64": b64, "scalars": fr["scalars"]}
