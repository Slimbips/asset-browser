"""Proof L_Algiers furniture: current formula, floor Z via trace, heading vs wall. No LoadLevel."""
from __future__ import annotations

import json
import math

import unreal

SAMPLES = (
    "MOHAA_prop_SM_table_0",
    "MOHAA_prop_SM_simplechair_1",
    "MOHAA_prop_SM_simplechair_4",
    "MOHAA_prop_SM_bunkertable_0",
    "MOHAA_prop_SM_cabinet_large_0",
    "MOHAA_prop_SM_single_bed_0",
)


def _xyz(v):
    return [round(float(v.x), 2), round(float(v.y), 2), round(float(v.z), 2)]


def _pyr(rot):
    return [round(float(rot.pitch), 2), round(float(rot.yaw), 2), round(float(rot.roll), 2)]


def _fwd(rot):
    yaw = math.radians(float(rot.yaw))
    return unreal.Vector(math.cos(yaw), math.sin(yaw), 0.0)


def _right(rot):
    yaw = math.radians(float(rot.yaw))
    return unreal.Vector(-math.sin(yaw), math.cos(yaw), 0.0)


def _trace(world, start, end):
    try:
        hit = unreal.SystemLibrary.line_trace_single(
            world,
            start,
            end,
            unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
            True,
            [],
            unreal.DrawDebugTrace.NONE,
            True,
        )
        if isinstance(hit, (tuple, list)) and len(hit) >= 2:
            ok, res = hit[0], hit[1]
            if ok and res:
                loc = getattr(res, "location", None) or getattr(res, "impact_point", None)
                nrm = getattr(res, "normal", None) or getattr(res, "impact_normal", None)
                actor = getattr(res, "actor", None)
                return {
                    "ok": True,
                    "loc": None if loc is None else _xyz(loc),
                    "normal": None if nrm is None else _xyz(nrm),
                    "actor": None if actor is None else str(actor.get_actor_label()),
                }
        if getattr(hit, "blocking_hit", False):
            loc = hit.location
            nrm = hit.normal
            actor = getattr(hit, "actor", None)
            return {
                "ok": True,
                "loc": _xyz(loc),
                "normal": _xyz(nrm),
                "actor": None if actor is None else str(actor.get_actor_label()),
            }
    except Exception as visc:
        return {"ok": False, "err": str(visc)}
    return {"ok": False}


def main() -> None:
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    print("WORLD", world.get_name() if world else "")
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = list(sub.get_all_level_actors() or [])
    map_actor = None
    n_sun = 0
    n_prop = 0
    by_label = {}
    for actor in actors:
        label = actor.get_actor_label() or ""
        by_label[label] = actor
        if label == "SM_Algiers":
            map_actor = actor
        if isinstance(actor, unreal.DirectionalLight):
            n_sun += 1
        if label.startswith("MOHAA_prop_"):
            n_prop += 1
    print("NSUN", n_sun, "NPROP", n_prop)
    if map_actor is None:
        print("NO MAP")
        return
    loc = map_actor.get_actor_location()
    rot = map_actor.get_actor_rotation()
    scl = map_actor.get_actor_scale3d()
    print("MAP loc", _xyz(loc), "rot", _pyr(rot), "scale", _xyz(scl))
    origin, extent = map_actor.get_actor_bounds(False)
    mn = [float(origin.x) - float(extent.x), float(origin.y) - float(extent.y), float(origin.z) - float(extent.z)]
    mx = [float(origin.x) + float(extent.x), float(origin.y) + float(extent.y), float(origin.z) + float(extent.z)]
    print("MAP AABB", [round(v, 1) for v in mn], [round(v, 1) for v in mx], "origin", _xyz(origin))

    expected = {
        "MOHAA_prop_SM_table_0": {"loc": [3213.61, 4131.54, -142.11], "rot": [0.0, -90.0, 0.0]},
        "MOHAA_prop_SM_simplechair_1": {"loc": [3218.94, 4046.78, -142.24], "rot": [0.0, -160.0, 0.0]},
        "MOHAA_prop_SM_simplechair_4": {"loc": [3223.67, 4193.24, -142.24], "rot": [0.0, 0.0, 0.0]},
        "MOHAA_prop_SM_bunkertable_0": {"loc": [-3032.76, 8280.4, 668.02], "rot": [0.0, 0.0, 0.0]},
        "MOHAA_prop_SM_cabinet_large_0": {"loc": [707.97, 7680.45, -233.68], "rot": [0.0, -225.0, 0.0]},
        "MOHAA_prop_SM_single_bed_0": {"loc": [782.32, 6979.92, -233.68], "rot": [0.0, -90.0, 0.0]},
    }

    props = [a for a in actors if (a.get_actor_label() or "").startswith("MOHAA_prop_")]
    if props:
        cy = sum(float(a.get_actor_location().y) for a in props) / len(props)
        n_inside = 0
        for a in props:
            p = a.get_actor_location()
            if mn[0] <= float(p.x) <= mx[0] and mn[1] <= float(p.y) <= mx[1] and mn[2] <= float(p.z) <= mx[2]:
                n_inside += 1
        print("PROP centroidY", round(cy, 1), "mapOriginY", round(float(origin.y), 1), "insideAABB", n_inside, "/", len(props))
        same_side = (cy >= 0) == (float(origin.y) >= 0)
        print("PROP_TOWN_SIDE", same_side, "(centroid Y sign matches map origin)")

    print("\n--- samples ---")
    for label in SAMPLES:
        actor = by_label.get(label)
        if actor is None:
            print("MISSING", label)
            continue
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        scl = actor.get_actor_scale3d()
        inside = mn[0] <= float(loc.x) <= mx[0] and mn[1] <= float(loc.y) <= mx[1] and mn[2] <= float(loc.z) <= mx[2]
        exp = expected.get(label)
        loc_match = rot_match = None
        if exp:
            loc_match = all(abs(float(_xyz(loc)[i]) - exp["loc"][i]) < 2.0 for i in range(3))
            er = exp["rot"]
            live = _pyr(rot)
            rot_match = all(abs(((live[i] - er[i] + 180) % 360) - 180) < 2.0 for i in range(3))
        down = _trace(world, loc + unreal.Vector(0, 0, 40), loc + unreal.Vector(0, 0, -400))
        fwd = _fwd(rot)
        right = _right(rot)
        wall_f = _trace(world, loc + unreal.Vector(0, 0, 40), loc + unreal.Vector(fwd.x * 600, fwd.y * 600, 40))
        wall_r = _trace(world, loc + unreal.Vector(0, 0, 40), loc + unreal.Vector(right.x * 600, right.y * 600, 40))
        rec = {
            "label": label,
            "loc": _xyz(loc),
            "rot": _pyr(rot),
            "scale": _xyz(scl),
            "insideAABB": inside,
            "matches_current_loc": loc_match,
            "matches_current_rot": rot_match,
            "floor_trace": down,
            "wall_forward": wall_f,
            "wall_right": wall_r,
        }
        if down.get("ok") and down.get("loc"):
            rec["floor_dz"] = round(float(loc.z) - down["loc"][2], 1)
        print("SAMPLE", json.dumps(rec))

    print("PROOF_DONE")


main()
