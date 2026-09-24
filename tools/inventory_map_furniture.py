"""List scanned BSPs and furniture instance counts. No Unreal import."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import STATE, collect_map_furniture, load_paths, scan_game  # noqa: E402


def main() -> None:
    load_paths()
    scanned = scan_game(STATE["game"])
    assets = scanned.get("assets") or []
    maps = [a for a in assets if a.get("kind") == "map" or (a.get("ext") or "").lower() == ".bsp"]
    maps.sort(key=lambda a: (a.get("list_path") or a.get("path") or "").lower())
    print("MAP_COUNT", len(maps))
    for a in maps:
        print("MAP", a.get("path"), "|", a.get("list_path") or "", "|", a.get("name") or "")

    # Furniture counts for DM + objective + a few interiors likely to have lump-25.
    prefer = []
    for a in maps:
        p = (a.get("path") or "").replace("\\", "/").lower()
        if "/dm/" in p or "/obj/" in p:
            prefer.append(a)
        stem = Path(a.get("path") or "").stem.lower()
        if stem in ("m4l3", "m2l1", "training"):
            prefer.append(a)
    seen = set()
    print("\nFURNITURE")
    for a in prefer:
        vp = a.get("path")
        if not vp or vp in seen:
            continue
        seen.add(vp)
        jobs = collect_map_furniture(vp)
        n = sum(len(g.get("spawns") or []) for g in jobs)
        names = sorted({g.get("name") or "" for g in jobs})
        sample = None
        for g in jobs:
            nm = (g.get("name") or "").lower()
            if any(k in nm for k in ("table", "desk", "chair", "crate", "barrel", "bed", "couch")):
                sample = (g.get("name"), (g.get("spawns") or [{}])[0].get("origin"), (g.get("spawns") or [{}])[0].get("location"))
                break
        if sample is None and jobs:
            g = jobs[0]
            sample = (g.get("name"), (g.get("spawns") or [{}])[0].get("origin"), (g.get("spawns") or [{}])[0].get("location"))
        print(
            "FURN",
            vp,
            "unique=%d" % len(jobs),
            "instances=%d" % n,
            "sample",
            sample,
            "names",
            ",".join(names[:12]),
        )


if __name__ == "__main__":
    main()
