"""Dump mohdm5 Snowy Park furniture vs current/old UE formulas and nearby floor."""
from __future__ import annotations

import json
import posixpath
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
    surface_nodraw_reason,
)
from server import (  # noqa: E402
    STATE,
    load_mesh_payload,
    load_paths,
    load_tik,
    norm,
    read_indexed,
    resolve_skelmodel,
    scan_game,
)

VP = "maps/DM/mohdm5.bsp"
NON_TREE = ("light", "lamp", "rock", "bench", "crate", "barrel", "fence", "post", "hydrant", "statue")


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


def main() -> None:
    load_paths()
    scan_game(STATE["game"])
    data = read_indexed(STATE["index"], VP)
    models = parse_bsp_models(data)
    world = models[0] if models else None
    print("======== Snowy Park", VP, "========")
    if world:
        mn, mx = world["mins"], world["maxs"]
        ue_min, ue_max = ue_aabb_from_bsp(mn, mx)
        print("worldspawn AABB BSP", [round(v, 2) for v in mn], [round(v, 2) for v in mx])
        print("worldspawn AABB UE", [round(v, 1) for v in ue_min], [round(v, 1) for v in ue_max])
        mesh_origin_y = (ue_min[1] + ue_max[1]) * 0.5
        print("worldspawn UE origin Y", round(mesh_origin_y, 1), "sign", "+" if mesh_origin_y >= 0 else "-")
    else:
        ue_min = ue_max = (0.0, 0.0, 0.0)
        mesh_origin_y = 0.0

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
    furn_stems: Counter[str] = Counter()
    for ent in statics:
        mdl = (ent.get("model") or "").replace("\\", "/")
        stems[mdl] += 1
        if is_furniture_tik(mdl):
            furn_stems[mdl] += 1
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
    print("inside_mesh", n_in, "/", len(recs), "town_side current", n_town, "old+X", n_old_town)

    picked = []
    seen = set()
    for r in recs:
        low = r["stem"].lower()
        kind = "tree" if "tree" in low else next((k for k in NON_TREE if k in low), None)
        if kind is None:
            continue
        if kind in seen and sum(1 for p in picked if p[0] == kind) >= 2:
            continue
        seen.add(kind)
        picked.append((kind, r))
        if len(picked) >= 6:
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
        below = [z for x, y, z in verts if (x - ox) ** 2 + (y - oy) ** 2 <= 96 * 96 and z <= oz + 16]
        floor_z = max(below) if below else None
        print(
            json.dumps(
                {
                    "kind": kind,
                    **{
                        k: s[k]
                        for k in (
                            "stem",
                            "bsp",
                            "bsp_angles",
                            "ue_loc_current",
                            "ue_rot_current",
                            "ue_loc_old_plusx",
                            "ue_rot_old_yaw90",
                            "inside_mesh",
                            "town_side_current",
                            "town_side_old_plusx",
                        )
                    },
                    "floor_bsp_z": None if floor_z is None else round(floor_z, 2),
                    "dz_bsp": None if floor_z is None else round(oz - floor_z, 2),
                }
            )
        )

    print("\n--- sprite surfaces on unique furniture TIKs ---")
    for mdl in sorted(furn_stems):
        try:
            tik_obj, tik_file = load_tik("", mdl)
        except Exception as visc:
            print(" tik fail", mdl, visc)
            continue
        folder = (tik_obj.get("path") or "").rstrip("/") or posixpath.dirname(tik_file or mdl)
        skels = [resolve_skelmodel(STATE["index"], folder, sk) for sk in (tik_obj.get("skelmodels") or [])]
        skels = [p for p in skels if p and norm(p) in STATE["index"] and p.lower().endswith(".skd")]
        if not skels:
            print(" no skd", mdl)
            continue
        try:
            prop = load_mesh_payload(skels[0], tik_file or mdl, full_geometry=True, use_idle=True)
        except Exception as visc:
            print(" mesh fail", mdl, visc)
            continue
        sprite = []
        kept = []
        for mat in prop.get("materials") or []:
            name = mat.get("surface") or mat.get("shader") or ""
            reason = surface_nodraw_reason(name, tik_obj) or (mat.get("hide_reason") or "")
            if mat.get("nodraw") or "sprite" in name.lower() or "autosprite" in str(reason).lower():
                sprite.append((name, reason or mat.get("hide_reason") or "nodraw"))
            else:
                kept.append(name)
        print(
            "TIK",
            Path(mdl).stem,
            "instances",
            furn_stems[mdl],
            "kept",
            len(kept),
            "sprite/nodraw",
            sprite,
        )


if __name__ == "__main__":
    main()
