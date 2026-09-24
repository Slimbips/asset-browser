"""Inspect live L_Snowy_Park: map xform, AABB, furniture loc/rot, town-side, floor Z.

No LoadLevel. If another map is open, only report asset existence and current world.
"""
from __future__ import annotations

import json
import math

import unreal

NON_TREE = ("light", "lamp", "rock", "bench", "crate", "barrel", "fence", "post", "hydrant", "statue")


def _xyz(v):
    return [round(float(v.x), 2), round(float(v.y), 2), round(float(v.z), 2)]


def _pyr(rot):
    return [round(float(rot.pitch), 2), round(float(rot.yaw), 2), round(float(rot.roll), 2)]


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
                actor = getattr(res, "actor", None)
                return {
                    "ok": True,
                    "loc": None if loc is None else _xyz(loc),
                    "actor": None if actor is None else str(actor.get_actor_label()),
                }
        if getattr(hit, "blocking_hit", False):
            loc = hit.location
            actor = getattr(hit, "actor", None)
            return {
                "ok": True,
                "loc": _xyz(loc),
                "actor": None if actor is None else str(actor.get_actor_label()),
            }
    except Exception as visc:
        return {"ok": False, "err": str(visc)}
    return {"ok": False}


def main() -> None:
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    world_name = world.get_name() if world else ""
    print("WORLD", world_name)
    for path in (
        "/Game/MOHAA/maps/L_Snowy_Park",
        "/Game/MOHAA/maps/SM_Snowy_Park",
        "/Game/MOHAA/maps/L_Algiers",
        "/Game/MOHAA/maps/L_Stalingrad",
        "/Game/MOHAA/maps/L_Remagen",
        "/Game/MOHAA/maps/L_Southern_France",
        "/Game/MOHAA/maps/L_Destroyed_Village",
        "/Game/MOHAA/maps/L_Crossroads",
        "/Game/MOHAA/maps/L_The_Crossroads",
    ):
        exists = unreal.EditorAssetLibrary.does_asset_exist(path)
        print("EXISTS", path, exists)

    if world_name != "L_Snowy_Park":
        print("NOT OPEN L_Snowy_Park (no LoadLevel)")
        try:
            mesh = unreal.EditorAssetLibrary.load_asset("/Game/MOHAA/maps/SM_Snowy_Park")
            if mesh is not None:
                b = mesh.get_bounds()
                print(
                    "MESH bounds origin",
                    _xyz(b.origin),
                    "extent",
                    [
                        round(float(b.box_extent.x), 1),
                        round(float(b.box_extent.y), 1),
                        round(float(b.box_extent.z), 1),
                    ],
                )
                print("MESH path", mesh.get_path_name())
                print("MESH origin Y sign", "+" if float(b.origin.y) >= 0 else "-")
        except Exception as exc:
            print("MESH skip", exc)
        return

    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = list(sub.get_all_level_actors() or [])
    print("NACTORS", len(actors))
    map_actor = None
    n_sun = 0
    n_prop = 0
    props = []
    by_label = {}
    for actor in actors:
        label = actor.get_actor_label() or ""
        by_label[label] = actor
        cls = actor.get_class().get_name() if actor.get_class() else ""
        if label == "SM_Snowy_Park":
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
        print("NO MAP ACTOR SM_Snowy_Park")
        for actor in actors:
            label = actor.get_actor_label() or ""
            if "Snowy" in label or label.startswith("SM_"):
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
    print("MAP origin", _xyz(origin), "extent", _xyz(extent), "Ysign", "+" if float(origin.y) >= 0 else "-")
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
        print("MESH origin Y sign", "+" if float(b.origin.y) >= 0 else "-")
    except Exception as exc:
        print("MESH skip", exc)
        b = None

    mesh_y = float(origin.y)
    if props:
        cx = sum(float(a.get_actor_location().x) for a in props) / len(props)
        cy = sum(float(a.get_actor_location().y) for a in props) / len(props)
        cz = sum(float(a.get_actor_location().z) for a in props) / len(props)
        print("PROP centroid", [round(cx, 1), round(cy, 1), round(cz, 1)])
        n_inside = 0
        n_highz = 0
        n_town = 0
        zs = []
        ys = []
        for a in props:
            p = a.get_actor_location()
            zs.append(float(p.z))
            ys.append(float(p.y))
            if mn[0] <= float(p.x) <= mx[0] and mn[1] <= float(p.y) <= mx[1] and mn[2] <= float(p.z) <= mx[2]:
                n_inside += 1
            if float(p.z) > mx[2] - 200:
                n_highz += 1
            if (float(p.y) >= 0) == (mesh_y >= 0):
                n_town += 1
        zs.sort()
        print(
            "PROP insideAABB",
            n_inside,
            "/",
            len(props),
            "town_side",
            n_town,
            "/",
            len(props),
            "highZ",
            n_highz,
            "Z p01/p50/p99",
            round(zs[max(0, len(zs) // 100)], 1),
            round(zs[len(zs) // 2], 1),
            round(zs[min(len(zs) - 1, len(zs) * 99 // 100)], 1),
        )
        same_side = (cy >= 0) == (mesh_y >= 0)
        print("PROP_TOWN_SIDE", same_side, "centroidY", round(cy, 1), "mapOriginY", round(mesh_y, 1))
        # Stale old +X would put Y on the opposite half of the mesh origin.
        print("STALE_OLD_PLUSX_HINT", (not same_side) and n_inside > 0)

    samples = []
    seen_kind = {}
    for actor in props:
        label = (actor.get_actor_label() or "").lower()
        kind = "tree" if "tree" in label else next((k for k in NON_TREE if k in label), None)
        if kind is None:
            continue
        n_of = seen_kind.get(kind, 0)
        if n_of >= 2:
            continue
        seen_kind[kind] = n_of + 1
        samples.append(actor)
        if "tree" in seen_kind and any(k in seen_kind for k in NON_TREE) and len(samples) >= 3:
            break
    if len(samples) < 3:
        for actor in props:
            if actor not in samples:
                samples.append(actor)
            if len(samples) >= 3:
                break

    print("\n--- live furniture samples ---")
    for actor in samples:
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        scl = actor.get_actor_scale3d()
        inside = mn[0] <= float(loc.x) <= mx[0] and mn[1] <= float(loc.y) <= mx[1] and mn[2] <= float(loc.z) <= mx[2]
        town = (float(loc.y) >= 0) == (mesh_y >= 0)
        down = _trace(world, loc + unreal.Vector(0, 0, 80), loc + unreal.Vector(0, 0, -800))
        rec = {
            "label": actor.get_actor_label(),
            "loc": _xyz(loc),
            "rot": _pyr(rot),
            "scale": _xyz(scl),
            "insideAABB": inside,
            "town_side": town,
            "floor_trace": down,
        }
        if down.get("ok") and down.get("loc"):
            rec["floor_dz"] = round(float(loc.z) - down["loc"][2], 1)
        print("SAMPLE", json.dumps(rec))

    # Counts by stem
    stems = {}
    for actor in props:
        label = actor.get_actor_label() or ""
        parts = label.replace("MOHAA_prop_", "").rsplit("_", 1)
        stem = parts[0] if parts else label
        stems[stem] = stems.get(stem, 0) + 1
    print("STEMS", json.dumps(stems))
    print("INSPECT_DONE")


main()
