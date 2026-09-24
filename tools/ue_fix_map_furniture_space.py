"""Restore unmirrored L_Remagen and move furniture into that BSP space.

Do not scale the map (1,-1,1). Do not LoadLevel. No retarget.
Map FBX is --map only (no Y-pre-negate). Furniture loc=(-Y,-X,Z)*2.54.
"""
from __future__ import annotations

import unreal

MESH_PATH = "/Game/MOHAA/maps/SM_Remagen"
FBX = r"C:\Users\paulh\Desktop\conv\asset-browser\export\Remagen\Remagen.fbx"
TABLE_UE = (3006.268, -10149.332, 40.767)
CHAIR_UE = (3475.126, -10048.545, 40.64)
TABLE_BSP = (3995.8, -1183.57, 16.05)


def _set(obj, prop, value) -> bool:
    try:
        obj.set_editor_property(prop, value)
        return True
    except Exception:
        return False


def _print_bounds(tag: str) -> dict:
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    map_actor = None
    table = None
    chair = None
    n_prop = 0
    n_sun = 0
    for actor in list(sub.get_all_level_actors() or []):
        label = actor.get_actor_label() or ""
        if label == "SM_Remagen":
            map_actor = actor
        if label.startswith("MOHAA_prop_"):
            n_prop += 1
        if label.startswith("MOHAA_prop_SM_table_") and table is None:
            table = actor
        if label.startswith("MOHAA_prop_SM_simplechair_") and chair is None:
            chair = actor
        if isinstance(actor, unreal.DirectionalLight):
            n_sun += 1
            print("SUN", label, actor.get_actor_location(), actor.get_actor_rotation())
    out = {"map": map_actor, "table": table, "chair": chair, "n_prop": n_prop, "n_sun": n_sun}
    if map_actor is None:
        print(tag, "NO SM_Remagen actor")
        return out
    loc = map_actor.get_actor_location()
    rot = map_actor.get_actor_rotation()
    scl = map_actor.get_actor_scale3d()
    origin, extent = map_actor.get_actor_bounds(False)
    print(
        tag,
        "actor loc",
        round(float(loc.x), 3),
        round(float(loc.y), 3),
        round(float(loc.z), 3),
        "rot",
        round(float(rot.pitch), 2),
        round(float(rot.yaw), 2),
        round(float(rot.roll), 2),
        "scale",
        round(float(scl.x), 4),
        round(float(scl.y), 4),
        round(float(scl.z), 4),
    )
    print(
        tag,
        "bounds origin",
        round(float(origin.x), 1),
        round(float(origin.y), 1),
        round(float(origin.z), 1),
        "extent",
        round(float(extent.x), 1),
        round(float(extent.y), 1),
        round(float(extent.z), 1),
        "props",
        n_prop,
        "dirlights",
        n_sun,
    )
    mn = (
        float(origin.x) - float(extent.x),
        float(origin.y) - float(extent.y),
        float(origin.z) - float(extent.z),
    )
    mx = (
        float(origin.x) + float(extent.x),
        float(origin.y) + float(extent.y),
        float(origin.z) + float(extent.z),
    )
    print(tag, "aabb min", [round(v, 1) for v in mn], "max", [round(v, 1) for v in mx])
    mesh = unreal.EditorAssetLibrary.load_asset(MESH_PATH)
    if mesh is not None:
        b = mesh.get_bounds()
        print(
            tag,
            "mesh bounds origin",
            round(float(b.origin.x), 1),
            round(float(b.origin.y), 1),
            round(float(b.origin.z), 1),
            "extent",
            round(float(b.box_extent.x), 1),
            round(float(b.box_extent.y), 1),
            round(float(b.box_extent.z), 1),
        )
    for name, actor in (("table", table), ("chair", chair)):
        if actor is None:
            print(tag, name, "MISSING")
            continue
        p = actor.get_actor_location()
        p = (float(p.x), float(p.y), float(p.z))
        inside = mn[0] <= p[0] <= mx[0] and mn[1] <= p[1] <= mx[1] and mn[2] <= p[2] <= mx[2]
        print(
            tag,
            name,
            "loc",
            round(p[0], 1),
            round(p[1], 1),
            round(p[2], 1),
            "inside_town_aabb",
            inside,
        )
        out[name + "_inside"] = inside
        out[name + "_loc"] = p
    print(tag, "claimed table BSP", TABLE_BSP, "UE (-Y,-X,Z)*2.54", TABLE_UE)
    print(tag, "claimed chair UE", CHAIR_UE)
    return out


def _reimport_map() -> None:
    task = unreal.AssetImportTask()
    task.filename = FBX
    task.destination_path = "/Game/MOHAA/maps"
    task.destination_name = "SM_Remagen"
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
    print("REIMPORT unmirrored map FBX", list(task.imported_object_paths or []))


def _mirror_furniture_into_map_space() -> int:
    """Existing props used loc=(-Y,X,Z)*2.54. Unmirrored map needs (-Y,-X,Z)*2.54."""
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    table = None
    for actor in list(sub.get_all_level_actors() or []):
        label = actor.get_actor_label() or ""
        if label.startswith("MOHAA_prop_SM_table_") and table is None:
            table = actor
    if table is None:
        print("FURNITURE skip: no table actor")
        return 0
    ty = float(table.get_actor_location().y)
    if ty < 0:
        print("FURNITURE already in unmirrored space table_y", round(ty, 1))
        return 0
    n = 0
    for actor in list(sub.get_all_level_actors() or []):
        label = actor.get_actor_label() or ""
        if not label.startswith("MOHAA_prop_"):
            continue
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        actor.set_actor_location(
            unreal.Vector(float(loc.x), -float(loc.y), float(loc.z)), False, False
        )
        actor.set_actor_rotation(
            unreal.Rotator(pitch=float(rot.pitch), yaw=-float(rot.yaw), roll=-float(rot.roll)),
            False,
        )
        n += 1
    print("FURNITURE Y-mirrored into map space", n)
    return n


def _dedupe_suns() -> None:
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    kept = None
    extra = 0
    for actor in list(sub.get_all_level_actors() or []):
        if not isinstance(actor, unreal.DirectionalLight):
            continue
        label = actor.get_actor_label() or ""
        if kept is None and label == "MOHAA_Sun":
            kept = actor
            continue
        extra += 1
        sub.destroy_actor(actor)
    if extra:
        print("REMOVED extra directional lights", extra)
    if kept is not None:
        lc = None
        for attr in ("light_component", "directional_light_component"):
            lc = getattr(kept, attr, None)
            if lc:
                break
        if lc is None:
            lc = kept.root_component
        _set(lc, "atmosphere_sun_light", True)
        _set(lc, "forward_shading_priority", 0)
        print("SUN kept", kept.get_actor_label())


def _focus_table(table) -> None:
    if table is None:
        return
    loc = table.get_actor_location()
    cam = unreal.Vector(float(loc.x) + 800.0, float(loc.y) + 800.0, float(loc.z) + 400.0)
    rot = unreal.Rotator(pitch=-22.0, yaw=-135.0, roll=0.0)
    try:
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        ues.set_level_viewport_camera_info(cam, rot)
        print("FOCUS table cam", round(float(cam.x), 1), round(float(cam.y), 1), round(float(cam.z), 1))
    except Exception as exc:
        print("focus skip", exc)


def main() -> None:
    print("LEVEL", unreal.EditorLevelLibrary.get_editor_world().get_name())
    before = _print_bounds("BEFORE")
    map_actor = before.get("map")
    if map_actor is not None:
        map_actor.set_actor_location(unreal.Vector(0, 0, 0), False, False)
        map_actor.set_actor_rotation(unreal.Rotator(0, 0, 0), False)
        map_actor.set_actor_scale3d(unreal.Vector(1, 1, 1))
    _reimport_map()
    after = _print_bounds("AFTER_REIMPORT")
    map_actor = after.get("map")
    if map_actor is not None:
        map_actor.set_actor_scale3d(unreal.Vector(1, 1, 1))
    _mirror_furniture_into_map_space()
    after = _print_bounds("AFTER_FURNITURE")
    _dedupe_suns()
    _focus_table(after.get("table"))
    try:
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
        print("SAVED L_Remagen")
    except Exception as exc:
        print("save skip", exc)
    print(
        "PROOF table_inside",
        after.get("table_inside"),
        "chair_inside",
        after.get("chair_inside"),
        "table_loc",
        after.get("table_loc"),
        "chair_loc",
        after.get("chair_loc"),
        "aabb_y_should_be_negative_side_max",
    )


main()
