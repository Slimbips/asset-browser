"""Dump tree_oak / sandbag tik scale, surfaces, nodraw, sprite groups."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from formats import surface_nodraw_reason  # noqa: E402
from server import STATE, load_paths, load_tik, scan_game  # noqa: E402


def dump_tik(vp: str) -> None:
    tik, tik_file = load_tik("", vp)
    print("\n====", vp, "file", tik_file)
    print("scale", tik.get("scale"), "skelmodels", tik.get("skelmodels"))
    print("surfaces", tik.get("surfaces"))
    print("init_surface_cmds", (tik.get("init_surface_cmds") or [])[:20])
    print("idle_surface_cmds", (tik.get("idle_surface_cmds") or [])[:20])
    names = []
    for spec in tik.get("surfaces") or []:
        names.append(spec.get("name") or "")
    extra = ["tree4sprite", "tree1sprite", "tree2asprite", "tallyuccasprite", "sprite"]
    for n in list(dict.fromkeys(names + extra)):
        if not n:
            continue
        print(" nodraw", n, "->", surface_nodraw_reason(n, tik))


def main() -> None:
    load_paths()
    scan_game(STATE["game"])
    for vp in (
        "models/static/tree_oak.tik",
        "models/static/tree_commontree.tik",
        "models/static/tree_juniper.tik",
        "models/static/sandbag_link_main.tik",
        "models/static/sandbag_link_topcap.tik",
        "models/static/bush_regularbush.tik",
        "models/furniture/table.tik",
    ):
        try:
            dump_tik(vp)
        except Exception as exc:
            print("FAIL", vp, exc)
            # try with extra slash variants
            for alt in (vp.replace("/", "//"), "models/" + vp):
                try:
                    dump_tik(alt)
                    break
                except Exception:
                    pass


if __name__ == "__main__":
    main()
