from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.ue_remote_run import matching_editor  # noqa: E402

UE_REMOTE_PY = Path(
    r"D:\epicgames\UE_5.8\Engine\Plugins\Experimental\PythonScriptPlugin\Content\Python"
)
PROJECT = Path(r"D:\Games\test\MohaaNoob\MohaaNoob.uproject")
PROOF = ROOT / "tools" / "ue_proof_map_furniture.py"
CHAR_PROOF = ROOT / "tools" / "ue_proof_noob_character.py"
SERVER = "http://127.0.0.1:8765"

MAPS = [
    ("maps/DM/mohdm3.bsp", "Remagen"),
    ("maps/DM/mohdm7.bsp", "Algiers"),
    ("maps/DM/mohdm4.bsp", "The Crossroads"),
    ("maps/DM/mohdm1.bsp", "Southern France"),
    ("maps/DM/mohdm2.bsp", "Destroyed Village"),
    ("maps/DM/mohdm5.bsp", "Snowy Park"),
    ("maps/DM/mohdm6.bsp", "Stalingrad"),
    ("maps/obj/obj_team1.bsp", "The Hunt"),
    ("maps/obj/obj_team2.bsp", "V2 Rocket Facility"),
    ("maps/obj/obj_team3.bsp", "Omaha Beach"),
    ("maps/obj/obj_team4.bsp", "The Bridge"),
    ("maps/m1l2a.bsp", "Diverting the Enemy"),
]


def slug(name: str) -> str:
    import re
    s = re.sub(r"[^A-Za-z0-9]+", "_", name or "asset").strip("_")
    return s[:80] or "asset"


def level_name(name: str) -> str:
    return "L_" + slug(name)


def run_ue(script: Path) -> str:
    sys.path.insert(0, str(UE_REMOTE_PY))
    import remote_execution as re

    session = re.RemoteExecution()
    session.start()
    try:
        node = None
        for _ in range(20):
            time.sleep(0.25)
            node = matching_editor(session.remote_nodes or [], PROJECT)
            if node:
                break
        if not node:
            return "NO EDITOR"
        session.open_command_connection(node["node_id"])
        data = session.run_command(script.read_text(encoding="utf-8"), unattended=True, exec_mode=re.MODE_EXEC_FILE)
        chunks = []
        for item in data.get("output") or []:
            chunks.append(str(item.get("output") if isinstance(item, dict) else item))
        if data.get("result"):
            chunks.append(str(data.get("result")))
        log = "\n".join(chunks)
        if not data.get("success"):
            log += "\nSUCCESS False"
        return log
    finally:
        session.stop()


def export_map(vp: str, name: str) -> dict:
    qs = urllib.parse.urlencode(
        {
            "path": vp,
            "kind": "unreal",
            "category": "maps",
            "name": name,
            "project": str(PROJECT),
            "textures": "1",
            "furniture": "1",
        }
    )
    url = SERVER + "/api/export?" + qs
    print("CONVERT", name, vp, flush=True)
    print("LEVEL", "/Game/MOHAA/maps/" + level_name(name), flush=True)
    print("PROJECT", PROJECT, flush=True)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=3600) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    return data


def export_character() -> dict:
    qs = urllib.parse.urlencode(
        {
            "path": "models/human/allied_army_soldier/usarmy.skd",
            "tik": "models/human/1st-ranger_engineer.tik",
            "kind": "unreal-skel",
            "category": "characters",
            "name": "1St-Ranger Engineer",
            "project": str(PROJECT),
        }
    )
    url = SERVER + "/api/export?" + qs
    print("CONVERT character 1St Ranger Engineer", flush=True)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=3600) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def summarize_map(name: str, result: dict, proof: str) -> dict:
    furn = result.get("furniture") or []
    n_inst = sum(int(x.get("instances") or 0) for x in furn)
    ue = result.get("unreal") or {}
    rec = {
        "name": name,
        "level": "/Game/MOHAA/maps/" + level_name(name),
        "ok": bool(result.get("ok")),
        "imported": ue.get("imported"),
        "via": ue.get("via"),
        "unique_props": len(furn),
        "prop_count": n_inst,
        "town_side": None,
        "floor_ok": None,
        "proof": proof[-4000:],
    }
    for line in proof.splitlines():
        if line.startswith("PROP_TOWN_SIDE"):
            rec["town_side"] = "True" in line
        if "NPROP" in line and line.startswith("NSUN"):
            parts = line.split()
            try:
                rec["prop_count"] = int(parts[parts.index("NPROP") + 1])
            except Exception:
                pass
        if "near_floor" in line and rec["floor_ok"] is None:
            rec["floor_ok"] = "True" in line or "'near_floor': True" in line or '"near_floor": true' in line.lower()
    print(
        "DONE",
        name,
        "level",
        rec["level"],
        "props",
        rec["prop_count"],
        "town_side",
        rec["town_side"],
        "imported",
        rec["imported"],
        flush=True,
    )
    print("OPEN", str(PROJECT), "then", rec["level"], flush=True)
    return rec


def main() -> None:
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    do_char = "--char" in sys.argv or not only
    maps = MAPS
    if only:
        maps = [m for m in MAPS if m[1].lower() in {x.lower() for x in only} or m[0] in only]
        do_char = "--char" in sys.argv
    out = {"project": str(PROJECT), "maps": [], "character": None}
    prev = ROOT / "export_noob_summary.json"
    if prev.is_file() and only:
        try:
            old = json.loads(prev.read_text(encoding="utf-8"))
            out["maps"] = list(old.get("maps") or [])
            out["character"] = old.get("character")
        except Exception:
            pass
    for vp, name in maps:
        try:
            result = export_map(vp, name)
            proof = run_ue(PROOF) if result.get("ok") else "EXPORT FAIL"
            rec = summarize_map(name, result, proof)
            rec["error"] = result.get("error")
            out["maps"].append(rec)
            dest = ROOT / ("export_%s_noob.json" % slug(name).lower())
            dest.write_text(json.dumps(result, indent=2)[:200000], encoding="utf-8")
        except Exception as visc:
            print("FAIL", name, visc, flush=True)
            out["maps"].append({"name": name, "error": str(visc), "ok": False})
    if do_char:
        try:
            result = export_character()
            proof = run_ue(CHAR_PROOF) if CHAR_PROOF.is_file() else ""
            ue = result.get("unreal") or {}
            out["character"] = {
                "ok": result.get("ok"),
                "imported": ue.get("imported"),
                "character_ready": ue.get("character_ready"),
                "log": (ue.get("log") or "")[-4000:],
                "proof": proof[-4000:],
                "anims": result.get("anims"),
                "skel_debug": result.get("skel_debug"),
            }
            print("CHAR READY", ue.get("character_ready"), flush=True)
            print(proof, flush=True)
            (ROOT / "export_1st_ranger_engineer_noob.json").write_text(
                json.dumps(result, indent=2)[:200000], encoding="utf-8"
            )
        except Exception as visc:
            print("CHAR FAIL", visc, flush=True)
            out["character"] = {"error": str(visc), "ok": False}
    (ROOT / "export_noob_summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("SUMMARY", ROOT / "export_noob_summary.json", flush=True)


if __name__ == "__main__":
    main()
