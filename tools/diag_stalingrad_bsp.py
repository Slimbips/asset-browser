"""Dump mohdm6 lump 25 / entities / map AABB vs dumpster-like props and courtyard floor."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from formats import (  # noqa: E402
    BSP_CM_PER_UNIT,
    SURF_NODRAW,
    SURF_SKY,
    _cstr,
    _i32,
    bsp_lump,
    entity_angles,
    entity_origin,
    is_furniture_tik,
    mohaa_angles_to_ue,
    mohaa_point_to_ue_cm,
    parse_bsp,
    parse_bsp_entities,
    parse_bsp_models,
    parse_bsp_static_models,
)
from server import load_paths, read_indexed, scan_game, STATE  # noqa: E402

KEYS = ("dumpster", "trash", "bin", "garbage", "crate", "mg42", "barrel", "desk", "box", "boiler")


def inside(p, mn, mx, pad=1.0):
    return all(mn[i] - pad <= p[i] <= mx[i] + pad for i in range(3))


def main() -> None:
    load_paths()
    scan_game(STATE["game"])
    vp = "maps/DM/mohdm6.bsp"
    data = read_indexed(STATE["index"], vp)
    print("BSP bytes", len(data), "version", _i32(data, 4))

    models = parse_bsp_models(data)
    world = models[0] if models else None
    if world:
        mn, mx = world["mins"], world["maxs"]
        print("worldspawn AABB BSP", mn, mx)
        ue_mn = mohaa_point_to_ue_cm(*mn)
        ue_mx = mohaa_point_to_ue_cm(*mx)
        # after (-Y,-X,Z) mins/maxs swap on X/Y
        ue_min = (min(ue_mn[0], ue_mx[0]), min(ue_mn[1], ue_mx[1]), min(ue_mn[2], ue_mx[2]))
        ue_max = (max(ue_mn[0], ue_mx[0]), max(ue_mn[1], ue_mx[1]), max(ue_mn[2], ue_mx[2]))
        print("worldspawn AABB UE cm", ue_min, ue_max)
    else:
        ue_min = ue_max = (0, 0, 0)
        mn = mx = (0, 0, 0)

    print("bsp models", len(models))
    for i, rec in enumerate(models[:12]):
        print("  model", i, "mins", rec["mins"], "maxs", rec["maxs"], "nsurf", rec["num_surf"])

    ents = parse_bsp_entities(data)
    statics = parse_bsp_static_models(data)
    print("entities", len(ents), "lump25", len(statics))

    print("\n=== entity models ===")
    for ent in ents:
        mdl = (ent.get("model") or ent.get("modelname") or "")
        cls = ent.get("classname") or ""
        if not mdl and not any(k in (cls + mdl).lower() for k in KEYS):
            continue
        ox, oy, oz = entity_origin(ent)
        pitch, yaw, roll = entity_angles(ent)
        ue = mohaa_point_to_ue_cm(ox, oy, oz)
        rot = mohaa_angles_to_ue(pitch, yaw, roll)
        hit = any(k in (cls + " " + mdl).lower() for k in KEYS)
        star = mdl.startswith("*")
        if hit or star or (mdl.endswith(".tik") or mdl.endswith(".tiki")):
            print(
                "ENT",
                cls,
                mdl,
                "bsp",
                (round(ox, 2), round(oy, 2), round(oz, 2)),
                "ue",
                tuple(round(v, 1) for v in ue),
                "rot",
                tuple(round(v, 1) for v in rot),
                "inside",
                inside(ue, ue_min, ue_max),
                "furn",
                is_furniture_tik(mdl),
            )

    print("\n=== lump25 matching / all ===")
    for i, ent in enumerate(statics):
        mdl = (ent.get("model") or "").replace("\\", "/")
        ox, oy, oz = entity_origin(ent)
        pitch, yaw, roll = entity_angles(ent)
        ue = mohaa_point_to_ue_cm(ox, oy, oz)
        rot = mohaa_angles_to_ue(pitch, yaw, roll)
        low = mdl.lower()
        hit = any(k in low for k in KEYS)
        rec = {
            "i": i,
            "model": mdl,
            "bsp": [ox, oy, oz],
            "ue": [round(ue[0], 3), round(ue[1], 3), round(ue[2], 3)],
            "rot": [round(rot[0], 3), round(rot[1], 3), round(rot[2], 3)],
            "inside": inside(ue, ue_min, ue_max),
            "furn": is_furniture_tik(mdl),
            "scale": ent.get("scale"),
        }
        if hit:
            print("HIT", json.dumps(rec))
        elif i < 8 or "static" in low:
            print("SM ", json.dumps(rec))

    print("\n=== all lump25 stems ===")
    stems = {}
    for ent in statics:
        mdl = (ent.get("model") or "").replace("\\", "/")
        stems.setdefault(mdl, 0)
        stems[mdl] += 1
    for mdl, n in sorted(stems.items(), key=lambda kv: (-kv[1], kv[0])):
        print(" %3d %s furn=%s" % (n, mdl, is_furniture_tik(mdl)))

    # shader flags / sky / nodraw
    tex_ofs, tex_len = bsp_lump(data, 0)
    stride = 140 if tex_len % 140 == 0 else (76 if tex_len % 76 == 0 else 80)
    shaders = []
    for i in range(tex_len // stride):
        sh = _cstr(data, tex_ofs + i * stride, 64).lower()
        flags = _i32(data, tex_ofs + i * stride + 64) if stride >= 68 else 0
        shaders.append((sh, flags))
    print("\n=== shaders SURF_SKY / NODRAW / floor-ish ===")
    for sh, flags in shaders:
        sky = bool(flags & SURF_SKY)
        nd = bool(flags & SURF_NODRAW)
        interesting = sky or nd or any(
            tok in sh for tok in ("floor", "flr", "dirt", "ground", "rubble", "rbbl", "sky", "terrain", "street", "cobble", "mud")
        )
        if interesting:
            print("  %s flags=0x%x sky=%s nodraw=%s" % (sh, flags, sky, nd))

    mesh = parse_bsp(data, max_indices=None, include_inline=True)
    pos = mesh.positions
    nvert = len(pos) // 3
    xs = pos[0::3]
    ys = pos[1::3]
    zs = pos[2::3]
    bsp_min = (min(xs), min(ys), min(zs))
    bsp_max = (max(xs), max(ys), max(zs))
    print("\nparsed mesh verts", nvert, "groups", len(mesh.groups), "skyShaders", mesh.sky_shaders)
    print("mesh AABB BSP", tuple(round(v, 1) for v in bsp_min), tuple(round(v, 1) for v in bsp_max))
    ue_bmin = mohaa_point_to_ue_cm(*bsp_min)
    ue_bmax = mohaa_point_to_ue_cm(*bsp_max)
    print(
        "mesh AABB UE",
        tuple(round(v, 1) for v in (min(ue_bmin[0], ue_bmax[0]), min(ue_bmin[1], ue_bmax[1]), min(ue_bmin[2], ue_bmax[2]))),
        tuple(round(v, 1) for v in (max(ue_bmin[0], ue_bmax[0]), max(ue_bmin[1], ue_bmax[1]), max(ue_bmin[2], ue_bmax[2]))),
    )
    print("blender log aabb was x[-3738.880 2722.880] y[-3860.800 3901.440] z[-426.720 2854.960]  (*2.54 already)")

    # Group Z ranges for floor-like shaders
    print("\n=== group Z ranges (floor-like names or large XY) ===")
    for g in mesh.groups:
        start, count = g["start"], g["count"]
        idxs = mesh.indices[start : start + count]
        gz = [pos[i * 3 + 2] for i in idxs]
        gx = [pos[i * 3] for i in idxs]
        gy = [pos[i * 3 + 1] for i in idxs]
        name = g.get("shader") or g.get("name") or ""
        dx = max(gx) - min(gx)
        dy = max(gy) - min(gy)
        floorish = any(tok in name for tok in ("floor", "flr", "dirt", "ground", "rubble", "rbbl", "terrain", "street", "cobble"))
        if floorish or (dx > 400 and dy > 400 and (max(gz) - min(gz)) < 80):
            print(
                "  %s tris=%d xy=%.0fx%.0f z=[%.1f %.1f] bsp"
                % (name, count // 3, dx, dy, min(gz), max(gz))
            )

    # Find dumpster-like: look at metal/desk/crate statics Z vs nearby floor
    targets = []
    for ent in list(ents) + list(statics):
        mdl = (ent.get("model") or ent.get("modelname") or "").lower()
        if any(k in mdl for k in ("dumpster", "crate", "mg42", "desk", "barrel", "bin")):
            targets.append(ent)
    print("\n=== target vs nearby mesh Z ===")
    for ent in targets:
        mdl = ent.get("model") or ent.get("modelname") or ""
        ox, oy, oz = entity_origin(ent)
        ue = mohaa_point_to_ue_cm(ox, oy, oz)
        # nearby verts in BSP XY radius 80
        near = []
        for i in range(nvert):
            x, y, z = pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]
            if (x - ox) ** 2 + (y - oy) ** 2 <= 80 * 80:
                near.append(z)
        zmin = min(near) if near else None
        zmax = max(near) if near else None
        # verts with |z-oz|<8 as "floor at origin"
        at = [z for z in near if abs(z - oz) < 8] if near else []
        below = [z for z in near if z <= oz + 4] if near else []
        floor_z = max(below) if below else None
        print(
            mdl,
            "bsp",
            (round(ox, 2), round(oy, 2), round(oz, 2)),
            "ue",
            tuple(round(v, 1) for v in ue),
            "near_verts",
            len(near),
            "zspan",
            None if zmin is None else (round(zmin, 1), round(zmax, 1)),
            "floor_at_or_below",
            None if floor_z is None else round(floor_z, 2),
            "dz",
            None if floor_z is None else round(oz - floor_z, 2),
            "insideAABB",
            inside(ue, ue_min, ue_max),
        )


if __name__ == "__main__":
    main()
