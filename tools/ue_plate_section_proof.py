"""Native Unreal mesh-section verts (no OBJ Y-up remap) + plate screenshot."""
from __future__ import annotations

import os

import unreal

OUT = r"D:\Games\test\Stalingrad\Saved\Screenshots\L_Remagen_plates_proof.png"
ASSETS = (
    "/Game/MOHAA/props/SM_flowerplate",
    "/Game/MOHAA/props/SM_servingplate",
    "/Game/MOHAA/props/SM_dish",
    "/Game/MOHAA/props/SM_simplechair",
    "/Game/MOHAA/props/SM_woodchair",
    "/Game/MOHAA/props/SM_banquet_table",
)


def _aabb(tag, pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    dx, dy, dz = max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)
    thin = "XYZ"[min(range(3), key=lambda i: (dx, dy, dz)[i])]
    standing = dz >= 0.7 * max(dx, dy) and min(dx, dy) <= 0.45 * max(dx, dy, dz)
    print(
        tag,
        "n",
        len(pts),
        "x",
        round(min(xs), 3),
        round(max(xs), 3),
        "dx",
        round(dx, 3),
        "y",
        round(min(ys), 3),
        round(max(ys), 3),
        "dy",
        round(dy, 3),
        "z",
        round(min(zs), 3),
        round(max(zs), 3),
        "dz",
        round(dz, 3),
        "thin",
        thin,
        "STANDING" if standing else "not_standing",
    )
    return dx, dy, dz, thin


def _section_verts(mesh):
    pts, nrm = [], []
    lib = getattr(unreal, "ProceduralMeshLibrary", None)
    if lib is None or not hasattr(lib, "get_section_from_static_mesh"):
        print("  no ProceduralMeshLibrary.get_section_from_static_mesh")
        return pts, nrm
    for si in range(8):
        try:
            data = lib.get_section_from_static_mesh(mesh, 0, si)
        except Exception as exc:
            if si == 0:
                print("  section0 fail", exc)
            break
        if not data:
            break
        verts = data[0] if len(data) > 0 else []
        normals = data[2] if len(data) > 2 else []
        if not verts:
            break
        for v in verts:
            pts.append((float(v.x), float(v.y), float(v.z)))
        for n in normals:
            nrm.append((float(n.x), float(n.y), float(n.z)))
        print("  section", si, "verts", len(verts), "normals", len(normals))
    return pts, nrm


def _avg(vs):
    if not vs:
        return (0, 0, 0)
    n = len(vs)
    return tuple(round(sum(v[i] for v in vs) / n, 3) for i in range(3))


def _actor_row(actor):
    loc = actor.get_actor_location()
    rot = actor.get_actor_rotation()
    scl = actor.get_actor_scale3d()
    origin, extent = actor.get_actor_bounds(False)
    comp = actor.static_mesh_component
    rel = None
    try:
        rel = comp.relative_rotation
    except Exception:
        try:
            rel = comp.get_editor_property("relative_rotation")
        except Exception:
            rel = "noprop"
    q = rot.quaternion()
    z = q.rotate_vector(unreal.Vector(0, 0, 1))
    y = q.rotate_vector(unreal.Vector(0, 1, 0))
    print(
        "ACTOR",
        actor.get_actor_label(),
        "loc",
        round(float(loc.x), 2),
        round(float(loc.y), 2),
        round(float(loc.z), 2),
        "P",
        round(float(rot.pitch), 3),
        "Y",
        round(float(rot.yaw), 3),
        "R",
        round(float(rot.roll), 3),
        "scale",
        round(float(scl.x), 4),
        round(float(scl.y), 4),
        round(float(scl.z), 4),
        "rel",
        rel,
        "axis+Z",
        round(float(z.x), 3),
        round(float(z.y), 3),
        round(float(z.z), 3),
        "axis+Y",
        round(float(y.x), 3),
        round(float(y.y), 3),
        round(float(y.z), 3),
        "worldSpan",
        round(2 * float(extent.x), 2),
        round(2 * float(extent.y), 2),
        round(2 * float(extent.z), 2),
        "worldZ",
        round(float(origin.z) - float(extent.z), 2),
        round(float(origin.z) + float(extent.z), 2),
    )


def _capture():
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    plate = table = None
    for actor in list(sub.get_all_level_actors() or []):
        label = (actor.get_actor_label() or "").lower()
        if plate is None and "flowerplate_0" in label:
            plate = actor
        if table is None and "banquet_table_0" in label:
            table = actor
        if any(s in label for s in ("flowerplate_0", "servingplate_0", "dish_0", "simplechair_0", "woodchair_1", "banquet_table_0")):
            _actor_row(actor)
    focus = plate or table
    if focus is None:
        print("NO FOCUS")
        return
    loc = focus.get_actor_location()
    cam = unreal.Vector(float(loc.x) + 80.0, float(loc.y) + 220.0, float(loc.z) + 160.0)
    rot = unreal.Rotator(pitch=-42.0, yaw=-110.0, roll=0.0)
    ues.set_level_viewport_camera_info(cam, rot)
    print("CAM", round(float(cam.x), 1), round(float(cam.y), 1), round(float(cam.z), 1))
    # SceneCapture so the file actually appears.
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    rt = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        "RT_PlateProof",
        "/Game/MOHAA/tmp",
        unreal.TextureRenderTarget2D,
        unreal.TextureRenderTargetFactoryNew(),
    )
    if rt is None:
        rt = unreal.EditorAssetLibrary.load_asset("/Game/MOHAA/tmp/RT_PlateProof")
    if rt is None:
        print("NO RT")
        return
    try:
        rt.set_editor_property("size_x", 1920)
        rt.set_editor_property("size_y", 1080)
        rt.set_editor_property("render_target_format", unreal.TextureRenderTargetFormat.RTF_RGBA8)
    except Exception as exc:
        print("rt props", exc)
    cap_actor = sub.spawn_actor_from_class(unreal.SceneCapture2D, cam, rot)
    comp = cap_actor.capture_component2d
    comp.set_editor_property("texture_target", rt)
    comp.set_editor_property("capture_every_frame", False)
    comp.set_editor_property("capture_on_movement", False)
    try:
        comp.set_editor_property("primitive_render_mode", unreal.SceneCapturePrimitiveRenderMode.PRM_RENDER_SCENE_PRIMITIVES)
    except Exception:
        pass
    try:
        comp.capture_scene()
    except Exception as exc:
        print("capture_scene", exc)
    try:
        unreal.RenderingLibrary.export_render_target(ues.get_editor_world(), rt, os.path.dirname(OUT), os.path.basename(OUT))
        print("WROTE", OUT, os.path.isfile(OUT))
    except Exception as exc:
        print("export rt", exc)
        try:
            unreal.SystemLibrary.execute_console_command(ues.get_editor_world(), "HighResShot 1920x1080")
            print("HighResShot issued")
        except Exception as exc2:
            print("highres", exc2)
    try:
        sub.destroy_actor(cap_actor)
    except Exception:
        pass


def main():
    print("LEVEL", unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world().get_name())
    for path in ASSETS:
        mesh = unreal.EditorAssetLibrary.load_asset(path)
        print("MESH", path.split("/")[-1])
        if mesh is None:
            print("  MISSING")
            continue
        b = mesh.get_bounds()
        print(
            "  get_bounds extent",
            round(float(b.box_extent.x), 3),
            round(float(b.box_extent.y), 3),
            round(float(b.box_extent.z), 3),
        )
        pts, nrm = _section_verts(mesh)
        if pts:
            _aabb("  SECTION", pts)
            print("  avg_n", _avg(nrm), "n0", nrm[0] if nrm else None)
        else:
            print("  no section verts")
    _capture()


main()
