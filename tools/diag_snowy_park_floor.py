"""Nearest BSP floor Z under current-formula Snowy Park samples."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from formats import mohaa_point_to_ue_cm, parse_bsp  # noqa: E402
from server import STATE, load_paths, read_indexed, scan_game  # noqa: E402

VP = "maps/DM/mohdm5.bsp"
SAMPLES = (
    ("tree_winter_smallpine_0", 1591.0, -4220.0, 87.0),
    ("rock_winter_medium_0", 1188.62, -5467.05, 120.0),
    ("lightpost_globe", None, None, None),  # filled from lump below
)


def main() -> None:
    load_paths()
    scan_game(STATE["game"])
    data = read_indexed(STATE["index"], VP)
    mesh = parse_bsp(data, max_indices=None, include_inline=True)
    pos = mesh.positions
    nvert = len(pos) // 3
    from formats import entity_origin, is_furniture_tik, parse_bsp_static_models  # noqa: E402

    globe = None
    for ent in parse_bsp_static_models(data):
        mdl = (ent.get("model") or "").replace("\\", "/").lower()
        if "lightpost_globe" in mdl:
            ox, oy, oz = entity_origin(ent)
            globe = ("lightpost_globe_winter_0", ox, oy, oz)
            break
    samples = [
        ("tree_winter_smallpine_0", 1591.0, -4220.0, 87.0),
        ("rock_winter_medium_0", 1188.62, -5467.05, 120.0),
    ]
    if globe:
        samples.append(globe)

    verts = [(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]) for i in range(nvert)]
    print("verts", nvert)
    for name, ox, oy, oz in samples:
        ue = mohaa_point_to_ue_cm(ox, oy, oz)
        near = []
        below = []
        closest = None
        for x, y, z in verts:
            dx, dy = x - ox, y - oy
            d2 = dx * dx + dy * dy
            if closest is None or d2 < closest[0]:
                closest = (d2, x, y, z)
            if d2 > 256 * 256:
                continue
            near.append((d2, x, y, z))
            if z <= oz + 48:
                below.append((d2, z))
        below.sort()
        near.sort()
        floor_z = max(z for _d, z in below) if below else None
        closest = near[0] if near else None
        print(
            name,
            "bsp",
            [round(ox, 2), round(oy, 2), round(oz, 2)],
            "ue",
            [round(v, 2) for v in ue],
            "near",
            len(near),
            "floor_bsp",
            None if floor_z is None else round(floor_z, 2),
            "floor_ue",
            None if floor_z is None else round(floor_z * 2.54, 2),
            "dz_cm",
            None if floor_z is None else round(ue[2] - floor_z * 2.54, 1),
            "closest_xy_bsp",
            None if closest is None else [round(closest[1], 1), round(closest[2], 1), round(closest[3], 1)],
            "closest_d_bsp",
            None if closest is None else round(closest[0] ** 0.5, 1),
        )


if __name__ == "__main__":
    main()
