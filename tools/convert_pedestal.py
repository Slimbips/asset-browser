import bpy
from mathutils import Vector
from pathlib import Path

src = Path(r"C:\Users\paulh\Desktop\New folder (14)\Meshy_AI_round_black_platform_0922133545_image-to-3d-texture.fbx")
dst = Path(r"C:\Users\paulh\Desktop\conv\asset-browser\web\pedestal.glb")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(src))

for ob in list(bpy.context.scene.objects):
    print("OBJ", ob.name, ob.type, "loc", tuple(ob.location), "dim", tuple(ob.dimensions) if ob.type == "MESH" else None)

meshes = [ob for ob in bpy.context.scene.objects if ob.type == "MESH"]
if not meshes:
    raise SystemExit("no mesh")

# World AABB
mn = Vector((1e9, 1e9, 1e9))
mx = Vector((-1e9, -1e9, -1e9))
for ob in meshes:
    for corner in ob.bound_box:
        w = ob.matrix_world @ Vector(corner)
        mn.x, mn.y, mn.z = min(mn.x, w.x), min(mn.y, w.y), min(mn.z, w.z)
        mx.x, mx.y, mx.z = max(mx.x, w.x), max(mx.y, w.y), max(mx.z, w.z)
print("AABB min", tuple(mn), "max", tuple(mx), "size", tuple(mx - mn))

dst.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=str(dst),
    export_format="GLB",
    export_texcoords=True,
    export_normals=True,
    export_materials="EXPORT",
    export_cameras=False,
    export_lights=False,
)
print("Wrote", dst, "bytes", dst.stat().st_size)
