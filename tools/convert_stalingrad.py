"""Re-convert L_Stalingrad with current generic loc/rot/scale. Uses disk code, not the stale HTTP server."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from export_ue import export_asset  # noqa: E402
from server import (
    STATE,
    collect_map_furniture,
    load_mesh_payload,
    load_paths,
    remember_project,
    scan_game,
    tex_png,
)

VP = "maps/DM/mohdm6.bsp"
PROJECT = r"D:\Games\test\Stalingrad\Stalingrad.uproject"


def main() -> None:
    load_paths()
    scan_game(STATE["game"])
    remember_project(PROJECT)
    payload = load_mesh_payload(VP, "", full_geometry=True, include_inline=True)
    print("MAP verts", payload.get("vertexCount") or len(payload.get("positions") or []) // 3, "kind", payload.get("kind"))
    furniture_jobs = []
    for item in collect_map_furniture(VP):
        try:
            prop = load_mesh_payload(item["skd"], item["tik"], full_geometry=True, use_idle=True)
            furniture_jobs.append({**item, "payload": prop})
        except Exception as exc:
            print("[furniture] skip", item.get("tik"), exc)
    for item in furniture_jobs:
        name = (item.get("name") or "").lower()
        if any(k in name for k in ("desk", "mg42", "crate", "dumpster", "chair", "barrel")):
            for sp in item.get("spawns") or []:
                print("SPAWN", item.get("name"), sp)
    result = export_asset(
        payload,
        "Stalingrad",
        "maps",
        tex_png,
        into_unreal=True,
        project=PROJECT,
        with_textures=True,
        furniture_jobs=furniture_jobs,
    )
    out = ROOT / "export_stalingrad_result.json"
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
            )
        ):
            print("UE", line)
    print("WROTE", out)


if __name__ == "__main__":
    main()
