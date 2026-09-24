"""Dump the LIVE editor level after a map Convert, fix lights if needed, screenshot."""
from __future__ import annotations

import json

import unreal

LEVEL = "/Game/MOHAA/maps/L_Stalingrad"
MESH = "/Game/MOHAA/maps/SM_Stalingrad"
SHOT = r"D:/Games/test/Stalingrad/Saved/Screenshots/L_Stalingrad_after_export.png"


def _set(obj, prop, value) -> bool:
    if obj is None:
        return False
    try:
        obj.set_editor_property(prop, value)
        return True
    except Exception:
        return False


def _comp(actor, *names):
    for name in names:
        try:
            val = getattr(actor, name, None)
            if val is not None:
                return val
        except Exception:
            pass
        try:
            return actor.get_editor_property(name)
        except Exception:
            pass
    return None


def _named(sub, label):
    for a in list(sub.get_all_level_actors() or []):
        if a.get_actor_label() == label:
            return a
    return None


def _world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def _describe(actor) -> dict:
    loc = actor.get_actor_location()
    info = {
        "label": actor.get_actor_label(),
        "class": actor.get_class().get_name(),
        "loc": [round(float(loc.x), 1), round(float(loc.y), 1), round(float(loc.z), 1)],
        "hidden_ed": bool(actor.is_hidden_ed()),
    }
    lc = _comp(actor, "light_component", "component", "root_component")
    if lc is None:
        return info
    for key, names in (
        ("intensity", ("intensity",)),
        ("intensity_units", ("intensity_units",)),
        ("mobility", ("mobility",)),
        ("visible", ("visible", "b_visible")),
        ("hidden_in_game", ("hidden_in_game", "b_hidden_in_game")),
        ("affects_world", ("affects_world", "b_affects_world")),
        ("cast_shadows", ("cast_shadows", "b_cast_shadows")),
        ("realtime", ("real_time_capture", "b_real_time_capture")),
        ("source_type", ("source_type",)),
        ("atm_sun", ("atmosphere_sun_light", "b_atmosphere_sun_light")),
    ):
        for name in names:
            try:
                val = lc.get_editor_property(name)
                info[key] = str(val) if not isinstance(val, (int, float, bool, type(None))) else val
                break
            except Exception:
                continue
    cube = None
    try:
        cube = lc.get_editor_property("cubemap")
    except Exception:
        pass
    info["cubemap"] = cube.get_path_name() if cube else None
    return info


def dump(tag: str) -> dict:
    world = _world()
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    cam = None
    try:
        loc, rot = ues.get_level_viewport_camera_info()
        cam = {
            "loc": [round(float(loc.x), 1), round(float(loc.y), 1), round(float(loc.z), 1)],
            "rot": [round(float(rot.pitch), 1), round(float(rot.yaw), 1), round(float(rot.roll), 1)],
        }
    except Exception as exc:
        cam = {"error": str(exc)}
    actors = []
    lights = []
    has_mesh = False
    for a in list(sub.get_all_level_actors() or []):
        cls = a.get_class().get_name()
        label = a.get_actor_label()
        actors.append(label + ":" + cls)
        if label == "SM_Stalingrad":
            has_mesh = True
        if any(k in cls for k in ("Light", "SkyAtmosphere", "ExponentialHeightFog", "PostProcess")):
            lights.append(_describe(a))
    mats = []
    try:
        mesh = unreal.EditorAssetLibrary.load_asset(MESH)
        slots = list(mesh.get_editor_property("static_materials") or [])[:6]
        for i, slot in enumerate(slots):
            mat = getattr(slot, "material_interface", None)
            row = {"i": i, "slot": str(getattr(slot, "material_slot_name", "")), "mat": None}
            if mat is not None:
                row["mat"] = mat.get_name()
                row["class"] = mat.get_class().get_name()
                parent = _comp(mat, "parent") or mat
                try:
                    row["shading"] = str(parent.get_editor_property("shading_model"))
                except Exception:
                    row["shading"] = "?"
            mats.append(row)
    except Exception as exc:
        mats = [{"error": str(exc)}]
    map_name = None
    try:
        map_name = world.get_map_name()
    except Exception:
        try:
            map_name = str(world.get_path_name())
        except Exception:
            map_name = world.get_name() if world else None
    state = {
        "tag": tag,
        "project": unreal.Paths.convert_relative_path_to_full(unreal.Paths.get_project_file_path()),
        "world": world.get_name() if world else None,
        "map_name": map_name,
        "camera": cam,
        "has_SM_Stalingrad": has_mesh,
        "actors": actors,
        "lights": lights,
        "materials": mats,
    }
    print("VERIFY", tag, json.dumps(state, default=str))
    return state


def _cmd(*lines):
    world = unreal.EditorLevelLibrary.get_editor_world()
    for line in lines:
        try:
            unreal.SystemLibrary.execute_console_command(world, line)
        except Exception:
            pass


def _ensure_lights(sub):
    movable = getattr(unreal.ComponentMobility, "MOVABLE", None)
    try:
        ws = _world().get_world_settings()
        _set(ws, "force_no_precomputed_lighting", True)
    except Exception:
        pass
    sun = _named(sub, "MOHAA_Sun")
    if sun is None:
        sun = sub.spawn_actor_from_class(
            unreal.DirectionalLight, unreal.Vector(0, 0, 8000), unreal.Rotator(-46, 35, 0)
        )
        if sun:
            sun.set_actor_label("MOHAA_Sun")
            print("SPAWNED MOHAA_Sun")
    if sun:
        try:
            sun.set_actor_hidden_in_game(False)
            sun.set_is_temporarily_hidden_in_editor(False)
        except Exception:
            pass
        if movable is not None:
            try:
                sun.root_component.set_editor_property("mobility", movable)
            except Exception:
                pass
        lc = _comp(sun, "light_component")
        unitless = getattr(unreal.LightUnits, "UNITLESS", None)
        if unitless is not None:
            _set(lc, "intensity_units", unitless)
        _set(lc, "intensity", 12.0)
        _set(lc, "atmosphere_sun_light", True)
        _set(lc, "cast_shadows", False)
        _set(lc, "affects_world", True)
        _set(lc, "visible", True)
        _set(lc, "hidden_in_game", False)
    atm_cls = getattr(unreal, "SkyAtmosphere", None)
    if atm_cls is not None and _named(sub, "MOHAA_SkyAtmosphere") is None:
        atm = sub.spawn_actor_from_class(atm_cls, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        if atm:
            atm.set_actor_label("MOHAA_SkyAtmosphere")
            print("SPAWNED MOHAA_SkyAtmosphere")
    fog_cls = getattr(unreal, "ExponentialHeightFog", None)
    if fog_cls is not None and _named(sub, "MOHAA_Fog") is None:
        fog = sub.spawn_actor_from_class(fog_cls, unreal.Vector(0, 0, 200), unreal.Rotator(0, 0, 0))
        if fog:
            fog.set_actor_label("MOHAA_Fog")
    sky = _named(sub, "MOHAA_SkyLight")
    if sky is not None:
        sc = _comp(sky, "light_component")
        realtime = False
        try:
            realtime = bool(sc.get_editor_property("real_time_capture"))
        except Exception:
            pass
        _set(sc, "real_time_capture", False)
        _set(sc, "lower_hemisphere_is_black", False)
        if realtime:
            print("DISABLED SkyLight realtime capture")
            try:
                sub.destroy_actor(sky)
                print("REMOVED realtime SkyLight")
                sky = None
            except Exception:
                _set(sc, "affects_world", False)
    pp_cls = getattr(unreal, "PostProcessVolume", None)
    if pp_cls is not None and _named(sub, "MOHAA_PostProcess") is None:
        pp = sub.spawn_actor_from_class(pp_cls, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        if pp:
            pp.set_actor_label("MOHAA_PostProcess")
            _set(pp, "unbound", True)
            _set(pp, "b_unbound", True)
    _cmd(
        "viewmode lit",
        "r.Unlit 0",
        "ShowFlag.Lighting 1",
        "ShowFlag.StaticMeshes 1",
        "ShowFlag.Atmosphere 1",
        "r.SkyAtmosphere 1",
        "r.DefaultFeature.AutoExposure 0",
        "r.EyeAdaptationQuality 0",
        "r.Shadow.Virtual.Enable 0",
    )


def _focus_mesh_actor(actor):
    origin, extent = actor.get_actor_bounds(False)
    ox, oy, oz = float(origin.x), float(origin.y), float(origin.z)
    ex = max(abs(float(extent.x)), 100.0)
    ey = max(abs(float(extent.y)), 100.0)
    ez = max(abs(float(extent.z)), 100.0)
    dist = max(ex, ey, ez) * 2.4
    loc = unreal.Vector(ox + dist, oy + dist, oz + ez + max(ez * 0.35, 600.0))
    rot = unreal.Rotator(-28, -135, 0)
    unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(loc, rot)
    print("FOCUS", round(float(loc.x), 1), round(float(loc.y), 1), round(float(loc.z), 1))


def main():
    before = dump("CURRENT")
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    world_name = before.get("world") or ""
    has_mesh = bool(before.get("has_SM_Stalingrad"))

    # Lights on whatever is actually open.
    _ensure_lights(sub)
    actor = _named(sub, "SM_Stalingrad")
    if actor is None and unreal.EditorAssetLibrary.does_asset_exist(MESH):
        mesh = unreal.EditorAssetLibrary.load_asset(MESH)
        actor = sub.spawn_actor_from_class(
            unreal.StaticMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0)
        )
        if actor and mesh:
            actor.set_actor_label("SM_Stalingrad")
            actor.static_mesh_component.set_static_mesh(mesh)
            _set(actor.static_mesh_component, "cast_shadow", False)
            print("SPAWNED SM_Stalingrad into", world_name)
    if actor:
        _focus_mesh_actor(actor)
    try:
        les.save_current_level()
    except Exception as visc:
        print("save current skip", visc)

    current_is_generated = "L_Stalingrad" in world_name or "stalingrad" in world_name.lower()
    if (not current_is_generated) and unreal.EditorAssetLibrary.does_asset_exist(LEVEL):
        print("ALSO loading generated", LEVEL)
        les.load_level(LEVEL)
        sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        _ensure_lights(sub)
        actor = _named(sub, "SM_Stalingrad")
        if actor is None and unreal.EditorAssetLibrary.does_asset_exist(MESH):
            mesh = unreal.EditorAssetLibrary.load_asset(MESH)
            actor = sub.spawn_actor_from_class(
                unreal.StaticMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0)
            )
            if actor and mesh:
                actor.set_actor_label("SM_Stalingrad")
                actor.static_mesh_component.set_static_mesh(mesh)
        if actor:
            _focus_mesh_actor(actor)
        try:
            les.save_current_level()
        except Exception:
            pass

    after = dump("AFTER")
    _cmd("viewmode lit", "HighResShot 1600x900 filename=" + SHOT)
    print("SHOT queued", SHOT)
    print("DONE", json.dumps({"before": before.get("world"), "after": after.get("world")}, default=str))


main()
