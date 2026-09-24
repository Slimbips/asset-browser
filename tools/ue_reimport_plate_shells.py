"""Reimport flipped dish FBXs into L_Remagen. Loc/rot/scale unchanged."""
from __future__ import annotations

import unreal

PROPS = r"C:\Users\paulh\Desktop\conv\asset-browser\export\Remagen\props"
STEMS = ("flowerplate", "servingplate", "dish")
DEST = "/Game/MOHAA/props"


def _set(obj, prop, value) -> bool:
    try:
        obj.set_editor_property(prop, value)
        return True
    except Exception:
        return False


def _reimport(stem: str) -> None:
    fbx = PROPS + "\\" + stem + ".fbx"
    name = "SM_" + stem
    task = unreal.AssetImportTask()
    task.filename = fbx
    task.destination_path = DEST
    task.destination_name = name
    task.automated = True
    task.save = True
    task.replace_existing = True
    options = unreal.FbxImportUI()
    options.import_mesh = True
    options.import_materials = False
    options.import_textures = False
    options.automated_import_should_detect_type = False
    options.import_animations = False
    options.import_as_skeletal = False
    options.mesh_type_to_import = unreal.FBXImportType.FBXIT_STATIC_MESH
    smd = options.static_mesh_import_data
    smd.combine_meshes = True
    smd.auto_generate_collision = True
    smd.import_uniform_scale = 1.0
    smd.convert_scene = True
    _set(smd, "convert_scene_unit", False)
    smd.force_front_x_axis = False
    _set(smd, "transform_vertex_to_absolute", True)
    task.options = options
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    print("REIMPORT", name, list(task.imported_object_paths or []))


def _print_actor(tag: str, actor) -> None:
    loc = actor.get_actor_location()
    rot = actor.get_actor_rotation()
    q = rot.quaternion()
    z = q.rotate_vector(unreal.Vector(0, 0, 1))
    origin, extent = actor.get_actor_bounds(False)
    mesh = None
    try:
        mesh = actor.static_mesh_component.static_mesh
    except Exception:
        pass
    b = mesh.get_bounds() if mesh else None
    print(
        tag,
        actor.get_actor_label(),
        "locZ",
        round(float(loc.z), 3),
        "P",
        round(float(rot.pitch), 2),
        "Y",
        round(float(rot.yaw), 2),
        "R",
        round(float(rot.roll), 2),
        "axis+Z",
        round(float(z.x), 3),
        round(float(z.y), 3),
        round(float(z.z), 3),
        "visZ",
        round(float(origin.z) - float(extent.z), 2),
        round(float(origin.z) + float(extent.z), 2),
        "mesh_minz",
        round(float(b.origin.z) - float(b.box_extent.z), 3) if b else None,
        "mesh_maxz",
        round(float(b.origin.z) + float(b.box_extent.z), 3) if b else None,
        "scale",
        round(float(actor.get_actor_scale3d().x), 4),
    )


def main() -> None:
    print("LEVEL", unreal.EditorLevelLibrary.get_editor_world().get_name())
    for stem in STEMS:
        _reimport(stem)

    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    plate = chair = table = None
    for actor in list(sub.get_all_level_actors() or []):
        label = (actor.get_actor_label() or "").lower()
        if plate is None and "flowerplate" in label:
            plate = actor
        if chair is None and "simplechair" in label:
            chair = actor
        if table is None and "banquet_table" in label:
            table = actor
    if plate:
        _print_actor("PROOF_PLATE", plate)
    if chair:
        _print_actor("PROOF_CHAIR", chair)
    if table:
        _print_actor("PROOF_TABLE", table)
    if plate and table:
        po, pe = plate.get_actor_bounds(False)
        to, te = table.get_actor_bounds(False)
        plate_min = float(po.z) - float(pe.z)
        table_top = float(to.z) + float(te.z)
        pr = plate.get_actor_rotation()
        cr = chair.get_actor_rotation() if chair else None
        print(
            "PROOF plate_on_cloth dZ_cm",
            round(plate_min - table_top, 2),
            "plate_pitch_roll",
            round(float(pr.pitch), 2),
            round(float(pr.roll), 2),
            "chair_pitch_roll",
            None if cr is None else (round(float(cr.pitch), 2), round(float(cr.roll), 2)),
            "chair_upright",
            None if chair is None else (float(chair.get_actor_bounds(False)[1].z) > 40.0),
        )
    if plate is not None:
        loc = plate.get_actor_location()
        cam = unreal.Vector(float(loc.x) + 80.0, float(loc.y) + 180.0, float(loc.z) + 40.0)
        rot = unreal.Rotator(pitch=-18.0, yaw=-110.0, roll=0.0)
        try:
            ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
            ues.set_level_viewport_camera_info(cam, rot)
            print("FOCUS plates")
        except Exception as exc:
            print("focus skip", exc)
    try:
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
        print("SAVED L_Remagen")
    except Exception as exc:
        print("save skip", exc)


main()
