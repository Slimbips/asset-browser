"""Proof L_Diverting_the_Enemy furniture: current formula, town-side Y. No LoadLevel."""
from __future__ import annotations

import json
import math

import unreal

WANT = ("simplechair", "square_table", "cardtable", "simpledesk")


def _xyz(v):
    return [round(float(v.x), 2), round(float(v.y), 2), round(float(v.z), 2)]


def _pyr(rot):
    return [round(float(rot.pitch), 2), round(float(rot.yaw), 2), round(float(rot.roll), 2)]


def main() -> None:
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    world_name = world.get_name() if world else ""
    print("WORLD", world_name)
    if world_name != "L_Diverting_the_Enemy":
        print("NOT OPEN L_Diverting_the_Enemy (no LoadLevel)")
        return
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = list(sub.get_all_level_actors() or [])
    map_actor = None
    n_sun = 0
    n_prop = 0
    props = []
    for actor in actors:
        label = actor.get_actor_label() or ""
        cls = actor.get_class().get_name() if actor.get_class() else ""
        if label == "SM_Diverting_the_Enemy":
            map_actor = actor
        if isinstance(actor, unreal.DirectionalLight) or "DirectionalLight" in cls:
            n_sun += 1
            print("SUN", label, "loc", _xyz(actor.get_actor_location()), "rot", _pyr(actor.get_actor_rotation()))
        if label.startswith("MOHAA_prop_"):
            n_prop += 1
            props.append(actor)
    print("NSUN", n_sun, "NPROP", n_prop)
    if map_actor is None:
        print("NO MAP ACTOR")
        return
    loc = map_actor.get_actor_location()
    rot = map_actor.get_actor_rotation()
    scl = map_actor.get_actor_scale3d()
    print("MAP", "loc", _xyz(loc), "rot", _pyr(rot), "scale", _xyz(scl))
    origin, extent = map_actor.get_actor_bounds(False)
    mn = [float(origin.x) - float(extent.x), float(origin.y) - float(extent.y), float(origin.z) - float(extent.z)]
    mx = [float(origin.x) + float(extent.x), float(origin.y) + float(extent.y), float(origin.z) + float(extent.z)]
    print("MAP AABB", [round(v, 1) for v in mn], [round(v, 1) for v in mx])
    print("MAP originY_sign", "+" if float(origin.y) >= 0 else "-")
    n_inside = 0
    n_pos_y = 0
    n_neg_y = 0
    for a in props:
        p = a.get_actor_location()
        if mn[0] <= float(p.x) <= mx[0] and mn[1] <= float(p.y) <= mx[1]:
            n_inside += 1
        if float(p.y) >= 0:
            n_pos_y += 1
        else:
            n_neg_y += 1
    print("PROP insideXY", n_inside, "/", len(props), "Y+ ", n_pos_y, "Y-", n_neg_y)
    # Expected first simplechair after current formula:
    expect = {
        "simplechair_0_loc": [11675.72, -15108.682, 528.32],
        "simplechair_0_rot": [0.0, -135.0, 0.0],
    }
    print("EXPECT simplechair_0", json.dumps(expect))
    for actor in props:
        label = (actor.get_actor_label() or "").lower()
        if not any(k in label for k in WANT):
            continue
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        scl = actor.get_actor_scale3d()
        inside = mn[0] <= float(loc.x) <= mx[0] and mn[1] <= float(loc.y) <= mx[1]
        print(
            "SAMPLE",
            json.dumps(
                {
                    "label": actor.get_actor_label(),
                    "loc": _xyz(loc),
                    "rot": _pyr(rot),
                    "scale": _xyz(scl),
                    "y_sign": "+" if float(loc.y) >= 0 else "-",
                    "insideXY": inside,
                }
            ),
        )
        if "simplechair_0" in label:
            dy = abs(float(loc.y) - expect["simplechair_0_loc"][1])
            print("SIMPLECHAIR_0 dy_from_current", round(dy, 2), "PASS" if dy < 2.0 else "FAIL")


main()
