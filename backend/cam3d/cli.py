"""Command line interface.

    cam3d doctor                              hardware + tools diagnostic
    cam3d reconstruct IMAGES_DIR OUT_DIR [--profile fast|high|ultra] [--export obj,glb,dae,...]
    cam3d export PROJECT_DIR --formats obj,dae  re-export an existing project's model
    cam3d serve [--host 0.0.0.0 --port 8765]  start the local API
"""
from __future__ import annotations

import argparse
import json
import logging
import re
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
    from .engine.vocab import cached_vocab_tree
    vt = cached_vocab_tree()
    print(f"  vocabulaire: {vt if vt else 'absent (téléchargé au 1er scan de plus de 150 images, ou : cam3d fetch-models)'}")
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
    res = run_exports(model, project / "exports", args.name, formats, lg, point_cloud=project / "reconstruction" / "dense_aligned.ply")
    lg.close()
    print()
    for r in res:
        print(f"  {r.format:<4}: {r.path}  ({r.size_bytes / 1e6:.1f} Mo)  {r.note}")
    return 0


class RedactTokensFilter(logging.Filter):
    """Masks ``token=`` / ``secret=`` query values in server logs."""

    _re = re.compile(r"(token=|secret=)[^&\s\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(self._re.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        record.msg = self._re.sub(r"\1***", str(record.msg))
        return True


def cmd_serve(args) -> int:
    try:
        import uvicorn
        from .server.app import create_app
    except ImportError as e:
        print(f"Serveur indisponible : {e}")
        return 2
    for name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(RedactTokensFilter())
    import asyncio

    from .server.config import Settings
    from .server.network import lan_addresses
    from .server.tls import TlsPaths, ensure_server_cert

    settings = Settings()
    settings.ensure_dirs()
    app = create_app(settings)
    ips = lan_addresses() if args.host in ("0.0.0.0", "::") else []
    https = args.https and bool(ips)
    if https:
        try:
            meta = ensure_server_cert(TlsPaths(settings.tls_dir), ips)
        except Exception as e:  # never block the app because of TLS
            print(f"HTTPS local indisponible ({e}) : seul HTTP sera servi.")
            https = False
    app.state.tls = {"enabled": https, "https_port": args.https_port if https else None, "http_port": args.port}
    print(f"Interface sur cet ordinateur : http://127.0.0.1:{args.port}")
    for ip in ips:
        print(f"Réseau local : http://{ip}:{args.port}" + (f"  ·  https://{ip}:{args.https_port} (caméra)" if https else "")
              + "  (appairage requis)")
    if https:
        print(f"Empreinte SHA-256 de l'autorité locale : {meta['ca_fingerprint_sha256']}")

    import contextlib
    import signal

    class _Server(uvicorn.Server):
        # One process serves HTTP and HTTPS: signals are handled once, below, for both servers.
        @contextlib.contextmanager
        def capture_signals(self):  # type: ignore[override]
            yield

        def install_signal_handlers(self) -> None:  # older uvicorn versions
            pass

    servers = [_Server(uvicorn.Config(app, host=args.host, port=args.port, lifespan="on"))]
    if https:
        p = TlsPaths(settings.tls_dir)
        servers.append(_Server(uvicorn.Config(app, host=args.host, port=args.https_port, lifespan="off",
                                              ssl_keyfile=str(p.key), ssl_certfile=str(p.crt))))

    def _stop(*_):
        for srv in servers:
            srv.should_exit = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _stop)

    async def _serve() -> None:
        await asyncio.gather(*(srv.serve() for srv in servers))

    asyncio.run(_serve())
    return 0


def cmd_fetch_models(args) -> int:
    from .engine.vocab import fetch_vocab_tree
    try:
        print(f"Vocabulaire visuel : {fetch_vocab_tree()}")
        return 0
    except Exception as e:
        print(f"Échec du téléchargement : {e}", file=sys.stderr)
        return 1


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
    f = sub.add_parser("fetch-models", help="télécharger le vocabulaire visuel COLMAP (grandes scènes, ~72 Mo, une fois)")
    f.set_defaults(func=cmd_fetch_models)
    s = sub.add_parser("serve", help="démarrer l'API locale")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--https-port", type=int, default=8443)
    s.add_argument("--no-https", dest="https", action="store_false",
                   help="ne pas servir le HTTPS local (caméra du navigateur indisponible sur téléphone)")
    s.set_defaults(func=cmd_serve)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
