"""Dump mohdm1 / mohdm4 lump 25 vs map AABB: sandbags, trees, tables."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from formats import (  # noqa: E402
    entity_angles,
    entity_origin,
    entity_scale,
    is_furniture_tik,
    mohaa_angles_to_ue,
    mohaa_point_to_ue_cm,
    parse_bsp,
    parse_bsp_entities,
    parse_bsp_models,
    parse_bsp_static_models,
)
from server import STATE, load_paths, read_indexed, scan_game  # noqa: E402

MAPS = (
    ("maps/DM/mohdm1.bsp", "Southern_France"),
    ("maps/DM/mohdm4.bsp", "Crossroads"),
)
KEYS = ("sandbag", "bag", "tree", "bush", "table", "chair", "pole", "lightpost", "wagon")


def inside(p, mn, mx, pad=1.0):
    return all(mn[i] - pad <= p[i] <= mx[i] + pad for i in range(3))


def ue_aabb_from_bsp(mn, mx):
    a = mohaa_point_to_ue_cm(*mn)
    b = mohaa_point_to_ue_cm(*mx)
    return (
        (min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2])),
        (max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2])),
    )


def dump_map(vp: str, title: str) -> None:
    data = read_indexed(STATE["index"], vp)
    models = parse_bsp_models(data)
    world = models[0] if models else None
    print("\n========", title, vp, "========")
    if world:
        mn, mx = world["mins"], world["maxs"]
        ue_min, ue_max = ue_aabb_from_bsp(mn, mx)
        print("worldspawn AABB BSP", [round(v, 2) for v in mn], [round(v, 2) for v in mx])
        print("worldspawn AABB UE", [round(v, 1) for v in ue_min], [round(v, 1) for v in ue_max])
    else:
        ue_min = ue_max = (0.0, 0.0, 0.0)
        mn = mx = (0.0, 0.0, 0.0)

    mesh = parse_bsp(data, max_indices=None, include_inline=True)
    pos = mesh.positions
    nvert = len(pos) // 3
    xs, ys, zs = pos[0::3], pos[1::3], pos[2::3]
    bsp_min = (min(xs), min(ys), min(zs))
    bsp_max = (max(xs), max(ys), max(zs))
    mesh_ue_min, mesh_ue_max = ue_aabb_from_bsp(bsp_min, bsp_max)
    print("mesh verts", nvert, "AABB BSP", [round(v, 1) for v in bsp_min], [round(v, 1) for v in bsp_max])
    print("mesh AABB UE", [round(v, 1) for v in mesh_ue_min], [round(v, 1) for v in mesh_ue_max])

    ents = parse_bsp_entities(data)
    statics = parse_bsp_static_models(data)
    print("entities", len(ents), "lump25", len(statics))

    stems: dict[str, int] = {}
    for ent in statics:
        mdl = (ent.get("model") or "").replace("\\", "/")
        stems[mdl] = stems.get(mdl, 0) + 1
    print("lump25 stems")
    for mdl, n in sorted(stems.items(), key=lambda kv: (-kv[1], kv[0])):
        print(" %3d %s furn=%s" % (n, mdl, is_furniture_tik(mdl)))

    print("\n--- sandbag / bag / tree / table / chair / pole ---")
    for src, bunch in (("ENT", ents), ("SM", statics)):
        for i, ent in enumerate(bunch):
            mdl = (ent.get("model") or ent.get("modelname") or "").replace("\\", "/")
            low = mdl.lower()
            if not any(k in low for k in KEYS):
                continue
            ox, oy, oz = entity_origin(ent)
            pitch, yaw, roll = entity_angles(ent)
            ue = mohaa_point_to_ue_cm(ox, oy, oz)
            rot = mohaa_angles_to_ue(pitch, yaw, roll)
            rec = {
                "src": src,
                "i": i,
                "model": mdl,
                "bsp": [round(ox, 2), round(oy, 2), round(oz, 2)],
                "bsp_angles": [round(pitch, 2), round(yaw, 2), round(roll, 2)],
                "ue_loc": [round(ue[0], 2), round(ue[1], 2), round(ue[2], 2)],
                "ue_rot": [round(rot[0], 2), round(rot[1], 2), round(rot[2], 2)],
                "scale": ent.get("scale") or entity_scale(ent),
                "inside_world": inside(ue, ue_min, ue_max),
                "inside_mesh": inside(ue, mesh_ue_min, mesh_ue_max),
            }
            print(json.dumps(rec))

    # Street-height sandbags: nearby mesh Z
    print("\n--- sandbag vs nearby mesh Z ---")
    for ent in statics:
        mdl = (ent.get("model") or "").replace("\\", "/").lower()
        if "sandbag" not in mdl and "flourbag" not in mdl:
            continue
        ox, oy, oz = entity_origin(ent)
        ue = mohaa_point_to_ue_cm(ox, oy, oz)
        near = []
        for vi in range(nvert):
            x, y, z = pos[vi * 3], pos[vi * 3 + 1], pos[vi * 3 + 2]
            if (x - ox) ** 2 + (y - oy) ** 2 <= 64 * 64:
                near.append(z)
        below = [z for z in near if z <= oz + 8] if near else []
        floor_z = max(below) if below else None
        print(
            Path(mdl).stem,
            "bsp",
            (round(ox, 2), round(oy, 2), round(oz, 2)),
            "ue",
            tuple(round(v, 1) for v in ue),
            "near",
            len(near),
            "floor_z",
            None if floor_z is None else round(floor_z, 2),
            "dz",
            None if floor_z is None else round(oz - floor_z, 2),
        )


def main() -> None:
    load_paths()
    scan_game(STATE["game"])
    for vp, title in MAPS:
        dump_map(vp, title)


if __name__ == "__main__":
    main()
