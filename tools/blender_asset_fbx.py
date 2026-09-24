"""Import a MOHAA asset OBJ (game units = cm, Z-up) and write a UE-ready FBX.

  blender --background --python blender_asset_fbx.py -- in.obj out.fbx [skel.json] [--map]
"""
from __future__ import annotations

import json
import re
import sys
from math import radians
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

if "--" in sys.argv:
    args = sys.argv[sys.argv.index("--") + 1 :]
else:
    args = sys.argv[-2:]

map_mode = "--map" in args
# --world used to pre-negate Y to cancel Unreal's FBX Y-mirror. That flipped
# the town (spiegelbeeld). Maps keep native left/right; furniture Y is mirrored.
args = [a for a in args if a not in ("--map", "--world")]

if len(args) < 2:
    print("ERROR: usage: blender --background --python blender_asset_fbx.py -- in.obj out.fbx [skel.json] [--map]")
    sys.exit(2)

obj_path = Path(args[0])
fbx_path = Path(args[1])
skel_path = Path(args[2]) if len(args) >= 3 and args[2] else None
# SKD/OBJ units are centimeters (Engineer ~185 tall). Blender scene is also cm
# (1 unit = 1 cm) so FBX UnitScaleFactor stays 1 and Unreal Bip01 scale is 1.
UNIT_TO_METERS = 1.0
# MOHAA character forward is +X (Z-up). The collaborator library and pack
# IK_Mohaa bake a rigid +90° Z rebase so character forward becomes +Y.
# Characters: Y-mirror then +90° world Z (mesh + bones stay glued, L stays L).
# That FBX is already Unreal/pack space — skeletal import must not convert_scene.
# BSP maps skip the Y-mirror so left/right matches native MOHAA / preview.
UNREAL_FORWARD_YAW = Matrix.Rotation(radians(90.0), 4, "Z")
DELTA_ROOT = "delta"

bpy.ops.wm.read_factory_settings(use_empty=True)
_scene = bpy.context.scene
_scene.unit_settings.system = "METRIC"
_scene.unit_settings.scale_length = 0.01

imported = False
obj_kwargs = dict(filepath=str(obj_path), global_scale=1.0, forward_axis="Y", up_axis="Z")
if skel_path:
    obj_kwargs["use_split_objects"] = False
    obj_kwargs["use_split_groups"] = False
try:
    bpy.ops.wm.obj_import(**obj_kwargs)
    imported = True
except TypeError:
    obj_kwargs.pop("use_split_objects", None)
    obj_kwargs.pop("use_split_groups", None)
    try:
        bpy.ops.wm.obj_import(**obj_kwargs)
        imported = True
    except Exception as exc:
        print("wm.obj_import failed:", exc)
except Exception as exc:
    print("wm.obj_import failed:", exc)

if not imported:
    try:
        bpy.ops.import_scene.obj(filepath=str(obj_path))
        imported = True
    except Exception as exc:
        print("import_scene.obj failed:", exc)
        sys.exit(3)

meshes = [ob for ob in bpy.context.scene.objects if ob.type == "MESH"]
print("Imported mesh objects:", len(meshes))
if not meshes:
    print("ERROR: no mesh objects after OBJ import")
    sys.exit(4)

bpy.ops.object.select_all(action="DESELECT")
for ob in meshes:
    ob.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
    print("Joined into 1 mesh object")


def _set(obj, prop, value):
    if obj is not None and hasattr(obj, prop):
        try:
            setattr(obj, prop, value)
            return True
        except Exception as exc:
            print("skip", type(obj).__name__, prop, exc)
    return False


def force_opaque_materials():
    """Blender 5.2 ignores blend_method; use surface_render_method + no image alpha."""
    for img in bpy.data.images:
        _set(img, "alpha_mode", "NONE")
        try:
            if img.channels >= 4 and img.size[0] and img.pixels:
                px = list(img.pixels)
                for i in range(3, len(px), 4):
                    px[i] = 1.0
                img.pixels[:] = px
                print("flattened alpha", img.name, img.size[:])
        except Exception as exc:
            print("image flatten skip", img.name, exc)
    for mat in bpy.data.materials:
        _set(mat, "blend_method", "OPAQUE")
        _set(mat, "surface_render_method", "DITHERED")
        _set(mat, "use_transparency_overlap", False)
        _set(mat, "use_transparent_shadow", False)
        _set(mat, "use_raytrace_refraction", False)
        _set(mat, "use_screen_refraction", False)
        _set(mat, "shadow_method", "OPAQUE")
        try:
            col = list(mat.diffuse_color)
            if len(col) >= 4:
                col[3] = 1.0
                mat.diffuse_color = col
        except Exception:
            pass
        tree = getattr(mat, "node_tree", None)
        if tree is None:
            print("OPAQUE", mat.name, "no nodes")
            continue
        for node in tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                for sock_name in ("Alpha", "Transmission Weight", "Transmission"):
                    sock = node.inputs.get(sock_name)
                    if not sock:
                        continue
                    for link in list(tree.links):
                        if link.to_socket == sock:
                            tree.links.remove(link)
                    try:
                        sock.default_value = 0.0 if "Transmission" in sock_name else 1.0
                    except Exception:
                        pass
            if node.type == "BSDF_TRANSPARENT":
                tree.nodes.remove(node)
            if node.type == "TEX_IMAGE":
                _set(node, "image", node.image)
                if getattr(node, "image", None) is not None:
                    _set(node.image, "alpha_mode", "NONE")
        print("OPAQUE", mat.name, "surface_render_method", getattr(mat, "surface_render_method", None))


def convert_mesh_coords(mesh, *, mirror_y=True):
    """Game units stay cm, optional Y-mirror, then +90° Z so +X forward becomes +Y.

    Characters need Y-mirror for Manny handedness. Maps keep native left/right
    (no character Y-mirror, no FBX pre-negate). Unreal's importer Y-mirrors
    static meshes; furniture spawn locations negate Unreal Y to match.
    """
    yaw = UNREAL_FORWARD_YAW.to_3x3()
    y_sign = -1.0 if mirror_y else 1.0
    for v in mesh.vertices:
        p = Vector((v.co.x * UNIT_TO_METERS, y_sign * v.co.y * UNIT_TO_METERS, v.co.z * UNIT_TO_METERS))
        p = yaw @ p
        v.co = p
    mesh.update()


def mohaa_world_to_blender(R_rows, T):
    """Convert a MOHAA bone (rows=axes, cm, Z-up) into Blender world.

    Mesh verts use (x, -y, z) then +90° Z. Bone matrices use the
    matching similarity so rest pose stays glued to the mesh.
    Local -90° Z makes Blender bone +Y follow MOHAA bone +X (limb axis).
    """
    B = Matrix(
        (
            (R_rows[0][0], R_rows[1][0], R_rows[2][0]),
            (R_rows[0][1], R_rows[1][1], R_rows[2][1]),
            (R_rows[0][2], R_rows[1][2], R_rows[2][2]),
        )
    )
    mirror = Matrix.Diagonal((1.0, -1.0, 1.0)).to_3x3()
    Rbl = mirror @ B @ mirror
    mat = Rbl.to_4x4()
    mat.translation = Vector((T[0] * UNIT_TO_METERS, -T[1] * UNIT_TO_METERS, T[2] * UNIT_TO_METERS))
    align = Matrix.Rotation(radians(-90.0), 4, "Z")
    return UNREAL_FORWARD_YAW @ mat @ align


def rebuild_mesh_from_skel(ob, skel):
    pos = skel.get("positions") or []
    idx = skel.get("indices") or []
    uvs = skel.get("uvs") or []
    nrm = skel.get("normals") or []
    verts = [(pos[i], pos[i + 1], pos[i + 2]) for i in range(0, len(pos), 3)]
    faces = [(idx[i], idx[i + 1], idx[i + 2]) for i in range(0, len(idx), 3) if i + 2 < len(idx)]
    if not verts or not faces:
        print("ERROR: skel JSON has no mesh data to rebuild")
        return False
    old_mats = list(ob.data.materials)
    me = bpy.data.meshes.new(ob.data.name + "_skd")
    me.from_pydata(verts, [], faces)
    me.update()
    if uvs:
        uv_layer = me.uv_layers.new(name="UVMap")
        for loop in me.loops:
            vi = loop.vertex_index
            if vi * 2 + 1 < len(uvs):
                uv_layer.data[loop.index].uv = (uvs[vi * 2], uvs[vi * 2 + 1])
    if nrm and len(nrm) >= len(verts) * 3:
        try:
            me.normals_split_custom_set_from_vertices(
                [Vector((nrm[i], nrm[i + 1], nrm[i + 2])) for i in range(0, len(verts) * 3, 3)]
            )
        except Exception as exc:
            print("custom normals skip", exc)
    for mat in old_mats:
        me.materials.append(mat)
    groups = [
        g
        for g in (skel.get("groups") or [])
        if not g.get("nodraw")
        and g.get("status") != "NODRAW"
        and int(g.get("count") or 0) > 0
    ]
    for gi, g in enumerate(groups):
        start = int(g.get("start") or 0) // 3
        count = int(g.get("count") or 0) // 3
        mi = gi if gi < len(me.materials) else max(0, len(me.materials) - 1)
        for pi in range(start, start + count):
            if 0 <= pi < len(me.polygons):
                me.polygons[pi].material_index = mi
    old = ob.data
    ob.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    print("Rebuilt mesh from SKD JSON", len(verts), "verts", len(faces), "tris")
    return True


def delta_world_matrix():
    """Pack/library scene root: +90° Z at the origin, no SKD bone-axis align."""
    return UNREAL_FORWARD_YAW.copy()


def bind_armature(ob, skel):
    bones = skel.get("bones") or []
    influences = skel.get("influences") or []
    if not bones:
        print("ERROR: no bones in skel JSON")
        return None, []
    amt = bpy.data.armatures.new("MOHAA_Skeleton")
    arm = bpy.data.objects.new("Armature", amt)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    edit = {}
    has_delta = any(str(b.get("name") or "") == DELTA_ROOT for b in bones)
    if not has_delta:
        # SKD roots at Bip01. The library/pack IK root is a non-deforming
        # `delta` parent at the origin (same names, no SKD/SKC rewrite).
        eb = amt.edit_bones.new(DELTA_ROOT)
        mat = delta_world_matrix()
        loc = mat.to_translation()
        y = (mat.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
        if y.length < 1e-8:
            y = Vector((0.0, 5.0, 0.0))
        eb.head = loc
        eb.tail = loc + y * 5.0
        try:
            eb.align_roll(mat.to_3x3() @ Vector((0.0, 0.0, 1.0)))
        except Exception:
            pass
        eb.use_connect = False
        eb.use_deform = False
        edit[DELTA_ROOT] = eb
        print("Added Unreal root wrapper", DELTA_ROOT, "(non-deforming, +90 Z)")
    for b in bones:
        name = str(b.get("name") or "bone")
        eb = amt.edit_bones.new(name)
        mat = mohaa_world_to_blender(b["world_r"], b["world_t"])
        loc = mat.to_translation()
        y = (mat.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
        if y.length < 1e-8:
            y = Vector((0.0, 5.0, 0.0))
        eb.head = loc
        eb.tail = loc + y * 5.0
        z = mat.to_3x3() @ Vector((0.0, 0.0, 1.0))
        try:
            eb.align_roll(z)
        except Exception:
            pass
        eb.use_connect = False
        eb.use_deform = True
        edit[name] = eb
    for b in bones:
        pi = int(b.get("parent_index", -1))
        if pi < 0 or pi >= len(bones):
            continue
        name = str(b.get("name") or "bone")
        parent_name = str(bones[pi].get("name") or "")
        if parent_name in edit and name in edit and parent_name != name:
            edit[name].parent = edit[parent_name]
    if not has_delta:
        for b in bones:
            if int(b.get("parent_index", -1)) >= 0:
                continue
            name = str(b.get("name") or "bone")
            if name in edit and name != DELTA_ROOT:
                edit[name].parent = edit[DELTA_ROOT]
    bpy.ops.object.mode_set(mode="POSE")
    done = set()
    order = []

    def visit(i):
        if i in done or i < 0 or i >= len(bones):
            return
        visit(int(bones[i].get("parent_index", -1)))
        done.add(i)
        order.append(i)

    for i in range(len(bones)):
        visit(i)
    if not has_delta:
        pb = arm.pose.bones.get(DELTA_ROOT)
        if pb is not None:
            pb.matrix = delta_world_matrix()
            bpy.context.view_layer.update()
    for i in order:
        b = bones[i]
        name = str(b.get("name") or "bone")
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue
        pb.matrix = mohaa_world_to_blender(b["world_r"], b["world_t"])
        bpy.context.view_layer.update()
    bpy.ops.pose.select_all(action="SELECT")
    try:
        bpy.ops.pose.armature_apply()
    except Exception as exc:
        print("armature_apply skip", exc)
    bpy.ops.object.mode_set(mode="OBJECT")

    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="OBJECT")
    existing = {vg.name for vg in ob.vertex_groups}
    for b in bones:
        name = str(b.get("name") or "bone")
        if name not in existing:
            ob.vertex_groups.new(name=name)
            existing.add(name)
    assigned = 0
    for vi, inf in enumerate(influences):
        if vi >= len(ob.data.vertices):
            break
        for item in inf or []:
            if not item:
                continue
            bi = int(item[0])
            w = float(item[1])
            if w <= 0.0 or bi < 0 or bi >= len(bones):
                continue
            vg = ob.vertex_groups.get(str(bones[bi].get("name") or "bone"))
            if vg is None:
                continue
            vg.add([vi], w, "ADD")
            assigned += 1
    print("Vertex group weights assigned", assigned, "on", min(len(influences), len(ob.data.vertices)), "verts")

    arm.matrix_world = Matrix.Identity(4)
    ob.matrix_world = Matrix.Identity(4)
    mod = ob.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm
    mod.use_vertex_groups = True
    mod.use_bone_envelopes = False
    ob.parent = arm
    ob.parent_type = "OBJECT"
    names = [str(bones[i].get("name") or "bone") for i in order]
    if not has_delta:
        names = [DELTA_ROOT] + names
    print("Armature bones", len(names), "mesh verts", len(ob.data.vertices), "root", names[0] if names else "")
    return arm, names


def clip_slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name or "anim").strip("_")
    return s[:80] or "anim"


def apply_animation_clip(arm, clip, bone_order):
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.scale = (1.0, 1.0, 1.0)
    action_name = str(clip.get("name") or clip.get("alias") or "anim")
    action = bpy.data.actions.new(name=action_name)
    if arm.animation_data is None:
        arm.animation_data_create()
    arm.animation_data.action = action
    fps = float(clip.get("fps") or 20.0)
    fps_i = max(1, int(round(fps)))
    scene = bpy.context.scene
    scene.render.fps = fps_i
    scene.render.fps_base = 1.0
    frames = clip.get("frames") or []
    scene.frame_start = 0
    scene.frame_end = max(0, len(frames) - 1)
    for fi, frame in enumerate(frames):
        scene.frame_set(fi)
        by = {b.get("name"): b for b in frame}
        pb_delta = arm.pose.bones.get(DELTA_ROOT)
        if pb_delta is not None and DELTA_ROOT not in by:
            pb_delta.matrix = delta_world_matrix()
            bpy.context.view_layer.update()
        # Parent-first, flush depsgraph per bone so pose.matrix setter
        # uses the new parent world (same as bind_armature).
        for name in bone_order:
            rec = by.get(name)
            if not rec:
                continue
            pb = arm.pose.bones.get(name)
            if pb is None:
                continue
            pb.matrix = mohaa_world_to_blender(rec["world_r"], rec["world_t"])
            bpy.context.view_layer.update()
        for pb in arm.pose.bones:
            pb.scale = (1.0, 1.0, 1.0)
            pb.keyframe_insert("location", frame=fi)
            pb.keyframe_insert("rotation_quaternion", frame=fi)
            pb.keyframe_insert("scale", frame=fi)
    print("Keyed clip", action_name, "frames", len(frames), "fps", fps_i)


def export_fbx(path, object_types, bake_anim=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    has_arm = "ARMATURE" in object_types
    # Scene is centimeters, so UnitScaleFactor is 1. FBX_SCALE_NONE keeps
    # Bip01 scale 1. Static meshes still use FBX_SCALE_ALL.
    bpy.ops.export_scene.fbx(
        filepath=str(path),
        use_selection=False,
        object_types=object_types,
        mesh_smooth_type="OFF",
        bake_space_transform=False,
        axis_forward="Y",
        axis_up="Z",
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_NONE" if has_arm else "FBX_SCALE_ALL",
        add_leaf_bones=False,
        use_armature_deform_only=False,
        bake_anim=bake_anim,
        bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True,
        path_mode="COPY",
        embed_textures=True,
        global_scale=1.0,
    )
    print("Wrote", path, "size", path.stat().st_size)


ob = bpy.context.view_layer.objects.active
skel = None
if skel_path:
    skel = json.loads(skel_path.read_text(encoding="utf-8"))
    print(
        "Loaded skeleton JSON",
        skel_path,
        "bones",
        len(skel.get("bones") or []),
        "influences",
        len(skel.get("influences") or []),
        "anims",
        len(skel.get("animations") or []),
    )

arm = None
bone_order = []
if ob and ob.type == "MESH":
    bpy.ops.object.mode_set(mode="OBJECT")
    if skel:
        n_mesh = len(ob.data.vertices)
        n_json = len(skel.get("influences") or []) or (len(skel.get("positions") or []) // 3)
        print("OBJ verts", n_mesh, "SKD verts", n_json)
        rebuild_mesh_from_skel(ob, skel)
    if map_mode:
        # Keep BSP world origin. OBJ import can park the object at the
        # centroid; bake that back so entity/staticmodel origins match verts.
        print("map object loc before apply", tuple(ob.location), "rot", tuple(ob.rotation_euler))
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        print("map object loc after apply", tuple(ob.location))
    convert_mesh_coords(ob.data, mirror_y=not map_mode)
    bpy.context.view_layer.update()
    force_opaque_materials()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    if map_mode:
        print("map mode: skip Y-mirror, keep +90 Z")
    else:
        try:
            # Open meshes (ejection ports, barrels) are not watertight;
            # make_consistent can flip a shell and punch a hole. Y-mirror
            # only needs a uniform winding flip.
            bpy.ops.mesh.flip_normals()
        except Exception as err:
            print("flip_normals skip", err)
        print("normals flipped after Y-mirror")
    bpy.ops.object.mode_set(mode="OBJECT")
    try:
        bpy.ops.object.shade_smooth()
    except Exception as err:
        print("shade_smooth skip", err)
    xs = [v.co.copy() for v in ob.data.vertices]
    dx = max(v.x for v in xs) - min(v.x for v in xs)
    dy = max(v.y for v in xs) - min(v.y for v in xs)
    dz = max(v.z for v in xs) - min(v.z for v in xs)
    print("Mesh size cm: %.3f x %.3f x %.3f" % (dx, dy, dz))
    if map_mode:
        print(
            "map aabb cm: x[%.3f %.3f] y[%.3f %.3f] z[%.3f %.3f]"
            % (
                min(v.x for v in xs),
                max(v.x for v in xs),
                min(v.y for v in xs),
                max(v.y for v in xs),
                min(v.z for v in xs),
                max(v.z for v in xs),
            )
        )
    if skel:
        arm, bone_order = bind_armature(ob, skel)
        if arm is not None:
            pb = arm.pose.bones.get("Bip01")
            if pb is not None:
                bpy.context.view_layer.update()
                ax = pb.matrix.to_3x3() @ Vector((1.0, 0.0, 0.0))
                ay = pb.matrix.to_3x3() @ Vector((0.0, 1.0, 0.0))
                print("Bip01 blender +X %.3f %.3f %.3f +Y %.3f %.3f %.3f T %.3f %.3f %.3f" % (
                    ax.x, ax.y, ax.z, ay.x, ay.y, ay.z,
                    pb.matrix.translation.x, pb.matrix.translation.y, pb.matrix.translation.z,
                ))
            pd = arm.pose.bones.get(DELTA_ROOT)
            if pd is not None:
                print("delta blender T %.3f %.3f %.3f parent %s" % (
                    pd.matrix.translation.x, pd.matrix.translation.y, pd.matrix.translation.z,
                    getattr(pd, "parent", None) and pd.parent.name or "None",
                ))
            pl = arm.pose.bones.get("Bip01 L Foot")
            pr = arm.pose.bones.get("Bip01 R Foot")
            if pl is not None and pr is not None:
                print("L Foot T %.3f %.3f %.3f  R Foot T %.3f %.3f %.3f" % (
                    pl.matrix.translation.x, pl.matrix.translation.y, pl.matrix.translation.z,
                    pr.matrix.translation.x, pr.matrix.translation.y, pr.matrix.translation.z,
                ))

export_fbx(fbx_path, {"MESH", "ARMATURE"} if skel else {"MESH"}, bake_anim=False)
if arm is not None:
    for clip in (skel or {}).get("animations") or []:
        apply_animation_clip(arm, clip, bone_order)
        anim_path = fbx_path.with_name(fbx_path.stem + "_A_" + clip_slug(clip.get("name") or clip.get("alias") or "anim") + ".fbx")
        export_fbx(anim_path, {"MESH", "ARMATURE"}, bake_anim=True)
sys.exit(0)
