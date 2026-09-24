"""Dump mohdm1 Southern France furniture vs current/old UE formulas and nearby floor."""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
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

VP = "maps/DM/mohdm1.bsp"
UMAP_CANDIDATES = (
    Path(r"D:\Games\test\Stalingrad\Content\MOHAA\maps\L_Southern_France.umap"),
    Path(r"D:\Games\test\Stalingrad\Content\MOHAA\Maps\L_Southern_France.umap"),
)
KEYS = (
    "table",
    "chair",
    "bed",
    "cabinet",
    "desk",
    "crate",
    "barrel",
    "bench",
    "stool",
    "lamp",
    "armchair",
    "piano",
    "sandbag",
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
    x, y, z = ox * 2.54, oy * 2.54, oz * 2.54
    return (-y, x, z)


def old_rot_yaw90(pitch, yaw, roll):
    return (pitch, -(yaw + 90.0), -roll)


def _count_packed(data: bytes, value: float) -> dict:
    hits = {"f64": 0, "f32": 0}
    raw64 = struct.pack("<d", float(value))
    raw32 = struct.pack("<f", float(value))
    hits["f64"] = data.count(raw64)
    hits["f32"] = data.count(raw32)
    return hits


def scan_umap(path: Path, samples: list[dict]) -> None:
    if not path.is_file():
        print("UMAP missing", path)
        return
    data = path.read_bytes()
    print("UMAP", path, "bytes", len(data), "mtime", path.stat().st_mtime)
    n_label = data.count(b"MOHAA_prop_")
    n_utf16 = data.count("MOHAA_prop_".encode("utf-16le"))
    print("UMAP label ascii", n_label, "utf16", n_utf16)
    for needle in (
        b"MOHAA_prop_SM_table_0",
        "MOHAA_prop_SM_table_0".encode("utf-16le"),
        b"SM_Southern_France",
        "SM_Southern_France".encode("utf-16le"),
    ):
        print("UMAP contains", needle[:40], data.find(needle) >= 0)
    for s in samples:
        cur = s["ue_loc_current"]
        old = s["ue_loc_old_plusx"]
        rot_c = s["ue_rot_current"]
        rot_o = s["ue_rot_old_yaw90"]
        rec = {
            "stem": s["stem"],
            "current_xyz": {axis: _count_packed(data, v) for axis, v in zip("xyz", cur)},
            "old_plusx_xyz": {axis: _count_packed(data, v) for axis, v in zip("xyz", old)},
            "current_yaw": _count_packed(data, rot_c[1]),
            "old_yaw90": _count_packed(data, rot_o[1]),
        }
        # Also search rounded-to-3 like collect_map_furniture spawn writes.
        rec["current_y_r3"] = _count_packed(data, round(cur[1], 3))
        rec["old_y_r3"] = _count_packed(data, round(old[1], 3))
        rec["current_x_r3"] = _count_packed(data, round(cur[0], 3))
        rec["old_x_r3"] = _count_packed(data, round(old[0], 3))
        rec["verdict"] = (
            "STALE_OLD_PLUSX"
            if rec["old_y_r3"]["f64"] + rec["old_y_r3"]["f32"] > rec["current_y_r3"]["f64"] + rec["current_y_r3"]["f32"]
            else (
                "FRESH_CURRENT"
                if rec["current_y_r3"]["f64"] + rec["current_y_r3"]["f32"] > 0
                else "UNKNOWN"
            )
        )
        print("UMAP SAMPLE", json.dumps(rec))


def main() -> None:
    load_paths()
    scan_game(STATE["game"])
    data = read_indexed(STATE["index"], VP)
    models = parse_bsp_models(data)
    world = models[0] if models else None
    print("======== Southern France", VP, "========")
    if world:
        mn, mx = world["mins"], world["maxs"]
        ue_min, ue_max = ue_aabb_from_bsp(mn, mx)
        print("worldspawn AABB BSP", [round(v, 2) for v in mn], [round(v, 2) for v in mx])
        print("worldspawn AABB UE", [round(v, 1) for v in ue_min], [round(v, 1) for v in ue_max])
        origin_y = (ue_min[1] + ue_max[1]) * 0.5
        print("worldspawn UE origin Y", round(origin_y, 1), "sign", "+" if origin_y >= 0 else "-")
    else:
        ue_min = ue_max = (0.0, 0.0, 0.0)
        origin_y = 0.0

    mesh = parse_bsp(data, max_indices=None, include_inline=True)
    pos = mesh.positions
    nvert = len(pos) // 3
    xs, ys, zs = pos[0::3], pos[1::3], pos[2::3]
    bsp_min = (min(xs), min(ys), min(zs))
    bsp_max = (max(xs), max(ys), max(zs))
    mesh_ue_min, mesh_ue_max = ue_aabb_from_bsp(bsp_min, bsp_max)
    mesh_origin = (
        (mesh_ue_min[0] + mesh_ue_max[0]) * 0.5,
        (mesh_ue_min[1] + mesh_ue_max[1]) * 0.5,
        (mesh_ue_min[2] + mesh_ue_max[2]) * 0.5,
    )
    print("mesh verts", nvert, "AABB BSP", [round(v, 1) for v in bsp_min], [round(v, 1) for v in bsp_max])
    print("mesh AABB UE", [round(v, 1) for v in mesh_ue_min], [round(v, 1) for v in mesh_ue_max])
    print("mesh origin UE", [round(v, 1) for v in mesh_origin], "Ysign", "+" if mesh_origin[1] >= 0 else "-")

    ents = parse_bsp_entities(data)
    statics = parse_bsp_static_models(data)
    print("entities", len(ents), "lump25", len(statics))

    stems: Counter[str] = Counter()
    for ent in statics:
        mdl = (ent.get("model") or "").replace("\\", "/")
        stems[mdl] += 1
    print("lump25 stems")
    for mdl, n in sorted(stems.items(), key=lambda kv: (-kv[1], kv[0])):
        print(" %3d %s furn=%s" % (n, mdl, is_furniture_tik(mdl)))

    recs = []
    for src, bunch in (("ENT", ents), ("SM", statics)):
        for i, ent in enumerate(bunch):
            mdl = (ent.get("model") or ent.get("modelname") or "").replace("\\", "/")
            if not is_furniture_tik(mdl):
                continue
            ox, oy, oz = entity_origin(ent)
            pitch, yaw, roll = entity_angles(ent)
            ue = mohaa_point_to_ue_cm(ox, oy, oz)
            rot = mohaa_angles_to_ue(pitch, yaw, roll)
            old = old_loc_plusx(ox, oy, oz)
            recs.append(
                {
                    "src": src,
                    "i": i,
                    "model": mdl,
                    "stem": Path(mdl).stem,
                    "bsp": [round(ox, 2), round(oy, 2), round(oz, 2)],
                    "bsp_angles": [round(pitch, 2), round(yaw, 2), round(roll, 2)],
                    "ue_loc_current": [round(ue[0], 2), round(ue[1], 2), round(ue[2], 2)],
                    "ue_rot_current": [round(rot[0], 2), round(rot[1], 2), round(rot[2], 2)],
                    "ue_loc_old_plusx": [round(v, 2) for v in old],
                    "ue_rot_old_yaw90": [round(v, 2) for v in old_rot_yaw90(pitch, yaw, roll)],
                    "scale": ent.get("scale") or entity_scale(ent),
                    "inside_world": inside(ue, ue_min, ue_max),
                    "inside_mesh": inside(ue, mesh_ue_min, mesh_ue_max),
                    "town_side_current": (ue[1] >= 0) == (mesh_origin[1] >= 0),
                    "town_side_old_plusx": (old[1] >= 0) == (mesh_origin[1] >= 0),
                }
            )
    print("FURNITURE recs", len(recs), "unique stems", len({r["stem"] for r in recs}))
    n_in = sum(1 for r in recs if r["inside_mesh"])
    n_town = sum(1 for r in recs if r["town_side_current"])
    n_old_town = sum(1 for r in recs if r["town_side_old_plusx"])
    cy = sum(r["ue_loc_current"][1] for r in recs) / max(len(recs), 1)
    cy_old = sum(r["ue_loc_old_plusx"][1] for r in recs) / max(len(recs), 1)
    print(
        "inside_mesh",
        n_in,
        "/",
        len(recs),
        "town_side current",
        n_town,
        "old+X",
        n_old_town,
        "centroidY current",
        round(cy, 1),
        "old+X",
        round(cy_old, 1),
        "meshOriginY",
        round(mesh_origin[1], 1),
    )

    picked = []
    seen = set()
    for r in recs:
        low = r["stem"].lower()
        kind = next((k for k in KEYS if k in low), None)
        if kind is None:
            continue
        if kind in seen and sum(1 for p in picked if p[0] == kind) >= 2:
            continue
        seen.add(kind)
        picked.append((kind, r))
        if len(picked) >= 8:
            break
    if len(picked) < 3:
        for r in recs:
            if r not in [p[1] for p in picked]:
                picked.append(("other", r))
            if len(picked) >= 3:
                break

    print("\n--- samples current vs old +X ---")
    step = max(1, nvert // 80000)
    verts = [(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]) for i in range(0, nvert, step)]
    for kind, s in picked:
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
        wall_dx = [abs(dx) for dx, dy, z in walls if abs(z - oz) < 24]
        wall_dy = [abs(dy) for dx, dy, z in walls if abs(z - oz) < 24]
        wall_axis = None
        if wall_dx and wall_dy:
            if sum(wall_dx) > sum(wall_dy) * 1.3:
                wall_axis = "along_BSP_X (UE -Y)"
            elif sum(wall_dy) > sum(wall_dx) * 1.3:
                wall_axis = "along_BSP_Y (UE -X)"
            else:
                wall_axis = "mixed"
        print(
            json.dumps(
                {
                    "kind": kind,
                    "stem": s["stem"],
                    "bsp": s["bsp"],
                    "bsp_angles": s["bsp_angles"],
                    "ue_loc_current": s["ue_loc_current"],
                    "ue_rot_current": s["ue_rot_current"],
                    "ue_loc_old_plusx": s["ue_loc_old_plusx"],
                    "ue_rot_old_yaw90": s["ue_rot_old_yaw90"],
                    "floor_z_bsp": None if floor_z is None else round(floor_z, 2),
                    "dz": None if floor_z is None else round(oz - floor_z, 2),
                    "wall_axis": wall_axis,
                    "town_side_current": s["town_side_current"],
                    "town_side_old_plusx": s["town_side_old_plusx"],
                }
            )
        )

    print("\nCLAIMED prior SM_table UE (-3191, -1727, 975)")
    claimed = (-3191.0, -1727.0, 975.0)
    y_bsp = -claimed[0] / 2.54
    x_bsp = -claimed[1] / 2.54
    z_bsp = claimed[2] / 2.54
    print("invert current loc=(-Y,-X,Z)*2.54 -> BSP", [round(x_bsp, 2), round(y_bsp, 2), round(z_bsp, 2)])
    x_old = claimed[1] / 2.54
    print("invert old loc=(-Y,X,Z)*2.54 -> BSP", [round(x_old, 2), round(y_bsp, 2), round(z_bsp, 2)])
    tables = [r for r in recs if "table" in r["stem"].lower() and "lamp" not in r["stem"].lower()]
    chairs = [r for r in recs if "chair" in r["stem"].lower()]
    print("TABLE count", len(tables), "CHAIR count", len(chairs))
    for s in tables[:4]:
        print(
            "TABLE",
            json.dumps(
                {
                    k: s[k]
                    for k in (
                        "stem",
                        "bsp",
                        "bsp_angles",
                        "ue_loc_current",
                        "ue_rot_current",
                        "ue_loc_old_plusx",
                        "ue_rot_old_yaw90",
                    )
                }
            ),
        )
    for s in chairs[:3]:
        print(
            "CHAIR",
            json.dumps(
                {
                    k: s[k]
                    for k in (
                        "stem",
                        "bsp",
                        "bsp_angles",
                        "ue_loc_current",
                        "ue_rot_current",
                        "ue_loc_old_plusx",
                        "ue_rot_old_yaw90",
                    )
                }
            ),
        )

    umap_samples = []
    if tables:
        umap_samples.append(tables[0])
    if chairs:
        umap_samples.append(chairs[0])
    print("\n--- umap disk scan (no LoadLevel) ---")
    found = False
    maps_dir = Path(r"D:\Games\test\Stalingrad\Content\MOHAA")
    if maps_dir.is_dir():
        for p in maps_dir.rglob("*.umap"):
            print("UMAP FILE", p)
            if "southern" in p.name.lower() or "france" in p.name.lower() or "mohdm1" in p.name.lower():
                scan_umap(p, umap_samples)
                found = True
    if not found:
        for p in UMAP_CANDIDATES:
            scan_umap(p, umap_samples)


if __name__ == "__main__":
    main()
