"""Command line interface.

    cam3d doctor                              hardware + tools diagnostic
    cam3d reconstruct IMAGES_DIR OUT_DIR [--profile fast|high|ultra] [--export obj,glb,dae,...]
    cam3d export PROJECT_DIR --formats obj,dae  re-export an existing project's model
    cam3d serve [--host 0.0.0.0 --port 8765]  start the local API (phase 3)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _print_event(ev) -> None:
    from .engine.events import STAGE_LABELS

    label = STAGE_LABELS[ev.stage]
    if ev.status == "progress":
        pct = f" {ev.progress * 100:5.1f}%" if ev.progress is not None else ""
        print(f"\r  [{label}]{pct} {ev.message[:90]:<90}", end="", flush=True)
    elif ev.status == "log":
        print(f"\n  [{label}] {ev.message}")
    else:
        print(f"\n[{label}] {ev.status.upper()} {ev.message}")


def cmd_doctor(args) -> int:
    from .engine.hardware import detect_hardware
    from .engine.tools import discover_tools

    hw = detect_hardware()
    tools = discover_tools()
    if args.json:
        print(json.dumps({"hardware": hw.to_dict(), "tools": tools.to_dict()}, indent=2, default=str))
        return 0
    print(f"OS: {hw.os} {hw.os_version} ({hw.arch})  Python {hw.python_version}")
    print(f"CPU: {hw.cpu_model}  ({hw.cpu_cores} cœurs)")
    print(f"RAM: {hw.ram_total_mb} Mo (disponible {hw.ram_available_mb} Mo)   Disque libre: {hw.disk_free_mb} Mo")
    print("GPU: " + (", ".join(f"{g.name} [{g.vendor}{', CUDA' if g.cuda_available else ''}]" for g in hw.gpus) or "aucun détecté"))
    for n in hw.notes:
        print("  ! " + n)
    print("Outils :")
    print(f"  pycolmap   : {'OK ' + str(tools.pycolmap.version) + ' (' + str(tools.pycolmap.note) + ')' if tools.pycolmap and tools.pycolmap.available else 'ABSENT'}")
    print(f"  colmap     : {tools.colmap.path or 'absent (optionnel)'}")
    for name, t in tools.openmvs.items():
        print(f"  OpenMVS/{name:<18}: {t.path or 'ABSENT'}")
    print(f"  blender    : {tools.blender.path if tools.blender and tools.blender.available else 'absent (optionnel)'}")
    print(f"  ffmpeg     : {tools.ffmpeg.path if tools.ffmpeg and tools.ffmpeg.available else 'absent (vidéo indisponible)'}")
    ok = tools.pycolmap and tools.pycolmap.available and tools.openmvs_available
    print("\nReconstruction possible : " + ("OUI" if ok else "NON (voir INSTALLATION.md)"))
    return 0 if ok else 1


def cmd_reconstruct(args) -> int:
    from .engine.pipeline import ReconstructionPipeline

    formats = tuple(f.strip() for f in args.export.split(",") if f.strip())
    pipe = ReconstructionPipeline(callback=_print_event, threads=args.threads)
    t = time.time()
    res = pipe.run(Path(args.images), Path(args.out), profile=args.profile, export_formats=formats, resume=args.resume)
    print()
    if res.success:
        print(f"OK en {time.time() - t:.0f}s : {res.num_faces} faces, {len(res.textures)} texture(s)")
        print(f"  modèle  : {res.model_obj}")
        print(f"  aperçu  : {res.preview_glb}")
        for e in res.exports:
            print(f"  export {e['format']:<4}: {e['path']}")
        return 0
    print(f"ÉCHEC à l'étape '{res.error_stage}' : {res.error}")
    return 2


def cmd_export(args) -> int:
    from .engine.events import Stage, StageLogger
    from .engine.mesh_io import load_obj
    from .engine.stages.export import run_exports

    project = Path(args.project)
    obj = project / "meshes" / f"{args.name}.obj"
    if not obj.exists():
        print(f"Modèle introuvable : {obj}")
        return 2
    model = load_obj(obj)
    formats = tuple(f.strip() for f in args.formats.split(",") if f.strip())
    lg = StageLogger(Stage.EXPORT, project / "logs", _print_event)
    res = run_exports(model, project / "exports", args.name, formats, lg, point_cloud=project / "reconstruction" / "dense.ply")
    lg.close()
    print()
    for r in res:
        print(f"  {r.format:<4}: {r.path}  ({r.size_bytes / 1e6:.1f} Mo)  {r.note}")
    return 0


def cmd_serve(args) -> int:
    try:
        import uvicorn
        from .server.app import create_app  # phase 3
    except ImportError as e:
        print(f"Serveur indisponible : {e}")
        return 2
    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cam3d", description="cam3D - scan 3D photoréaliste, gratuit et local")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor", help="diagnostic matériel et outils")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_doctor)
    r = sub.add_parser("reconstruct", help="reconstruire un modèle à partir d'un dossier de photos")
    r.add_argument("images")
    r.add_argument("out")
    r.add_argument("--profile", default="fast", choices=["fast", "high", "ultra"])
    r.add_argument("--export", default="obj,glb,dae", help="formats séparés par des virgules: obj,glb,stl,ply,dae")
    r.add_argument("--threads", type=int, default=0)
    r.add_argument("--resume", action="store_true", help="reprendre les étapes déjà terminées")
    r.set_defaults(func=cmd_reconstruct)
    e = sub.add_parser("export", help="ré-exporter le modèle d'un projet")
    e.add_argument("project")
    e.add_argument("--formats", default="obj,dae")
    e.add_argument("--name", default="model")
    e.set_defaults(func=cmd_export)
    s = sub.add_parser("serve", help="démarrer l'API locale")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(func=cmd_serve)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
