"""Prove m1l2a campaign furniture formula vs umap packed floats. No Unreal load."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from formats import (  # noqa: E402
    BSP_LUMP_STATICMODELDEF,
    BSP_STATIC_MODEL_SIZE,
    bsp_lump,
    entity_angles,
    entity_origin,
    mohaa_angles_to_ue,
    mohaa_point_to_ue_cm,
    parse_bsp,
    parse_bsp_entities,
    parse_bsp_models,
    parse_bsp_static_models,
)
from server import STATE, load_paths, read_indexed, scan_game  # noqa: E402

VP = "maps/m1l2a.bsp"
UMAP = Path(r"D:\Games\test\Stalingrad\Content\MOHAA\maps\L_Diverting_the_Enemy.umap")
KEYS = ("table", "chair", "desk", "crate", "bed", "cabinet", "stool", "cot", "palm")


def old_loc_plusx(ox, oy, oz):
    x, y, z = ox * 2.54, oy * 2.54, oz * 2.54
    return (-y, x, z)


def old_rot_yaw90(pitch, yaw, roll):
    return (pitch, -(yaw + 90.0), -roll)


def _count_packed(data: bytes, value: float) -> int:
    raw = struct.pack("<f", float(value))
    return data.count(raw)


def main() -> None:
    load_paths()
    scan_game(STATE["game"])
    data = read_indexed(STATE["index"], VP)
    ident = data[:4]
    version = struct.unpack_from("<i", data, 4)[0]
    ofs, ln = bsp_lump(data, BSP_LUMP_STATICMODELDEF)
    print("BSP", VP, "ident", ident, "version", version, "lump25 ofs", ofs, "len", ln, "mod164", ln % BSP_STATIC_MODEL_SIZE)
    models = parse_bsp_models(data)
    world = models[0] if models else None
    if world:
        mn, mx = world["mins"], world["maxs"]
        a = mohaa_point_to_ue_cm(*mn)
        b = mohaa_point_to_ue_cm(*mx)
        print("world AABB BSP", [round(v, 2) for v in mn], [round(v, 2) for v in mx])
        print(
            "world AABB UE current",
            [round(min(a[i], b[i]), 1) for i in range(3)],
            [round(max(a[i], b[i]), 1) for i in range(3)],
        )
    mesh = parse_bsp(data, max_indices=None, include_inline=True)
    preview = parse_bsp(data, include_inline=True)
    print("mesh verts", len(mesh.positions) // 3, "idx", len(mesh.indices), "preview verts", len(preview.positions) // 3, "idx", len(preview.indices))
    ents = parse_bsp_entities(data)
    statics = parse_bsp_static_models(data)
    print("entities", len(ents), "static_models", len(statics))
    samples = []
    for ent in list(statics) + list(ents):
        model = (ent.get("model") or ent.get("modelname") or "").lower()
        if not any(k in model for k in KEYS) and "chair" not in model and "desk" not in model:
            continue
        ox, oy, oz = entity_origin(ent)
        pitch, yaw, roll = entity_angles(ent)
        cur = mohaa_point_to_ue_cm(ox, oy, oz)
        old = old_loc_plusx(ox, oy, oz)
        rot = mohaa_angles_to_ue(pitch, yaw, roll)
        samples.append(
            {
                "model": model,
                "classname": ent.get("classname"),
                "bsp": [round(ox, 2), round(oy, 2), round(oz, 2)],
                "bsp_angles": [round(pitch, 2), round(yaw, 2), round(roll, 2)],
                "ue_loc_current": [round(v, 3) for v in cur],
                "ue_loc_old_plusx": [round(v, 3) for v in old],
                "ue_rot_current": [round(v, 3) for v in rot],
                "ue_rot_old_yaw90": [round(v, 3) for v in old_rot_yaw90(pitch, yaw, roll)],
            }
        )
        if len(samples) >= 8:
            break
    print("SAMPLES", json.dumps(samples, indent=2))
    umap = UMAP.read_bytes() if UMAP.is_file() else b""
    print("UMAP", UMAP, "bytes", len(umap), "mtime", UMAP.stat().st_mtime if UMAP.is_file() else None)
    for s in samples[:5]:
        cur_y = s["ue_loc_current"][1]
        old_y = s["ue_loc_old_plusx"][1]
        cur_yaw = s["ue_rot_current"][1]
        old_yaw = s["ue_rot_old_yaw90"][1]
        print(
            "PACKED",
            Path(s["model"]).stem,
            "current_xy",
            _count_packed(umap, s["ue_loc_current"][0]),
            _count_packed(umap, cur_y),
            "old_plusx_y",
            _count_packed(umap, old_y),
            "current_yaw",
            _count_packed(umap, cur_yaw),
            "old_yaw90",
            _count_packed(umap, old_yaw),
            "loc",
            s["ue_loc_current"],
            "old",
            s["ue_loc_old_plusx"],
        )


if __name__ == "__main__":
    main()
