"""Inspect live L_Algiers: map xform, AABB, furniture loc/rot/scale. No LoadLevel."""
from __future__ import annotations

import json
import math

import unreal

KEYS = (
    "table",
    "chair",
    "stall",
    "sandbag",
    "crate",
    "bed",
    "cabinet",
    "desk",
    "cart",
    "barrel",
    "bench",
    "stool",
    "wagon",
    "awning",
    "market",
)


def _xyz(v):
    return [round(float(v.x), 2), round(float(v.y), 2), round(float(v.z), 2)]


def _pyr(rot):
    return [round(float(rot.pitch), 2), round(float(rot.yaw), 2), round(float(rot.roll), 2)]


def _fwd_xy(rot):
    yaw = math.radians(float(rot.yaw))
    # Unreal actor forward is +X rotated by yaw around Z.
    return [round(math.cos(yaw), 3), round(math.sin(yaw), 3)]


def main() -> None:
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    world_name = world.get_name() if world else ""
    print("WORLD", world_name)
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = list(sub.get_all_level_actors() or [])
    print("NACTORS", len(actors))
    map_actor = None
    n_sun = 0
    n_prop = 0
    props = []
    for actor in actors:
        label = actor.get_actor_label() or ""
        cls = actor.get_class().get_name() if actor.get_class() else ""
        if label == "SM_Algiers":
            map_actor = actor
        if isinstance(actor, unreal.DirectionalLight) or "DirectionalLight" in cls:
            n_sun += 1
            loc = actor.get_actor_location()
            rot = actor.get_actor_rotation()
            print("SUN", label, "loc", _xyz(loc), "rot", _pyr(rot))
        if label.startswith("MOHAA_prop_"):
            n_prop += 1
            props.append(actor)
    print("NSUN", n_sun, "NPROP", n_prop)
    if map_actor is None:
        print("NO MAP ACTOR SM_Algiers")
        for actor in actors:
            label = actor.get_actor_label() or ""
            if "Algiers" in label or label.startswith("SM_"):
                loc = actor.get_actor_location()
                rot = actor.get_actor_rotation()
                scl = actor.get_actor_scale3d()
                print("CAND", label, "loc", _xyz(loc), "rot", _pyr(rot), "scale", _xyz(scl))
        return
    loc = map_actor.get_actor_location()
    rot = map_actor.get_actor_rotation()
    scl = map_actor.get_actor_scale3d()
    print("MAP", map_actor.get_actor_label(), "loc", _xyz(loc), "rot", _pyr(rot), "scale", _xyz(scl))
    origin, extent = map_actor.get_actor_bounds(False)
    mn = [float(origin.x) - float(extent.x), float(origin.y) - float(extent.y), float(origin.z) - float(extent.z)]
    mx = [float(origin.x) + float(extent.x), float(origin.y) + float(extent.y), float(origin.z) + float(extent.z)]
    print("MAP AABB", [round(v, 1) for v in mn], [round(v, 1) for v in mx])
    print("MAP origin", _xyz(origin), "extent", _xyz(extent))
    try:
        mesh = map_actor.static_mesh_component.static_mesh
        b = mesh.get_bounds()
        print(
            "MESH bounds origin",
            _xyz(b.origin),
            "extent",
            [round(float(b.box_extent.x), 1), round(float(b.box_extent.y), 1), round(float(b.box_extent.z), 1)],
        )
        print("MESH path", mesh.get_path_name())
    except Exception as exc:
        print("MESH skip", exc)

    # Cluster check: prop centroid vs map origin
    if props:
        cx = sum(float(a.get_actor_location().x) for a in props) / len(props)
        cy = sum(float(a.get_actor_location().y) for a in props) / len(props)
        cz = sum(float(a.get_actor_location().z) for a in props) / len(props)
        print("PROP centroid", [round(cx, 1), round(cy, 1), round(cz, 1)])
        n_inside = 0
        n_highz = 0
        zs = []
        for a in props:
            p = a.get_actor_location()
            zs.append(float(p.z))
            if mn[0] <= float(p.x) <= mx[0] and mn[1] <= float(p.y) <= mx[1] and mn[2] <= float(p.z) <= mx[2]:
                n_inside += 1
            if float(p.z) > mx[2] - 200:
                n_highz += 1
        zs.sort()
        print(
            "PROP insideAABB",
            n_inside,
            "/",
            len(props),
            "highZ",
            n_highz,
            "Z p01/p50/p99",
            round(zs[max(0, len(zs) // 100)], 1),
            round(zs[len(zs) // 2], 1),
            round(zs[min(len(zs) - 1, len(zs) * 99 // 100)], 1),
        )

    # Sample 5-8 furniture of interesting types
    seen = set()
    samples = []
    for actor in props:
        label = (actor.get_actor_label() or "").lower()
        kind = next((k for k in KEYS if k in label), None)
        if kind is None:
            continue
        key = kind
        n_of = sum(1 for s in samples if key in (s.get_actor_label() or "").lower())
        if n_of >= 2:
            continue
        samples.append(actor)
        if len(samples) >= 8:
            break
    if len(samples) < 5:
        for actor in props:
            if actor not in samples:
                samples.append(actor)
            if len(samples) >= 8:
                break

    print("\n--- live furniture samples ---")
    for actor in samples:
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        scl = actor.get_actor_scale3d()
        inside = mn[0] <= float(loc.x) <= mx[0] and mn[1] <= float(loc.y) <= mx[1] and mn[2] <= float(loc.z) <= mx[2]
        rec = {
            "label": actor.get_actor_label(),
            "loc": _xyz(loc),
            "rot": _pyr(rot),
            "scale": _xyz(scl),
            "fwd_xy": _fwd_xy(rot),
            "insideAABB": inside,
        }
        print("SAMPLE", json.dumps(rec))

    print("\n--- all table/chair/stall/sandbag ---")
    for actor in props:
        label = actor.get_actor_label() or ""
        low = label.lower()
        if not any(k in low for k in ("table", "chair", "stall", "sandbag")):
            continue
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        inside = mn[0] <= float(loc.x) <= mx[0] and mn[1] <= float(loc.y) <= mx[1] and mn[2] <= float(loc.z) <= mx[2]
        print(
            json.dumps(
                {
                    "label": label,
                    "loc": _xyz(loc),
                    "rot": _pyr(rot),
                    "fwd_xy": _fwd_xy(rot),
                    "insideAABB": inside,
                }
            )
        )

    try:
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        cam_loc, cam_rot = ues.get_level_viewport_camera_info()
        print("CAM", _xyz(cam_loc), _pyr(cam_rot))
    except Exception as exc:
        print("CAM skip", exc)


main()
