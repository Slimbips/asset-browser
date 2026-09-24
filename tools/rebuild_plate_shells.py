"""Rebuild down-facing dish OBJs/FBXs. Vertex Z unchanged; front flipped to +Z."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from export_ue import BLENDER, BLENDER_SCRIPT, prop_shell_faces_neg_z, run_blender  # noqa: E402

PROPS = ROOT / "export" / "Remagen" / "props"
STEMS = ("flowerplate", "servingplate", "dish")


def _parse_obj(path: Path) -> dict:
    pos: list[float] = []
    nrm: list[float] = []
    uvs: list[float] = []
    faces: list[tuple[int, int, int]] = []
    header: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("v "):
            x, y, z = map(float, line.split()[1:4])
            pos.extend((x, y, z))
        elif line.startswith("vn "):
            x, y, z = map(float, line.split()[1:4])
            nrm.extend((x, y, z))
        elif line.startswith("vt "):
            u, v = map(float, line.split()[1:3])
            uvs.extend((u, v))
        elif line.startswith("f "):
            parts = line.split()[1:]
            ids = [int(p.split("/")[0]) - 1 for p in parts[:3]]
            faces.append((ids[0], ids[1], ids[2]))
        else:
            header.append(line)
    return {"pos": pos, "nrm": nrm, "uvs": uvs, "faces": faces, "header": header}


def _write_obj(path: Path, data: dict, *, flip: bool) -> None:
    pos, nrm, uvs, faces, header = data["pos"], data["nrm"], data["uvs"], data["faces"], data["header"]
    lines = []
    for h in header:
        if h.startswith("v ") or h.startswith("vn ") or h.startswith("vt ") or h.startswith("f "):
            continue
        lines.append(h + "\n")
    if not any(l.startswith("mtllib") for l in lines):
        lines.insert(0, "mtllib %s\n" % path.with_suffix(".mtl").name)
    nverts = len(pos) // 3
    for i in range(nverts):
        lines.append("v %.6f %.6f %.6f\n" % (pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]))
    for i in range(len(uvs) // 2):
        lines.append("vt %.6f %.6f\n" % (uvs[i * 2], uvs[i * 2 + 1]))
    for i in range(len(nrm) // 3):
        nx, ny, nz = nrm[i * 3], nrm[i * 3 + 1], nrm[i * 3 + 2]
        if flip:
            nx, ny, nz = -nx, -ny, -nz
        lines.append("vn %.6f %.6f %.6f\n" % (nx, ny, nz))
    lines.append("usemtl %s\ng %s\n" % (path.stem, path.stem))
    for a, b, c in faces:
        if flip:
            b, c = c, b
        a, b, c = a + 1, b + 1, c + 1
        lines.append("f %d/%d/%d %d/%d/%d %d/%d/%d\n" % (a, a, a, b, b, b, c, c, c))
    path.write_text("".join(lines), encoding="utf-8")


def _avg_nz(nrm: list[float], flip: bool) -> float:
    if not nrm:
        return 0.0
    s = 0.0
    n = 0
    for i in range(2, len(nrm), 3):
        s += -nrm[i] if flip else nrm[i]
        n += 1
    return s / max(n, 1)


def main() -> None:
    if not BLENDER.is_file():
        raise SystemExit("Blender missing: %s" % BLENDER)
    print("BLENDER", BLENDER)
    print("SCRIPT", BLENDER_SCRIPT)
    for stem in STEMS:
        obj = PROPS / (stem + ".obj")
        if not obj.is_file():
            print("MISSING", obj)
            continue
        data = _parse_obj(obj)
        need = prop_shell_faces_neg_z(data["pos"], data["nrm"])
        zs = data["pos"][2::3]
        print(
            "OBJ",
            stem,
            "need_flip",
            need,
            "z",
            round(min(zs), 3),
            round(max(zs), 3),
            "avg_nz_before",
            round(_avg_nz(data["nrm"], False), 3),
        )
        if need:
            _write_obj(obj, data, flip=True)
            data2 = _parse_obj(obj)
            zs2 = data2["pos"][2::3]
            print(
                "  after_flip z",
                round(min(zs2), 3),
                round(max(zs2), 3),
                "avg_nz",
                round(_avg_nz(data2["nrm"], False), 3),
            )
        fbx = PROPS / (stem + ".fbx")
        log = run_blender(obj, fbx, None, map_mode=True)
        print("FBX", fbx, "size", fbx.stat().st_size if fbx.is_file() else 0)
        for line in log.splitlines():
            if "Mesh size" in line or "map mode" in line or "Wrote " in line:
                print(" ", line)


if __name__ == "__main__":
    main()
