"""Dump mohdm7 Algiers furniture vs current/old UE formulas and nearby floor/walls."""
from __future__ import annotations

import json
import math
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

VP = "maps/DM/mohdm7.bsp"
KEYS = (
    "table",
    "chair",
    "stall",
    "sandbag",
    "crate",
    "bed",
    "cabinet",
    "desk",
    "market",
    "cart",
    "barrel",
    "bench",
    "stool",
    "awning",
    "wagon",
)


def inside(p, mn, mx, pad=1.0):
    return all(mn[i] - pad <= p[i] <= mx[i] + pad for i in range(3))


def ue_aabb_from_bsp(mn, mx):
    a = mohaa_point_to_ue_cm(*mn)
    b = mohaa_point_to_ue_cm(*mx)
    return (
        (min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2])),
        (max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2])),
    )


def old_loc_plusx(ox, oy, oz):
    """Old mirrored-map loc=(-Y, X, Z)*2.54 — Unreal Y has opposite sign."""
    x, y, z = ox * 2.54, oy * 2.54, oz * 2.54
    return (-y, x, z)


def old_rot_yaw90(pitch, yaw, roll):
    return (pitch, -(yaw + 90.0), -roll)


def main() -> None:
    load_paths()
    scan_game(STATE["game"])
    data = read_indexed(STATE["index"], VP)
    models = parse_bsp_models(data)
    world = models[0] if models else None
    print("======== Algiers", VP, "========")
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

    # Sky-ish: high Z cluster
    z_sorted = sorted(zs)
    print("mesh Z p01/p50/p99", round(z_sorted[nvert // 100], 1), round(z_sorted[nvert // 2], 1), round(z_sorted[nvert * 99 // 100], 1))

    ents = parse_bsp_entities(data)
    statics = parse_bsp_static_models(data)
    print("entities", len(ents), "lump25", len(statics))

    stems: dict[str, int] = {}
    furn_stems: dict[str, int] = {}
    for ent in statics:
        mdl = (ent.get("model") or "").replace("\\", "/")
        stems[mdl] = stems.get(mdl, 0) + 1
        if is_furniture_tik(mdl):
            furn_stems[mdl] = furn_stems.get(mdl, 0) + 1
    print("lump25 stems")
    for mdl, n in sorted(stems.items(), key=lambda kv: (-kv[1], kv[0])):
        print(" %3d %s furn=%s" % (n, mdl, is_furniture_tik(mdl)))

    print("\n--- furniture KEYS vs formulas ---")
    samples = []
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
                "stem": Path(mdl).stem,
                "bsp": [round(ox, 2), round(oy, 2), round(oz, 2)],
                "bsp_angles": [round(pitch, 2), round(yaw, 2), round(roll, 2)],
                "ue_loc_current": [round(ue[0], 2), round(ue[1], 2), round(ue[2], 2)],
                "ue_rot_current": [round(rot[0], 2), round(rot[1], 2), round(rot[2], 2)],
                "ue_loc_old_plusx": [round(v, 2) for v in old_loc_plusx(ox, oy, oz)],
                "ue_rot_old_yaw90": [round(v, 2) for v in old_rot_yaw90(pitch, yaw, roll)],
                "scale": ent.get("scale") or entity_scale(ent),
                "inside_world": inside(ue, ue_min, ue_max),
                "inside_mesh": inside(ue, mesh_ue_min, mesh_ue_max),
            }
            samples.append(rec)
            print(json.dumps(rec))

    print("\n--- nearby floor Z + wall heading ---")
    # Build a coarse XY grid of verts for nearby queries
    verts = [(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]) for i in range(nvert)]
    interesting = [s for s in samples if any(k in s["stem"].lower() for k in ("table", "chair", "stall", "sandbag", "crate", "bed"))]
    seen_stems = set()
    picked = []
    for s in interesting:
        if s["stem"] in seen_stems and sum(1 for p in picked if p["stem"] == s["stem"]) >= 2:
            continue
        seen_stems.add(s["stem"])
        picked.append(s)
        if len(picked) >= 10:
            break
    if not picked:
        picked = samples[:8]
    for s in picked:
        ox, oy, oz = s["bsp"]
        near = []
        walls = []
        for x, y, z in verts:
            dx, dy = x - ox, y - oy
            if dx * dx + dy * dy > 96 * 96:
                continue
            near.append((x, y, z))
            if abs(z - oz) < 48 and abs(dx) + abs(dy) > 8:
                walls.append((dx, dy, z))
        below = [z for _x, _y, z in near if z <= oz + 8]
        floor_z = max(below) if below else None
        # Dominant wall tangent: largest |dx| vs |dy| among verts at wall height
        wall_dx = [abs(dx) for dx, dy, z in walls if abs(z - oz) < 24]
        wall_dy = [abs(dy) for dx, dy, z in walls if abs(z - oz) < 24]
        wall_axis = None
        if wall_dx and wall_dy:
            # If nearby verts spread more in X, wall is likely Y-facing (along X)
            if sum(wall_dx) > sum(wall_dy) * 1.3:
                wall_axis = "along_BSP_X (UE -Y)"
            elif sum(wall_dy) > sum(wall_dx) * 1.3:
                wall_axis = "along_BSP_Y (UE -X)"
            else:
                wall_axis = "mixed"
        yaw = s["bsp_angles"][1]
        ue_yaw = s["ue_rot_current"][1]
        old_yaw = s["ue_rot_old_yaw90"][1]
        print(
            json.dumps(
                {
                    "stem": s["stem"],
                    "bsp": s["bsp"],
                    "bsp_yaw": yaw,
                    "ue_loc": s["ue_loc_current"],
                    "ue_yaw": ue_yaw,
                    "old_yaw90": old_yaw,
                    "near": len(near),
                    "floor_z": None if floor_z is None else round(floor_z, 2),
                    "dz": None if floor_z is None else round(oz - floor_z, 2),
                    "wall_axis": wall_axis,
                    "prop_heading_current": "UE yaw %s (BSP yaw %s)" % (ue_yaw, yaw),
                }
            )
        )

    print("\nCLAIMED prior SM_table UE (3214, 4132, -142)")
    # invert current formula: X_ue=-Y*2.54, Y_ue=-X*2.54, Z=Z*2.54
    claimed = (3214.0, 4132.0, -142.0)
    y_bsp = -claimed[0] / 2.54
    x_bsp = -claimed[1] / 2.54
    z_bsp = claimed[2] / 2.54
    print("invert current loc=(-Y,-X,Z)*2.54 -> BSP", [round(x_bsp, 2), round(y_bsp, 2), round(z_bsp, 2)])
    y_old = -claimed[0] / 2.54
    x_old = claimed[1] / 2.54
    print("invert old loc=(-Y,X,Z)*2.54 -> BSP", [round(x_old, 2), round(y_old, 2), round(z_bsp, 2)])
    for s in samples:
        if "table" not in s["stem"].lower():
            continue
        print("TABLE", json.dumps({k: s[k] for k in ("stem", "bsp", "bsp_angles", "ue_loc_current", "ue_rot_current", "ue_loc_old_plusx", "ue_rot_old_yaw90")}))


if __name__ == "__main__":
    main()
