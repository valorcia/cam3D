"""Blender headless validation of a COLLADA (.dae) export.

Usage:
    blender -b --python scripts/blender/validate_dae.py -- <file.dae> [report.json] [render.png]

Checks: import succeeds, mesh objects, face count, UV layer present, materials
with image textures whose files exist on disk, bounding box, up axis sanity.
Optionally renders a quick Cycles preview (CPU) to render.png for visual QA.
"""
import json
import math
import os
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
dae = argv[0]
report_path = argv[1] if len(argv) > 1 else None
render_path = argv[2] if len(argv) > 2 else None

bpy.ops.wm.read_factory_settings(use_empty=True)
ok = True
errors = []
try:
    bpy.ops.wm.collada_import(filepath=dae)
except Exception as e:  # noqa
    ok = False
    errors.append(f"import failed: {e}")

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
objects = []
for o in meshes:
    me = o.data
    uv_layers = [uv.name for uv in me.uv_layers]
    mats = []
    for slot in o.material_slots:
        m = slot.material
        if m is None:
            continue
        images = []
        if m.use_nodes:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image is not None:
                    p = bpy.path.abspath(n.image.filepath)
                    images.append({"file": n.image.filepath, "exists": os.path.exists(p), "size": list(n.image.size)})
        mats.append({"name": m.name, "images": images})
    bb = [list(o.matrix_world @ __import__("mathutils").Vector(c)) for c in o.bound_box]
    xs, ys, zs = zip(*bb)
    objects.append({
        "name": o.name, "vertices": len(me.vertices), "faces": len(me.polygons),
        "uv_layers": uv_layers, "materials": mats,
        "bbox_min": [min(xs), min(ys), min(zs)], "bbox_max": [max(xs), max(ys), max(zs)],
    })

if not meshes:
    ok = False
    errors.append("no mesh objects after import")
for o in objects:
    if not o["uv_layers"]:
        errors.append(f"{o['name']}: no UV layer")
    if not any(img["exists"] for m in o["materials"] for img in m["images"]):
        errors.append(f"{o['name']}: no existing texture image bound to material")
if errors:
    ok = False

report = {"file": dae, "ok": ok, "errors": errors, "objects": objects, "blender": bpy.app.version_string}

if render_path and meshes:
    try:
        scene = bpy.context.scene
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 16
        scene.render.resolution_x, scene.render.resolution_y = 800, 600
        scene.render.resolution_percentage = 100
        scene.render.filepath = render_path
        # frame all objects with a camera looking from +X,-Y,+Z (Blender is Z-up like SketchUp)
        import mathutils
        mins = [min(o["bbox_min"][i] for o in objects) for i in range(3)]
        maxs = [max(o["bbox_max"][i] for o in objects) for i in range(3)]
        centre = mathutils.Vector([(a + b) / 2 for a, b in zip(mins, maxs)])
        size = max(b - a for a, b in zip(mins, maxs))
        cam_data = bpy.data.cameras.new("cam")
        cam = bpy.data.objects.new("cam", cam_data)
        scene.collection.objects.link(cam)
        direction = mathutils.Vector((1.0, -1.4, 0.8)).normalized()
        cam.location = centre + direction * size * 1.6
        cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
        cam_data.clip_end = size * 20
        scene.camera = cam
        sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
        sun.data.energy = 3.0
        sun.rotation_euler = (math.radians(50), 0, math.radians(30))
        scene.collection.objects.link(sun)
        world = bpy.data.worlds.new("w")
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs[1].default_value = 0.6
        scene.world = world
        bpy.ops.render.render(write_still=True)
        report["render"] = render_path
    except Exception as e:  # noqa
        report["render_error"] = str(e)

text = json.dumps(report, indent=2)
print("CAM3D_DAE_REPORT " + json.dumps(report))
if report_path:
    with open(report_path, "w") as f:
        f.write(text)
sys.exit(0 if ok else 1)
