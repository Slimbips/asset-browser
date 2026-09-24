"""Write the preview mesh to OBJ/FBX and optionally import it into the selected UE project."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path

from PIL import Image

from formats import BSP_CM_PER_UNIT, bake_lod_payload, cubemap_to_equirect, lod_screen_sizes, pick_lod_cutoffs, write_dds_cubemap

ROOT = Path(__file__).resolve().parent
EXPORT_ROOT = ROOT / "export"
BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")
BLENDER_SCRIPT = ROOT / "tools" / "blender_asset_fbx.py"
UE_EDITOR = Path(r"D:\epicgames\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe")
UE_EDITOR_UI = Path(r"D:\epicgames\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe")
UE_PROJECT = Path(r"D:\Games\test\Stalingrad\Stalingrad.uproject")
UE_IMPORT_SRC = ROOT / "tools" / "ue_import_asset.py"
UE_OPAQUE_SRC = ROOT / "tools" / "fix_mohaa_opaque.py"
UE_CHARACTER_READY_SRC = ROOT / "tools" / "ue_character_ready.py"
PACK_T3D_SRC = ROOT / "tools" / "pack_retarget"
UE_REMOTE_PY = Path(
    r"D:\epicgames\UE_5.8\Engine\Plugins\Experimental\PythonScriptPlugin\Content\Python"
)

PROGRESS = {"pct": 0, "status": "Ready", "active": False}
_ACTIVE_PROJECT: Path | None = None


def get_active_project() -> Path | None:
    return _ACTIVE_PROJECT


def set_active_project(value: str | Path | None = None) -> Path:
    global _ACTIVE_PROJECT
    project = resolve_project(value)
    _ACTIVE_PROJECT = project
    return project


def resolve_project(value: str | Path | None = None) -> Path:
    raw = str(value).strip().strip('"') if value is not None else ""
    if not raw:
        if _ACTIVE_PROJECT is not None:
            return _ACTIVE_PROJECT
        if UE_PROJECT.is_file():
            raw = str(UE_PROJECT)
        else:
            raise ValueError("Choose an Unreal project first")
    candidate = Path(raw).expanduser()
    if candidate.is_dir():
        matches = sorted(candidate.glob("*.uproject"))
        if len(matches) != 1:
            raise ValueError("Choose a folder containing one .uproject file, or select the .uproject file itself.")
        candidate = matches[0]
    if candidate.suffix.lower() != ".uproject" or not candidate.is_file():
        raise ValueError("Unreal project not found. Choose a project folder or an existing .uproject file.")
    try:
        data = json.loads(candidate.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as exc:
        raise ValueError("Cannot read Unreal project: " + str(exc)) from exc
    if not isinstance(data, dict) or "FileVersion" not in data:
        raise ValueError("This file is not a valid Unreal project descriptor.")
    project = candidate.resolve()
    ensure_project_python(project, data)
    return project


def ensure_project_python(project: Path, data: dict | None = None) -> None:
    """A stock Third Person project can Convert without the user enabling Python."""
    if data is None:
        try:
            data = json.loads(project.read_text(encoding="utf-8-sig"))
        except (ValueError, OSError):
            return
    plugins = list(data.get("Plugins") or [])
    names = {
        str(item.get("Name") or "").lower()
        for item in plugins
        if isinstance(item, dict)
    }
    changed = False
    if "pythonscriptplugin" not in names:
        plugins.append({"Name": "PythonScriptPlugin", "Enabled": True})
        data["Plugins"] = plugins
        changed = True
    if changed:
        project.write_text(json.dumps(data, indent="\t") + "\n", encoding="utf-8")
        print("[ue] enabled PythonScriptPlugin on %s" % project.name, flush=True)
    ini = project.parent / "Config" / "DefaultEngine.ini"
    try:
        text = ini.read_text(encoding="utf-8") if ini.is_file() else ""
    except OSError:
        return
    section = "[/Script/PythonScriptPlugin.PythonScriptPluginSettings]"
    if section in text and "bRemoteExecution=" in text:
        if re.search(r"bRemoteExecution\s*=\s*True", text, re.I):
            return
        text = re.sub(r"bRemoteExecution\s*=\s*\w+", "bRemoteExecution=True", text, count=1, flags=re.I)
    elif section in text:
        text = text.replace(section, section + "\nbRemoteExecution=True", 1)
    else:
        extra = (
            "\n%s\n"
            "bRemoteExecution=True\n"
            "RemoteExecutionMulticastGroupEndpoint=239.0.0.1:6766\n"
            "RemoteExecutionMulticastBindAddress=127.0.0.1\n"
            % section
        )
        text = (text.rstrip() + extra) if text.strip() else extra.lstrip()
    ini.parent.mkdir(parents=True, exist_ok=True)
    ini.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    print("[ue] enabled Python remote execution in DefaultEngine.ini", flush=True)


def launch_unreal_editor(project: str | Path | None = None) -> dict:
    """Open the chosen .uproject in Unreal Editor. Does not close a running editor."""
    project = resolve_project(project)
    editor = UE_EDITOR_UI if UE_EDITOR_UI.is_file() else None
    if editor is not None:
        flags = 0
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags |= subprocess.DETACHED_PROCESS
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            [str(editor), str(project)],
            cwd=str(project.parent),
            close_fds=True,
            creationflags=flags,
        )
    else:
        os.startfile(str(project))
    return {
        "launched": True,
        "project": str(project),
        "folder": str(project.parent),
        "name": project.stem,
        "editor": str(editor or ""),
    }


def matching_editor(nodes, project):
    # Names alone are not unique: two different folders can both contain Game.uproject.
    for node in nodes:
        root = node.get("project_root")
        if root and Path(root).resolve() == project.parent.resolve() and node.get("project_name") == project.stem:
            return node
    return None


def set_progress(pct: int, status: str) -> None:
    PROGRESS["pct"] = max(0, min(100, int(pct)))
    PROGRESS["status"] = status
    PROGRESS["active"] = True
    print("[export] %d%% %s" % (PROGRESS["pct"], status), flush=True)


def _png_opaque(data: bytes) -> bytes:
    """Drop leftover TGA alpha so Unreal does not treat the mesh as glass."""
    img = Image.open(BytesIO(data))
    if img.mode != "RGB":
        img = img.convert("RGB")
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _png_missing() -> bytes:
    """Honest missing albedo so Unreal does not reuse another slot's TGA."""
    img = Image.new("RGB", (16, 16), (255, 0, 255))
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name or "asset").strip("_")
    return s[:80] or "asset"


def _safe_mat(name: str, used: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_]+", "_", name or "mat").strip("_") or "mat"
    if base[0].isdigit():
        base = "m_" + base
    out = base
    n = 2
    while out.lower() in used:
        out = "%s_%d" % (base, n)
        n += 1
    used.add(out.lower())
    return out


def prop_shell_faces_neg_z(pos: list, nrm: list) -> bool:
    """Shallow idle-posed dish whose decorative front points toward -Z.

    Furniture SKD bind is 3dsmax Y-up. Idle quat (0.5, 0.5, 0.5, -0.5) maps
    bone +Y → world +Z, so chair feet stay at min Z. Plate bowls also open
    +Z, but every SKD normal is −Y in bind (−Z after idle). A global 180°
    pitch would invert chairs/tables/trees; only this shell is flipped.
    """
    if not pos or not nrm or len(pos) < 9 or len(nrm) < 3:
        return False
    nz = [nrm[i + 2] for i in range(0, len(nrm), 3)]
    avg_nz = sum(nz) / len(nz)
    if avg_nz > -0.5:
        return False
    xs = [pos[i] for i in range(0, len(pos), 3)]
    ys = [pos[i + 1] for i in range(0, len(pos), 3)]
    zs = [pos[i + 2] for i in range(0, len(pos), 3)]
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    dz = max(zs) - min(zs)
    span = max(dx, dy)
    return span > 1e-6 and dz <= 0.45 * span


def write_obj(
    payload: dict,
    dest: Path,
    category: str,
    tex_png,
    stem: str | None = None,
    write_textures: bool = True,
) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    stem = stem or dest.name
    obj_path = dest / (stem + ".obj")
    mtl_path = dest / (stem + ".mtl")
    pos = payload.get("positions") or []
    nrm = payload.get("normals") or []
    uvs = payload.get("uvs") or []
    idx = payload.get("indices") or []
    mats = payload.get("materials") or []
    flip_weapon = (category or "").lower() == "weapons"
    # Keep vertex Z (bowl stays concave-up). Reverse winding + normals so the
    # floral/eating face is +Z after Unreal's FBX Y-mirror.
    flip_shell = (category or "").lower() == "props" and prop_shell_faces_neg_z(pos, nrm)
    if flip_shell:
        print("[obj] flip down-facing prop shell %s avg_nz was negative" % (stem or dest.name), flush=True)
    used = set()
    mat_names = []
    tex_files = []

    mtl_lines = ["# MOHAA asset\n"]
    for i, mat in enumerate(mats):
        mname = _safe_mat(mat.get("surface") or mat.get("shader") or "mat%d" % i, used)
        mat_names.append(mname)
        mtl_lines.append("newmtl %s\nKd %.2f %.2f %.2f\nKs 0.05 0.05 0.05\nNs 12\n" % (
            mname, 1.0 if write_textures else 0.62, 1.0 if write_textures else 0.62, 1.0 if write_textures else 0.62
        ))
        tex_path = mat.get("texture")
        if not write_textures:
            mtl_lines.append("\n")
            continue
        if mat.get("status") == "FOUND" and tex_path and not str(tex_path).startswith("/"):
            png_name = slug(Path(str(tex_path).replace("\\", "/")).stem) + ".png"
            png_path = dest / png_name
            try:
                if write_textures or not png_path.is_file():
                    png = tex_png(tex_path)
                    png = _png_opaque(png)
                    png_path.write_bytes(png)
                mtl_lines.append("map_Kd %s\n" % png_name)
                tex_files.append(str(png_path))
            except Exception as exc:
                mtl_lines.append("# texture failed %s: %s\n" % (tex_path, exc))
        elif (mat.get("status") or "").upper() == "MISSING" and not mat.get("nodraw") and not mat.get("is_sky"):
            sh = str(mat.get("shader") or mat.get("surface") or "missing").replace("\\", "/")
            png_name = slug(Path(sh).stem) + "_MISSING.png"
            png_path = dest / png_name
            try:
                if write_textures or not png_path.is_file():
                    png_path.write_bytes(_png_missing())
                mtl_lines.append("map_Kd %s\n" % png_name)
                mtl_lines.append("# MISSING %s\n" % (mat.get("missing") or sh))
                tex_files.append(str(png_path))
            except Exception as exc:
                mtl_lines.append("# missing placeholder failed %s: %s\n" % (sh, exc))
        mtl_lines.append("\n")
    mtl_path.write_text("".join(mtl_lines), encoding="utf-8")

    lines = ["mtllib %s\n" % mtl_path.name]
    nverts = len(pos) // 3
    for i in range(nverts):
        x, y, z = pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]
        if flip_weapon:
            y, z = -y, -z
        lines.append("v %.6f %.6f %.6f\n" % (x, y, z))
    for i in range(len(uvs) // 2):
        lines.append("vt %.6f %.6f\n" % (uvs[i * 2], uvs[i * 2 + 1]))
    for i in range(len(nrm) // 3):
        nx, ny, nz = nrm[i * 3], nrm[i * 3 + 1], nrm[i * 3 + 2]
        if flip_weapon:
            ny, nz = -ny, -nz
        if flip_shell:
            nx, ny, nz = -nx, -ny, -nz
        lines.append("vn %.6f %.6f %.6f\n" % (nx, ny, nz))

    for mi, mat in enumerate(mats):
        if mat.get("nodraw") or mat.get("status") == "NODRAW":
            continue
        start = int(mat.get("start") or 0)
        count = int(mat.get("count") or 0)
        if count <= 0:
            continue
        lines.append("usemtl %s\ng %s\n" % (mat_names[mi], mat_names[mi]))
        for t in range(0, count, 3):
            a = idx[start + t] + 1
            b = idx[start + t + 1] + 1
            c = idx[start + t + 2] + 1
            if flip_shell:
                b, c = c, b
            lines.append("f %d/%d/%d %d/%d/%d %d/%d/%d\n" % (a, a, a, b, b, b, c, c, c))
    obj_path.write_text("".join(lines), encoding="utf-8")
    return {"obj": str(obj_path), "mtl": str(mtl_path), "textures": tex_files, "verts": nverts}


def write_sky_export(sky: dict, dest: Path, tex_png) -> dict:
    """Write Q3 cubemap faces, a DDS TextureCube, and an equirect PNG for Unreal."""
    dest.mkdir(parents=True, exist_ok=True)
    env = str(sky.get("env") or "sky")
    stem = slug(Path(env.replace("\\", "/")).name or "sky")
    faces_out = {}
    images = {}
    tex_files = []
    for side, vfs_path in (sky.get("faces") or {}).items():
        if not vfs_path:
            continue
        png_name = "%s_%s.png" % (stem, side)
        png_path = dest / png_name
        png = _png_opaque(tex_png(vfs_path))
        png_path.write_bytes(png)
        faces_out[side] = str(png_path)
        tex_files.append(str(png_path))
        images[side] = Image.open(BytesIO(png)).convert("RGB")
    if len(images) < 4:
        return {
            "env": env,
            "faces": faces_out,
            "files": tex_files,
            "cubemap_dds": "",
            "equirect": "",
        }
    dds_path = dest / (stem + "_cube.dds")
    write_dds_cubemap(images, dds_path)
    tex_files.append(str(dds_path))
    eq_path = dest / (stem + "_equirect.png")
    cubemap_to_equirect(images).save(eq_path, format="PNG")
    tex_files.append(str(eq_path))
    print(
        "[export] sky %s faces %d dds %s equirect %s"
        % (env, len(images), dds_path.name, eq_path.name),
        flush=True,
    )
    return {
        "env": env,
        "faces": faces_out,
        "files": tex_files,
        "cubemap_dds": str(dds_path),
        "equirect": str(eq_path),
    }


def _finite(v) -> bool:
    try:
        return all(math.isfinite(float(x)) for x in v)
    except Exception:
        return False


def _finite_mat(R) -> bool:
    try:
        return all(_finite(row) for row in R)
    except Exception:
        return False


def validate_skeletal(payload: dict) -> dict:
    """Log skeleton/skin stats and collect errors. Does not invent weights."""
    import math as _math

    bones = list(payload.get("skeleton") or [])
    influences = list(payload.get("influences") or [])
    nverts = len(payload.get("positions") or []) // 3
    ntris = len(payload.get("indices") or []) // 3
    errors: list[str] = []
    weighted = 0
    zero_inf = 0
    bad_sum = 0
    max_inf = 0
    by_name = {}
    for i, b in enumerate(bones):
        name = str(b.get("name") or "")
        idx = int(b.get("index", i))
        parent = int(b.get("parent_index", -1))
        if name in by_name:
            errors.append("duplicate bone name '%s' at %d and %d" % (name, by_name[name], idx))
        by_name[name] = idx
        if parent < -1 or parent >= len(bones):
            errors.append("bone %d '%s' missing parent index %d" % (idx, name, parent))
        lt = b.get("local_t") or b.get("pos") or [0, 0, 0]
        lq = b.get("local_quat") or [0, 0, 0, 1]
        wr = b.get("world_r")
        wt = b.get("world_t") or b.get("pos")
        if not _finite(lt) or not _finite(lq) or (wr is not None and not _finite_mat(wr)) or not _finite(wt):
            errors.append("bone %d '%s' has NaN/Inf transform" % (idx, name))
    if len(influences) != nverts:
        errors.append("influence count %d != vertex count %d" % (len(influences), nverts))
    n_bones = len(bones)
    for vi, inf in enumerate(influences):
        pairs = inf or []
        max_inf = max(max_inf, len(pairs))
        if not pairs:
            zero_inf += 1
            continue
        weighted += 1
        wsum = 0.0
        for item in pairs:
            bi = int(item[0])
            w = float(item[1])
            if bi < 0 or bi >= n_bones:
                errors.append("vertex %d invalid bone index %d" % (vi, bi))
            if w < 0.0 or not _math.isfinite(w):
                errors.append("vertex %d invalid weight %s on bone %d" % (vi, w, bi))
            wsum += w
        if abs(wsum - 1.0) > 0.02:
            bad_sum += 1
    lines = [
        "Skeleton:",
        "bone count %d" % n_bones,
    ]
    for i, b in enumerate(bones):
        lt = b.get("local_t") or [0, 0, 0]
        lq = b.get("local_quat") or [0, 0, 0, 1]
        lines.append(
            "bone %d name=%s parent=%d local_pos=(%.6f %.6f %.6f) local_rot=(%.6f %.6f %.6f %.6f)"
            % (
                int(b.get("index", i)),
                b.get("name") or "",
                int(b.get("parent_index", -1)),
                float(lt[0]),
                float(lt[1]),
                float(lt[2]),
                float(lq[0]),
                float(lq[1]),
                float(lq[2]),
                float(lq[3]),
            )
        )
    lines.extend(
        [
            "Mesh:",
            "vertex count %d" % nverts,
            "triangle count %d" % ntris,
            "Skin:",
            "number of weighted vertices %d" % weighted,
            "maximum influences per vertex %d" % max_inf,
            "vertices with zero influences %d" % zero_inf,
            "weights not summing approximately to 1.0 %d" % bad_sum,
        ]
    )
    if errors:
        lines.append("Errors:")
        # Keep the log readable; unique the first 80.
        seen = []
        for err in errors:
            if err not in seen:
                seen.append(err)
            if len(seen) >= 80:
                break
        lines.extend(seen)
        if len(errors) > len(seen):
            lines.append("... %d more errors" % (len(errors) - len(seen)))
    report = "\n".join(lines)
    print("[skel]\n" + report, flush=True)
    return {
        "bone_count": n_bones,
        "vertex_count": nverts,
        "triangle_count": ntris,
        "weighted_vertices": weighted,
        "max_influences": max_inf,
        "zero_influences": zero_inf,
        "bad_weight_sum": bad_sum,
        "error_count": len(errors),
        "errors": errors[:80],
        "report": report,
    }


def write_skel_json(payload: dict, dest: Path, stem: str, animations: list | None = None) -> Path:
    path = dest / (stem + ".skel.json")
    data = {
        "bones": payload.get("skeleton") or [],
        "influences": payload.get("influences") or [],
        "positions": payload.get("positions") or [],
        "normals": payload.get("normals") or [],
        "uvs": payload.get("uvs") or [],
        "indices": payload.get("indices") or [],
        "groups": payload.get("materials") or payload.get("groups") or [],
        "animations": animations or [],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def run_blender(
    obj_path: Path,
    fbx_path: Path,
    skel_path: Path | None = None,
    map_mode: bool = False,
) -> str:
    if not BLENDER.is_file():
        raise FileNotFoundError("Blender not found: %s" % BLENDER)
    fbx_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(BLENDER),
        "--background",
        "--python",
        str(BLENDER_SCRIPT),
        "--",
        str(obj_path),
        str(fbx_path),
    ]
    if skel_path:
        cmd.append(str(skel_path))
    if map_mode:
        cmd.append("--map")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    log = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    for line in log.splitlines():
        if (
            "Mesh size" in line
            or line.startswith("Wrote ")
            or "map mode" in line
            or "map aabb" in line
            or "Y-mirror" in line
        ):
            print("[blender]", line, flush=True)
    if proc.returncode != 0 or not fbx_path.is_file():
        raise RuntimeError("Blender FBX export failed (%s)\n%s" % (proc.returncode, log[-4000:]))
    return log[-2000:]


def write_ue_import_script(
    fbx_path: Path,
    asset_name: str,
    category: str,
    lod_fbxs: list[Path] | None = None,
    screen_sizes: list[float] | None = None,
    skeletal: bool = False,
    anim_fbxs: list[dict] | None = None,
    project: Path | None = None,
    kind: str = "",
    sky: dict | None = None,
    with_textures: bool = True,
    furniture: list[dict] | None = None,
) -> Path:
    project = resolve_project(project)
    UE_IMPORT_PY = project.parent / "Content" / "Python" / "import_mohaa_asset.py"
    UE_IMPORT_JOB = UE_IMPORT_PY.with_name("import_mohaa_job.json")
    UE_CHARACTER_READY_DST = UE_IMPORT_PY.with_name("ue_character_ready.py")
    PACK_T3D_DST = UE_IMPORT_PY.parent / "pack_retarget"
    dest = "/Game/MOHAA/" + slug(category or "Assets")
    UE_IMPORT_PY.parent.mkdir(parents=True, exist_ok=True)
    UE_IMPORT_PY.write_text(UE_IMPORT_SRC.read_text(encoding="utf-8"), encoding="utf-8")
    if UE_OPAQUE_SRC.is_file():
        (UE_IMPORT_PY.parent / "fix_mohaa_opaque.py").write_text(
            UE_OPAQUE_SRC.read_text(encoding="utf-8"), encoding="utf-8"
        )
    if skeletal:
        UE_CHARACTER_READY_DST.write_text(
            UE_CHARACTER_READY_SRC.read_text(encoding="utf-8"), encoding="utf-8"
        )
        PACK_T3D_DST.mkdir(parents=True, exist_ok=True)
        for t3d in PACK_T3D_SRC.glob("*.T3D"):
            shutil.copy2(t3d, PACK_T3D_DST / t3d.name)
    job = {
        "project": str(project),
        "fbx": str(fbx_path),
        "dest": dest,
        "name": asset_name,
        "lod_files": [str(p) for p in (lod_fbxs or [])],
        "screens": list(screen_sizes or [1.0]),
        "skeletal": bool(skeletal),
        "kind": kind or (("map" if (category or "").lower() == "maps" else "")),
        "anim_files": [
            {
                "fbx": str(a["fbx"]),
                "name": a["name"],
                "fps": float(a.get("fps") or 30.0),
            }
            for a in (anim_fbxs or [])
        ],
        "sky": sky or {},
        "with_textures": bool(with_textures),
        "furniture": list(furniture or []),
    }
    UE_IMPORT_JOB.write_text(json.dumps(job, indent=2), encoding="utf-8")
    return UE_IMPORT_PY


def _run_unreal_live(script: Path, project: Path) -> dict | None:
    """Import into the already-open editor instead of launching UnrealEditor-Cmd."""
    if str(UE_REMOTE_PY) not in sys.path:
        sys.path.insert(0, str(UE_REMOTE_PY))
    try:
        import remote_execution as re
    except Exception as exc:
        print("[ue] remote module missing: %s" % exc, flush=True)
        return None
    session = re.RemoteExecution()
    try:
        session.start()
        node = None
        for _ in range(40):
            time.sleep(0.5)
            nodes = session.remote_nodes or []
            node = matching_editor(nodes, project)
            if node:
                break
        if not node:
            return None
        set_progress(86, "Importing into open Unreal editor")
        session.open_command_connection(node["node_id"])
        # Run the copied file so Content/Python imports (fix_mohaa_opaque, pack T3Ds)
        # resolve. Dumping the source as a <string> fails on a fresh Third Person project.
        data = session.run_command(str(script), unattended=True, exec_mode=re.MODE_EXEC_FILE)
        chunks = []
        for item in data.get("output") or []:
            if isinstance(item, dict):
                chunks.append(str(item.get("output") or ""))
            else:
                chunks.append(str(item))
        log = "\n".join(chunks)
        if data.get("result"):
            log += "\n" + str(data.get("result"))
        ok = bool(data.get("success"))
        ready = ""
        for line in log.splitlines():
            if "CHARACTER READY ok=" in line or line.startswith("CHARACTER READY FAILED"):
                ready = line.strip()
        return {
            "imported": ok,
            "exit": 0 if ok else 1,
            "asset": "",
            "log": log[-4000:],
            "script": str(script),
            "via": "live-editor",
            "character_ready": ready,
        }
    except Exception as exc:
        print("[ue] live import failed: %s" % exc, flush=True)
        return {
            "imported": False,
            "reason": str(exc),
            "via": "live-editor",
            "log": str(exc),
            "exit": 1,
            "asset": "",
            "script": str(script),
        }
    finally:
        try:
            session.stop()
        except Exception:
            pass


def run_unreal_import(
    fbx_path: Path,
    asset_name: str,
    category: str,
    lod_fbxs: list[Path] | None = None,
    screen_sizes: list[float] | None = None,
    skeletal: bool = False,
    anim_fbxs: list[dict] | None = None,
    project: Path | None = None,
    kind: str = "",
    sky: dict | None = None,
    with_textures: bool = True,
    furniture: list[dict] | None = None,
) -> dict:
    project = resolve_project(project)
    if not UE_EDITOR.is_file():
        return {"imported": False, "reason": "Configured Unreal Editor not found"}
    set_progress(80, "Writing Unreal import script")
    script = write_ue_import_script(
        fbx_path,
        asset_name,
        category,
        lod_fbxs,
        screen_sizes,
        skeletal=skeletal,
        anim_fbxs=anim_fbxs,
        project=project,
        kind=kind,
        sky=sky,
        with_textures=with_textures,
        furniture=furniture,
    )
    if skeletal:
        set_progress(86, "Importing character, TIKI anims, Manny retarget")
    live = _run_unreal_live(script, project)
    if live is not None:
        live["lods"] = len(lod_fbxs or [])
        return live
    set_progress(84, "Starting Unreal (close the editor if this waits)")
    cmd = [
        str(UE_EDITOR),
        str(project),
        "-unattended",
        "-nopause",
        "-nosplash",
        "-ExecutePythonScript=%s" % script,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return {
            "imported": False,
            "reason": "Unreal import timed out. Close the editor and try again.",
            "exit": -1,
            "asset": "",
            "log": "",
            "script": str(script),
            "lods": len(lod_fbxs or []),
        }
    log = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    uasset = project.parent / "Content" / "MOHAA" / slug(category or "Assets") / (asset_name + ".uasset")
    editor_log = project.parent / "Saved" / "Logs" / (project.stem + ".log")
    if editor_log.is_file():
        try:
            log += "\n" + editor_log.read_text(encoding="utf-8", errors="replace")[-4000:]
        except Exception:
            pass
    ok = proc.returncode == 0 and (uasset.is_file() or "IMPORTED" in log)
    return {
        "imported": ok,
        "exit": proc.returncode,
        "asset": str(uasset) if uasset.is_file() else "",
        "log": log[-3000:],
        "script": str(script),
        "lods": len(lod_fbxs or []),
        "via": "unreal-cmd",
    }


def _copy_lod_sidecars(dest: Path, stem: str, lod_bundle: dict | None, raw_import: Path) -> list[str]:
    copied = []
    files = (lod_bundle or {}).get("files") or []
    raw_import.mkdir(parents=True, exist_ok=True)
    seen = set()
    for item in files:
        data = item.get("bytes") or b""
        if not data:
            continue
        src_stem = item.get("stem") or stem
        names = [src_stem + ".lod"]
        if src_stem != stem:
            names.append(stem + ".lod")
        for name in names:
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            out = dest / name
            out.write_bytes(data)
            (raw_import / name).write_bytes(data)
            copied.append(str(out))
    return copied


def export_asset(
    payload: dict,
    name: str,
    category: str,
    tex_png,
    into_unreal: bool = True,
    lod_bundle: dict | None = None,
    skeletal: bool = False,
    anim_bundle: dict | None = None,
    project: str | Path | None = None,
    with_textures: bool = True,
    furniture_jobs: list[dict] | None = None,
) -> dict:
    project = resolve_project(project) if into_unreal else None
    is_map = (payload.get("kind") == "map") or (category or "").lower() == "maps"
    if is_map:
        skeletal = False
        pts = payload.get("positions") or []
        payload["positions"] = [float(v) * BSP_CM_PER_UNIT for v in pts]
        print(
            "[export] map scale %.2f cm/unit (%d verts)" % (BSP_CM_PER_UNIT, len(pts) // 3),
            flush=True,
        )
    stem = slug(name or Path(payload.get("source") or "asset").stem)
    dest = EXPORT_ROOT / stem
    raw_import = project.parent / "RawImport" / "MOHAA" if project else dest / "RawImport"
    set_progress(8, "Writing OBJ")
    if dest.exists():
        for old in dest.glob("*"):
            if old.is_file():
                old.unlink()
        props_old = dest / "props"
        if props_old.is_dir():
            for old in props_old.glob("*"):
                if old.is_file():
                    old.unlink()
    written = write_obj(payload, dest, category, tex_png, write_textures=with_textures)
    sky_job = {}
    if is_map and with_textures and payload.get("sky") and (payload["sky"].get("faces") or {}):
        set_progress(12, "Writing sky cubemap")
        sky_job = write_sky_export(payload["sky"], dest, tex_png)
        written["textures"].extend(sky_job.get("files") or [])
    fbx_path = dest / (stem + ".fbx")
    skel_path = None
    skel_debug = None
    if skeletal:
        set_progress(12, "Validating skeleton and skin weights")
        skel_debug = validate_skeletal(payload)
        if not (payload.get("skeleton") or []):
            raise RuntimeError("Skeletal export needs SKD bones; none found on this asset")
        anims = list((anim_bundle or {}).get("clips") or [])
        skel_path = write_skel_json(payload, dest, stem, animations=anims)
        (dest / (stem + ".skel.txt")).write_text(skel_debug["report"], encoding="utf-8")
    set_progress(22, "Blender FBX")
    blender_log = run_blender(Path(written["obj"]), fbx_path, skel_path, map_mode=is_map)
    raw_import.mkdir(parents=True, exist_ok=True)
    copied = raw_import / fbx_path.name
    copied.write_bytes(fbx_path.read_bytes())
    for rel in sky_job.get("files") or []:
        src = Path(rel)
        if src.is_file():
            (raw_import / src.name).write_bytes(src.read_bytes())
    lod_paths = _copy_lod_sidecars(dest, stem, lod_bundle, raw_import)
    lod_fbxs: list[Path] = []
    lod_stats = []
    if not skeletal and not is_map:
        surfaces = (lod_bundle or {}).get("surfaces") or {}
        set_progress(40, "Building LOD meshes")
        cutoffs = pick_lod_cutoffs((lod_bundle or {}).get("lod_index") or [], payload, surfaces)
        for i, cut in enumerate(cutoffs, start=1):
            baked = bake_lod_payload(payload, surfaces, cut)
            if not baked:
                continue
            set_progress(40 + i * 12, "Blender LOD %d" % i)
            lod_stem = "%s_LOD%d" % (stem, i)
            lod_written = write_obj(
                baked, dest, category, tex_png, stem=lod_stem, write_textures=False
            )
            lod_fbx = dest / (lod_stem + ".fbx")
            blender_log += "\n" + run_blender(Path(lod_written["obj"]), lod_fbx)
            raw_lod = raw_import / lod_fbx.name
            raw_lod.write_bytes(lod_fbx.read_bytes())
            lod_fbxs.append(lod_fbx)
            lod_stats.append(
                {
                    "lod": i,
                    "cutoff": cut,
                    "verts": baked.get("vertexCount"),
                    "tris": baked.get("triangleCount"),
                    "fbx": str(lod_fbx),
                }
            )
    screens = lod_screen_sizes(len(lod_fbxs), (lod_bundle or {}).get("lod_control"))
    anim_fbx_list = []
    if skeletal:
        for clip in (anim_bundle or {}).get("clips") or []:
            alias = slug(clip.get("name") or clip.get("alias") or "anim")
            ap = dest / ("%s_A_%s.fbx" % (stem, alias))
            if ap.is_file():
                (raw_import / ap.name).write_bytes(ap.read_bytes())
                names = ["AS_" + stem + "_" + alias]
                for extra in clip.get("ue_aliases") or []:
                    extra_name = "AS_" + stem + "_" + slug(extra)
                    if extra_name not in names:
                        names.append(extra_name)
                for as_name in names:
                    anim_fbx_list.append(
                        {
                            "fbx": ap,
                            "name": as_name,
                            "fps": float(clip.get("fps") or 30.0),
                        }
                    )
            else:
                print("[anim] blender missing %s" % ap, flush=True)
    furniture_out = []
    if is_map and furniture_jobs:
        props_dir = dest / "props"
        props_dir.mkdir(parents=True, exist_ok=True)
        raw_props = raw_import / "props"
        raw_props.mkdir(parents=True, exist_ok=True)
        nprop = len(furniture_jobs)
        for i, fj in enumerate(furniture_jobs):
            pstem = slug(fj.get("name") or "prop")
            set_progress(58 + int(20 * i / max(nprop, 1)), "Furniture %s" % pstem)
            prop_payload = dict(fj.get("payload") or {})
            if not prop_payload.get("positions"):
                print("[furniture] empty mesh %s" % pstem, flush=True)
                continue
            try:
                written_p = write_obj(
                    prop_payload,
                    props_dir,
                    "props",
                    tex_png,
                    stem=pstem,
                    write_textures=True,
                )
                pfbx = props_dir / (pstem + ".fbx")
                blender_log += "\n" + run_blender(Path(written_p["obj"]), pfbx, None, map_mode=True)
                (raw_props / pfbx.name).write_bytes(pfbx.read_bytes())
                furniture_out.append(
                    {
                        "fbx": str(pfbx),
                        "dest": "/Game/MOHAA/props",
                        "name": "SM_" + pstem,
                        "skeletal": False,
                        "spawns": list(fj.get("spawns") or []),
                    }
                )
                print(
                    "[furniture] fbx %s instances=%d" % (pstem, len(fj.get("spawns") or [])),
                    flush=True,
                )
            except Exception as exc:
                print("[furniture] export fail %s: %s" % (pstem, exc), flush=True)
    result = {
        "ok": True,
        "name": stem,
        "obj": written["obj"],
        "fbx": str(fbx_path),
        "raw_import": str(copied),
        "project": str(project) if project else None,
        "textures": written["textures"],
        "verts": written["verts"],
        "blender": blender_log[-800:],
        "lod_files": lod_paths,
        "lods": lod_stats,
        "skeletal": bool(skeletal),
        "skel_debug": skel_debug,
        "anims": [
            {
                "alias": c.get("alias"),
                "frames": c.get("frame_count"),
                "fps": c.get("fps"),
                "file": c.get("file"),
            }
            for c in ((anim_bundle or {}).get("clips") or [])
        ],
        "anim_fbxs": [str(a["fbx"]) for a in anim_fbx_list],
        "sky": sky_job or payload.get("sky"),
        "with_textures": bool(with_textures),
        "furniture": [
            {"name": f["name"], "instances": len(f.get("spawns") or []), "fbx": f["fbx"]}
            for f in furniture_out
        ],
        "unreal": None,
    }
    if into_unreal:
        prefix = "SK_" if skeletal else "SM_"
        result["unreal"] = run_unreal_import(
            fbx_path,
            prefix + stem,
            category,
            lod_fbxs,
            screens,
            skeletal=skeletal,
            anim_fbxs=anim_fbx_list,
            project=project,
            kind="map" if is_map else "",
            sky=sky_job if with_textures else {},
            with_textures=with_textures,
            furniture=furniture_out,
        )
    set_progress(100, "Done")
    PROGRESS["active"] = False
    return result
