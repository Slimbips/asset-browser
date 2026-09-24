"""Proof L_Snowy_Park furniture on park floor. No LoadLevel."""
from __future__ import annotations

import json

import unreal

SAMPLES = (
    "MOHAA_prop_SM_tree_winter_smallpine_0",
    "MOHAA_prop_SM_rock_winter_medium_0",
    "MOHAA_prop_SM_lightpost_globe_winter_0",
    "MOHAA_prop_SM_lightpost_sidemounted_winter_0",
    "MOHAA_prop_SM_tree_winter_thintrunk_0",
)


def _xyz(v):
    return [round(float(v.x), 2), round(float(v.y), 2), round(float(v.z), 2)]


def _pyr(rot):
    return [round(float(rot.pitch), 2), round(float(rot.yaw), 2), round(float(rot.roll), 2)]


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
        actor = getattr(res, "actor", None) or getattr(res, "hit_actor", None)
        try:
            if loc is None:
                loc = res.get_editor_property("location")
        except Exception:
            pass
        label = None
        try:
            label = actor.get_actor_label() if actor else None
        except Exception:
            label = str(actor) if actor else None
        return {"ok": True, "loc": None if loc is None else _xyz(loc), "actor": label, "kind": "tuple"}
    try:
        blocking = bool(hit.get_editor_property("blocking_hit"))
    except Exception:
        blocking = bool(getattr(hit, "blocking_hit", False))
    if not blocking:
        return {"ok": False, "kind": "hitresult-miss"}
    loc = getattr(hit, "location", None)
    actor = getattr(hit, "actor", None) or getattr(hit, "hit_actor", None)
    label = None
    try:
        label = actor.get_actor_label() if actor else None
    except Exception:
        label = str(actor) if actor else None
    return {"ok": True, "loc": None if loc is None else _xyz(loc), "actor": label, "kind": "hitresult"}


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
    by_label = {}
    n_sun = 0
    n_prop = 0
    for actor in actors:
        label = actor.get_actor_label() or ""
        by_label[label] = actor
        if label == "SM_Snowy_Park":
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
    smc = map_actor.static_mesh_component
    try:
        print("MAP collision_enabled", smc.get_collision_enabled(), "actor_collision", map_actor.actor_enable_collision)
    except Exception as visc:
        print("MAP collision skip", visc)
    try:
        mesh = smc.static_mesh
        bs = mesh.body_setup
        print("MAP collision_trace_flag", bs.collision_trace_flag if bs else None)
        print("MAP has_collision", True if bs else False)
    except Exception as visc:
        print("MAP body_setup skip", visc)

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
        ploc = actor.get_actor_location()
        prot = actor.get_actor_rotation()
        pscl = actor.get_actor_scale3d()
        inside = mn[0] <= float(ploc.x) <= mx[0] and mn[1] <= float(ploc.y) <= mx[1] and mn[2] <= float(ploc.z) <= mx[2]
        town = (float(ploc.y) >= 0) == (float(origin.y) >= 0)
        traces = []
        for ch in channels:
            traces.append(
                _trace(
                    world,
                    unreal.Vector(float(ploc.x), float(ploc.y), mx[2] + 200.0),
                    unreal.Vector(float(ploc.x), float(ploc.y), mn[2] - 200.0),
                    ch,
                )
            )
            traces.append(
                _trace(
                    world,
                    ploc + unreal.Vector(0, 0, 400),
                    ploc + unreal.Vector(0, 0, -800),
                    ch,
                )
            )
        hit = next((t for t in traces if t.get("ok")), traces[0] if traces else {"ok": False})
        rec = {
            "label": label,
            "loc": _xyz(ploc),
            "rot": _pyr(prot),
            "scale": _xyz(pscl),
            "insideAABB": inside,
            "town_side": town,
            "floor_trace": hit,
        }
        if hit.get("ok") and hit.get("loc"):
            rec["floor_dz"] = round(float(ploc.z) - hit["loc"][2], 1)
        print("SAMPLE", json.dumps(rec))
        for t in traces:
            if t.get("ok"):
                print("  HIT", json.dumps(t))
                break
        else:
            print("  MISS", json.dumps(traces[0] if traces else {}))

    print("PROOF_DONE")


main()
