"""Proof: Stalingrad dumpster (simplemetaldesk) + MG42 sit on map brushes. No LoadLevel."""
from __future__ import annotations

import json

import unreal

# BSP origins from maps/DM/mohdm6.bsp. Formula loc=(-Y,-X,Z)*2.54
DESK_BSP = (267.2, 153.6, 32.0)
DESK_UE = (-153.6 * 2.54, -267.2 * 2.54, 32.0 * 2.54)  # (-390.144, -678.688, 81.28)
MG_BSP = (257.0, -173.0, 284.0)
MG_UE = (173.0 * 2.54, -257.0 * 2.54, 284.0 * 2.54)  # (439.42, -652.78, 721.36)
FLOOR_BSP_Z = 32.0
ROOF_NEAR_BSP_Z = 224.0  # nearest kept brush under MG XY in parse_bsp


def _pyr(rot):
    return [round(float(rot.pitch), 2), round(float(rot.yaw), 2), round(float(rot.roll), 2)]


def _xyz(v):
    return [round(float(v.x), 2), round(float(v.y), 2), round(float(v.z), 2)]


def _named(sub, prefix: str):
    for actor in list(sub.get_all_level_actors() or []):
        label = actor.get_actor_label() or ""
        if label.startswith(prefix):
            return actor
    return None


def _trace_down(world, loc, dist=4000.0):
    start = unreal.Vector(float(loc.x), float(loc.y), float(loc.z) + 80.0)
    end = unreal.Vector(float(loc.x), float(loc.y), float(loc.z) - dist)
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
            unreal.LinearColor(1, 0, 0, 1),
            unreal.LinearColor(0, 1, 0, 1),
            0.0,
        )
    except Exception as exc:
        print("TRACE skip", exc)
        return None
    if not hit:
        return None
    try:
        blocking = bool(hit.get_editor_property("blocking_hit") or hit.get("blocking_hit"))
    except Exception:
        blocking = bool(getattr(hit, "blocking_hit", False))
    if not blocking:
        try:
            blocking = bool(hit.to_tuple()[0]) if hasattr(hit, "to_tuple") else False
        except Exception:
            blocking = False
    loc_hit = None
    try:
        loc_hit = hit.get_editor_property("location")
    except Exception:
        loc_hit = getattr(hit, "location", None)
    actor = None
    try:
        actor = hit.get_editor_property("hit_actor")
    except Exception:
        actor = getattr(hit, "hit_actor", None)
    z = float(loc_hit.z) if loc_hit is not None else None
    name = ""
    try:
        name = actor.get_actor_label() if actor else ""
    except Exception:
        name = str(actor or "")
    return {"blocking": blocking, "z": None if z is None else round(z, 2), "actor": name}


def main() -> None:
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    print("WORLD", world.get_name() if world else "")
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    map_actor = None
    n_sun = 0
    n_prop = 0
    for actor in list(sub.get_all_level_actors() or []):
        label = actor.get_actor_label() or ""
        if label == "SM_Stalingrad":
            map_actor = actor
        if label.startswith("MOHAA_prop_"):
            n_prop += 1
        if isinstance(actor, unreal.DirectionalLight):
            n_sun += 1
    print("NSUN", n_sun, "NPROP", n_prop)
    if map_actor is None:
        print("NO MAP")
        return
    origin, extent = map_actor.get_actor_bounds(False)
    mn = [float(origin.x) - float(extent.x), float(origin.y) - float(extent.y), float(origin.z) - float(extent.z)]
    mx = [float(origin.x) + float(extent.x), float(origin.y) + float(extent.y), float(origin.z) + float(extent.z)]
    print("MAP AABB", [round(v, 1) for v in mn], [round(v, 1) for v in mx])
    scl = map_actor.get_actor_scale3d()
    print("MAP scale", _xyz(scl), "loc", _xyz(map_actor.get_actor_location()))

    desk = _named(sub, "MOHAA_prop_SM_simplemetaldesk_")
    mg = _named(sub, "MOHAA_prop_SM_mg42_gun_")
    bipod = _named(sub, "MOHAA_prop_SM_mg42_bipod_")
    chair = _named(sub, "MOHAA_prop_SM_bunkerchair_")

    def report(tag, actor, expected, bsp, floor_z_cm):
        if actor is None:
            print(tag, "MISSING")
            return None
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        inside = mn[0] <= float(loc.x) <= mx[0] and mn[1] <= float(loc.y) <= mx[1] and mn[2] <= float(loc.z) <= mx[2]
        err = (
            abs(float(loc.x) - expected[0]),
            abs(float(loc.y) - expected[1]),
            abs(float(loc.z) - expected[2]),
        )
        dz_floor = float(loc.z) - floor_z_cm
        print(
            tag,
            actor.get_actor_label(),
            "bsp",
            bsp,
            "ue",
            _xyz(loc),
            "rot",
            _pyr(rot),
            "expected",
            [round(v, 2) for v in expected],
            "err_cm",
            [round(v, 2) for v in err],
            "insideAABB",
            inside,
            "dz_floor_cm",
            round(dz_floor, 2),
        )
        hit = _trace_down(world, loc) if world else None
        if hit:
            print(tag, "trace", json.dumps(hit), "actor_minus_hit_z", None if hit["z"] is None else round(float(loc.z) - hit["z"], 2))
        return loc

    dloc = report("DUMPSTER", desk, DESK_UE, DESK_BSP, FLOOR_BSP_Z * 2.54)
    report("MG42", mg, MG_UE, MG_BSP, ROOF_NEAR_BSP_Z * 2.54)
    if bipod:
        print("BIPOD", bipod.get_actor_label(), _xyz(bipod.get_actor_location()), _pyr(bipod.get_actor_rotation()))
    if chair:
        print("CHAIR", chair.get_actor_label(), _xyz(chair.get_actor_location()), _pyr(chair.get_actor_rotation()))

    # Camera: look down at dumpster from the courtyard side.
    target = dloc or unreal.Vector(DESK_UE[0], DESK_UE[1], DESK_UE[2])
    cam = unreal.Vector(float(target.x) + 900.0, float(target.y) + 900.0, float(target.z) + 700.0)
    rot = unreal.Rotator(pitch=-28.0, yaw=-135.0, roll=0.0)
    try:
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        ues.set_level_viewport_camera_info(cam, rot)
        print("CAM", _xyz(cam), _pyr(rot))
    except Exception as exc:
        print("CAM skip", exc)


main()
