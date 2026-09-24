"""Dump live L_Remagen plate/table actors vs mesh bounds. No LoadLevel."""
from __future__ import annotations

import unreal

WANT = (
    "flowerplate",
    "servingplate",
    "dish",
    "banquet_table",
    "ornaterectable",
    "table",
    "simplechair",
    "woodchair",
    "tree_oak",
    "hanglamp",
    "wallsconce",
)


def _print_mesh(tag: str, mesh) -> None:
    if mesh is None:
        print(tag, "NO MESH")
        return
    b = mesh.get_bounds()
    print(
        tag,
        "mesh",
        mesh.get_name(),
        "origin",
        round(float(b.origin.x), 2),
        round(float(b.origin.y), 2),
        round(float(b.origin.z), 2),
        "extent",
        round(float(b.box_extent.x), 2),
        round(float(b.box_extent.y), 2),
        round(float(b.box_extent.z), 2),
        "minz",
        round(float(b.origin.z) - float(b.box_extent.z), 2),
        "maxz",
        round(float(b.origin.z) + float(b.box_extent.z), 2),
    )


def main() -> None:
    print("LEVEL", unreal.EditorLevelLibrary.get_editor_world().get_name())
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    n_prop = 0
    n_sun = 0
    map_actor = None
    rows = []
    for actor in list(sub.get_all_level_actors() or []):
        label = actor.get_actor_label() or ""
        if label == "SM_Remagen":
            map_actor = actor
        if isinstance(actor, unreal.DirectionalLight):
            n_sun += 1
        if not label.startswith("MOHAA_prop_"):
            continue
        n_prop += 1
        low = label.lower()
        if not any(w in low for w in WANT):
            continue
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        origin, extent = actor.get_actor_bounds(False)
        mesh = None
        try:
            mesh = actor.static_mesh_component.static_mesh
        except Exception:
            pass
        rows.append((label, loc, rot, origin, extent, mesh, actor))

    print("props", n_prop, "dirlights", n_sun)
    if map_actor is not None:
        loc = map_actor.get_actor_location()
        rot = map_actor.get_actor_rotation()
        scl = map_actor.get_actor_scale3d()
        origin, extent = map_actor.get_actor_bounds(False)
        mn = (
            float(origin.x) - float(extent.x),
            float(origin.y) - float(extent.y),
            float(origin.z) - float(extent.z),
        )
        mx = (
            float(origin.x) + float(extent.x),
            float(origin.y) + float(extent.y),
            float(origin.z) + float(extent.z),
        )
        print(
            "MAP loc",
            round(float(loc.x), 2),
            round(float(loc.y), 2),
            round(float(loc.z), 2),
            "rot",
            round(float(rot.pitch), 2),
            round(float(rot.yaw), 2),
            round(float(rot.roll), 2),
            "scale",
            tuple(round(float(v), 4) for v in (scl.x, scl.y, scl.z)),
        )
        print("MAP aabb min", [round(v, 1) for v in mn], "max", [round(v, 1) for v in mx])
    else:
        mn = mx = None

    banquet = None
    for label, loc, rot, origin, extent, mesh, actor in sorted(rows, key=lambda r: r[0]):
        p = (float(loc.x), float(loc.y), float(loc.z))
        print(
            "ACTOR",
            label,
            "loc",
            round(p[0], 2),
            round(p[1], 2),
            round(p[2], 2),
            "rot P",
            round(float(rot.pitch), 2),
            "Y",
            round(float(rot.yaw), 2),
            "R",
            round(float(rot.roll), 2),
            "bounds_z",
            round(float(origin.z) - float(extent.z), 2),
            round(float(origin.z) + float(extent.z), 2),
        )
        _print_mesh("  ", mesh)
        if "banquet_table" in label.lower() and banquet is None:
            banquet = (p, origin, extent, mesh)
        if mn is not None:
            inside = mn[0] <= p[0] <= mx[0] and mn[1] <= p[1] <= mx[1] and mn[2] <= p[2] <= mx[2]
            if "table" in label.lower() or "chair" in label.lower() or "tree_oak" in label.lower():
                print("  inside_town_aabb", inside)

    if banquet is not None:
        bp, borigin, bextent, bmesh = banquet
        table_top = float(borigin.z) + float(bextent.z)
        print("BANQUET origin_z", round(bp[2], 2), "visual_top", round(table_top, 2))
        for label, loc, rot, origin, extent, mesh, actor in rows:
            if not any(w in label.lower() for w in ("flowerplate", "servingplate", "dish")):
                continue
            pz = float(loc.z)
            vis_min = float(origin.z) - float(extent.z)
            vis_max = float(origin.z) + float(extent.z)
            print(
                "VS_TABLE",
                label,
                "actorZ",
                round(pz, 2),
                "visZ",
                round(vis_min, 2),
                round(vis_max, 2),
                "dActorZ",
                round(pz - bp[2], 2),
                "dVisMin_from_tabletop",
                round(vis_min - table_top, 2),
            )

    for name in (
        "/Game/MOHAA/props/SM_flowerplate",
        "/Game/MOHAA/props/SM_servingplate",
        "/Game/MOHAA/props/SM_dish",
        "/Game/MOHAA/props/SM_banquet_table",
        "/Game/MOHAA/props/SM_table",
        "/Game/MOHAA/props/SM_simplechair",
        "/Game/MOHAA/props/SM_tree_oak",
    ):
        mesh = unreal.EditorAssetLibrary.load_asset(name)
        _print_mesh("ASSET " + name.split("/")[-1], mesh)


main()
