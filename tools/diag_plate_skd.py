"""Compare SKD bind vs idle AABB for plates vs chairs."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from formats import mesh_to_json, parse_skc, parse_skd  # noqa: E402
from server import (  # noqa: E402
    STATE,
    idle_skc_path,
    load_tik,
    norm,
    read_indexed,
    resolve_skelmodel,
    scan_game,
)

STEMS = ("flowerplate", "servingplate", "dish", "simplechair", "woodchair", "banquet_table")


def _aabb(pos):
    xs = pos[0::3]
    ys = pos[1::3]
    zs = pos[2::3]
    dx, dy, dz = max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)
    thin = "XYZ"[min(range(3), key=lambda i: (dx, dy, dz)[i])]
    return {
        "x": (round(min(xs), 3), round(max(xs), 3), round(dx, 3)),
        "y": (round(min(ys), 3), round(max(ys), 3), round(dy, 3)),
        "z": (round(min(zs), 3), round(max(zs), 3), round(dz, 3)),
        "thin": thin,
        "n": len(xs),
    }


def _avg_n(nrm):
    if not nrm:
        return (0, 0, 0)
    n = len(nrm) // 3
    return (
        round(sum(nrm[0::3]) / n, 3),
        round(sum(nrm[1::3]) / n, 3),
        round(sum(nrm[2::3]) / n, 3),
    )


def main():
    scan_game(STATE["game"])
    index = STATE["index"]
    for rec in sorted(index.values(), key=lambda r: r.get("path") or ""):
        p = rec.get("path") or ""
        low = p.lower()
        if not any(s in low for s in STEMS):
            continue
        if not low.endswith((".skd", ".tik", ".skc")):
            continue
        print("VFS", p)

    for stem in STEMS:
        tik_hits = [
            rec["path"]
            for rec in index.values()
            if rec.get("path", "").lower().endswith(".tik")
            and Path(rec["path"]).stem.lower() == stem
        ]
        print("\n====", stem, "tik", tik_hits)
        if not tik_hits:
            continue
        tik_obj, tik_file = load_tik("", tik_hits[0])
        folder = (tik_obj.get("path") or "").rstrip("/") or str(Path(tik_file).parent).replace("\\", "/")
        skels = [resolve_skelmodel(index, folder, sk) for sk in (tik_obj.get("skelmodels") or [])]
        skels = [p for p in skels if p and norm(p) in index and p.lower().endswith(".skd")]
        idle = idle_skc_path(tik_obj, tik_file)
        print("  skd", skels)
        print("  scale", tik_obj.get("scale"), "idle", idle)
        if not skels:
            continue
        data = read_indexed(index, skels[0])
        bind = mesh_to_json(parse_skd(data, None, "bind", tik_obj))
        print("  BIND aabb", _aabb(bind["positions"]), "avg_n", _avg_n(bind.get("normals") or []))
        bones = bind.get("skeleton") or []
        for b in bones[:4]:
            print(
                "  BIND bone",
                b.get("name"),
                "lq",
                [round(float(x), 4) for x in (b.get("local_quat") or [])],
                "wt",
                [round(float(x), 3) for x in (b.get("world_t") or [])],
            )
        if idle and norm(idle) in index:
            skc = parse_skc(read_indexed(index, idle))
            ch = skc.get("channels") or {}
            print("  IDLE channels", len(ch), "sample", list(ch.keys())[:8])
            for key, val in list(ch.items())[:8]:
                if key.endswith(" rot") or key.endswith("_rot") or "rot" in key.lower():
                    print("   ", key, [round(float(x), 4) for x in val])
            # print all rot channels
            for key, val in ch.items():
                if "rot" in key.lower():
                    print("   ROT", key, [round(float(x), 4) for x in val])
            posed = mesh_to_json(parse_skd(data, ch, "idle", tik_obj))
            print("  IDLE aabb", _aabb(posed["positions"]), "avg_n", _avg_n(posed.get("normals") or []))
            for b in (posed.get("skeleton") or [])[:4]:
                print(
                    "  IDLE bone",
                    b.get("name"),
                    "lq",
                    [round(float(x), 4) for x in (b.get("local_quat") or [])],
                    "wt",
                    [round(float(x), 3) for x in (b.get("world_t") or [])],
                )
        else:
            print("  NO IDLE")


if __name__ == "__main__":
    main()
