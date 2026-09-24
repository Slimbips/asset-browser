"""Proof L_Southern_France furniture: current formula, floor Z, heading vs wall. No LoadLevel."""
from __future__ import annotations

import json
import math

import unreal

SAMPLES = (
    "MOHAA_prop_SM_table_0",
    "MOHAA_prop_SM_table_1",
    "MOHAA_prop_SM_armchairposh_1",
    "MOHAA_prop_SM_simplechair_0",
    "MOHAA_prop_SM_stoolposh_1",
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


def _parse_hit(hit):
    if hit is None:
        return {"ok": False}
    if isinstance(hit, (tuple, list)):
        if not hit:
            return {"ok": False, "kind": "empty-tuple"}
        ok = bool(hit[0])
        res = hit[1] if len(hit) > 1 else None
        if not ok:
            return {"ok": False, "kind": "tuple-miss"}
        loc = getattr(res, "location", None) or getattr(res, "impact_point", None)
        nrm = getattr(res, "normal", None) or getattr(res, "impact_normal", None)
        actor = getattr(res, "actor", None) or getattr(res, "hit_actor", None)
        label = None
        try:
            label = actor.get_actor_label() if actor else None
        except Exception:
            label = str(actor) if actor else None
        return {
            "ok": True,
            "loc": None if loc is None else _xyz(loc),
            "normal": None if nrm is None else _xyz(nrm),
            "actor": label,
            "kind": "tuple",
        }
    try:
        blocking = bool(hit.get_editor_property("blocking_hit"))
    except Exception:
        blocking = bool(getattr(hit, "blocking_hit", False))
    if not blocking:
        return {"ok": False, "kind": "hitresult-miss"}
    loc = getattr(hit, "location", None)
    nrm = getattr(hit, "normal", None)
    actor = getattr(hit, "actor", None) or getattr(hit, "hit_actor", None)
    label = None
    try:
        label = actor.get_actor_label() if actor else None
    except Exception:
        label = str(actor) if actor else None
    return {
        "ok": True,
        "loc": None if loc is None else _xyz(loc),
        "normal": None if nrm is None else _xyz(nrm),
        "actor": label,
        "kind": "hitresult",
    }


def _trace(world, start, end, channel):
    try:
        hit = unreal.SystemLibrary.line_trace_single(
            world,
            start,
            end,
            channel,
            True,
            [],
            unreal.DrawDebugTrace.NONE,
            True,
        )
        rec = _parse_hit(hit)
        rec["start"] = _xyz(start)
        rec["end"] = _xyz(end)
        rec["channel"] = str(channel)
        return rec
    except Exception as visc:
        return {"ok": False, "err": str(visc), "channel": str(channel)}


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
    loc = map_actor.get_actor_location()
    rot = map_actor.get_actor_rotation()
    scl = map_actor.get_actor_scale3d()
    print("MAP loc", _xyz(loc), "rot", _pyr(rot), "scale", _xyz(scl))
    origin, extent = map_actor.get_actor_bounds(False)
    mn = [float(origin.x) - float(extent.x), float(origin.y) - float(extent.y), float(origin.z) - float(extent.z)]
    mx = [float(origin.x) + float(extent.x), float(origin.y) + float(extent.y), float(origin.z) + float(extent.z)]
    print("MAP AABB", [round(v, 1) for v in mn], [round(v, 1) for v in mx], "origin", _xyz(origin))
    mesh_y = float(origin.y)
    try:
        b = map_actor.static_mesh_component.static_mesh.get_bounds()
        mesh_y = float(b.origin.y)
        print("MESH origin", _xyz(b.origin), "Ysign", "+" if mesh_y >= 0 else "-")
    except Exception as exc:
        print("MESH skip", exc)

    expected = {
        "MOHAA_prop_SM_table_0": {"loc": [-3191.28, -1727.38, 975.49], "rot": [0.0, -180.0, 0.0]},
        "MOHAA_prop_SM_table_1": {"loc": [-3800.02, -2845.89, 975.49], "rot": [0.0, -270.0, 0.0]},
        "MOHAA_prop_SM_armchairposh_1": {"loc": [-3366.24, -1680.79, 975.36], "rot": [0.0, -200.0, 0.0]},
        "MOHAA_prop_SM_simplechair_0": {"loc": [-5014.62, -3315.46, 1300.48], "rot": [0.0, -135.0, 0.0]},
        "MOHAA_prop_SM_stoolposh_1": {"loc": [-2169.16, -2727.96, 975.36], "rot": [0.0, 0.0, 0.0]},
    }

    props = [a for a in actors if (a.get_actor_label() or "").startswith("MOHAA_prop_")]
    if props:
        cy = sum(float(a.get_actor_location().y) for a in props) / len(props)
        n_inside = 0
        n_town = 0
        for a in props:
            p = a.get_actor_location()
            if mn[0] <= float(p.x) <= mx[0] and mn[1] <= float(p.y) <= mx[1] and mn[2] <= float(p.z) <= mx[2]:
                n_inside += 1
            if (float(p.y) >= 0) == (mesh_y >= 0):
                n_town += 1
        same_side = (cy >= 0) == (mesh_y >= 0)
        print(
            "PROP centroidY",
            round(cy, 1),
            "mapOriginY",
            round(mesh_y, 1),
            "insideAABB",
            n_inside,
            "/",
            len(props),
            "town_side",
            n_town,
            "/",
            len(props),
        )
        print("PROP_TOWN_SIDE", same_side, "(centroid Y sign matches map origin)")
        print("STALE_OLD_PLUSX_HINT", (not same_side) and n_inside > 0)

    channels = []
    for name in ("ECC_VISIBILITY", "ECC_WORLD_STATIC", "TRACE_TYPE_QUERY1"):
        ch = getattr(unreal.TraceTypeQuery, name, None)
        if ch is not None:
            channels.append(ch)
    print("CHANNELS", [str(c) for c in channels])

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
        town = (float(loc.y) >= 0) == (mesh_y >= 0)
        exp = expected.get(label)
        loc_match = rot_match = None
        if exp:
            loc_match = all(abs(float(_xyz(loc)[i]) - exp["loc"][i]) < 2.0 for i in range(3))
            er = exp["rot"]
            live = _pyr(rot)
            rot_match = all(abs(((live[i] - er[i] + 180) % 360) - 180) < 2.0 for i in range(3))
        down = {"ok": False}
        for ch in channels:
            cand = _trace(world, loc + unreal.Vector(0, 0, 80), loc + unreal.Vector(0, 0, -800), ch)
            if cand.get("ok"):
                down = cand
                break
        fwd = _fwd(rot)
        right = _right(rot)
        wall_f = {"ok": False}
        wall_r = {"ok": False}
        for ch in channels:
            if not wall_f.get("ok"):
                wall_f = _trace(
                    world,
                    loc + unreal.Vector(0, 0, 40),
                    loc + unreal.Vector(fwd.x * 600, fwd.y * 600, 40),
                    ch,
                )
            if not wall_r.get("ok"):
                wall_r = _trace(
                    world,
                    loc + unreal.Vector(0, 0, 40),
                    loc + unreal.Vector(right.x * 600, right.y * 600, 40),
                    ch,
                )
        rec = {
            "label": label,
            "loc": _xyz(loc),
            "rot": _pyr(rot),
            "scale": _xyz(scl),
            "insideAABB": inside,
            "town_side": town,
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
