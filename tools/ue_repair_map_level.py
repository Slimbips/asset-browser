"""Repair lighting/camera on an already-imported MOHAA map level.

Does not reimport FBX. Safe to run in the open editor.
"""
from __future__ import annotations

import json

import unreal

LEVEL = "/Game/MOHAA/maps/L_Stalingrad"
MESH = "/Game/MOHAA/maps/SM_Stalingrad"


def _set(obj, prop, value) -> bool:
    try:
        obj.set_editor_property(prop, value)
        return True
    except Exception:
        return False


def _actor_named(sub, label: str):
    try:
        for old in list(sub.get_all_level_actors() or []):
            if old.get_actor_label() == label:
                return old
    except Exception:
        pass
    return None


def _mobility(actor, mode) -> None:
    try:
        actor.set_editor_property("mobility", mode)
    except Exception:
        pass
    try:
        root = actor.root_component
        if root:
            root.set_editor_property("mobility", mode)
    except Exception:
        pass


def _ensure_basic_lighting(sub) -> dict:
    movable = getattr(unreal.ComponentMobility, "MOVABLE", None)
    spawned = []
    sun = _actor_named(sub, "MOHAA_Sun")
    if sun is None:
        sun = sub.spawn_actor_from_class(
            unreal.DirectionalLight, unreal.Vector(0, 0, 4000), unreal.Rotator(-50, 40, 0)
        )
        if sun:
            sun.set_actor_label("MOHAA_Sun")
            spawned.append("MOHAA_Sun")
    if sun:
        if movable is not None:
            _mobility(sun, movable)
        try:
            lc = sun.light_component
            _set(lc, "intensity", 12.0)
            _set(lc, "atmosphere_sun_light", True)
            _set(lc, "cast_shadows", False)
            try:
                lc.set_editor_property("light_color", unreal.Color(255, 244, 214, 255))
            except Exception:
                pass
        except Exception:
            pass

    atm_cls = getattr(unreal, "SkyAtmosphere", None)
    atm = _actor_named(sub, "MOHAA_SkyAtmosphere")
    if atm_cls is not None and atm is None:
        atm = sub.spawn_actor_from_class(atm_cls, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        if atm:
            atm.set_actor_label("MOHAA_SkyAtmosphere")
            spawned.append("MOHAA_SkyAtmosphere")

    fog_cls = getattr(unreal, "ExponentialHeightFog", None)
    if fog_cls is not None and _actor_named(sub, "MOHAA_Fog") is None:
        fog = sub.spawn_actor_from_class(fog_cls, unreal.Vector(0, 0, 200), unreal.Rotator(0, 0, 0))
        if fog:
            fog.set_actor_label("MOHAA_Fog")
            spawned.append("MOHAA_Fog")

    sky = _actor_named(sub, "MOHAA_SkyLight")
    if sky is None:
        sky = sub.spawn_actor_from_class(
            unreal.SkyLight, unreal.Vector(0, 0, 3500), unreal.Rotator(0, 0, 0)
        )
        if sky:
            sky.set_actor_label("MOHAA_SkyLight")
            spawned.append("MOHAA_SkyLight")
    if sky:
        if movable is not None:
            _mobility(sky, movable)
        try:
            sc = sky.light_component
            _set(sc, "intensity", 1.0)
            _set(sc, "real_time_capture", False)
            _set(sc, "lower_hemisphere_is_black", False)
            try:
                sc.set_editor_property(
                    "lower_hemisphere_color", unreal.LinearColor(0.18, 0.18, 0.22, 1.0)
                )
            except Exception:
                pass
            recapture = getattr(sc, "recapture_sky", None)
            if callable(recapture):
                recapture()
        except Exception:
            pass
    return {"spawned": spawned, "sun": bool(sun), "sky": bool(sky), "atmosphere": bool(atm)}


def _prepare_map_materials(mesh) -> int:
    n = 0
    try:
        slots = list(mesh.get_editor_property("static_materials") or [])
    except Exception:
        return 0
    for slot in slots:
        mat = getattr(slot, "material_interface", None)
        if mat is None:
            continue
        if _set(mat, "two_sided", True) or _set(mat, "is_two_sided", True):
            n += 1
        try:
            unreal.EditorAssetLibrary.save_asset(mat.get_path_name().split(".")[0])
        except Exception:
            pass
    return n


def repair() -> dict:
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if les is not None and unreal.EditorAssetLibrary.does_asset_exist(LEVEL):
        les.load_level(LEVEL)
        print("LEVEL LOAD", LEVEL)

    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    lights = _ensure_basic_lighting(sub)

    mesh = unreal.EditorAssetLibrary.load_asset(MESH)
    actor = _actor_named(sub, "SM_Stalingrad")
    if actor is None and mesh is not None:
        actor = sub.spawn_actor_from_class(
            unreal.StaticMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0)
        )
        if actor:
            actor.set_actor_label("SM_Stalingrad")
            actor.static_mesh_component.set_static_mesh(mesh)
            print("SPAWNED SM_Stalingrad")

    bounds = {}
    two_sided = 0
    scaled = False
    if mesh is not None:
        two_sided = _prepare_map_materials(mesh)
        try:
            b = mesh.get_bounds()
            bounds["mesh_origin"] = [float(b.origin.x), float(b.origin.y), float(b.origin.z)]
            bounds["mesh_extent"] = [float(b.box_extent.x), float(b.box_extent.y), float(b.box_extent.z)]
        except Exception as visc:
            print("mesh bounds skip", visc)

    if actor is not None:
        try:
            origin, extent = actor.get_actor_bounds(False)
            bounds["actor_origin"] = [float(origin.x), float(origin.y), float(origin.z)]
            bounds["actor_extent"] = [float(extent.x), float(extent.y), float(extent.z)]
            loc = actor.get_actor_location()
            bounds["actor_location"] = [float(loc.x), float(loc.y), float(loc.z)]
            sc = actor.get_actor_scale3d()
            max_ext = max(abs(float(extent.x)), abs(float(extent.y)), abs(float(extent.z)))
            # Existing inch-as-cm import is ~15 m half-extent; bake 2.54 so doors match characters.
            if abs(float(sc.x) - 1.0) < 0.05 and max_ext < 2500.0:
                actor.set_actor_scale3d(unreal.Vector(2.54, 2.54, 2.54))
                scaled = True
                origin, extent = actor.get_actor_bounds(False)
                bounds["actor_extent_scaled"] = [
                    float(extent.x),
                    float(extent.y),
                    float(extent.z),
                ]
            ox, oy, oz = float(origin.x), float(origin.y), float(origin.z)
            ex = max(abs(float(extent.x)), 100.0)
            ey = max(abs(float(extent.y)), 100.0)
            ez = max(abs(float(extent.z)), 100.0)
            dist = max(ex, ey, ez) * 1.6
            ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
            ues.set_level_viewport_camera_info(
                unreal.Vector(ox + dist, oy - dist, oz + max(ez * 0.35, 400.0)),
                unreal.Rotator(-18, 135, 0),
            )
            print(
                "FOCUS origin",
                round(ox, 1),
                round(oy, 1),
                round(oz, 1),
                "extent",
                round(ex, 1),
                round(ey, 1),
                round(ez, 1),
            )
        except Exception as visc:
            print("actor bounds skip", visc)

    labels = []
    try:
        for a in list(sub.get_all_level_actors() or []):
            labels.append(a.get_actor_label() + ":" + a.get_class().get_name())
    except Exception:
        pass

    try:
        les.save_current_level()
    except Exception:
        pass
    try:
        unreal.EditorAssetLibrary.save_asset(LEVEL)
    except Exception:
        pass

    result = {
        "ok": True,
        "level": LEVEL,
        "mesh": MESH,
        "lights": lights,
        "bounds": bounds,
        "two_sided": two_sided,
        "scaled_2_54": scaled,
        "actors": labels,
    }
    print("REPAIR", json.dumps(result))
    return result


repair()
