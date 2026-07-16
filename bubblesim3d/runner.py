"""Batch runner for the pore-scale track (Track B) — offline compute.

    python -m bubblesim3d.runner --substrate ni_foam --grid 64 --frames 200

Generates a voxel microstructure and advances external-surface Faradaic gas
generation plus connected-pore bubble filling, writing per-frame snapshots
under results/<run>/ for playback in the 3-D app. There is no electrochemical
reaction penetration into the scaffold. Windows-safe: pathlib, ASCII-only
progress log (cp949 consoles), --resume.

P3 scope: generate + save the scaffold and manifest (frames=0 -> static
scaffold playback). P4 fills the physics frame loop via bubblesim3d.pore3d.
"""
import argparse
import sys
from pathlib import Path

from .params3d import Pore3DConfig
from .microstructure import generate, microstructure_stats
from . import snapshots

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"


def log(msg):
    """ASCII-only line (avoid cp949 console errors on Windows)."""
    sys.stdout.write(msg.encode("ascii", "replace").decode("ascii") + "\n")
    sys.stdout.flush()


def run(cfg: Pore3DConfig, out_dir: Path, frames: int, created="", resume=False):
    out_dir = Path(out_dir)
    solid, meta = generate(cfg)
    h = meta["h_um"] * 1e-6
    stats = microstructure_stats(solid, h)
    log("[gen] %s %d^3  eps target=%.3f achieved=%.3f measured=%.3f  area=%.0f/m"
        % (cfg.substrate, cfg.n, meta["eps_target"], meta["eps_achieved"],
           stats["porosity"], stats["specific_area"]))
    log("[gen] pore percolates=%s  solid percolates=%s"
        % (stats["percolates_y"], stats["solid_percolates"]))
    snapshots.save_scaffold(out_dir, solid, {**meta, **stats})

    manifest = {
        "run": out_dir.name, "created": created,
        "substrate": cfg.substrate, "nanostructure": cfg.nanostructure,
        "electrode": cfg.electrode, "grid": cfg.n, "h_um": meta["h_um"],
        "j_A_cm2": cfg.j_A_cm2, "dt_s": cfg.dt_s, "frames": 0,
        "eps_target": meta["eps_target"], "eps_achieved": meta["eps_achieved"],
        "porosity": stats["porosity"], "specific_area": stats["specific_area"],
        "seed": cfg.seed,
    }

    if frames > 0:
        # P4: import here so P3 works before pore3d exists
        try:
            from .pore3d import PoreSim3D
        except ImportError:
            log("[warn] pore3d not available yet (P4) -> writing scaffold only")
            snapshots.save_manifest(out_dir, manifest)
            return manifest
        sim = PoreSim3D(cfg, solid, meta)
        for i in range(1, frames + 1):
            sim.advance()
            snapshots.save_frame(out_dir, i, sim.gas_mask(), sim.scalars(),
                                 surf_current=sim.surface_current())
            if i % 10 == 0 or i == frames:
                s = sim.scalars()
                log("[frame %4d/%d] cov=%.3f holdup=%.4f vented=%.3e"
                    % (i, frames, s.get("coverage", 0), s.get("holdup", 0),
                       s.get("vented", 0)))
        manifest["frames"] = frames

    snapshots.save_manifest(out_dir, manifest)
    log("[done] %s" % out_dir)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description="Track B pore-scale batch runner")
    ap.add_argument("--substrate", default="ni_foam",
                    help="ni_foam | ss_foam | carbon_paper | ni_mesh | flat_plate")
    ap.add_argument("--nano", default="nanoparticle")
    ap.add_argument("--electrode", default="HER", choices=["HER", "OER"])
    ap.add_argument("--grid", type=int, default=64, help="voxels per edge")
    ap.add_argument("--j", type=float, default=0.4, help="current density [A/cm^2]")
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="", help="results/<name> (default: auto)")
    ap.add_argument("--stamp", default="", help="creation timestamp (Date unavailable in-proc)")
    args = ap.parse_args(argv)

    cfg = Pore3DConfig(substrate=args.substrate, nanostructure=args.nano,
                       electrode=args.electrode, n=args.grid, j_A_cm2=args.j,
                       seed=args.seed, frames=args.frames)
    name = args.out or f"{args.substrate}_{args.grid}_{args.seed}"
    out_dir = RESULTS / name
    run(cfg, out_dir, args.frames, created=args.stamp)


if __name__ == "__main__":
    main()
