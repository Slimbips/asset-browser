"""Convert a MOHAA BSP + furniture into the open Unreal project.

Uses disk code (same pipeline as convert_stalingrad.py), not the HTTP server.

  python tools/convert_map.py maps/DM/mohdm1.bsp Southern_France
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from export_ue import export_asset  # noqa: E402
from server import (  # noqa: E402
    STATE,
    collect_map_furniture,
    load_mesh_payload,
    load_paths,
    remember_project,
    scan_game,
    tex_png,
)

PROJECT = r"D:\Games\test\Stalingrad\Stalingrad.uproject"


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: python tools/convert_map.py <vfs-bsp> <unreal-name>")
        sys.exit(2)
    vp = sys.argv[1].replace("\\", "/")
    name = sys.argv[2]
    load_paths()
    scan_game(STATE["game"])
    remember_project(PROJECT)
    payload = load_mesh_payload(vp, "", full_geometry=True, include_inline=True)
    print("MAP", name, vp, "verts", payload.get("vertexCount") or len(payload.get("positions") or []) // 3, "kind", payload.get("kind"))
    furniture_jobs = []
    for item in collect_map_furniture(vp):
        try:
            prop = load_mesh_payload(item["skd"], item["tik"], full_geometry=True, use_idle=True)
            furniture_jobs.append({**item, "payload": prop})
        except Exception as exc:
            print("[furniture] skip", item.get("tik"), exc)
    n_inst = sum(len(j.get("spawns") or []) for j in furniture_jobs)
    print("FURNITURE unique", len(furniture_jobs), "instances", n_inst)
    for item in furniture_jobs:
        nm = (item.get("name") or "").lower()
        if any(k in nm for k in ("desk", "table", "chair", "bed", "armchair", "crate", "piano", "sandbag", "cabinet")):
            for sp in (item.get("spawns") or [])[:1]:
                print("SPAWN", item.get("name"), sp)
    result = export_asset(
        payload,
        name,
        "maps",
        tex_png,
        into_unreal=True,
        project=PROJECT,
        with_textures=True,
        furniture_jobs=furniture_jobs,
    )
    out = ROOT / ("export_%s_result.json" % name.lower())
    out.write_text(json.dumps(result, indent=2)[:200000], encoding="utf-8")
    ue = result.get("unreal") or {}
    print("UNREAL imported", ue.get("imported"), "via", ue.get("via"), "exit", ue.get("exit"))
    log = str(ue.get("log") or "")
    for line in log.splitlines():
        if any(
            tok in line
            for tok in (
                "LEVEL",
                "SPAWNED",
                "FURNITURE",
                "MAP actor",
                "ACTOR bounds",
                "HID sky",
                "REMOVED extra",
                "DONE",
                "FAIL",
                "IMPORTED",
                "inside_map_aabb",
            )
        ):
            print("UE", line)
    print("WROTE", out)


if __name__ == "__main__":
    main()
