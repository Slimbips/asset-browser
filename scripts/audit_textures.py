"""Audit SKD/TIK materials via the running asset-browser server.

Usage:
    python scripts/audit_textures.py                 # all mesh categories
    python scripts/audit_textures.py vehicles
    python scripts/audit_textures.py characters heads
    python scripts/audit_textures.py weapons vehicles
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8765"
GAME = "D:/Games/test/moh_convert_game"
SKIP = {"FOUND", "NODRAW", "SKY"}


def fetch_json(url: str, timeout: int = 60) -> dict:
    return json.loads(urllib.request.urlopen(url, timeout=timeout).read())


def mesh_mats(asset: dict) -> tuple[list[dict], str | None]:
    qs = urllib.parse.urlencode(
        {
            k: v
            for k, v in (
                ("path", asset.get("skelmodel") or asset["path"]),
                ("tik", asset.get("tik_path") or ""),
            )
            if v
        }
    )
    try:
        data = fetch_json(BASE + "/api/mesh?" + qs, timeout=90)
        return data.get("materials") or [], data.get("error")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("latin1", "replace")[:240]
        return [], "HTTP %s %s" % (exc.code, body)
    except Exception as exc:
        return [], str(exc)


def select_assets(assets: list[dict], names: list[str]) -> list[dict]:
    if not names:
        return [
            a
            for a in assets
            if a.get("category") in ("weapons", "characters", "vehicles", "props", "fx")
            and a.get("skelmodel")
        ]
    out = []
    seen = set()
    for a in assets:
        if not a.get("skelmodel"):
            continue
        path = (a.get("path") or "").replace("\\", "/").lower()
        cat = a.get("category") or ""
        hit = False
        for name in names:
            n = name.lower()
            if n == "heads":
                hit = "/heads/" in path
            elif n in ("all", "*"):
                hit = cat in ("weapons", "characters", "vehicles", "props")
            else:
                hit = cat == n or n in path
            if hit:
                break
        if hit:
            key = a["path"].lower()
            if key not in seen:
                seen.add(key)
                out.append(a)
    return out


def main() -> int:
    names = [a for a in sys.argv[1:] if not a.startswith("-")]
    scan = fetch_json(BASE + "/api/scan?path=" + urllib.parse.quote(GAME, safe="/:"))
    assets = select_assets(scan.get("assets") or [], names)
    label = ",".join(names) if names else "all"
    print("audit %s: %d assets" % (label, len(assets)), flush=True)
    nerr = 0
    nmiss = 0
    shown = 0
    for i, a in enumerate(assets, 1):
        if i == 1 or i % 100 == 0 or i == len(assets):
            print("  ... %d / %d" % (i, len(assets)), flush=True)
        mats, err = mesh_mats(a)
        miss = [m for m in mats if (m.get("status") or "") not in SKIP]
        if not err and not miss:
            continue
        nmiss += 1
        if err:
            nerr += 1
        if shown < 80:
            shown += 1
            print(a["path"], "tik", a.get("tik_path") or "-", "err", err, flush=True)
            for m in miss[:10]:
                print(
                    "  ",
                    m.get("surface"),
                    "->",
                    m.get("shader"),
                    "->",
                    m.get("missing") or m.get("status"),
                )
    print("with missing/error %d / %d (http/load errors %d)" % (nmiss, len(assets), nerr), flush=True)
    return 1 if nmiss else 0


if __name__ == "__main__":
    raise SystemExit(main())
