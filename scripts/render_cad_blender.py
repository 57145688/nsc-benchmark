"""Render the exported CAD models with Blender in background mode.

Blender runs its own Python interpreter, so this script is not imported by the
rest of the project:

    blender -b -P scripts/render_cad_blender.py -- --root <repo> --out results/figures

Each STL is written in centimetres (``results/cad/manifest.json``); the meshes
are scaled to metres here so lighting distances and camera framing stay in a
sane range.  Long, thin parts (fuel pin, assembly, module) also get a section
view because a full-length elevation is only a few pixels wide.
"""

import argparse
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

# One entry per image: view direction, orthographic zoom (fraction of the
# largest bounding-box dimension), resolution, plus optional section options.
VARIANTS = {
    "pin": [
        dict(view=(0.40, -1.0, 0.18), zoom=1.05, res=(700, 1400)),
        dict(
            view=(0.40, -1.0, 0.18),
            zoom=0.12,
            res=(700, 900),
            cutaway=True,
            height_fraction=0.62,
        ),
    ],
    "assembly": [
        dict(view=(0.50, -1.0, 0.28), zoom=1.12, res=(900, 1500)),
        dict(view=(0.50, -1.0, 0.28), zoom=0.35, res=(900, 1000), cutaway=True,
             height_fraction=0.55),
    ],
    "core": [
        dict(view=(0.20, -0.45, 1.0), zoom=1.05, res=(1300, 1300)),
        dict(view=(0.55, -1.0, 0.26), zoom=1.08, res=(1300, 1300), cutaway=True),
    ],
    "module": [
        dict(view=(0.55, -1.0, 0.16), zoom=1.05, res=(800, 1600)),
        dict(view=(0.55, -1.0, 0.16), zoom=1.05, res=(800, 1600), cutaway=True),
    ],
}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="results/figures")
    parser.add_argument("--levels", nargs="+", default=list(VARIANTS))
    parser.add_argument("--samples", type=int, default=32)
    return parser.parse_args(argv)


def set_engine(scene):
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        try:
            scene.render.engine = engine
            return engine
        except TypeError:
            continue
    return scene.render.engine


def make_material(name, color, metallic=0.55, roughness=0.32):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    return material


def setup_world(scene):
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    background = world.node_tree.nodes["Background"]
    background.inputs[0].default_value = (0.035, 0.045, 0.060, 1.0)
    background.inputs[1].default_value = 1.0
    scene.world = world


def add_sun(name, rotation, energy):
    data = bpy.data.lights.new(name, type="SUN")
    data.energy = energy
    data.angle = math.radians(4.0)
    light = bpy.data.objects.new(name, data)
    light.rotation_euler = rotation
    bpy.context.collection.objects.link(light)


def setup_lights():
    add_sun("key", (math.radians(55), 0.0, math.radians(35)), 4.0)
    add_sun("fill", (math.radians(70), 0.0, math.radians(-110)), 1.8)
    add_sun("rim", (math.radians(-55), 0.0, math.radians(165)), 2.5)


def import_stl(path, scale=0.01):
    bpy.ops.wm.stl_import(filepath=path)
    obj = bpy.context.selected_objects[0]
    obj.name = os.path.splitext(os.path.basename(path))[0]
    obj.scale = (scale, scale, scale)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    try:
        bpy.ops.object.shade_smooth()
        bpy.ops.object.shade_auto_smooth(angle=math.radians(35))
    except (AttributeError, RuntimeError):
        pass
    return obj


def bounds(obj):
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    low = Vector((min(c[i] for c in corners) for i in range(3)))
    high = Vector((max(c[i] for c in corners) for i in range(3)))
    return low, high


def move_to_origin(obj):
    low, high = bounds(obj)
    centre = (low + high) / 2.0
    obj.location.x -= centre.x
    obj.location.y -= centre.y
    obj.location.z -= low.z
    bpy.context.view_layer.update()


def cut_half(obj):
    """Delete the half nearest the camera (-y) so the render shows the interior."""
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    doomed = [vertex for vertex in bm.verts if vertex.co.y < -1e-6]
    bmesh.ops.delete(bm, geom=doomed, context="VERTS")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def add_camera(centre, ortho_scale, direction):
    data = bpy.data.cameras.new("Camera")
    data.type = "ORTHO"
    data.ortho_scale = ortho_scale
    camera = bpy.data.objects.new("Camera", data)
    bpy.context.collection.objects.link(camera)
    direction = Vector(direction).normalized()
    camera.location = centre + direction * ortho_scale * 6.0
    camera.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = camera
    return camera


def render_level(args, level):
    stl = os.path.join(args.root, "results", "cad", f"nuscale_{level}.stl")
    if not os.path.exists(stl):
        print(f"missing {stl}", flush=True)
        return

    for index, variant in enumerate(VARIANTS[level]):
        cutaway = variant.get("cutaway", False)
        width, height = variant["res"]

        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        set_engine(scene)
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        try:
            scene.eevee.taa_render_samples = args.samples
        except AttributeError:
            pass
        setup_world(scene)
        setup_lights()

        obj = import_stl(stl)
        if cutaway:
            cut_half(obj)
        obj.data.materials.append(
            make_material("steel", (0.60, 0.66, 0.74), metallic=0.78, roughness=0.30)
        )
        move_to_origin(obj)

        low, high = bounds(obj)
        centre = (low + high) / 2.0
        size = max(high - low)
        fraction = variant.get("height_fraction")
        if fraction is not None:
            centre.z = low.z + (high.z - low.z) * fraction
        add_camera(centre, size * variant["zoom"], variant["view"])

        suffix = "_section" if cutaway else ""
        name = f"cad_{level}{suffix}.png"
        scene.render.filepath = os.path.join(args.out_dir, name)
        bpy.ops.render.render(write_still=True)
        print(f"rendered {name}", flush=True)


def main():
    args = parse_args()
    args.root = os.path.abspath(args.root)
    args.out_dir = os.path.join(args.root, args.out)
    os.makedirs(args.out_dir, exist_ok=True)
    for level in args.levels:
        render_level(args, level)


if __name__ == "__main__":
    main()
