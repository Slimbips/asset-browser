"""Proof: furniture on the currently open map. Town-side Y + floor Z. No LoadLevel."""
from __future__ import annotations

import json

import unreal

SAMPLE_PREFIXES = (
    "MOHAA_prop_SM_sandbag_link_main_",
    "MOHAA_prop_SM_sandbag_link_topcap_",
    "MOHAA_prop_SM_table_",
    "MOHAA_prop_SM_banquet_table_",
    "MOHAA_prop_SM_simplemetaldesk_",
    "MOHAA_prop_SM_metaldesk_",
    "MOHAA_prop_SM_nazi_crate_",
    "MOHAA_prop_SM_armchairposh_",
    "MOHAA_prop_SM_simplechair_",
    "MOHAA_prop_SM_bunkerchair_",
    "MOHAA_prop_SM_bunkertable_",
    "MOHAA_prop_SM_bunkerbench_",
    "MOHAA_prop_SM_single_bed_",
    "MOHAA_prop_SM_cabinet_large_",
    "MOHAA_prop_SM_churchpew_",
    "MOHAA_prop_SM_piano_",
    "MOHAA_prop_SM_bathtubwithshowerhead_",
    "MOHAA_prop_SM_toilet_",
)


def _xyz(v):
    return [round(float(v.x), 2), round(float(v.y), 2), round(float(v.z), 2)]


def _pyr(rot):
    return [round(float(rot.pitch), 2), round(float(rot.yaw), 2), round(float(rot.roll), 2)]


def _trace_down(world, loc):
    start = loc + unreal.Vector(0, 0, 80)
    end = loc + unreal.Vector(0, 0, -800)
    channels = []
    for name in ("ECC_VISIBILITY", "ECC_WORLD_STATIC", "TRACE_TYPE_QUERY1"):
        ch = getattr(unreal.TraceTypeQuery, name, None)
        if ch is not None:
            channels.append(ch)
    last = {"ok": False}
    for ch in channels:
        try:
            hit = unreal.SystemLibrary.line_trace_single(
                world,
                start,
                end,
                ch,
                True,
                [],
                unreal.DrawDebugTrace.NONE,
                True,
            )
        except Exception as visc:
            last = {"ok": False, "err": str(visc)}
            continue
        point = None
        if isinstance(hit, (tuple, list)) and len(hit) >= 2 and hit[0] and hit[1]:
            point = getattr(hit[1], "location", None) or getattr(hit[1], "impact_point", None)
        elif getattr(hit, "blocking_hit", False):
            point = getattr(hit, "location", None)
        if point is None:
            continue
        dz = float(loc.z) - float(point.z)
        return {"ok": True, "hit": _xyz(point), "dz": round(dz, 1), "near_floor": abs(dz) < 80.0}
    return last


def main() -> None:
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    world_name = world.get_name() if world else ""
    print("WORLD", world_name)
    want_map = ("SM_" + world_name[2:]) if world_name.startswith("L_") else ""
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    map_actor = None
    n_sun = 0
    n_prop = 0
    props = []
    for actor in list(sub.get_all_level_actors() or []):
        label = actor.get_actor_label() or ""
        if want_map and label == want_map:
            map_actor = actor
        if label.startswith("MOHAA_prop_"):
            n_prop += 1
            props.append(actor)
        if isinstance(actor, unreal.DirectionalLight):
            n_sun += 1
    print("NSUN", n_sun, "NPROP", n_prop)
    if map_actor is None:
        print("NO MAP")
        return
    print("MAP", map_actor.get_actor_label(), "scale", _xyz(map_actor.get_actor_scale3d()), "loc", _xyz(map_actor.get_actor_location()))
    origin, extent = map_actor.get_actor_bounds(False)
    mn = [float(origin.x) - float(extent.x), float(origin.y) - float(extent.y), float(origin.z) - float(extent.z)]
    mx = [float(origin.x) + float(extent.x), float(origin.y) + float(extent.y), float(origin.z) + float(extent.z)]
    print("MAP AABB", [round(v, 1) for v in mn], [round(v, 1) for v in mx])

    mesh_y = float(origin.y)
    try:
        smc = getattr(map_actor, "static_mesh_component", None)
        mesh = smc.static_mesh if smc is not None else None
        if mesh is not None:
            b = mesh.get_bounds()
            mesh_y = float(b.origin.y)
            print(
                "MAP MESH origin",
                _xyz(b.origin),
                "extent",
                [
                    round(float(b.box_extent.x), 1),
                    round(float(b.box_extent.y), 1),
                    round(float(b.box_extent.z), 1),
                ],
                "originY_sign",
                "+" if mesh_y >= 0 else "-",
            )
    except Exception as visc:
        print("MAP MESH skip", visc)

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

    samples = []
    seen = set()
    for prefix in SAMPLE_PREFIXES:
        for actor in props:
            label = actor.get_actor_label() or ""
            if label in seen:
                continue
            if label.startswith(prefix):
                seen.add(label)
                samples.append(actor)
                break
    if not samples and props:
        samples = [props[0]]
    if not samples:
        print("SAMPLE MISSING")
        return
    proof = {
        "world": world.get_name() if world else "",
        "map": map_actor.get_actor_label(),
        "nprop": n_prop,
        "nsun": n_sun,
        "aabb": [[round(v, 1) for v in mn], [round(v, 1) for v in mx]],
        "mapOriginY": round(mesh_y, 1),
        "samples": [],
    }
    for sample in samples:
        loc = sample.get_actor_location()
        rot = sample.get_actor_rotation()
        scl = sample.get_actor_scale3d()
        inside = mn[0] <= float(loc.x) <= mx[0] and mn[1] <= float(loc.y) <= mx[1] and mn[2] <= float(loc.z) <= mx[2]
        town = (float(loc.y) >= 0) == (mesh_y >= 0)
        floor = _trace_down(world, loc)
        rec = {
            "label": sample.get_actor_label(),
            "loc": _xyz(loc),
            "rot": _pyr(rot),
            "scale": _xyz(scl),
            "insideAABB": inside,
            "town_side": town,
            "floor": floor,
        }
        proof["samples"].append(rec)
        print(
            "SAMPLE",
            rec["label"],
            "loc",
            rec["loc"],
            "rot",
            rec["rot"],
            "scale",
            rec["scale"],
            "insideAABB",
            inside,
            "town_side",
            town,
            "floor",
            floor,
        )
    try:
        mesh = samples[0].static_mesh_component.static_mesh
        if mesh is not None:
            b = mesh.get_bounds()
            print(
                "SAMPLE MESH",
                mesh.get_name(),
                "extent",
                round(float(b.box_extent.x), 1),
                round(float(b.box_extent.y), 1),
                round(float(b.box_extent.z), 1),
            )
    except Exception as visc:
        print("sample mesh skip", visc)
    for label_want in ("MOHAA_prop_SM_tree_oak_0", "MOHAA_prop_SM_tree_commontree_0"):
        for actor in props:
            if (actor.get_actor_label() or "") == label_want:
                try:
                    mesh = actor.static_mesh_component.static_mesh
                    b = mesh.get_bounds() if mesh else None
                    print(
                        "TREE",
                        label_want,
                        "loc",
                        _xyz(actor.get_actor_location()),
                        "rot",
                        _pyr(actor.get_actor_rotation()),
                        "mesh_extent",
                        None
                        if b is None
                        else [
                            round(float(b.box_extent.x), 1),
                            round(float(b.box_extent.y), 1),
                            round(float(b.box_extent.z), 1),
                        ],
                    )
                except Exception as visc:
                    print("TREE skip", label_want, visc)
                break
    print("PROOF", json.dumps(proof))


main()
