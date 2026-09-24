"""Clamp pack uasset custom versions so UE 5.8.2 will load them."""
from __future__ import annotations

import struct
from pathlib import Path

PACK = Path(r"D:\Games\test\Stalingrad\Content\MOH\Characters")

# Clamp pack custom versions to UE 5.8.2 HeadCode.
CLAMP = {
    bytes.fromhex("fb0c82a75943a720142c548c50cf2396"): 43,  # Dev-ControlRig 47->43
    bytes.fromhex("9b9549dce74dc05388ea5691395d7c5e"): 25,  # Dev-RigVM 27->25
    bytes.fromhex("686308e7584c236b701b3984915e2616"): 20,  # FortniteRelease 22->20
    bytes.fromhex("86181d60844f64acded316aad6c7ea0d"): 268,  # FortniteMain
    bytes.fromhex("81d57d69ab414fe6ec514aaa28b6b7be"): 123,  # UE5-Main
}


def patch_file(path: Path) -> int:
    data = bytearray(path.read_bytes())
    changed = 0
    for guid, max_ver in CLAMP.items():
        start = 0
        while True:
            i = data.find(guid, start)
            if i < 0 or i + 20 > len(data):
                break
            cur = struct.unpack_from("<i", data, i + 16)[0]
            if cur > max_ver:
                data[i + 16 : i + 20] = struct.pack("<i", max_ver)
                changed += 1
            start = i + 16
    if changed:
        path.write_bytes(data)
    return changed


def main() -> None:
    print("clamp map", len(CLAMP), "guids")
    files = list(PACK.rglob("*.uasset"))
    touched = fields = fail = 0
    for p in files:
        try:
            n = patch_file(p)
            if n:
                touched += 1
                fields += n
        except Exception as exc:
            fail += 1
            if fail <= 8:
                print("FAIL", p, exc)
    print("files", len(files), "patched", touched, "fields", fields, "fail", fail)


if __name__ == "__main__":
    main()
