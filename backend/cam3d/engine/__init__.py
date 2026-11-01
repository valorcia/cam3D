"""Reconstruction engine.

This package must stay independent from the web server (``cam3d.server``):
it only depends on the filesystem, external tools (COLMAP / OpenMVS / Blender /
FFmpeg) and scientific Python libraries. The server, the CLI and future native
apps all drive it through :class:`cam3d.engine.pipeline.ReconstructionPipeline`.
"""
