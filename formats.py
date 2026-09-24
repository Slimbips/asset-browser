"""MOHAA SKD / BSP / TIKI / image helpers."""
from __future__ import annotations

import io
import math
import posixpath
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def _i32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<i", buf, off)[0]


def _f32(buf: bytes, off: int) -> float:
    return struct.unpack_from("<f", buf, off)[0]


def _cstr(buf: bytes, off: int, n: int) -> str:
    return buf[off : off + n].split(b"\x00", 1)[0].decode("latin1", "replace")


@dataclass
class Mesh:
    positions: list[float] = field(default_factory=list)
    normals: list[float] = field(default_factory=list)
    uvs: list[float] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)
    groups: list[dict] = field(default_factory=list)
    bones: int = 0
    surfaces: int = 0
    bone_list: list[dict] = field(default_factory=list)
    skin_log: list[dict] = field(default_factory=list)
    pose: str = ""
    visibility_note: str = ""
    influences: list[list[list[float]]] = field(default_factory=list)
    sky_shaders: list[str] = field(default_factory=list)


TIKI_SURF_NODRAW = 1 << 2
IDLE_SURFACE_FRAMES = {"entry", "enter", "first"}


def parse_tiki(text: bytes, *, filename: str = "", loader=None) -> dict:
    raw = text.decode("latin1", "replace")
    if loader:
        raw = _expand_tiki_includes(raw, filename, loader)
    meta = {
        "skelmodels": [],
        "all_skelmodels": [],
        "skel_surfaces": {},
        "shaders": [],
        "surfaces": [],
        "anims": [],
        "classname": "",
        "display_name": "",
        "weapontype": "",
        "scale": 1.0,
        "path": "",
        "description": "",
        "cache": [],
        "init_surface_cmds": [],
        "idle_surface_cmds": [],
    }
    setup = _tiki_named_block(raw, "setup")
    # Head-pack TIKs are only `path` + `case headskin` — no setup {} wrapper.
    if not setup and re.search(r"\b(skelmodel|case)\b", raw, re.I):
        setup = raw
    parsed_setup = _parse_setup_active(setup, meta["path"])
    if parsed_setup["path"]:
        meta["path"] = parsed_setup["path"]
    meta["skelmodels"] = parsed_setup["skelmodels"]
    meta["all_skelmodels"] = parsed_setup["all_skelmodels"]
    meta["skel_surfaces"] = parsed_setup["skel_surfaces"]
    meta["surfaces"] = parsed_setup["surfaces"]
    meta["shaders"] = [s["shader"] for s in meta["surfaces"] if s.get("shader")]
    for m in re.finditer(r"^\s*scale\s+([0-9.]+)", raw, re.I | re.M):
        try:
            meta["scale"] = float(m.group(1))
        except ValueError:
            pass
    for m in re.finditer(r"^\s*classname\s+(\S+)", raw, re.I | re.M):
        meta["classname"] = m.group(1).strip().strip('"')
        break
    for m in re.finditer(r"^\s*weapontype\s+(\S+)", raw, re.I | re.M):
        meta["weapontype"] = m.group(1).strip().strip('"')
        break
    for m in re.finditer(r'^\s*name\s+"([^"]+)"', raw, re.I | re.M):
        meta["display_name"] = m.group(1)
        break
    for m in re.finditer(r"^\s*cache\s+(\S+)", raw, re.I | re.M):
        meta["cache"].append(m.group(1).strip().strip('"'))
    meta["init_surface_cmds"] = _parse_surface_flag_cmds(
        "".join(_tiki_all_named_blocks(raw, "init")), allow_bare=True
    )
    meta["anims"] = []
    idle_cmds_body = ""
    for anims_body in _tiki_all_named_blocks(raw, "animations"):
        path_marks = []
        for pm in re.finditer(r"^\s*\$?path\s+(\S+)", anims_body, re.I | re.M):
            if pm.group(1).lower().endswith(".skc"):
                continue
            path_marks.append((pm.start(), _norm_tiki_path(pm.group(1))))
        for m in re.finditer(r"^\s*(\w+)\s+(\S+\.skc)", anims_body, re.M | re.I):
            anim_folder = ""
            for start, folder in path_marks:
                if start < m.start():
                    anim_folder = folder
                else:
                    break
            rec = {"alias": m.group(1), "file": m.group(2), "flags": [], "folder": anim_folder}
            rest = anims_body[m.end() :]
            nl = rest.find("\n")
            same = rest[: nl if nl >= 0 else len(rest)].split("//", 1)[0]
            tokens = _tokenize(same)
            i = 0
            while i < len(tokens) and tokens[i] != "{":
                rec["flags"].append(tokens[i])
                i += 1
            brace_here = "{" in same
            brace_next = False
            if not brace_here and nl >= 0:
                brace_next = rest[nl + 1 :].lstrip().startswith("{")
            if brace_here or brace_next:
                rec["commands"], _ = _read_brace_block(rest, rest.find("{"))
            meta["anims"].append(rec)
        if not idle_cmds_body:
            idle_cmds_body = _tiki_anim_commands(anims_body, "idle")
    meta["idle_surface_cmds"] = _parse_surface_flag_cmds(
        idle_cmds_body, allow_bare=False, frames=IDLE_SURFACE_FRAMES
    )
    return meta


# OpenMOHAA uses sv_mapname, else "utils". Preview follows that default so
# `includes m1l1 { ... }` (and other map packs) stay out of idle — same as
# not attaching weapon cache/clips.
TIKI_PREVIEW_MAP = "utils"


def _includes_section_applies(names: list[str]) -> bool:
    return any(n == TIKI_PREVIEW_MAP for n in names)


def _expand_tiki_includes(raw: str, filename: str, loader, depth: int = 0) -> str:
    """In-line MOHAA `$include path` the same way the TIKI script lexer does."""
    if depth > 12:
        return raw
    out: list[str] = []
    skip_depth = 0
    pending_skip = False
    for line in raw.splitlines(True):
        code = line.split("//", 1)[0]
        if skip_depth:
            skip_depth += code.count("{") - code.count("}")
            if skip_depth <= 0:
                skip_depth = 0
            continue
        tokens = _tokenize(code.strip())
        if pending_skip:
            if not tokens:
                continue
            if tokens[0] == "{":
                skip_depth = code.count("{") - code.count("}")
                pending_skip = False
                if skip_depth <= 0:
                    skip_depth = 0
                continue
            pending_skip = False
        if tokens and tokens[0].lower() == "includes":
            names: list[str] = []
            brace = False
            for tok in tokens[1:]:
                if tok == "{":
                    brace = True
                    break
                if tok != "}":
                    names.append(tok.lower().strip('"'))
            if names and not _includes_section_applies(names):
                if brace:
                    skip_depth = code.count("{") - code.count("}")
                    if skip_depth <= 0:
                        skip_depth = 0
                else:
                    pending_skip = True
                continue
        if len(tokens) < 2 or tokens[0].lower() != "$include":
            out.append(line)
            continue
        inc = tokens[1].strip('"').replace("\\", "/")
        if "/" not in inc and filename:
            inc = posixpath.join(posixpath.dirname(filename.replace("\\", "/")), inc)
        data = loader(inc)
        if data is None:
            out.append("// missing $include %s\n" % inc)
            continue
        nested = data.decode("latin1", "replace") if isinstance(data, (bytes, bytearray)) else str(data)
        expanded = _expand_tiki_includes(nested, inc, loader, depth + 1)
        out.append(expanded)
        if expanded and not expanded.endswith("\n"):
            out.append("\n")
    return "".join(out)


def _skip_ws_and_comments(raw: str, i: int) -> int:
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if raw.startswith("//", i):
            nl = raw.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if raw.startswith("/*", i):
            end = raw.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        break
    return i


def _tiki_named_block(raw: str, name: str) -> str:
    for body, _end in _iter_tiki_named_blocks(raw, name):
        return body
    return ""


def _tiki_all_named_blocks(raw: str, name: str) -> list[str]:
    return [body for body, _end in _iter_tiki_named_blocks(raw, name)]


def _iter_tiki_named_blocks(raw: str, name: str):
    """Yield (body, end) for `name { ... }`, allowing // comments before `{`."""
    pos = 0
    pat = re.compile(rf"\b{name}\b", re.I)
    while pos < len(raw):
        m = pat.search(raw, pos)
        if not m:
            return
        i = _skip_ws_and_comments(raw, m.end())
        if i < len(raw) and raw[i] == "{":
            body, end = _read_brace_block(raw, i)
            yield body, end
            pos = end
        else:
            pos = m.end()


def _norm_tiki_path(path: str) -> str:
    path = (path or "").strip().strip('"').replace("\\", "/")
    if path and not path.endswith("/"):
        path += "/"
    return path


def _join_skel_path(folder: str, sk: str) -> str:
    sk = (sk or "").strip().strip('"').replace("\\", "/")
    if not sk:
        return ""
    if "/" in sk:
        return sk
    return posixpath.join((folder or "").rstrip("/"), sk) if folder else sk


def _parse_setup_active(setup_body: str, init_path: str) -> dict:
    """Collect skelmodels/surfaces that are visible in the default TIKI setup.

    Unconditional setup lines always apply. Sibling `case` blocks are alternatives:
    only the first branch at each level is taken (first head skin + first head mesh,
    first weapon case which is often 'none').
    """
    cleaned = []
    for line in setup_body.splitlines():
        cleaned.append(line.split("//", 1)[0])
    text = "\n".join(cleaned).replace("{", " { ").replace("}", " } ")
    tokens = _tokenize(text)
    models: list[str] = []
    all_models: list[str] = []
    surfaces: list[dict] = []
    skel_surfaces: dict[str, list[dict]] = {}
    path = _norm_tiki_path(init_path)
    body_path = ""

    def parse_surface_at(i: int, folder: str) -> tuple[int, dict]:
        if i + 1 >= len(tokens):
            return i + 1, {"name": "", "shader": "", "flags": ""}
        surf = {"name": tokens[i + 1], "shader": "", "flags": ""}
        j = i + 2
        while j < len(tokens):
            key = tokens[j].lower()
            if key in ("path", "skelmodel", "surface", "case", "scale", "ischaracter", "includes") or tokens[j] in "{}":
                break
            if key == "shader" and j + 1 < len(tokens):
                sh = tokens[j + 1]
                if "." in sh and not sh.startswith("$") and not sh.startswith("*"):
                    sh = folder + sh
                surf["shader"] = sh
                j += 2
                continue
            if key == "flags" and j + 1 < len(tokens):
                surf["flags"] = tokens[j + 1]
                j += 2
                continue
            j += 1
        return j, surf

    def walk(i: int, cur_path: str, active: bool, collect: bool, inherited: list[dict]) -> tuple[int, str]:
        nonlocal path, body_path
        saw_case = False
        local_path = cur_path
        block_models: list[str] = []
        block_surfaces: list[dict] = list(inherited)

        def commit_block() -> None:
            for m in block_models:
                key = m.replace("\\", "/").lower()
                if key and block_surfaces:
                    skel_surfaces.setdefault(key, list(block_surfaces))

        while i < len(tokens):
            tok = tokens[i]
            low = tok.lower()
            if tok == "}":
                commit_block()
                return i + 1, local_path
            if low in ("path", "$path") and i + 1 < len(tokens):
                local_path = _norm_tiki_path(tokens[i + 1])
                i += 2
                continue
            if low == "skelmodel" and i + 1 < len(tokens):
                joined = _join_skel_path(local_path, tokens[i + 1])
                if collect:
                    all_models.append(joined)
                    block_models.append(joined)
                if active:
                    models.append(joined)
                    if not body_path:
                        body_path = local_path
                i += 2
                continue
            if low == "surface":
                i, surf = parse_surface_at(i, local_path)
                if collect:
                    block_surfaces.append(surf)
                if active:
                    surfaces.append(surf)
                continue
            if low == "case":
                i += 1
                while i < len(tokens) and tokens[i] != "{":
                    i += 1
                if i < len(tokens) and tokens[i] == "{":
                    take = active and not saw_case
                    if active:
                        saw_case = True
                    i, _ = walk(i + 1, local_path, take, collect, block_surfaces)
                continue
            if low == "includes":
                while i < len(tokens) and tokens[i] != "{":
                    i += 1
                if i < len(tokens) and tokens[i] == "{":
                    i, _ = walk(i + 1, local_path, False, False, block_surfaces)
                continue
            if tok == "{":
                i, _ = walk(i + 1, local_path, active, collect, block_surfaces)
                continue
            i += 1
        commit_block()
        return i, local_path

    walk(0, path, True, True, [])

    def uniq_paths(items: list[str]) -> list[str]:
        seen = set()
        out = []
        for m in items:
            key = m.replace("\\", "/").lower()
            if not m or key in seen:
                continue
            seen.add(key)
            out.append(m)
        return out

    return {
        "skelmodels": uniq_paths(models),
        "all_skelmodels": uniq_paths(all_models),
        "skel_surfaces": skel_surfaces,
        "surfaces": surfaces,
        "path": body_path or path,
    }


def _tiki_anim_commands(anims_body: str, alias: str) -> str:
    m = re.search(rf"^\s*{re.escape(alias)}\s+\S+\.skc\b", anims_body, re.I | re.M)
    if not m:
        return ""
    rest = anims_body[m.end() :].lstrip()
    if not rest.startswith("{"):
        return ""
    body, _ = _read_brace_block(rest, 0)
    return body


def _parse_tiki_surfaces(setup_body: str, tik_path: str) -> list[dict]:
    """Parse TIKI setup `surface <name> shader <shader>` lines (order matters)."""
    surfaces = []
    for line in setup_body.splitlines():
        code = line.split("//", 1)[0].strip()
        if not code:
            continue
        tokens = _tokenize(code)
        if not tokens or tokens[0].lower() != "surface" or len(tokens) < 2:
            continue
        surf = {"name": tokens[1], "shader": "", "flags": ""}
        j = 2
        while j < len(tokens):
            key = tokens[j].lower()
            if key == "shader" and j + 1 < len(tokens):
                sh = tokens[j + 1]
                if "." in sh and not sh.startswith("$") and not sh.startswith("*"):
                    sh = tik_path + sh
                surf["shader"] = sh
                j += 2
            elif key == "flags" and j + 1 < len(tokens):
                surf["flags"] = tokens[j + 1]
                j += 2
            else:
                j += 1
        surfaces.append(surf)
    return surfaces


def _parse_surface_flag_cmds(text: str, allow_bare: bool, frames: set[str] | None = None) -> list[dict]:
    """Parse `surface name +nodraw` commands from init or animation blocks."""
    cmds = []
    for line in text.splitlines():
        tokens = _tokenize(line.split("//", 1)[0].strip())
        if not tokens:
            continue
        i = 0
        frame = ""
        head = tokens[0].lower()
        if head in ("entry", "first", "last") or head.isdigit():
            frame = head
            i = 1
        if i >= len(tokens) or tokens[i].lower() != "surface" or i + 1 >= len(tokens):
            continue
        if frame:
            if frames is not None and frame not in frames:
                continue
        elif not allow_bare:
            continue
        name = tokens[i + 1]
        for tok in tokens[i + 2 :]:
            action, mask = _parse_surface_flag_token(tok)
            if not mask:
                continue
            cmds.append({"name": name, "token": tok, "action": action, "mask": mask, "frame": frame or "init"})
    return cmds


def _parse_surface_flag_token(token: str) -> tuple[str, int]:
    t = token.strip()
    action = "add"
    if t.startswith("+"):
        action = "add"
        t = t[1:]
    elif t.startswith("-"):
        action = "clear"
        t = t[1:]
    if t.lower() != "nodraw":
        return action, 0
    return action, TIKI_SURF_NODRAW


def match_tiki_surface(spec_name: str, surf_name: str) -> bool:
    sl = (spec_name or "").lower()
    low = (surf_name or "").lower()
    if sl == "all":
        return True
    if "*" in spec_name:
        return low.startswith(sl.split("*", 1)[0])
    return sl == low


def surface_nodraw_reason(surf_name: str, tik: dict | None) -> str | None:
    """Idle visibility: setup flags, then init, then idle entry/first. Cache/attach models are not loaded."""
    low = (surf_name or "").lower()
    # Camera-facing LOD cards (deformVertexes autoSprite2). Static meshes cannot
    # autosprite, so the authored quad shows as an opaque slab after +90 Z.
    if "sprite" in low:
        return "autosprite lod billboard"
    if not tik:
        return None
    flags = 0
    reason = None
    for spec in tik.get("surfaces") or []:
        if not match_tiki_surface(spec.get("name") or "", surf_name):
            continue
        sh = (spec.get("shader") or "").lower()
        if "sprite" in sh:
            return "autosprite lod billboard"
        flag_tok = (spec.get("flags") or "").lower()
        if "nodraw" in flag_tok.split():
            flags |= TIKI_SURF_NODRAW
            reason = "setup flags nodraw (%s)" % spec.get("name")
    for cmd in (tik.get("init_surface_cmds") or []) + (tik.get("idle_surface_cmds") or []):
        if not match_tiki_surface(cmd.get("name") or "", surf_name):
            continue
        if cmd.get("action") == "clear":
            flags &= ~int(cmd.get("mask") or 0)
            if not (flags & TIKI_SURF_NODRAW):
                reason = None
        else:
            flags |= int(cmd.get("mask") or 0)
            if flags & TIKI_SURF_NODRAW:
                reason = "%s %s %s" % (cmd.get("frame") or "init", cmd.get("name"), cmd.get("token"))
    return reason if flags & TIKI_SURF_NODRAW else None


def _tokenize(line: str) -> list[str]:
    out = []
    buf = []
    in_q = False
    for ch in line:
        if ch == '"':
            in_q = not in_q
            continue
        if ch.isspace() and not in_q:
            if buf:
                out.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


SKIP_MAPS = ("$lightmap", "$deluxemap", "$texture")
BUILTIN_MAPS = {
    "$whiteimage": "builtin:white",
    "*white": "builtin:white",
    "$identitynormalmap": "builtin:white",
}

# Q3 / MOHAA surface flags (dshader_t.surfaceFlags)
SURF_SKY = 0x4
SURF_NODRAW = 0x80
SKY_FACE_SIDES = ("ft", "bk", "up", "dn", "rt", "lf")
# After blender +90 Z, Unreal cubemap faces sample these Q3 sides.
DDS_FACE_FROM_Q3 = ("bk", "ft", "rt", "lf", "up", "dn")


def sky_face_candidates(env_base: str, side: str) -> list[str]:
    """skyParms env/name → env/name_ft, env/nameft, plus any original extension."""
    raw = (env_base or "").replace("\\", "/").strip().strip('"')
    if not raw or raw in ("-", "null", "none"):
        return []
    stem, ext = posixpath.splitext(raw)
    base = stem or raw
    side = (side or "").lower()
    names = [base + "_" + side, base + side]
    if ext:
        names = [n + ext for n in names] + names
    return names


def is_null_sky_box(token: str) -> bool:
    t = (token or "").strip().strip('"').lower()
    return t in ("", "-", "null", "none")


def _cube_face_uv(sc: float, tc: float, size: int) -> tuple[int, int]:
    u = int(max(0, min(size - 1, (sc * 0.5 + 0.5) * (size - 1) + 0.5)))
    v = int(max(0, min(size - 1, (1.0 - (tc * 0.5 + 0.5)) * (size - 1) + 0.5)))
    return u, v


def sample_q3_cubemap(qx: float, qy: float, qz: float, faces: dict, size: int) -> tuple[int, int, int]:
    """Sample Q3 Z-up sky cubemap (rt=+X, ft=+Y, up=+Z) from a unit direction."""
    ax, ay, az = abs(qx), abs(qy), abs(qz)
    if ax >= ay and ax >= az:
        if qx >= 0.0:
            side, sc, tc = "rt", -qy / ax, qz / ax
        else:
            side, sc, tc = "lf", qy / ax, qz / ax
    elif ay >= ax and ay >= az:
        if qy >= 0.0:
            side, sc, tc = "ft", qx / ay, qz / ay
        else:
            side, sc, tc = "bk", -qx / ay, qz / ay
    else:
        if qz >= 0.0:
            side, sc, tc = "up", qx / az, qy / az
        else:
            side, sc, tc = "dn", qx / az, -qy / az
    px = faces.get(side)
    if px is None:
        return (0, 0, 0)
    u, v = _cube_face_uv(sc, tc, size)
    try:
        return px[u, v]
    except Exception:
        return (0, 0, 0)


def cubemap_to_equirect(face_images: dict[str, Image.Image], width: int | None = None) -> Image.Image:
    """Q3 cubemap → Unreal lat-long (accounts for BSP mesh +90° Z)."""
    first = next((face_images[s] for s in SKY_FACE_SIDES if s in face_images), None)
    if first is None:
        raise ValueError("no cubemap faces")
    size = min(first.size)
    faces = {}
    blank = (0, 0, 0)
    for side in SKY_FACE_SIDES:
        img = face_images.get(side)
        if img is None:
            continue
        rgb = img.convert("RGB").resize((size, size), Image.BICUBIC)
        faces[side] = rgb.load()
    w = int(width or min(1024, max(512, size * 4)))
    h = w // 2
    out = Image.new("RGB", (w, h))
    pix = out.load()
    for y in range(h):
        lat = (0.5 - (y + 0.5) / h) * math.pi
        cl, sl = math.cos(lat), math.sin(lat)
        for x in range(w):
            lon = ((x + 0.5) / w) * 2.0 * math.pi - math.pi
            # Equirect in Unreal: lon around Z, Z up. Undo map +90 Z → Q3.
            ux = cl * math.cos(lon)
            uy = cl * math.sin(lon)
            uz = sl
            qx, qy, qz = uy, -ux, uz
            pix[x, y] = sample_q3_cubemap(qx, qy, qz, faces, size) if faces else blank
    return out


def write_dds_cubemap(face_images: dict[str, Image.Image], dest) -> str:
    """Uncompressed BGRA DDS cubemap. Face order is DirectX +X,-X,+Y,-Y,+Z,-Z."""
    dest = Path(dest)
    first = next((face_images[s] for s in DDS_FACE_FROM_Q3 if s in face_images), None)
    if first is None:
        raise ValueError("no cubemap faces for DDS")
    size = min(first.size)
    rgb_faces = {}
    for side in SKY_FACE_SIDES:
        img = face_images.get(side)
        if img is None:
            continue
        rgb_faces[side] = img.convert("RGB").resize((size, size), Image.BICUBIC)
    flags = 0x1 | 0x2 | 0x4 | 0x8 | 0x1000  # caps, height, width, pitch, pixelformat
    caps = 0x1000 | 0x8  # texture | complex
    caps2 = 0x200 | 0x400 | 0x800 | 0x1000 | 0x2000 | 0x4000 | 0x8000
    pf_flags = 0x41  # RGB | alphapixels
    header = struct.pack(
        "<4sI 6I 11I 8I 5I",
        b"DDS ",
        124,
        flags,
        size,
        size,
        size * 4,
        0,
        1,
        *([0] * 11),
        32,
        pf_flags,
        0,
        32,
        0x00FF0000,
        0x0000FF00,
        0x000000FF,
        0xFF000000,
        caps,
        caps2,
        0,
        0,
        0,
    )
    chunks = [header]
    for side in DDS_FACE_FROM_Q3:
        img = rgb_faces.get(side) or Image.new("RGB", (size, size), (80, 120, 180))
        # DDS is typically origin bottom-left; flip so Unreal +Y is up.
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
        raw = img.tobytes()
        bgra = bytearray(size * size * 4)
        for i in range(size * size):
            r, g, b = raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2]
            o = i * 4
            bgra[o] = b
            bgra[o + 1] = g
            bgra[o + 2] = r
            bgra[o + 3] = 255
        chunks.append(bytes(bgra))
    dest.write_bytes(b"".join(chunks))
    return str(dest)


def parse_shader_file(text: str, filename: str) -> dict[str, dict]:
    """Parse a Quake 3 / MOHAA .shader file into name -> definition."""
    shaders: dict[str, dict] = {}
    s = _strip_c_comments(text)
    i = 0
    n = len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break
        if s.startswith("//", i):
            nl = s.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        name_start = i
        while i < n and not s[i].isspace() and s[i] != "{":
            i += 1
        name = s[name_start:i].strip().strip('"')
        while i < n and s[i].isspace():
            i += 1
        if i >= n or s[i] != "{":
            continue
        body, i = _read_brace_block(s, i)
        if not name or name.startswith("{"):
            continue
        shaders[name] = _parse_shader_body(name, body, filename)
    return shaders


def _strip_c_comments(text: str) -> str:
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("//", i):
            nl = text.find("\n", i)
            if nl < 0:
                break
            out.append("\n")
            i = nl + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                break
            out.append(" ")
            i = end + 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _read_brace_block(s: str, i: int) -> tuple[str, int]:
    assert s[i] == "{"
    i += 1
    depth = 1
    start = i
    while i < len(s) and depth:
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start:i], i + 1
        i += 1
    return s[start:], len(s)


def _parse_shader_body(name: str, body: str, filename: str) -> dict:
    maps: list[str] = []
    env_maps: list[str] = []
    notes: list[str] = []
    qer = ""
    cull_none = False
    blend = False
    alpha_test = False
    env = False
    surfaceparm_sky = False
    sky_parms = None
    tokens = _tokenize(body.replace("{", " { ").replace("}", " } "))
    i = 0
    depth = 0
    stage_maps: list[tuple[str, bool]] = []
    stage_env = False

    def flush_stage() -> None:
        # tcGen environment stages are reflections, not albedo (e.g. poster4 on wood).
        nonlocal stage_maps, stage_env
        dest = env_maps if stage_env else maps
        for path, is_clamp in stage_maps:
            dest.append(path)
            if is_clamp:
                notes.append("clampmap")
        stage_maps = []
        stage_env = False

    while i < len(tokens):
        tok = tokens[i]
        low = tok.lower()
        if tok == "{":
            depth += 1
            if depth == 1:
                stage_maps = []
                stage_env = False
            i += 1
            continue
        if tok == "}":
            if depth == 1:
                flush_stage()
            depth = max(0, depth - 1)
            i += 1
            continue
        if low == "qer_editorimage" and i + 1 < len(tokens):
            qer = tokens[i + 1]
            i += 2
            continue
        if low in ("map", "clampmap", "clampmapx", "clampmapy") and i + 1 < len(tokens):
            path = tokens[i + 1]
            is_clamp = low.startswith("clamp")
            if depth >= 1:
                stage_maps.append((path, is_clamp))
            else:
                maps.append(path)
                if is_clamp:
                    notes.append(low)
            i += 2
            continue
        if low in ("animmap", "animmaponce", "animmapphase") and i + 1 < len(tokens):
            j = i + 1
            if j < len(tokens):
                try:
                    float(tokens[j])
                    j += 1
                except ValueError:
                    pass
            if low == "animmapphase" and j < len(tokens):
                j += 1
            if j < len(tokens) and tokens[j] not in "{}":
                path = tokens[j]
                if depth >= 1:
                    stage_maps.append((path, False))
                else:
                    maps.append(path)
                notes.append("animMap")
            i = j + 1
            continue
        if low == "cull" and i + 1 < len(tokens) and tokens[i + 1].lower() in ("none", "disable", "twosided"):
            cull_none = True
            notes.append("cull none")
            i += 2
            continue
        if low == "blendfunc":
            args = []
            i += 1
            while i < len(tokens) and tokens[i] not in "{}" and len(args) < 2:
                args.append(tokens[i])
                i += 1
            blend = True
            notes.append("blendFunc " + " ".join(args))
            continue
        if low == "alphafunc":
            alpha_test = True
            notes.append("alphaFunc " + (tokens[i + 1] if i + 1 < len(tokens) else ""))
            i += 2
            continue
        if low == "deformvertexes" and i + 1 < len(tokens):
            kind = tokens[i + 1].lower()
            notes.append("deformVertexes " + tokens[i + 1])
            if kind in ("autosprite", "autosprite2"):
                notes.append("autosprite")
            i += 2
            continue
        if low == "tcgen" and i + 1 < len(tokens):
            notes.append("tcGen " + tokens[i + 1])
            if tokens[i + 1].lower().startswith("environment"):
                env = True
                if depth >= 1:
                    stage_env = True
            i += 2
            continue
        if low == "rgbgen" and i + 1 < len(tokens):
            notes.append("rgbGen " + tokens[i + 1])
            i += 2
            continue
        if low == "skyparms":
            farbox = tokens[i + 1] if i + 1 < len(tokens) else "-"
            cloud = tokens[i + 2] if i + 2 < len(tokens) else "-"
            nearbox = tokens[i + 3] if i + 3 < len(tokens) else "-"
            sky_parms = {
                "farbox": farbox,
                "cloudheight": cloud,
                "nearbox": nearbox,
            }
            notes.append("skyParms " + farbox)
            i += 4
            continue
        if low == "surfaceparm" and i + 1 < len(tokens):
            parm = tokens[i + 1].lower()
            notes.append("surfaceparm " + parm)
            if parm == "sky":
                surfaceparm_sky = True
            i += 2
            continue
        i += 1
    if stage_maps:
        flush_stage()
    is_sky = bool(sky_parms) or surfaceparm_sky
    return {
        "name": name,
        "file": filename,
        "maps": maps,
        "env_maps": env_maps,
        "qer_editorimage": qer,
        "cull_none": cull_none,
        "blend": blend,
        "alpha_test": alpha_test,
        "autosprite": any("autosprite" in (n or "").lower() for n in notes),
        "env": env,
        "is_sky": is_sky,
        "sky_parms": sky_parms,
        "notes": notes,
        "body": body.strip(),
    }


BONE_TYPES = {
    0: "ROTATION",
    1: "POSROT",
    2: "IKSHOULDER",
    3: "IKELBOW",
    4: "IKWRIST",
    5: "HOSEROT",
    6: "AVROT",
    7: "ZERO",
    9: "WORLD",
    10: "HOSEROTBOTH",
    11: "HOSEROTPARENT",
}


def quat_to_mat(q: tuple[float, float, float, float]) -> list[list[float]]:
    """MOHAA QuatToMat: rows are the bone axes."""
    x, y, z, w = q[0], q[1], q[2], q[3]
    x2, y2, z2 = x + x, y + y, z + z
    xx, xy, xz = x * x2, x * y2, x * z2
    yy, yz, zz = y * y2, y * z2, z * z2
    wx, wy, wz = w * x2, w * y2, w * z2
    return [
        [1.0 - (yy + zz), xy - wz, xz + wy],
        [xy + wz, 1.0 - (xx + zz), yz - wx],
        [xz - wy, yz + wx, 1.0 - (xx + yy)],
    ]


def _mul_skel(local_r: list[list[float]], local_t: tuple[float, float, float], parent_r, parent_t):
    """SkelMat4::Multiply(local, parent): world = local composed onto parent."""
    rw = [[0.0, 0.0, 0.0] for _ in range(3)]
    for i in range(3):
        for j in range(3):
            rw[i][j] = (
                local_r[i][0] * parent_r[0][j]
                + local_r[i][1] * parent_r[1][j]
                + local_r[i][2] * parent_r[2][j]
            )
    tw = [0.0, 0.0, 0.0]
    for j in range(3):
        tw[j] = (
            local_t[0] * parent_r[0][j]
            + local_t[1] * parent_r[1][j]
            + local_t[2] * parent_r[2][j]
            + parent_t[j]
        )
    return rw, tw


def invert_skel(R, T):
    """Inverse of a MOHAA (R, T) where R rows are bone axes."""
    rt = [
        [R[0][0], R[1][0], R[2][0]],
        [R[0][1], R[1][1], R[2][1]],
        [R[0][2], R[1][2], R[2][2]],
    ]
    inv_t = (
        -(R[0][0] * T[0] + R[0][1] * T[1] + R[0][2] * T[2]),
        -(R[1][0] * T[0] + R[1][1] * T[1] + R[1][2] * T[2]),
        -(R[2][0] * T[0] + R[2][1] * T[1] + R[2][2] * T[2]),
    )
    return rt, inv_t


def local_from_world(R, T, parent_R, parent_T):
    """local = world composed onto inverse(parent). Matches viewer world = local * parent."""
    if parent_R is None:
        return _copy_r(R), tuple(T)
    inv_r, inv_t = invert_skel(parent_R, parent_T)
    return _mul_skel(R, T, inv_r, inv_t)


def _ident_r():
    return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def parse_skc(data: bytes) -> dict:
    """Parse SKC/SKAN channels. Frame 0 stays in `channels` for the viewer."""
    if data[:4] != b"SKAN":
        raise ValueError("Not an SKC/SKAN file")
    frame_time = float(struct.unpack_from("<f", data, 16)[0] or 0.0)
    nchan, ofs_names, nframes = struct.unpack_from("<3i", data, 36)
    names = []
    for i in range(nchan):
        names.append(_cstr(data, ofs_names + i * 32, 32))
    frames: list[dict] = []
    packed = 48 + 48 * max(nframes, 0)
    for f in range(max(int(nframes), 1)):
        ofs_values = _i32(data, 48 + 48 * f + 44) if nframes else packed
        if ofs_values <= 0 or ofs_values + nchan * 16 > len(data):
            ofs_values = packed + f * nchan * 16
        chans = {}
        for i, name in enumerate(names):
            vals = struct.unpack_from("<4f", data, ofs_values + i * 16)
            chans[name.lower()] = vals
        frames.append(chans)
    if frame_time <= 1e-6:
        frame_time = 0.05
    channels = frames[0] if frames else {}
    return {
        "names": names,
        "channels": channels,
        "frames": frames,
        "numFrames": nframes,
        "numChannels": nchan,
        "frameTime": frame_time,
    }


def _chan(channels: dict, name: str, suffix: str, default):
    key = (name + " " + suffix).lower()
    if key in channels:
        return channels[key]
    return default


_BONE_CHANNELS = {
    "ROTATION": 1,
    "POSROT": 2,
    "IKWRIST": 2,
}
_BONE_REFS = {
    "IKELBOW": 1,
    "IKWRIST": 1,
    "HOSEROT": 1,
    "HOSEROTBOTH": 1,
    "HOSEROTPARENT": 1,
    "AVROT": 2,
}


def _read_cstrings(buf: bytes, off: int, count: int) -> list[str]:
    out = []
    for _ in range(count):
        if off >= len(buf):
            break
        end = buf.find(b"\x00", off)
        if end < 0:
            break
        out.append(buf[off:end].decode("latin1", "replace"))
        off = end + 1
    return out


def parse_skd_bones(data: bytes) -> list[dict]:
    num_bones = _u32(data, 76)
    ofs_bones = _u32(data, 80)
    bones = []
    off = ofs_bones
    for i in range(num_bones):
        name = _cstr(data, off, 32)
        parent = _cstr(data, off + 32, 32)
        btype = _i32(data, off + 64)
        ofs_base, ofs_chan, ofs_bn, ofs_end = struct.unpack_from("<4i", data, off + 68)
        kind = BONE_TYPES.get(btype, str(btype))
        floats: list[float] = []
        if ofs_base and ofs_end - ofs_base >= 4:
            n = min((ofs_end - ofs_base) // 4, 8)
            floats = list(struct.unpack_from("<%df" % n, data, off + ofs_base))
        chans = _read_cstrings(data, off + ofs_chan, _BONE_CHANNELS.get(kind, 0)) if ofs_chan else []
        refs = _read_cstrings(data, off + ofs_bn, _BONE_REFS.get(kind, 0)) if ofs_bn else []
        offset = (0.0, 0.0, 0.0)
        length = 0.0
        weight = 0.5
        bend_ratio = 1.0
        bend_max = math.pi
        spin_ratio = 1.0
        if kind == "ROTATION" and len(floats) >= 3:
            offset = (floats[0], floats[1], floats[2])
        elif kind == "IKSHOULDER" and len(floats) >= 7:
            offset = (floats[4], floats[5], floats[6])
        elif kind in ("IKELBOW", "IKWRIST") and len(floats) >= 3:
            length = math.sqrt(floats[0] ** 2 + floats[1] ** 2 + floats[2] ** 2)
        elif kind == "AVROT" and len(floats) >= 4:
            weight = floats[0]
            offset = (floats[1], floats[2], floats[3])
        elif kind in ("HOSEROT", "HOSEROTBOTH", "HOSEROTPARENT") and len(floats) >= 6:
            bend_ratio, bend_max, spin_ratio = floats[0], floats[1], floats[2]
            offset = (floats[3], floats[4], floats[5])
        bones.append(
            {
                "index": i,
                "name": name,
                "parent": parent,
                "parent_index": -1,
                "type": kind,
                "type_id": btype,
                "base": offset,
                "offset": offset,
                "length": length,
                "weight": weight,
                "bend_ratio": bend_ratio,
                "bend_max": bend_max,
                "spin_ratio": spin_ratio,
                "refs": refs,
                "channels": chans,
            }
        )
        off += ofs_end
    by_name = {b["name"].lower(): b["index"] for b in bones}
    for b in bones:
        if b["parent"] and b["parent"].lower() not in ("worldbone", ""):
            b["parent_index"] = by_name.get(b["parent"].lower(), -1)
        b["ref_index"] = [by_name[r.lower()] for r in b["refs"] if r.lower() in by_name]
        if b["type"] == "IKELBOW" and b["ref_index"]:
            bones[b["ref_index"][0]]["upper_length"] = b["length"]
        if b["type"] == "IKWRIST" and b["ref_index"]:
            sh = bones[b["ref_index"][0]]
            sh["lower_length"] = b["length"]
            sh["wrist_index"] = b["index"]
    return bones


def _vadd(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vmul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _vlen(a):
    return math.sqrt(_dot(a, a))


def _norm(a):
    l = _vlen(a)
    if l < 1e-12:
        return (0.0, 0.0, 0.0), 0.0
    return _vmul(a, 1.0 / l), l


def _copy_r(R):
    return [list(row) for row in R]


def mat_to_quat(R: list[list[float]]) -> tuple[float, float, float, float]:
    trace = R[0][0] + R[1][1] + R[2][2]
    if trace > 0.0:
        s = math.sqrt(trace + 1.0)
        w = s * 0.5
        s = 0.5 / s
        return (
            (R[2][1] - R[1][2]) * s,
            (R[0][2] - R[2][0]) * s,
            (R[1][0] - R[0][1]) * s,
            w,
        )
    i = 0
    if R[1][1] > R[0][0]:
        i = 1
    if R[2][2] > R[i][i]:
        i = 2
    nxt = (1, 2, 0)
    j, k = nxt[i], nxt[j := nxt[i]]
    s = math.sqrt((R[i][i] - (R[j][j] + R[k][k])) + 1.0)
    q = [0.0, 0.0, 0.0, 1.0]
    q[i] = s * 0.5
    s = 0.5 / s if s else 0.0
    q[3] = (R[k][j] - R[j][k]) * s
    q[j] = (R[j][i] + R[i][j]) * s
    q[k] = (R[k][i] + R[i][k]) * s
    return (q[0], q[1], q[2], q[3])


def _slerp(q0, q1, t):
    q0 = tuple(q0)
    q1 = list(q1)
    dot = q0[0] * q1[0] + q0[1] * q1[1] + q0[2] * q1[2] + q0[3] * q1[3]
    if dot < 0:
        q1 = [-x for x in q1]
        dot = -dot
    if dot > 0.9995:
        out = [a + t * (b - a) for a, b in zip(q0, q1)]
        n = math.sqrt(sum(x * x for x in out)) or 1.0
        return tuple(x / n for x in out)
    theta = math.acos(min(1.0, max(-1.0, dot)))
    s = math.sin(theta) or 1.0
    a = math.sin((1.0 - t) * theta) / s
    b = math.sin(t * theta) / s
    return tuple(a * x + b * y for x, y in zip(q0, q1))


def bind_pose_matrices(bones: list[dict], channels: dict | None) -> list[tuple]:
    """World-space (R, T). POSROT/ROTATION from SKC; legs use MOHAA IK (thigh/calf/foot)."""
    channels = channels or {}
    out: list[tuple | None] = [None] * len(bones)
    ik: dict[int, dict] = {}

    def _eval_ik(si: int):
        if si in ik:
            return ik[si]
        sh = bones[si]
        wi = sh.get("wrist_index")
        if wi is None:
            ik[si] = {}
            return ik[si]
        wr = bones[wi]
        if sh["parent_index"] >= 0:
            pr, pt = world(sh["parent_index"])
        else:
            pr, pt = _ident_r(), (0.0, 0.0, 0.0)
        off = sh["offset"]
        base_t = (
            pt[0] + off[0] * pr[0][0] + off[1] * pr[1][0] + off[2] * pr[2][0],
            pt[1] + off[0] * pr[0][1] + off[1] * pr[1][1] + off[2] * pr[2][1],
            pt[2] + off[0] * pr[0][2] + off[1] * pr[1][2] + off[2] * pr[2][2],
        )
        # InvertAxis 0 and 2 on the copied parent rotation
        base_r = _copy_r(pr)
        for a in (0, 2):
            base_r[a][0] = -base_r[a][0]
            base_r[a][1] = -base_r[a][1]
            base_r[a][2] = -base_r[a][2]
        wrist_q = _chan(channels, wr["name"], "rot", (0.0, 0.0, 0.0, 1.0))
        wrist_p = _chan(channels, wr["name"], "pos", (0.0, 0.0, 0.0, 0.0))[:3]
        wrist_p = (float(wrist_p[0]), float(wrist_p[1]), float(wrist_p[2]))
        target_r = quat_to_mat(wrist_q)
        R = _copy_r(base_r)
        T = list(base_t)
        aim, dist = _norm(_vsub(wrist_p, base_t))
        R[0] = list(aim)
        y = _cross(tuple(base_r[2]), aim)
        y2 = _cross(tuple(target_r[2]), aim)
        y = _vadd(y, y2)
        y, ylen = _norm(y)
        if ylen == 0.0:
            y = (0.0, 1.0, 0.0)
        R[1] = list(y)
        R[2] = list(_cross(tuple(R[0]), tuple(R[1])))
        upper = float(sh.get("upper_length") or 0.0)
        lower = float(sh.get("lower_length") or 0.0)
        max_reach = upper + lower - 0.001
        if dist > max_reach > 0:
            dist = max_reach
            wrist_p = _vadd(tuple(T), _vmul(tuple(R[0]), max_reach))
        denom = dist * upper * 2.0
        max_len = 1.0
        if denom:
            max_len = (dist * dist + upper * upper - lower * lower) / denom
            if max_len > 1.0:
                max_len = 1.0
        elbow_denom = upper * lower * 2.0
        cos_elbow = 0.0
        if elbow_denom:
            cos_elbow = -(
                (lower * lower + upper * upper - dist * dist) / elbow_denom
            )
        length = -math.sqrt(max(0.0, 1.0 - max_len * max_len))
        for i in range(3):
            c, s = R[0][i], R[1][i]
            R[0][i] = c * max_len - s * length
            R[1][i] = s * max_len + c * length
        ik[si] = {
            "R": R,
            "T": tuple(T),
            "cos_elbow": cos_elbow,
            "upper": upper,
            "wrist_R": target_r,
            "wrist_T": wrist_p,
        }
        return ik[si]

    def _invert_rt(R, T):
        rt = [
            [R[0][0], R[1][0], R[2][0]],
            [R[0][1], R[1][1], R[2][1]],
            [R[0][2], R[1][2], R[2][2]],
        ]
        # -dot(axis_i, T): same as skelBone_HoseRot parent inverse translation.
        inv_t = (
            -(R[0][0] * T[0] + R[0][1] * T[1] + R[0][2] * T[2]),
            -(R[1][0] * T[0] + R[1][1] * T[1] + R[1][2] * T[2]),
            -(R[2][0] * T[0] + R[2][1] * T[1] + R[2][2] * T[2]),
        )
        return rt, inv_t

    def _invert_axes(R, axes=(0, 2)):
        out = _copy_r(R)
        for a in axes:
            out[a][0] = -out[a][0]
            out[a][1] = -out[a][1]
            out[a][2] = -out[a][2]
        return out

    def _hose(parent_r, parent_t, target_r, target_t, b, invert_parent=False, invert_target=False, negate_xz=False):
        # skelBone_HoseRot / HoseRotBoth / HoseRotParent
        if invert_parent:
            parent_r = _invert_axes(parent_r)
        if invert_target:
            target_r = _invert_axes(target_r)
        offset = b["offset"]
        if negate_xz:
            offset = (-offset[0], offset[1], -offset[2])
        aim = tuple(parent_r[0])
        target_aim = tuple(target_r[0])
        rotaxis = _cross(target_aim, aim)
        slen = _dot(rotaxis, rotaxis)
        if slen == 0.0:
            rotaxis = (1.0, 0.0, 0.0)
        elif abs(slen - 1.0) > 1e-8:
            rotaxis, _ = _norm(rotaxis)
        dp = _dot(aim, target_aim)
        if dp < 1.0:
            angle = math.acos(max(-1.0, min(1.0, dp))) if dp > -0.999 else (math.pi * 2.0)
        else:
            angle = 0.0
        v_scale = angle * b["bend_ratio"]
        if v_scale > b["bend_max"]:
            v_scale = b["bend_max"]
        inv_r, inv_t = _invert_rt(parent_r, parent_t)
        rotaxis = (
            rotaxis[0] * inv_r[0][0] + rotaxis[1] * inv_r[1][0] + rotaxis[2] * inv_r[2][0],
            rotaxis[0] * inv_r[0][1] + rotaxis[1] * inv_r[1][1] + rotaxis[2] * inv_r[2][1],
            rotaxis[0] * inv_r[0][2] + rotaxis[1] * inv_r[1][2] + rotaxis[2] * inv_r[2][2],
        )
        half = v_scale * 0.5
        c = math.cos(half)
        l = math.sqrt(max(0.0, 1.0 - c * c))
        q = (rotaxis[0] * l, rotaxis[1] * l, rotaxis[2] * l, c)
        if b["spin_ratio"] < 1.0:
            loc_r, _loc_t = _mul_skel(target_r, target_t, inv_r, inv_t)
            tq = mat_to_quat(loc_r)
            q = _slerp(tq, q, b["spin_ratio"])
        local_r = quat_to_mat(q)
        return _mul_skel(local_r, offset, parent_r, parent_t)

    def world(i: int):
        if out[i] is not None:
            return out[i]
        b = bones[i]
        btype = b["type"]
        if btype == "ZERO":
            if b["parent_index"] >= 0:
                out[i] = world(b["parent_index"])
            else:
                out[i] = (_ident_r(), (0.0, 0.0, 0.0))
            return out[i]
        if btype == "IKSHOULDER":
            solved = _eval_ik(i)
            if not solved:
                out[i] = (_ident_r(), (0.0, 0.0, 0.0))
            else:
                out[i] = (solved["R"], solved["T"])
            return out[i]
        if btype == "IKELBOW" and b["ref_index"]:
            solved = _eval_ik(b["ref_index"][0])
            if not solved:
                out[i] = (_ident_r(), (0.0, 0.0, 0.0))
                return out[i]
            R = _copy_r(solved["R"])
            T = list(solved["T"])
            u = solved["upper"]
            T[0] += R[0][0] * u
            T[1] += R[0][1] * u
            T[2] += R[0][2] * u
            ce = solved["cos_elbow"]
            fl = math.sqrt(max(0.0, 1.0 - ce * ce))
            for ax in range(3):
                c, s = R[0][ax], R[1][ax]
                R[0][ax] = c * ce - s * fl
                R[1][ax] = s * ce + c * fl
            out[i] = (R, tuple(T))
            return out[i]
        if btype == "IKWRIST" and b["ref_index"]:
            solved = _eval_ik(b["ref_index"][0])
            if not solved:
                out[i] = (_ident_r(), (0.0, 0.0, 0.0))
            else:
                # Wrist SKC pos/rot is model-space, not parent-relative.
                out[i] = (solved["wrist_R"], solved["wrist_T"])
            return out[i]
        if btype in ("HOSEROT", "HOSEROTBOTH", "HOSEROTPARENT") and b["ref_index"]:
            if b["parent_index"] >= 0:
                pr, pt = world(b["parent_index"])
            else:
                pr, pt = _ident_r(), (0.0, 0.0, 0.0)
            tr, tt = world(b["ref_index"][0])
            tgt = bones[b["ref_index"][0]]
            # Hip helpers: pelvis X is opposite the IK thigh → HoseRotParent.
            # Ankle helpers: foot/calf X both point down the shin, but the
            # pant offsets were authored up the shin → HoseRotBoth.
            use_parent = btype == "HOSEROTPARENT" or tgt["type"] == "IKSHOULDER"
            use_both = btype == "HOSEROTBOTH" or tgt["type"] == "IKELBOW"
            out[i] = _hose(
                pr,
                pt,
                tr,
                tt,
                b,
                invert_parent=use_parent or use_both,
                invert_target=use_both,
                negate_xz=use_parent or use_both,
            )
            return out[i]
        if btype == "AVROT" and len(b["ref_index"]) >= 2:
            r1, t1 = world(b["ref_index"][0])
            r2, t2 = world(b["ref_index"][1])
            q = _slerp(mat_to_quat(r1), mat_to_quat(r2), b["weight"])
            local_r = quat_to_mat(q)
            if b["parent_index"] >= 0:
                pr, pt = world(b["parent_index"])
                wr, wt = _mul_skel(_ident_r(), b["offset"], pr, pt)
            else:
                wr, wt = _ident_r(), b["offset"]
            out[i] = (local_r, wt)
            return out[i]
        rot = _chan(channels, b["name"], "rot", (0.0, 0.0, 0.0, 1.0))
        if btype == "ROTATION":
            pos = b["offset"]
        else:
            pos = _chan(channels, b["name"], "pos", (0.0, 0.0, 0.0, 0.0))[:3]
        local_r = quat_to_mat(rot)
        local_t = (float(pos[0]), float(pos[1]), float(pos[2]))
        if b["parent_index"] >= 0:
            pr, pt = world(b["parent_index"])
            out[i] = _mul_skel(local_r, local_t, pr, pt)
        else:
            out[i] = (local_r, local_t)
        return out[i]

    for i in range(len(bones)):
        world(i)
    return out  # type: ignore


def _skin_point(ox, oy, oz, R, T, w):
    return (
        (ox * R[0][0] + oy * R[1][0] + oz * R[2][0] + T[0]) * w,
        (ox * R[0][1] + oy * R[1][1] + oz * R[2][1] + T[1]) * w,
        (ox * R[0][2] + oy * R[1][2] + oz * R[2][2] + T[2]) * w,
    )


def _skin_normal(nx, ny, nz, R):
    return (
        nx * R[0][0] + ny * R[1][0] + nz * R[2][0],
        nx * R[0][1] + ny * R[1][1] + nz * R[2][1],
        nx * R[0][2] + ny * R[1][2] + nz * R[2][2],
    )


def parse_skd(
    data: bytes,
    channels: dict | None = None,
    pose_label: str = "",
    tik: dict | None = None,
    reveal_if_all_hidden: bool = False,
) -> Mesh:
    if data[:4] not in (b"SKMD", b"SKL "):
        raise ValueError("Not an SKD/SKB file")
    version = _i32(data, 4)
    num_surfs = _u32(data, 72)
    num_bones = _u32(data, 76)
    ofs_surfs = _u32(data, 84)
    bones = parse_skd_bones(data) if num_bones else []
    pose = bind_pose_matrices(bones, channels)
    ident = _ident_r()
    zero_t = (0.0, 0.0, 0.0)
    mesh = Mesh(bones=num_bones, surfaces=num_surfs, bone_list=[], pose=pose_label)
    for i, b in enumerate(bones):
        R, T = pose[i]
        R = _copy_r(R)
        T = (float(T[0]), float(T[1]), float(T[2]))
        if b["parent_index"] >= 0:
            pr, pt = pose[b["parent_index"]]
            lr, lt = local_from_world(R, T, pr, pt)
        else:
            lr, lt = _copy_r(R), T
        lq = mat_to_quat(lr)
        mesh.bone_list.append(
            {
                "index": i,
                "name": b["name"],
                "parent": b["parent"],
                "parent_index": b["parent_index"],
                "type": b["type"],
                "pos": [T[0], T[1], T[2]],
                "world_t": [T[0], T[1], T[2]],
                "world_r": R,
                "local_t": [lt[0], lt[1], lt[2]],
                "local_r": lr,
                "local_quat": [lq[0], lq[1], lq[2], lq[3]],
            }
        )
    off = ofs_surfs
    surf_names: list[str] = []
    scan = ofs_surfs
    for _ in range(num_surfs):
        if scan + 100 > len(data):
            break
        surf_names.append(_cstr(data, scan + 4, 64))
        ofs_end = struct.unpack_from("<I", data, scan + 92)[0]
        scan += ofs_end
    hide_map = {n: surface_nodraw_reason(n, tik) for n in surf_names}
    # Only the selected skelmodel may ignore a full +nodraw set so a clicked
    # cache/attachment SKD is still inspectable. Extra setup models (gear that
    # idle hides, e.g. bangalore tubes) must stay hidden.
    if reveal_if_all_hidden and surf_names and all(hide_map.values()):
        mesh.visibility_note = (
            "TIK hides every surface at spawn (surface all +nodraw); "
            "shown because this asset is the selected preview"
        )
        hide_map = {n: None for n in surf_names}
    for _ in range(num_surfs):
        if off + 100 > len(data):
            break
        name = _cstr(data, off + 4, 64)
        ntri, nvert, _proc, ofs_tri, ofs_vert, _c, ofs_end, _ci = struct.unpack_from(
            "<8I", data, off + 68
        )
        hide_reason = hide_map.get(name)
        if hide_reason:
            mesh.groups.append(
                {
                    "name": name,
                    "start": len(mesh.indices),
                    "count": 0,
                    "shader": name,
                    "nodraw": True,
                    "hide_reason": hide_reason,
                }
            )
            mesh.skin_log.append(
                {
                    "surface": name,
                    "vertex_count": nvert,
                    "triangle_count": ntri,
                    "bone_indices": [],
                    "bone_names": [],
                    "bone_counts": {},
                    "num_weights": 0,
                    "weight_min": 0.0,
                    "weight_max": 0.0,
                    "nodraw": True,
                    "hide_reason": hide_reason,
                    "local_bounds": {"min": [0, 0, 0], "max": [0, 0, 0]},
                    "world_bounds": {"min": [0, 0, 0], "max": [0, 0, 0]},
                }
            )
            off += ofs_end
            continue
        base = len(mesh.positions) // 3
        vo = off + ofs_vert
        bones_used: dict[int, int] = {}
        nweights = 0
        wmin, wmax = 1e9, 0.0
        loc_min = [1e9, 1e9, 1e9]
        loc_max = [-1e9, -1e9, -1e9]
        world_min = [1e9, 1e9, 1e9]
        world_max = [-1e9, -1e9, -1e9]
        for _v in range(nvert):
            if vo + 28 > len(data):
                break
            nx, ny, nz, u, v, nw, nm = struct.unpack_from("<fffffII", data, vo)
            vo += 28
            if version >= 5:
                vo += nm * 16
            weights = []
            wsum = 0.0
            for _w in range(nw):
                if vo + 20 > len(data):
                    break
                bi, bw, ox, oy, oz = struct.unpack_from("<iffff", data, vo)
                vo += 20
                weights.append((bi, bw, ox, oy, oz))
                wsum += bw
                nweights += 1
                if bw < wmin:
                    wmin = bw
                if bw > wmax:
                    wmax = bw
                bones_used[bi] = bones_used.get(bi, 0) + 1
                loc_min[0], loc_min[1], loc_min[2] = min(loc_min[0], ox), min(loc_min[1], oy), min(loc_min[2], oz)
                loc_max[0], loc_max[1], loc_max[2] = max(loc_max[0], ox), max(loc_max[1], oy), max(loc_max[2], oz)
            if wsum > 1e-8:
                scale = 1.0 / wsum
                weights = [(bi, bw * scale, ox, oy, oz) for bi, bw, ox, oy, oz in weights]
            px = py = pz = 0.0
            first_r = ident
            for bi, bw, ox, oy, oz in weights:
                if 0 <= bi < len(pose):
                    R, T = pose[bi]
                else:
                    R, T = ident, zero_t
                if first_r is ident:
                    first_r = R
                sx, sy, sz = _skin_point(ox, oy, oz, R, T, bw)
                px += sx
                py += sy
                pz += sz
            nnx, nny, nnz = _skin_normal(nx, ny, nz, first_r)
            mesh.positions.extend((px, py, pz))
            mesh.normals.extend((nnx, nny, nnz))
            mesh.uvs.extend((u, 1.0 - v))
            mesh.influences.append([[int(bi), float(bw)] for bi, bw, _ox, _oy, _oz in weights])
            world_min[0], world_min[1], world_min[2] = min(world_min[0], px), min(world_min[1], py), min(world_min[2], pz)
            world_max[0], world_max[1], world_max[2] = max(world_max[0], px), max(world_max[1], py), max(world_max[2], pz)
        to = off + ofs_tri
        start = len(mesh.indices)
        for _t in range(ntri):
            a, b, c = struct.unpack_from("<3I", data, to)
            to += 12
            mesh.indices.extend((base + a, base + c, base + b))
        mesh.groups.append(
            {
                "name": name,
                "start": start,
                "count": ntri * 3,
                "shader": name,
                "vert_base": base,
                "vert_count": nvert,
            }
        )
        mesh.skin_log.append(
            {
                "surface": name,
                "vertex_count": nvert,
                "triangle_count": ntri,
                "bone_indices": sorted(bones_used.keys()),
                "bone_names": [bones[i]["name"] for i in sorted(bones_used.keys()) if 0 <= i < len(bones)],
                "bone_counts": {str(k): v for k, v in sorted(bones_used.items())},
                "num_weights": nweights,
                "weight_min": 0.0 if nweights == 0 else wmin,
                "weight_max": 0.0 if nweights == 0 else wmax,
                "local_bounds": {"min": loc_min if nvert else [0, 0, 0], "max": loc_max if nvert else [0, 0, 0]},
                "world_bounds": {
                    "min": world_min if nvert else [0, 0, 0],
                    "max": world_max if nvert else [0, 0, 0],
                },
            }
        )
        off += ofs_end
    return mesh


NODRAW = (
    "nodraw",
    "clip",
    "hint",
    "skip",
    "trigger",
    "origin",
    "caulk",
    "caulksky",
    "areaportal",
    "clusterportal",
    "lightgrid",
    "antiportal",
    "metalclip",
    "playerclip",
    "monsterclip",
    "weaponclip",
)

# Quake 3 / MOHAA dsurface_t.surfaceType
MST_PLANAR = 1
MST_PATCH = 2
MST_TRIANGLE_SOUP = 3
MST_FLARE = 4
MST_TERRAIN = 5

# Preview in the browser stays capped; Unreal export passes None.
BSP_PREVIEW_MAX_INDICES = 400_000
# MOHAA world units are inches. SKD/character meshes are already centimeters.
BSP_CM_PER_UNIT = 2.54
# TIKI props that are not map furniture (no character retarget).
BSP_FURNITURE_SKIP = (
    "/human/",
    "/player/",
    "/emitters/",
    "/fx/",
    "/vehicles/",
    "/animate/",
)
# cStaticModel_t in qfiles.h: name[128] + origin + angles + scale + 2 ints.
BSP_LUMP_MODELS = 13
BSP_LUMP_STATICMODELDEF = 25
BSP_STATIC_MODEL_SIZE = 164
BSP_HEADER_LUMPS = 28


def _qbez(a, b, c, t: float):
    omt = 1.0 - t
    return (
        omt * omt * a[0] + 2.0 * omt * t * b[0] + t * t * c[0],
        omt * omt * a[1] + 2.0 * omt * t * b[1] + t * t * c[1],
        omt * omt * a[2] + 2.0 * omt * t * b[2] + t * t * c[2],
    )


def _qbez2(a, b, c, t: float):
    omt = 1.0 - t
    return (
        omt * omt * a[0] + 2.0 * omt * t * b[0] + t * t * c[0],
        omt * omt * a[1] + 2.0 * omt * t * b[1] + t * t * c[1],
    )


def _tessellate_patch(
    points: list,
    uvs: list,
    normals: list,
    width: int,
    height: int,
    subdiv: int = 3,
) -> tuple[list, list, list, list]:
    """Quadratic Bezier patch (Q3/MOHAA): overlapping 3x3 control grids."""
    pos_out: list[float] = []
    nrm_out: list[float] = []
    uv_out: list[float] = []
    idx_out: list[int] = []
    if width < 2 or height < 2 or width * height > len(points):
        return pos_out, nrm_out, uv_out, idx_out
    step = 2 if (width >= 3 and height >= 3 and width % 2 == 1 and height % 2 == 1) else 1
    if step == 1:
        # Control-point triangulation fallback for odd-sized patches that are not 3x3 cells.
        base = 0
        for y in range(height):
            for x in range(width):
                p = points[y * width + x]
                n = normals[y * width + x]
                uv = uvs[y * width + x]
                pos_out.extend(p)
                nrm_out.extend(n)
                uv_out.extend(uv)
        for y in range(height - 1):
            for x in range(width - 1):
                a = y * width + x
                b = a + 1
                c = a + width
                d = c + 1
                idx_out.extend((a, c, b, b, c, d))
        return pos_out, nrm_out, uv_out, idx_out

    nlev = max(1, int(subdiv))
    for y0 in range(0, height - 2, 2):
        for x0 in range(0, width - 2, 2):
            ctrl_p = [[points[(y0 + j) * width + (x0 + i)] for i in range(3)] for j in range(3)]
            ctrl_n = [[normals[(y0 + j) * width + (x0 + i)] for i in range(3)] for j in range(3)]
            ctrl_uv = [[uvs[(y0 + j) * width + (x0 + i)] for i in range(3)] for j in range(3)]
            grid_base = len(pos_out) // 3
            for vv in range(nlev + 1):
                tv = vv / nlev
                for uu in range(nlev + 1):
                    tu = uu / nlev
                    col_p = [_qbez(ctrl_p[j][0], ctrl_p[j][1], ctrl_p[j][2], tu) for j in range(3)]
                    col_n = [_qbez(ctrl_n[j][0], ctrl_n[j][1], ctrl_n[j][2], tu) for j in range(3)]
                    col_uv = [_qbez2(ctrl_uv[j][0], ctrl_uv[j][1], ctrl_uv[j][2], tu) for j in range(3)]
                    p = _qbez(col_p[0], col_p[1], col_p[2], tv)
                    n = _qbez(col_n[0], col_n[1], col_n[2], tv)
                    uv = _qbez2(col_uv[0], col_uv[1], col_uv[2], tv)
                    ln = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) or 1.0
                    pos_out.extend(p)
                    nrm_out.extend((n[0] / ln, n[1] / ln, n[2] / ln))
                    uv_out.extend(uv)
            stride = nlev + 1
            for vv in range(nlev):
                for uu in range(nlev):
                    a = grid_base + vv * stride + uu
                    b = a + 1
                    c = a + stride
                    d = c + 1
                    idx_out.extend((a, c, b, b, c, d))
    return pos_out, nrm_out, uv_out, idx_out


def parse_bsp_entities(data: bytes) -> list[dict]:
    """Parse the BSP entity lump as a list of lowercase-key dicts."""
    if data[:4] != b"2015" or len(data) < 20:
        return []
    text = ""
    for i in range(28):
        ofs, ln = struct.unpack_from("<ii", data, 12 + i * 8)
        if ln <= 0 or ofs < 0 or ofs + ln > len(data):
            continue
        lump = data[ofs : ofs + ln]
        if b'"classname"' in lump:
            text = lump.decode("latin-1", "replace")
            break
    if not text:
        return []
    ents = []
    for block in re.findall(r"\{(.*?)\}", text, re.S):
        kv = {}
        for k, v in re.findall(r'"([^"]+)"\s+"([^"]*)"', block):
            kv[k.lower()] = v
        if kv:
            ents.append(kv)
    return ents


def bsp_lump(data: bytes, lump_id: int) -> tuple[int, int]:
    """(ofs, len) for a MOHAA lump. Version <=18 shifts lumps after brushes by +1."""
    if data[:4] != b"2015" or len(data) < 20:
        return (0, 0)
    version = _i32(data, 4)
    idx = lump_id
    if version <= 18 and lump_id > 12:
        idx += 1
    if idx < 0 or idx >= BSP_HEADER_LUMPS:
        return (0, 0)
    ofs, ln = struct.unpack_from("<ii", data, 12 + idx * 8)
    if ln <= 0 or ofs < 0 or ofs + ln > len(data):
        return (0, 0)
    return (ofs, ln)


def parse_bsp_models(data: bytes) -> list[dict]:
    """MOHAA dmodel_t is 40 bytes: mins, maxs, firstSurf, numSurf, firstBrush, numBrushes."""
    ofs, ln = bsp_lump(data, BSP_LUMP_MODELS)
    if ln <= 0 or ln % 40:
        return []
    out = []
    for i in range(ln // 40):
        o = ofs + i * 40
        mins = struct.unpack_from("<3f", data, o)
        maxs = struct.unpack_from("<3f", data, o + 12)
        first_surf, num_surf, first_brush, num_brush = struct.unpack_from("<4i", data, o + 24)
        out.append(
            {
                "mins": mins,
                "maxs": maxs,
                "first_surf": first_surf,
                "num_surf": num_surf,
                "first_brush": first_brush,
                "num_brush": num_brush,
            }
        )
    return out


def parse_vec3(text: str, default: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    parts = (text or "").replace(",", " ").split()
    if len(parts) < 3:
        return default
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError:
        return default


def entity_origin(ent: dict) -> tuple[float, float, float]:
    return parse_vec3(ent.get("origin") or "")


def entity_angles(ent: dict) -> tuple[float, float, float]:
    """Return pitch, yaw, roll in degrees (MOHAA / Quake)."""
    if ent.get("angles"):
        return parse_vec3(ent.get("angles") or "")
    try:
        return (0.0, float(ent.get("angle") or 0.0), 0.0)
    except ValueError:
        return (0.0, 0.0, 0.0)


def entity_scale(ent: dict) -> float:
    for key in ("scale", "modelscale"):
        raw = ent.get(key)
        if raw:
            try:
                return float(raw)
            except ValueError:
                pass
    return 1.0


def mohaa_point_to_ue_cm(x: float, y: float, z: float) -> tuple[float, float, float]:
    """BSP world units → Unreal cm: *2.54, +90° Z, then negate Unreal Y.

    Map brushes export with --map (no character Y-mirror, +90° Z) and keep
    world origin. Unreal's Blender FBX importer then Y-mirrors static meshes,
    which is the visually-correct town. Furniture (lump 25 + TIKI entities)
    must land in that same imported space: loc=(-Y, -X, Z)*2.54. Do not
    pre-negate the map FBX and do not scale the map actor (1,-1,1).

    SKD meshes are centimeters. TIKI `scale` (typically 0.52 = 16/30.5) converts
    cm → world units; use mohaa_model_scale_to_ue so table tops meet plate Z.
    """
    x *= BSP_CM_PER_UNIT
    y *= BSP_CM_PER_UNIT
    z *= BSP_CM_PER_UNIT
    return (-y, -x, z)


def mohaa_angles_to_ue(pitch: float, yaw: float, roll: float) -> tuple[float, float, float]:
    """BSP instance rotator → Unreal (pitch, yaw, roll).

    Map and furniture FBX already bake blender +90° Z (same as loc=(-Y,-X,Z)*2.54).
    Unreal then Y-mirrors static meshes, which reverses yaw/roll sense. Actor
    yaw must not add another +90° — that double-count put every prop a
    quarter-turn off the brushes (table across the floorboards, chairs
    edge-on). Pitch/roll stay so plates remain flat (thin in Z).

    Old: (pitch, -(yaw + 90), -roll). New: (pitch, -yaw, -roll).
    """
    return (pitch, -yaw, -roll)


def mohaa_model_scale_to_ue(tik_scale: float, instance_scale: float = 1.0) -> float:
    """Actor scale for a TIKI static mesh spawned into *2.54 map space.

    SKD verts are centimeters. TIKI scale converts cm → BSP world units
    (0.52 = 16 units/foot / 30.5 cm; 1.0 = SKD already in world units).
    Origins use *2.54, so the mesh must too: tik_scale * instance * 2.54.
    """
    try:
        ts = float(tik_scale)
    except (TypeError, ValueError):
        ts = 1.0
    try:
        inst = float(instance_scale)
    except (TypeError, ValueError):
        inst = 1.0
    if ts <= 0.0:
        ts = 1.0
    if inst <= 0.0:
        inst = 1.0
    return ts * inst * BSP_CM_PER_UNIT


def _rotate_yaw(x: float, y: float, z: float, yaw_deg: float) -> tuple[float, float, float]:
    if not yaw_deg:
        return (x, y, z)
    a = math.radians(yaw_deg)
    c, s = math.cos(a), math.sin(a)
    return (x * c - y * s, x * s + y * c, z)


def _inline_face_map(data: bytes, nfaces: int) -> tuple[list[int], dict[int, tuple[float, float, float, float]]]:
    """face index → model index, and model → (ox, oy, oz, yaw)."""
    face_model = [0] * nfaces
    for mi, rec in enumerate(parse_bsp_models(data)):
        first, n = rec["first_surf"], rec["num_surf"]
        for fi in range(first, first + n):
            if 0 <= fi < nfaces:
                face_model[fi] = mi
    origins: dict[int, tuple[float, float, float, float]] = {0: (0.0, 0.0, 0.0, 0.0)}
    for ent in parse_bsp_entities(data):
        model = ent.get("model") or ""
        if not model.startswith("*"):
            continue
        try:
            idx = int(model[1:])
        except ValueError:
            continue
        ox, oy, oz = entity_origin(ent)
        _pitch, yaw, _roll = entity_angles(ent)
        origins[idx] = (ox, oy, oz, yaw)
    return face_model, origins


def _apply_inline(
    x: float, y: float, z: float, origin: tuple[float, float, float, float]
) -> tuple[float, float, float]:
    ox, oy, oz, yaw = origin
    x, y, z = _rotate_yaw(x, y, z, yaw)
    return (x + ox, y + oy, z + oz)


def parse_bsp_static_models(data: bytes) -> list[dict]:
    """LUMP_STATICMODELDEF: TIKI props Radiant placed in the map (chairs, trees, lamps).

    These are not entities. Entity-lump furniture is only interactobject / script_model.
    Returned dicts reuse entity key names so collect_map_furniture can spawn them.
    """
    ofs, ln = bsp_lump(data, BSP_LUMP_STATICMODELDEF)
    if ln <= 0 or ln % BSP_STATIC_MODEL_SIZE:
        return []
    out = []
    for i in range(ln // BSP_STATIC_MODEL_SIZE):
        o = ofs + i * BSP_STATIC_MODEL_SIZE
        model = _cstr(data, o, 128).replace("\\", "/")
        ox, oy, oz = struct.unpack_from("<3f", data, o + 128)
        pitch, yaw, roll = struct.unpack_from("<3f", data, o + 140)
        scale = struct.unpack_from("<f", data, o + 152)[0]
        out.append(
            {
                "classname": "static_model",
                "model": model,
                "origin": "%g %g %g" % (ox, oy, oz),
                "angles": "%g %g %g" % (pitch, yaw, roll),
                "scale": ("%g" % scale) if scale else "1",
            }
        )
    return out


def is_furniture_tik(path: str) -> bool:
    low = (path or "").replace("\\", "/").lower()
    if not low.endswith(".tik") and not low.endswith(".tiki"):
        return False
    if any(part in low for part in BSP_FURNITURE_SKIP):
        return False
    # Light-sprite coronas, not mesh furniture.
    if "corona" in posixpath.basename(low):
        return False
    return True


def parse_bsp(data: bytes, max_indices: int | None = BSP_PREVIEW_MAX_INDICES, *, include_inline: bool = True) -> Mesh:
    if data[:4] != b"2015":
        raise ValueError("Not a MOHAA BSP")
    version = _i32(data, 4)
    if version not in (18, 19, 20, 21):
        raise ValueError(f"Unsupported BSP version {version}")

    def lump(i: int) -> tuple[int, int]:
        # ident + version + checksum, then lump_t[28]
        return struct.unpack_from("<ii", data, 12 + i * 8)

    tex_ofs, tex_len = lump(0)
    face_ofs, face_len = lump(3)
    vert_ofs, vert_len = lump(4)
    idx_ofs, idx_len = lump(5)

    shaders: list[str] = []
    shader_flags: list[int] = []
    # dshader_t: name[64] + 3 ints + fenceMask[64] = 140
    stride = 140 if tex_len % 140 == 0 else (76 if tex_len % 76 == 0 else 80)
    for i in range(tex_len // stride):
        shaders.append(_cstr(data, tex_ofs + i * stride, 64).lower())
        shader_flags.append(_i32(data, tex_ofs + i * stride + 64) if stride >= 68 else 0)

    nverts = vert_len // 44
    verts_xyz = []
    verts_n = []
    verts_uv = []
    for i in range(nverts):
        o = vert_ofs + i * 44
        x, y, z, u, v = struct.unpack_from("<fffff", data, o)
        nx, ny, nz = struct.unpack_from("<fff", data, o + 28)
        verts_xyz.append((x, y, z))
        verts_n.append((nx, ny, nz))
        verts_uv.append((u, 1.0 - v))

    nidx = idx_len // 4
    indices = struct.unpack_from("<%dI" % nidx, data, idx_ofs) if nidx else ()
    nfaces = face_len // 108
    face_model, inline_origins = _inline_face_map(data, nfaces)
    identity = (0.0, 0.0, 0.0, 0.0)

    def is_nodraw(sh: str, flags: int) -> bool:
        if flags & SURF_NODRAW:
            return True
        parts = sh.replace("\\", "/").split("/")
        base = parts[-1] if parts else sh
        if any(tok in parts for tok in NODRAW) or base in NODRAW:
            return True
        return any(base.endswith(tok) for tok in ("clip", "hint", "skip", "caulk", "trigger", "nodraw"))

    buckets: dict[str, list[tuple[int, int, int, tuple]]] = {}
    patches: list[tuple[str, int, int, int, tuple]] = []
    sky_shaders: list[str] = []
    used = 0
    skipped = {MST_PATCH: 0, MST_FLARE: 0, MST_TERRAIN: 0, "capped": 0, "sky": 0}

    def would_exceed(count: int) -> bool:
        return max_indices is not None and used + count > max_indices

    for fi in range(nfaces):
        fo = face_ofs + fi * 108
        shader_num, _fog, stype, first_vert, num_verts, first_idx, num_idx = struct.unpack_from(
            "<7i", data, fo
        )
        model_i = face_model[fi] if fi < len(face_model) else 0
        if model_i and not include_inline:
            continue
        origin = inline_origins.get(model_i, identity) if model_i else identity
        sh = shaders[shader_num] if 0 <= shader_num < len(shaders) else ""
        flags = shader_flags[shader_num] if 0 <= shader_num < len(shader_flags) else 0
        if flags & SURF_SKY:
            if sh and sh not in sky_shaders:
                sky_shaders.append(sh)
            skipped["sky"] += 1
            continue
        if not sh or is_nodraw(sh, flags):
            continue
        if stype == MST_FLARE:
            skipped[MST_FLARE] += 1
            continue
        if stype == MST_PATCH:
            patch_w, patch_h = struct.unpack_from("<ii", data, fo + 96)
            if patch_w < 2 or patch_h < 2 or first_vert < 0:
                skipped[MST_PATCH] += 1
                continue
            if first_vert + patch_w * patch_h > nverts:
                skipped[MST_PATCH] += 1
                continue
            # 3x3 cells at subdiv 3 → 16 quads × 6 indices; fallback grid is similar order.
            nlev = 3
            cells_x = max(1, (patch_w - 1) // 2)
            cells_y = max(1, (patch_h - 1) // 2)
            est = cells_x * cells_y * nlev * nlev * 6
            if would_exceed(est):
                skipped["capped"] += 1
                break
            patches.append((sh, first_vert, patch_w, patch_h, origin))
            used += est
            continue
        if stype not in (0, MST_PLANAR, MST_TRIANGLE_SOUP, MST_TERRAIN):
            continue
        if first_vert < 0 or num_verts <= 0:
            continue
        if num_idx >= 3 and first_idx >= 0:
            count = num_idx
        elif num_verts >= 3:
            first_idx = -1
            count = (num_verts - 2) * 3
        else:
            continue
        if would_exceed(count):
            skipped["capped"] += 1
            break
        buckets.setdefault(sh, []).append(
            (first_vert, first_idx, num_idx if first_idx >= 0 else num_verts, origin)
        )
        used += count

    mesh = Mesh(surfaces=0, pose="bsp", sky_shaders=sky_shaders)
    for sh, faces in buckets.items():
        remap = {}
        base = len(mesh.positions) // 3
        start = len(mesh.indices)
        for first_vert, first_idx, n, origin in faces:
            if first_idx >= 0:
                local = [indices[first_idx + k] for k in range(n)]
            else:
                local = []
                for t in range(1, n - 1):
                    local.extend((0, t, t + 1))
            for loc in local:
                src = first_vert + loc
                if src < 0 or src >= nverts:
                    continue
                key = (src, origin)
                if key not in remap:
                    remap[key] = base + len(remap)
                    px, py, pz = verts_xyz[src]
                    nx, ny, nz = verts_n[src]
                    u, v = verts_uv[src]
                    px, py, pz = _apply_inline(px, py, pz, origin)
                    nx, ny, nz = _rotate_yaw(nx, ny, nz, origin[3])
                    mesh.positions.extend((px, py, pz))
                    mesh.normals.extend((nx, ny, nz))
                    mesh.uvs.extend((u, v))
                mesh.indices.append(remap[key])
        count = len(mesh.indices) - start
        if count:
            mesh.groups.append({"name": sh, "start": start, "count": count, "shader": sh})

    for sh, first_vert, patch_w, patch_h, origin in patches:
        pts = [_apply_inline(*p, origin) for p in verts_xyz[first_vert : first_vert + patch_w * patch_h]]
        nrms = [_rotate_yaw(*n, origin[3]) for n in verts_n[first_vert : first_vert + patch_w * patch_h]]
        uvs = verts_uv[first_vert : first_vert + patch_w * patch_h]
        p_pos, p_n, p_uv, p_idx = _tessellate_patch(pts, uvs, nrms, patch_w, patch_h)
        if not p_idx:
            continue
        base = len(mesh.positions) // 3
        start = len(mesh.indices)
        mesh.positions.extend(p_pos)
        mesh.normals.extend(p_n)
        mesh.uvs.extend(p_uv)
        mesh.indices.extend(base + i for i in p_idx)
        count = len(mesh.indices) - start
        if count:
            mesh.groups.append({"name": sh, "start": start, "count": count, "shader": sh})

    mesh.surfaces = len(mesh.groups)
    if skipped["capped"]:
        mesh.visibility_note = "bsp truncated at %d indices" % (max_indices or 0)
    return mesh


def parse_map_info(text: bytes) -> dict:
    raw = text.decode("latin1", "replace")
    entities = raw.count("{")
    brushes = len(re.findall(r"\(\s*-?\d", raw))
    classes = re.findall(r'"classname"\s+"([^"]+)"', raw)
    return {
        "entities": len(classes),
        "brushes_est": brushes // 6,
        "class_counts": {c: classes.count(c) for c in sorted(set(classes))[:40]},
        "blocks": entities,
    }


def image_to_png(data: bytes, filename: str, max_size: int = 1024) -> bytes:
    blob, _ctype = encode_preview_image(data, filename, max_size=max_size, fmt="png")
    return blob


def encode_preview_image(
    data: bytes, filename: str, max_size: int = 1024, fmt: str = "jpeg"
) -> tuple[bytes, str]:
    """Decode a MOHAA TGA/JPG/DDS and emit a small JPEG (or PNG) for the browser."""
    name = (filename or "").lower()
    fmt = (fmt or "jpeg").lower()
    if fmt == "jpg":
        fmt = "jpeg"
    if name.endswith(".png") and fmt == "png" and max_size >= 2048:
        return data, "image/png"
    bio = io.BytesIO(data)
    try:
        img = Image.open(bio)
        img.load()
    except Exception as exc:
        raise ValueError(f"Cannot decode {filename}") from exc
    if (
        fmt == "jpeg"
        and name.endswith((".jpg", ".jpeg"))
        and img.mode in ("RGB", "L")
        and max(img.size) <= max_size
    ):
        return data, "image/jpeg"
    resample = Image.BILINEAR if max_size <= 256 else Image.BICUBIC
    if fmt == "jpeg":
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (16, 21, 28))
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.convert("RGB")
        img.thumbnail((max_size, max_size), resample)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=78, optimize=False, subsampling=2)
        return out.getvalue(), "image/jpeg"
    img = img.convert("RGBA")
    img.thumbnail((max_size, max_size), resample)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=False, compress_level=1)
    return out.getvalue(), "image/png"


def mesh_to_json(mesh: Mesh) -> dict:
    return {
        "positions": mesh.positions,
        "normals": mesh.normals,
        "uvs": mesh.uvs,
        "indices": mesh.indices,
        "groups": mesh.groups,
        "bones": mesh.bones,
        "surfaces": mesh.surfaces,
        "vertexCount": len(mesh.positions) // 3,
        "triangleCount": len(mesh.indices) // 3,
        "skeleton": mesh.bone_list,
        "influences": mesh.influences,
        "skinLog": mesh.skin_log,
        "pose": mesh.pose,
        "visibilityNote": mesh.visibility_note,
        "skyShaders": list(mesh.sky_shaders or []),
    }


def merge_meshes(parts: list[Mesh], pose_label: str = "") -> Mesh:
    """Concatenate extra TIKI setup skelmodels (body + head + hands + helmet).

    Skeletons are merged by bone name onto the first SKD. Extra SKDs reuse the
    same MOHAA hierarchy the viewer already solved; new bones (fingers, helmet)
    are appended and reparented by name. Vertex weights are remapped to that
    shared list — never invented.
    """
    if not parts:
        return Mesh(pose=pose_label)
    if len(parts) == 1:
        if pose_label:
            parts[0].pose = pose_label
        return parts[0]
    out = Mesh(pose=pose_label or parts[0].pose)
    notes = []

    def _map_skeleton(extra_bones: list[dict]) -> list[int]:
        by_name = {(b.get("name") or "").lower(): i for i, b in enumerate(out.bone_list)}
        mapping = [-1] * len(extra_bones)

        def add(i: int) -> int:
            if i < 0 or i >= len(extra_bones):
                return -1
            if mapping[i] >= 0:
                return mapping[i]
            b = extra_bones[i]
            key = (b.get("name") or "bone").lower()
            if key in by_name:
                mapping[i] = by_name[key]
                return mapping[i]
            parent_out = add(int(b.get("parent_index", -1)))
            nb = dict(b)
            nb["index"] = len(out.bone_list)
            nb["parent_index"] = parent_out
            out.bone_list.append(nb)
            by_name[key] = nb["index"]
            mapping[i] = nb["index"]
            return mapping[i]

        for i in range(len(extra_bones)):
            add(i)
        return mapping

    for mesh in parts:
        vbase = len(out.positions) // 3
        ibase = len(out.indices)
        out.positions.extend(mesh.positions)
        out.normals.extend(mesh.normals)
        out.uvs.extend(mesh.uvs)
        out.indices.extend(i + vbase for i in mesh.indices)
        for g in mesh.groups:
            ng = dict(g)
            ng["start"] = int(g.get("start") or 0) + ibase
            if g.get("vert_base") is not None:
                ng["vert_base"] = int(g["vert_base"]) + vbase
            out.groups.append(ng)
        out.skin_log.extend(mesh.skin_log)
        bone_map = _map_skeleton(mesh.bone_list)
        nmap = len(bone_map)
        for inf in mesh.influences:
            remapped = []
            for bi, w in inf:
                idx = int(bi)
                if 0 <= idx < nmap and bone_map[idx] >= 0:
                    remapped.append([bone_map[idx], float(w)])
                else:
                    remapped.append([idx, float(w)])
            out.influences.append(remapped)
        out.bones = len(out.bone_list)
        out.surfaces += mesh.surfaces
        if mesh.visibility_note:
            notes.append(mesh.visibility_note)
    out.visibility_note = " | ".join(notes)
    return out


_ANIM_FOCUS_BONES = (
    "Bip01 L UpperArm",
    "Bip01 L Forearm",
    "Bip01 L Hand",
    "Bip01 R UpperArm",
    "Bip01 R Forearm",
    "Bip01 R Hand",
    "Bip01 L Clavicle",
    "Bip01 R Clavicle",
    "Bip01 Spine",
    "Bip01 Spine1",
    "Bip01 Spine2",
    "Bip01 Neck",
    "Bip01 Head",
    "helper Rshoulder",
    "tag_weapon_right",
    "tag_weapon_left",
)
_COMPOSE_LOG_BONES = (
    "Bip01",
    "Bip01 Pelvis",
    "Bip01 Spine",
    "Bip01 Spine1",
    "Bip01 Spine2",
    "Bip01 Neck",
    "Bip01 Head",
    "Bip01 L Thigh",
    "Bip01 L Calf",
    "Bip01 L Foot",
    "Bip01 L Toe0",
    "Bip01 R Thigh",
    "Bip01 R Calf",
    "Bip01 R Foot",
    "Bip01 R Toe0",
    "Bip01 L Clavicle",
    "Bip01 L UpperArm",
    "Bip01 L Forearm",
    "Bip01 L Hand",
    "Bip01 R Clavicle",
    "Bip01 R UpperArm",
    "Bip01 R Forearm",
    "Bip01 R Hand",
    "Bip01 L Finger0",
    "Bip01 R Finger0",
    "tag_weapon_right",
    "tag_weapon_left",
    "helper Lshoulder",
    "helper Rshoulder",
    "helper Lelbow",
    "helper Relbow",
    "helper Lhip",
    "helper Rhip",
)
_ANIM_FOCUS_SUBSTR = (
    "finger",
    "helmet",
    "helper",
    "tag_weapon",
    "ik",
)
_ANIM_LENGTH_PAIRS = (
    ("Bip01 L UpperArm", "Bip01 L Forearm"),
    ("Bip01 L Forearm", "Bip01 L Hand"),
    ("Bip01 R UpperArm", "Bip01 R Forearm"),
    ("Bip01 R Forearm", "Bip01 R Hand"),
)


def evaluate_animation_frames(
    skd_bone_groups: list[list[dict]],
    skc: dict,
    bone_names: list[str],
    base_channels: dict | None = None,
) -> list[list[dict]]:
    """World poses per SKC frame, merged by bone NAME (never raw SKD indices).

    Accessory SKDs (hands, helmet, gear) often reuse Bip01 arm names with a
    truncated hierarchy. Last-wins overwrote the body solver and stretched
    skin. First SKD keeps shared bones; extra-only bones keep their local
    offset and are recomposed onto the merged parent world.

    Action clips (no Bip01+feet pos) pass idle `base_channels`. Overlay keys
    win; omitted channels keep the base. Full-body walk/run omit the base so
    the existing per-clip path is unchanged.
    """
    frames_in = skc.get("frames") or ([skc.get("channels")] if skc.get("channels") else [])
    out = []
    overwrite_logged = False
    for raw_chans in frames_in:
        chans = overlay_skc_channels(base_channels, raw_chans) if base_channels else raw_chans
        intro: dict[str, tuple] = {}
        for bones in skd_bone_groups:
            pose = bind_pose_matrices(bones, chans)
            for b, (R, T) in zip(bones, pose):
                name = b["name"]
                pi = int(b.get("parent_index", -1))
                if pi >= 0:
                    pr, pt = pose[pi]
                    lr, lt = local_from_world(R, T, pr, pt)
                    pname = bones[pi]["name"]
                else:
                    lr, lt = _copy_r(R), (float(T[0]), float(T[1]), float(T[2]))
                    pname = None
                if name in intro:
                    if not overwrite_logged:
                        old_t = intro[name][3]
                        d = (
                            (float(T[0]) - old_t[0]) ** 2
                            + (float(T[1]) - old_t[1]) ** 2
                            + (float(T[2]) - old_t[2]) ** 2
                        ) ** 0.5
                        if d > 0.05:
                            print(
                                "[anim] keep first SKD for '%s' (later SKD world delta %.3f)"
                                % (name, d),
                                flush=True,
                            )
                    continue
                intro[name] = (
                    _copy_r(lr),
                    (float(lt[0]), float(lt[1]), float(lt[2])),
                    pname,
                    (float(T[0]), float(T[1]), float(T[2])),
                    _copy_r(R),
                )
        resolved: dict[str, tuple] = {}

        def world_of(name: str):
            if name in resolved:
                return resolved[name]
            rec = intro.get(name)
            if rec is None:
                return None
            lr, lt, pname, ow, oR = rec
            if not pname or pname not in intro:
                resolved[name] = (_copy_r(oR), ow)
                return resolved[name]
            parent = world_of(pname)
            if parent is None:
                resolved[name] = (_copy_r(oR), ow)
                return resolved[name]
            wr, wt = _mul_skel(lr, lt, parent[0], parent[1])
            resolved[name] = (wr, tuple(wt))
            return resolved[name]

        for name in bone_names:
            world_of(name)
        frame = []
        for name in bone_names:
            rec = resolved.get(name)
            if rec:
                R, T = rec
                frame.append(
                    {
                        "name": name,
                        "world_r": _copy_r(R),
                        "world_t": [float(T[0]), float(T[1]), float(T[2])],
                    }
                )
        out.append(frame)
        overwrite_logged = True
    return out


def _skc_channel_bone(name: str) -> str:
    low = (name or "").strip()
    for suf in (" pos", " rot", " offset"):
        if low.lower().endswith(suf):
            return low[: -len(suf)]
    return low


def skc_channel_keys(skc: dict | None) -> set[str]:
    """Lowercased 'bone suffix' keys present in the SKC (e.g. 'bip01 pos')."""
    out = set()
    for ch in (skc or {}).get("names") or []:
        if ch:
            out.add(str(ch).lower())
    if not out:
        for key in ((skc or {}).get("channels") or {}):
            out.add(str(key).lower())
    return out


def skc_has_delta(skc: dict | None) -> bool:
    """OpenMOHAA bHasDelta: Bip01 pos + both foot pos channels."""
    keys = skc_channel_keys(skc)
    return (
        "bip01 pos" in keys
        and "bip01 r foot pos" in keys
        and "bip01 l foot pos" in keys
    )


def skc_has_upper(skc: dict | None) -> bool:
    """OpenMOHAA bHasUpper: spine + spine1 rotation channels."""
    keys = skc_channel_keys(skc)
    return "bip01 spine rot" in keys and "bip01 spine1 rot" in keys


def skc_has_morph(skc: dict | None) -> bool:
    """OpenMOHAA bHasMorph: viseme / facial channels (see skeletor_loadanimation.cpp)."""
    keys = skc_channel_keys(skc)
    morph = (
        "viseme_bump", "visme_cage_", "visme_earth", "visme_fave", "visme_if",
        "visme_new", "visme_ox", "visme_roar", "visme_size", "visme_though",
        "visme_told", "visme_wet", "brow_frown", "brow_r_lift", "brow_lift",
        "brow_worry", "eye_blink", "jaw_open-closed", "jaw_open-open",
    )
    return any(k in keys for k in morph)


def _clean_tiki_flags(flags) -> list[str]:
    out = []
    for raw in flags or []:
        tok = str(raw).strip()
        if not tok or tok.startswith("//") or tok == "{":
            continue
        out.append(tok)
    return out


def classify_skc_clip(
    skc: dict | None,
    flags=None,
    skeleton_names: list[str] | None = None,
) -> dict:
    """Classify an SKC from channel coverage + TIKI flags (not alias name).

    OpenMOHAA skeletor.cpp BuildFrameList / SkeletorGetAnimFrame:
    bHasDelta (Bip01 pos + both foot pos) → movement/full-body slot, clip-only.
    else → action slot; missing channels keep the motion/idle pose (GetSlerpValue
    only writes channels the clip actually contains).

    TIKI has no torso/legs mask. TAF_DELTADRIVEN is loop wrapping, not additive.
    Actor upperanim always StartActionAnimSlot; HASDELTA clips can occupy both
    motion and action slots (actor.cpp UpdateSayAnim).
    """
    flags = _clean_tiki_flags(flags)
    has_delta = skc_has_delta(skc)
    has_upper = skc_has_upper(skc)
    has_morph = skc_has_morph(skc)
    keys = skc_channel_keys(skc)
    has_bip_pos = "bip01 pos" in keys
    has_lfoot = "bip01 l foot pos" in keys
    has_rfoot = "bip01 r foot pos" in keys
    has_feet = has_lfoot and has_rfoot
    delta_driven = any(f.lower() == "deltadriven" for f in flags)
    skc_bones = []
    seen = set()
    for ch in (skc or {}).get("names") or []:
        bone = _skc_channel_bone(ch)
        key = bone.lower()
        if not bone or key in seen:
            continue
        seen.add(key)
        skc_bones.append(bone)
    skel = [str(n) for n in (skeleton_names or []) if n]
    animated = [n for n in skel if n.lower() in seen] if skel else list(skc_bones)
    unanimated = [n for n in skel if n.lower() not in seen]
    extra = [b for b in skc_bones if b.lower() not in {n.lower() for n in skel}] if skel else []
    nchan = int((skc or {}).get("numChannels") or 0)
    morph_only = has_morph and nchan > 0 and nchan <= 16 and not has_upper and not has_delta
    if has_delta:
        type_name = "full-body"
        compose = "clip_only"
        layer = "motion"
        base_pose = "none"
    elif morph_only:
        type_name = "morph/face"
        compose = "overlay_idle"
        layer = "action"
        base_pose = "idle"
    elif has_feet and not has_upper:
        type_name = "lower-body overlay"
        compose = "overlay_idle"
        layer = "action"
        base_pose = "idle"
    elif has_upper and not has_feet:
        type_name = "upper-body overlay"
        compose = "overlay_idle"
        layer = "action"
        base_pose = "idle"
    else:
        type_name = "partial overlay"
        compose = "overlay_idle"
        layer = "action"
        base_pose = "idle"
    return {
        "type": type_name,
        "compose": compose,
        "layer": layer,
        "base_pose": base_pose,
        "has_delta": has_delta,
        "has_upper": has_upper,
        "has_morph": has_morph,
        "delta_driven": delta_driven,
        "additive": False,
        "has_bip01_pos": has_bip_pos,
        "has_feet": has_feet,
        "animated_bones": animated,
        "unanimated_bones": unanimated,
        "skc_bones": skc_bones,
        "extra_bones": extra,
        "tiki_flags": flags,
        "channel_count": nchan,
        "frame_count": int((skc or {}).get("numFrames") or 0),
        "frame_time": float((skc or {}).get("frameTime") or 0.05),
    }


def log_skc_classification(
    alias: str,
    skc_path: str,
    cls: dict,
    frames: list | None = None,
) -> None:
    """Print the per-clip classification block used for export."""
    fps = 1.0 / float(cls.get("frame_time") or 0.05)
    flags = cls.get("tiki_flags") or []
    height = ""
    if frames:
        raw0 = frames[0] if frames else []
        by = {b.get("name"): b for b in raw0}
        for name in ("Bip01", "Bip01 Pelvis"):
            rec = by.get(name)
            if rec and rec.get("world_t"):
                t = rec["world_t"]
                height += " %s_z=%.3f" % (name.replace(" ", "_"), float(t[2]))
    print("Animation: %s" % alias, flush=True)
    print("Type: %s (%s layer)" % (cls.get("type"), cls.get("layer")), flush=True)
    print("Base pose: %s" % cls.get("base_pose"), flush=True)
    print(
        "Animated bones: %d %s"
        % (len(cls.get("animated_bones") or []), ", ".join((cls.get("animated_bones") or [])[:24])),
        flush=True,
    )
    print(
        "Unanimated bones: %d %s"
        % (len(cls.get("unanimated_bones") or []), ", ".join((cls.get("unanimated_bones") or [])[:24])),
        flush=True,
    )
    print("Frame rate: %.3f" % fps, flush=True)
    print("Frame count: %s" % cls.get("frame_count"), flush=True)
    print(
        "Root motion: bHasDelta=%s Bip01_pos=%s both_feet=%s%s"
        % (cls.get("has_delta"), cls.get("has_bip01_pos"), cls.get("has_feet"), height),
        flush=True,
    )
    print(
        "TIKI flags / channels: flags=%s deltadriven=%s bHasUpper=%s channels=%s file=%s"
        % (
            " ".join(str(f) for f in flags) or "(none)",
            cls.get("delta_driven"),
            cls.get("has_upper"),
            cls.get("channel_count"),
            skc_path,
        ),
        flush=True,
    )


def overlay_skc_channels(base: dict | None, overlay: dict | None) -> dict:
    """Action SKC over idle/locomotion: overlay keys win, missing keep base.

    Matches skeletor GetSlerpValue / GetLerpValue3: a clip only writes channels
    it actually contains. Identity is never invented for omitted bones.
    """
    out = dict(base or {})
    out.update(overlay or {})
    return out


def _skc_animates_bone(keys: set[str], bone: str) -> bool:
    low = (bone or "").lower()
    return (low + " pos") in keys or (low + " rot") in keys


def _focus_names(export_names: list[str]) -> list[str]:
    seen = set()
    out = []
    for name in list(_ANIM_FOCUS_BONES) + list(export_names):
        if not name or name in seen:
            continue
        low = name.lower()
        keep = name in _ANIM_FOCUS_BONES or any(s in low for s in _ANIM_FOCUS_SUBSTR)
        if not keep:
            continue
        seen.add(name)
        out.append(name)
    return out


def parse_tiki_anim_events(body: str) -> list[dict]:
    """Frame-tagged TIKI animation commands. Log-only; never executed."""
    if not (body or "").strip():
        return []
    events: list[dict] = []
    frame = "entry"
    for raw in body.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        tokens = _tokenize(line)
        if not tokens:
            continue
        if tokens == ["}"]:
            continue
        head = tokens[0].lower()
        if head in ("entry", "exit", "first", "last") or tokens[0].isdigit():
            frame = tokens[0]
            tokens = tokens[1:]
            if tokens and tokens[0] == "{":
                tokens = tokens[1:]
            if not tokens:
                continue
        if tokens and tokens[0] == "{":
            continue
        if not tokens:
            continue
        events.append(
            {
                "frame": frame,
                "cmd": tokens[0],
                "args": tokens[1:],
            }
        )
    return events


def log_tiki_anim_events(alias: str, skc_path: str, commands: str, frame_time: float) -> None:
    """Print TIKI animation events for later Unreal reproduction. Does not implement them."""
    events = parse_tiki_anim_events(commands)
    print(
        "[anim-events] %s file=%s commands=%d frameTime=%.4f (log only)"
        % (alias, skc_path, len(events), float(frame_time or 0.0)),
        flush=True,
    )
    if not events:
        print("[anim-events]   (no TIKI command block)", flush=True)
        return
    for ev in events:
        args = " ".join(str(a) for a in (ev.get("args") or []))
        blob = ("%s %s" % (ev.get("cmd") or "", args)).lower()
        hint = any(h in blob for h in (
            "attach", "weapon", "magazine", "mag", "clip", "muzzle", "reload",
            "flash", "sound", "surface", "nodraw", "show", "hide", "cache",
            "tag", "fire", "spawn", "model",
        ))
        mark = " *" if hint else ""
        print(
            "[anim-events]   frame=%s cmd=%s %s%s"
            % (ev.get("frame"), ev.get("cmd"), args, mark),
            flush=True,
        )


def log_animation_focus(
    alias: str,
    bone_groups: list[list[dict]],
    skc: dict,
    frames: list[list[dict]],
    base_channels: dict | None = None,
    compose: str = "",
) -> None:
    """Print SKC raw / local / viewer world / export world for arm bones."""
    bones0 = bone_groups[0] if bone_groups else []
    by_bone = {b["name"]: b for b in bones0}
    n = len(skc.get("frames") or [])
    if n <= 0:
        return
    export_names = [str(b.get("name") or "") for b in (frames[0] if frames else [])]
    merged = set(export_names)
    skc_keys = skc_channel_keys(skc)
    skc_bones = []
    seen_ch = set()
    for ch in skc.get("names") or []:
        bone = _skc_channel_bone(ch)
        key = bone.lower()
        if not bone or key in seen_ch:
            continue
        seen_ch.add(key)
        skc_bones.append(bone)
    extra = [b for b in skc_bones if b not in merged]
    if extra:
        print(
            "[anim-debug] %s SKC channels not on merged skeleton (%d): %s"
            % (alias, len(extra), ", ".join(extra[:24])),
            flush=True,
        )
    print(
        "[anim-compose] %s mode=%s bHasDelta=%s bHasUpper=%s overlay=%s"
        % (
            alias,
            compose or ("overlay_idle" if base_channels else "clip_only"),
            skc_has_delta(skc),
            skc_has_upper(skc),
            "idle" if base_channels else "none",
        ),
        flush=True,
    )
    idxs = sorted({0, n // 2, n - 1})
    print("[anim-debug] %s  (hyphen names are Unreal-imported Bip01-L-UpperArm etc.)" % alias, flush=True)
    low_alias = (alias or "").lower()
    detailed = any(s in low_alias for s in ("shoot", "fire", "reload")) or bool(base_channels)
    focus = _focus_names(export_names) if detailed else list(_ANIM_FOCUS_BONES)
    if detailed:
        focus = list(dict.fromkeys(list(_COMPOSE_LOG_BONES) + list(focus)))
    for fi in idxs:
        raw = skc["frames"][fi]
        chans = overlay_skc_channels(base_channels, raw) if base_channels else raw
        pose = bind_pose_matrices(bones0, chans)
        viewer = {b["name"]: (R, T) for b, (R, T) in zip(bones0, pose)}
        export = {b["name"]: b for b in frames[fi]}
        print("[anim-debug] --- %s frame %d / %d ---" % (alias, fi, n - 1), flush=True)
        for name in focus:
            b = by_bone.get(name)
            raw_pos = _chan(raw, name, "pos", None)
            raw_rot = _chan(raw, name, "rot", None)
            has_pos = (name.lower() + " pos") in skc_keys
            has_rot = (name.lower() + " rot") in skc_keys
            animated = has_pos or has_rot
            pos_src = "skc" if has_pos else ("idle" if base_channels else "default-identity")
            rot_src = "skc" if has_rot else ("idle" if base_channels else "default-identity")
            source = "skc" if (has_pos and has_rot) else (
                "skc+idle" if animated and base_channels else (
                    "idle" if base_channels else "default-identity"
                )
            )
            print(
                "  %s type=%s  animated=%s  mask=%s  base=%s  pos_src=%s rot_src=%s  SKC pos=%s  SKC rot=%s"
                % (
                    name,
                    (b or {}).get("type"),
                    "yes" if animated else "no",
                    "clip-channel" if animated else "inherit",
                    source,
                    pos_src,
                    rot_src,
                    None if raw_pos is None else tuple(round(float(x), 4) for x in raw_pos),
                    None if raw_rot is None else tuple(round(float(x), 4) for x in raw_rot),
                ),
                flush=True,
            )
            if name not in viewer and name not in export:
                print("    missing on first SKD and export", flush=True)
                continue
            if name not in viewer:
                et = tuple(export[name]["world_t"])
                print(
                    "    extra-only export world T %s"
                    % (tuple(round(float(x), 4) for x in et),),
                    flush=True,
                )
                continue
            R, T = viewer[name]
            pr = pt = None
            if b and int(b.get("parent_index", -1)) >= 0:
                pr, pt = pose[b["parent_index"]]
            lr, lt = local_from_world(R, T, pr, pt)
            ex = export.get(name)
            et = tuple(ex["world_t"]) if ex else None
            d = None
            if et is not None:
                d = (
                    (et[0] - T[0]) ** 2 + (et[1] - T[1]) ** 2 + (et[2] - T[2]) ** 2
                ) ** 0.5
            print(
                "    local T %s  composed world T %s  export world T %s  |export-composed|=%s"
                % (
                    tuple(round(float(x), 4) for x in lt),
                    tuple(round(float(x), 4) for x in T),
                    None if et is None else tuple(round(float(x), 4) for x in et),
                    None if d is None else round(d, 4),
                ),
                flush=True,
            )
        for a, bname in _ANIM_LENGTH_PAIRS:
            pa = export.get(a) or {}
            pb = export.get(bname) or {}
            ta = pa.get("world_t")
            tb = pb.get("world_t")
            if not ta or not tb:
                continue
            dist = (
                (float(ta[0]) - float(tb[0])) ** 2
                + (float(ta[1]) - float(tb[1])) ** 2
                + (float(ta[2]) - float(tb[2])) ** 2
            ) ** 0.5
            print(
                "    length %s -> %s  %.3f cm (%.2f in)"
                % (a, bname, dist, dist / 2.54),
                flush=True,
            )


def parse_lod_control(data: bytes) -> dict | None:
    """Parse a MOHAA .lod sidecar (lodControl_t, 24 floats / 96 bytes)."""
    if not data or len(data) < 96:
        return None
    f = struct.unpack_from("<24f", data, 0)
    return {
        "min_metric": f[0],
        "max_metric": f[1],
        "curve": [{"pos": f[2 + i * 2], "val": f[3 + i * 2]} for i in range(5)],
        "consts": [
            {"base": f[12 + i * 3], "scale": f[13 + i * 3], "cutoff": f[14 + i * 3]}
            for i in range(4)
        ],
    }


def extract_skd_lod(data: bytes) -> dict:
    """Read SKD lodIndex[10] plus per-surface pCollapse / pCollapseIndex.

    LightRay3D and Milkshape rewrite the SKD without these tables, which is
    what severs the model from its .lod sidecar. Preview skinning is unchanged.
    """
    empty = {"lod_index": [], "surfaces": []}
    if not data or data[:4] not in (b"SKMD", b"SKL "):
        return empty
    if len(data) < 132:
        return empty
    lod_index = list(struct.unpack_from("<10i", data, 92))
    num_surfs = _u32(data, 72)
    ofs_surfs = _u32(data, 84)
    off = ofs_surfs
    surfaces = []
    for _ in range(num_surfs):
        if off + 100 > len(data):
            break
        name = _cstr(data, off + 4, 64)
        ntri, nvert, _proc, ofs_tri, ofs_vert, ofs_col, ofs_end, ofs_ci = struct.unpack_from(
            "<8I", data, off + 68
        )
        rec = {
            "name": name,
            "nvert": nvert,
            "ntri": ntri,
            "collapse": [],
            "collapse_index": [],
        }
        if nvert and ofs_col and off + ofs_col + nvert * 4 <= min(len(data), off + ofs_end):
            rec["collapse"] = list(struct.unpack_from("<%di" % nvert, data, off + ofs_col))
        if nvert and ofs_ci and off + ofs_ci + nvert * 4 <= min(len(data), off + ofs_end):
            rec["collapse_index"] = list(struct.unpack_from("<%di" % nvert, data, off + ofs_ci))
        surfaces.append(rec)
        off += ofs_end if ofs_end else 100
    return {"lod_index": lod_index, "surfaces": surfaces}


def collapse_vertex_map(
    nvert: int, collapse: list[int], collapse_index: list[int], cutoff: int
) -> list[int]:
    render_count = nvert
    while render_count > 0 and collapse_index[render_count - 1] < cutoff:
        render_count -= 1
    remap = list(range(nvert))
    for k in range(render_count, nvert):
        src = collapse[k] if k < len(collapse) else 0
        remap[k] = remap[src] if 0 <= src < nvert else 0
    return remap


def bake_lod_payload(payload: dict, surfaces: dict, cutoff: int) -> dict | None:
    """Build a lower-detail copy of a posed export payload using SKD collapse."""
    pos = payload.get("positions") or []
    nrm = payload.get("normals") or []
    uvs = payload.get("uvs") or []
    idx = payload.get("indices") or []
    mats = payload.get("materials") or []
    groups = payload.get("groups") or []
    new_pos: list[float] = []
    new_nrm: list[float] = []
    new_uv: list[float] = []
    new_idx: list[int] = []
    new_groups: list[dict] = []
    new_mats: list[dict] = []
    total_tris = 0

    def _push_vert(old: int, remap: dict[int, int]) -> int:
        if old not in remap:
            remap[old] = len(new_pos) // 3
            o3 = old * 3
            o2 = old * 2
            if o3 + 2 < len(pos):
                new_pos.extend(pos[o3 : o3 + 3])
            else:
                new_pos.extend((0.0, 0.0, 0.0))
            if o3 + 2 < len(nrm):
                new_nrm.extend(nrm[o3 : o3 + 3])
            else:
                new_nrm.extend((0.0, 0.0, 1.0))
            if o2 + 1 < len(uvs):
                new_uv.extend(uvs[o2 : o2 + 2])
            else:
                new_uv.extend((0.0, 0.0))
        return remap[old]

    for gi, g in enumerate(groups):
        mat = mats[gi] if gi < len(mats) else {}
        if mat.get("nodraw") or mat.get("status") == "NODRAW":
            continue
        start = int(g.get("start") or 0)
        count = int(g.get("count") or 0)
        g_idx = idx[start : start + count]
        if len(g_idx) < 3:
            continue
        rec = surfaces.get(g["name"]) or {}
        nvert = int(rec.get("nvert") or g.get("vert_count") or 0)
        vert_base = int(g.get("vert_base") if g.get("vert_base") is not None else min(g_idx))
        cmap = []
        if nvert and rec.get("collapse") and rec.get("collapse_index"):
            cmap = collapse_vertex_map(nvert, rec["collapse"], rec["collapse_index"], cutoff)
        remap: dict[int, int] = {}
        gstart = len(new_idx)
        for t in range(0, len(g_idx) - 2, 3):
            trip = []
            for k in range(3):
                old = g_idx[t + k]
                if cmap:
                    local = old - vert_base
                    if 0 <= local < nvert:
                        old = vert_base + cmap[local]
                trip.append(old)
            if trip[0] == trip[1] or trip[1] == trip[2] or trip[0] == trip[2]:
                continue
            new_idx.extend(_push_vert(v, remap) for v in trip)
        gc = len(new_idx) - gstart
        if gc < 3:
            continue
        total_tris += gc // 3
        ng = dict(g)
        ng["start"] = gstart
        ng["count"] = gc
        ng["vert_base"] = 0
        ng["vert_count"] = len(remap)
        new_groups.append(ng)
        nm = dict(mat)
        nm["start"] = gstart
        nm["count"] = gc
        new_mats.append(nm)

    if total_tris < 8:
        return None
    out = dict(payload)
    out["positions"] = new_pos
    out["normals"] = new_nrm
    out["uvs"] = new_uv
    out["indices"] = new_idx
    out["groups"] = new_groups
    out["materials"] = new_mats
    out["vertexCount"] = len(new_pos) // 3
    out["triangleCount"] = total_tris
    return out


def pick_lod_cutoffs(lod_index: list[int], payload: dict, surfaces: dict, want: int = 3) -> list[int]:
    positive = [v for v in lod_index if v > 0]
    if not positive or not surfaces:
        return []
    orig = int(payload.get("triangleCount") or len(payload.get("indices") or []) // 3)
    min_tris = max(12, int(orig * 0.04))
    n = len(positive)
    raw = []
    for frac in (0.25, 0.5, 0.7)[:want]:
        raw.append(positive[min(n - 1, max(0, int(round(frac * (n - 1)))))])
    chosen = []
    for cut in raw:
        if cut in chosen:
            continue
        baked = bake_lod_payload(payload, surfaces, cut)
        if baked and int(baked.get("triangleCount") or 0) >= min_tris:
            chosen.append(cut)
    return chosen


def lod_screen_sizes(n_extra: int, lod_control: dict | None) -> list[float]:
    sizes = [1.0]
    pts = [c for c in (lod_control or {}).get("curve") or [] if float(c.get("pos") or 0) > 0.05]
    for i in range(n_extra):
        if i < len(pts):
            sizes.append(max(0.05, 1.0 - float(pts[i]["pos"])))
        else:
            sizes.append(max(0.05, 0.5 / float(2**i)))
    return sizes
