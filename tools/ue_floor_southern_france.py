"""Closest-point floor + BSP-in-UE wall heading for Southern France. No LoadLevel."""
from __future__ import annotations

import json
import math

import unreal

SAMPLES = (
    "MOHAA_prop_SM_table_0",
    "MOHAA_prop_SM_armchairposh_1",
    "MOHAA_prop_SM_simplechair_0",
)


def _xyz(v):
    return [round(float(v.x), 2), round(float(v.y), 2), round(float(v.z), 2)]


def _pyr(rot):
    return [round(float(rot.pitch), 2), round(float(rot.yaw), 2), round(float(rot.roll), 2)]


def main() -> None:
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    print("WORLD", world.get_name() if world else "")
    for path in (
        "/Game/MOHAA/maps/L_Southern_France",
        "/Game/MOHAA/maps/SM_Southern_France",
        "/Game/MOHAA/maps/L_Algiers",
        "/Game/MOHAA/maps/SM_Algiers",
        "/Game/MOHAA/maps/L_Snowy_Park",
        "/Game/MOHAA/maps/SM_Snowy_Park",
        "/Game/MOHAA/maps/L_Stalingrad",
        "/Game/MOHAA/maps/SM_Stalingrad",
        "/Game/MOHAA/maps/L_Remagen",
        "/Game/MOHAA/maps/SM_Remagen",
        "/Game/MOHAA/maps/L_Destroyed_Village",
        "/Game/MOHAA/maps/SM_Destroyed_Village",
        "/Game/MOHAA/maps/L_Crossroads",
        "/Game/MOHAA/maps/SM_Crossroads",
    ):
        print("EXISTS", path, unreal.EditorAssetLibrary.does_asset_exist(path))

    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    by_label = {}
    map_actor = None
    n_sun = 0
    n_prop = 0
    for actor in list(sub.get_all_level_actors() or []):
        label = actor.get_actor_label() or ""
        by_label[label] = actor
        if label == "SM_Southern_France":
            map_actor = actor
        if isinstance(actor, unreal.DirectionalLight):
            n_sun += 1
        if label.startswith("MOHAA_prop_"):
            n_prop += 1
    print("NSUN", n_sun, "NPROP", n_prop)
    if map_actor is None:
        print("NO MAP")
        return
    smc = map_actor.static_mesh_component
    try:
        print("SMC collision_enabled", smc.get_collision_enabled())
        print("actor_enable_collision", map_actor.get_editor_property("actor_enable_collision"))
    except Exception as visc:
        print("collision skip", visc)
    origin, extent = map_actor.get_actor_bounds(False)
    print("MAP origin", _xyz(origin), "extent", _xyz(extent))

    for label in SAMPLES:
        actor = by_label.get(label)
        if actor is None:
            print("MISSING", label)
            continue
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        yaw = math.radians(float(rot.yaw))
        fwd = [round(math.cos(yaw), 3), round(math.sin(yaw), 3)]
        closest = unreal.Vector()
        dist = None
        try:
            dist = smc.get_closest_point_on_collision(loc)
            if isinstance(dist, (tuple, list)):
                if len(dist) >= 2:
                    closest = dist[1]
                    dist = dist[0]
            elif isinstance(dist, unreal.Vector):
                closest = dist
                dist = 0.0
        except Exception as visc:
            print("CLOSEST fail", label, visc)
            dist = None
        rec = {
            "label": label,
            "loc": _xyz(loc),
            "rot": _pyr(rot),
            "fwd_xy": fwd,
            "closest": _xyz(closest) if dist is not None else None,
            "dist": None if dist is None else round(float(dist), 2),
        }
        if dist is not None:
            rec["dz"] = round(float(loc.z) - float(closest.z), 2)
            rec["dxy"] = round(
                ((float(loc.x) - float(closest.x)) ** 2 + (float(loc.y) - float(closest.y)) ** 2) ** 0.5, 2
            )
        print("CLOSEST", json.dumps(rec))

    print("FLOOR_DONE")


main()
