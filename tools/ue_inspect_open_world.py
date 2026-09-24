"""Inspect currently open world. Do not LoadLevel."""
from __future__ import annotations

import json
import math

import unreal


def _xyz(v):
    return [round(float(v.x), 2), round(float(v.y), 2), round(float(v.z), 2)]


def _pyr(rot):
    return [round(float(rot.pitch), 2), round(float(rot.yaw), 2), round(float(rot.roll), 2)]


def main() -> None:
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    world_name = world.get_name() if world else ""
    print("WORLD", world_name)
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = list(sub.get_all_level_actors() or [])
    print("NACTORS", len(actors))
    n_sun = 0
    n_prop = 0
    map_actor = None
    props = []
    labels = []
    for actor in actors:
        label = actor.get_actor_label() or ""
        cls = actor.get_class().get_name() if actor.get_class() else ""
        labels.append(label)
        if label.startswith("SM_") and "Sky" not in label and map_actor is None:
            map_actor = actor
        if isinstance(actor, unreal.DirectionalLight) or "DirectionalLight" in cls:
            n_sun += 1
            print("SUN", label, "loc", _xyz(actor.get_actor_location()), "rot", _pyr(actor.get_actor_rotation()))
        if label.startswith("MOHAA_prop_"):
            n_prop += 1
            props.append(actor)
    print("NSUN", n_sun, "NPROP", n_prop)
    print("ACTORS", labels[:40])
    if map_actor:
        loc = map_actor.get_actor_location()
        rot = map_actor.get_actor_rotation()
        scl = map_actor.get_actor_scale3d()
        print("MAP", map_actor.get_actor_label(), "loc", _xyz(loc), "rot", _pyr(rot), "scale", _xyz(scl))
        origin, extent = map_actor.get_actor_bounds(False)
        mn = [float(origin.x) - float(extent.x), float(origin.y) - float(extent.y), float(origin.z) - float(extent.z)]
        mx = [float(origin.x) + float(extent.x), float(origin.y) + float(extent.y), float(origin.z) + float(extent.z)]
        print("MAP AABB", [round(v, 1) for v in mn], [round(v, 1) for v in mx])
        print("MAP originY_sign", "+" if float(origin.y) >= 0 else "-")
        n_inside = 0
        for a in props:
            p = a.get_actor_location()
            if mn[0] <= float(p.x) <= mx[0] and mn[1] <= float(p.y) <= mx[1]:
                n_inside += 1
        print("PROP insideXY", n_inside, "/", len(props))
        for actor in props[:12]:
            loc = actor.get_actor_location()
            rot = actor.get_actor_rotation()
            scl = actor.get_actor_scale3d()
            print(
                "SAMPLE",
                json.dumps(
                    {
                        "label": actor.get_actor_label(),
                        "loc": _xyz(loc),
                        "rot": _pyr(rot),
                        "scale": _xyz(scl),
                    }
                ),
            )
    exist = unreal.EditorAssetLibrary.does_asset_exist("/Game/MOHAA/maps/L_Diverting_the_Enemy")
    mesh_exist = unreal.EditorAssetLibrary.does_asset_exist("/Game/MOHAA/maps/SM_Diverting_the_Enemy")
    print("ASSET L_Diverting_the_Enemy", exist, "SM_Diverting_the_Enemy", mesh_exist)


main()
