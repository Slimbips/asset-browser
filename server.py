"""Minimal MOHAA asset browser: scan pk3s + SKD preview with real shader resolve."""
from __future__ import annotations

import json
import posixpath
import re
import threading
import subprocess
from collections import OrderedDict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from zipfile import ZipFile

from PIL import Image

from export_ue import (
    PROGRESS,
    export_asset,
    get_active_project,
    launch_unreal_editor,
    resolve_project,
    set_active_project,
    UE_EDITOR_UI,
)
from formats import (
    BSP_PREVIEW_MAX_INDICES,
    BUILTIN_MAPS,
    SKIP_MAPS,
    SKY_FACE_SIDES,
    evaluate_animation_frames,
    log_animation_focus,
    log_tiki_anim_events,
    extract_skd_lod,
    encode_preview_image,
    image_to_png,
    is_null_sky_box,
    merge_meshes,
    mesh_to_json,
    entity_angles,
    entity_origin,
    entity_scale,
    is_furniture_tik,
    mohaa_angles_to_ue,
    mohaa_model_scale_to_ue,
    mohaa_point_to_ue_cm,
    parse_bsp,
    parse_bsp_entities,
    parse_bsp_static_models,
    parse_lod_control,
    parse_shader_file,
    parse_skc,
    parse_skd,
    parse_skd_bones,
    parse_tiki,
    sky_face_candidates,
    classify_skc_clip,
    log_skc_classification,
    skc_has_delta,
    skc_has_upper,
)

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DEFAULT_GAME = Path(r"D:\Games\test\moh_convert_game")
PATHS_FILE = ROOT / "paths.json"
PORT = 8765
IMAGE_EXTS = (".tga", ".jpg", ".jpeg", ".png", ".dds")

STATE = {
    "game": str(DEFAULT_GAME) if DEFAULT_GAME.exists() else "",
    "project": "",
    "index": {},
    "shaders": {},
    "tik_by_skd": {},
    "skel_surfaces": {},
}


def _ps_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def load_paths() -> dict:
    try:
        data = json.loads(PATHS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    game = str(data.get("game") or "").strip()
    project = str(data.get("project") or "").strip()
    if game and Path(game).is_dir():
        STATE["game"] = game
    if project:
        try:
            STATE["project"] = str(set_active_project(project))
        except ValueError:
            STATE["project"] = ""
    return {"game": STATE["game"], "project": STATE["project"]}


def save_paths() -> None:
    active = get_active_project()
    payload = {
        "game": STATE.get("game") or "",
        "project": str(active or STATE.get("project") or ""),
    }
    tmp = PATHS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(PATHS_FILE)


def project_payload(project: Path) -> dict:
    return {"project": str(project), "folder": str(project.parent), "name": project.stem}


def remember_project(value: str | Path | None = None) -> Path:
    project = set_active_project(value)
    STATE["project"] = str(project)
    save_paths()
    return project


def win_pick(script: str) -> str:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
        capture_output=True,
        encoding="utf-8-sig",
        timeout=300,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise RuntimeError("Picker could not open. Paste the path instead.")
    return (result.stdout or "").strip()


def pick_game_folder(initial: str = "") -> str | None:
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$dialog.Description = 'Select MOHAA assets folder (contains main/ pk3s)'; "
        "$dialog.ShowNewFolderButton = $false; "
    )
    if initial and Path(initial).is_dir():
        script += "$dialog.SelectedPath = %s; " % _ps_literal(initial)
    script += (
        "if ($dialog.ShowDialog() -eq 'OK') { "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "[Console]::Write($dialog.SelectedPath) }; $dialog.Dispose()"
    )
    value = win_pick(script)
    return value or None


def pick_unreal_project(initial: str = "") -> str | None:
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$dialog = New-Object System.Windows.Forms.OpenFileDialog; "
        "$dialog.Title = 'Select Unreal Engine project'; "
        "$dialog.Filter = 'Unreal Engine project (*.uproject)|*.uproject|All files (*.*)|*.*'; "
        "$dialog.CheckFileExists = $true; "
    )
    start = Path(initial) if initial else None
    if start and start.is_file():
        start = start.parent
    if start and start.is_dir():
        script += "$dialog.InitialDirectory = %s; " % _ps_literal(str(start))
    script += (
        "if ($dialog.ShowDialog() -eq 'OK') { "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "[Console]::Write($dialog.FileName) }; $dialog.Dispose()"
    )
    value = win_pick(script)
    return value or None


load_paths()


def norm(p: str) -> str:
    return p.replace("\\", "/").lstrip("/").lower()


# Display folders/titles so maps/DM/mohdm6.bsp shows up as Deathmatch / Stalingrad.
MAP_TITLES = {
    "mohdm1": ("Deathmatch", "Southern France"),
    "mohdm2": ("Deathmatch", "Destroyed Village"),
    "mohdm3": ("Deathmatch", "Remagen"),
    "mohdm4": ("Deathmatch", "The Crossroads"),
    "mohdm5": ("Deathmatch", "Snowy Park"),
    "mohdm6": ("Deathmatch", "Stalingrad"),
    "mohdm7": ("Deathmatch", "Algiers"),
    "obj_team1": ("Objective", "The Hunt"),
    "obj_team2": ("Objective", "V2 Rocket Facility"),
    "obj_team3": ("Objective", "Omaha Beach"),
    "obj_team4": ("Objective", "The Bridge"),
    "training": ("", "Training"),
    "credits": ("", "Credits"),
    "void": ("", "Void"),
    "briefing1": ("Briefing", "Lighting the Torch"),
    "briefing2": ("Briefing", "Scuttling the U-529"),
    "briefing3": ("Briefing", "Operation Overlord"),
    "briefing4": ("Briefing", "Behind Enemy Lines"),
    "briefing5": ("Briefing", "The Hunt for the King Tiger"),
    "briefing6": ("Briefing", "Return to Schmerzen"),
    "m1l1": ("Campaign/1 Lighting the Torch", "Rendezvous with the Resistance"),
    "m1l2a": ("Campaign/1 Lighting the Torch", "Diverting the Enemy"),
    "m1l2b": ("Campaign/1 Lighting the Torch", "The Rescue"),
    "m1l3a": ("Campaign/1 Lighting the Torch", "Sabotage the Motorpool"),
    "m1l3b": ("Campaign/1 Lighting the Torch", "Lighting the Torch"),
    "m1l3c": ("Campaign/1 Lighting the Torch", "The Docks"),
    "m2l1": ("Campaign/2 Scuttling the U-529", "Secret Documents of the Kriegsmarine"),
    "m2l2a": ("Campaign/2 Scuttling the U-529", "Naxos Radar"),
    "m2l2b": ("Campaign/2 Scuttling the U-529", "The U-boat Pens"),
    "m2l2c": ("Campaign/2 Scuttling the U-529", "Scuttling the U-529"),
    "m2l3": ("Campaign/2 Scuttling the U-529", "Escape from Trondheim"),
    "m3l1a": ("Campaign/3 Operation Overlord", "Omaha Beach"),
    "m3l1b": ("Campaign/3 Operation Overlord", "The Bunkers"),
    "m3l2": ("Campaign/3 Operation Overlord", "Battle in the Bocage"),
    "m3l3": ("Campaign/3 Operation Overlord", "The Nebelwerfers"),
    "m4l0": ("Campaign/4 Behind Enemy Lines", "The Sniper's Arrival"),
    "m4l1": ("Campaign/4 Behind Enemy Lines", "The Catch"),
    "m4l2": ("Campaign/4 Behind Enemy Lines", "The Escape"),
    "m4l3": ("Campaign/4 Behind Enemy Lines", "The Manor"),
    "m5l1a": ("Campaign/5 Hunt for the King Tiger", "The Siegfried Forest"),
    "m5l1b": ("Campaign/5 Hunt for the King Tiger", "The King Tiger"),
    "m5l2a": ("Campaign/5 Hunt for the King Tiger", "The Roer River"),
    "m5l2b": ("Campaign/5 Hunt for the King Tiger", "The Bridge"),
    "m5l3": ("Campaign/5 Hunt for the King Tiger", "Sniper's Last Stand"),
    "m6l1a": ("Campaign/6 Return to Schmerzen", "The Rail Yard"),
    "m6l1b": ("Campaign/6 Return to Schmerzen", "Mustard Gas"),
    "m6l1c": ("Campaign/6 Return to Schmerzen", "The Facility"),
    "m6l2a": ("Campaign/6 Return to Schmerzen", "The Communications Wire"),
    "m6l2b": ("Campaign/6 Return to Schmerzen", "The Power Station"),
    "m6l3a": ("Campaign/6 Return to Schmerzen", "Fort Schmerzen"),
    "m6l3b": ("Campaign/6 Return to Schmerzen", "The Prisoners"),
    "m6l3c": ("Campaign/6 Return to Schmerzen", "The Gas Plant"),
    "m6l3d": ("Campaign/6 Return to Schmerzen", "The Command Centre"),
    "m6l3e": ("Campaign/6 Return to Schmerzen", "Escape from Schmerzen"),
    "t1l1": ("Campaign/Spearhead Stalingrad", "A Lucky Break"),
    "t1l2": ("Campaign/Spearhead Stalingrad", "Preparatory Barrage"),
    "t1l3": ("Campaign/Spearhead Stalingrad", "The Rescue of Pavlov"),
}


def map_listing(path: str) -> tuple[str, str]:
    stem = Path(path).stem.lower()
    folder, title = MAP_TITLES.get(stem, ("", Path(path).stem.replace("_", " ").title()))
    if folder:
        return folder + "/" + title, title
    low = path.replace("\\", "/").lower()
    if "/dm/" in low:
        return "Deathmatch/" + title, title
    if "/obj/" in low:
        return "Objective/" + title, title
    if "/briefing/" in low:
        return "Briefing/" + title, title
    return title, title


def categorize(path: str) -> str:
    p = path.lower()
    if p.endswith(".bsp") or p.startswith("maps/"):
        return "maps"
    if "/weapons/" in p or p.startswith("models/ammo/"):
        return "weapons"
    if "/human/" in p or "/player/" in p or "allied" in p or "/axis/" in p or p.startswith("models/posed/"):
        return "characters"
    if "/vehicle" in p or "/jeep" in p or "/tank" in p or "/plane" in p:
        return "vehicles"
    if "/fx/" in p or "/emitters/" in p or p.startswith("models/fx/"):
        return "fx"
    if p.endswith((".tga", ".jpg", ".jpeg", ".dds")):
        return "textures"
    return "props"


def find_pk3s(game: Path) -> list[Path]:
    out = []
    for sub in ("", "main", "mainta", "maintt"):
        d = game / sub if sub else game
        if not d.is_dir():
            continue
        for fn in sorted(d.iterdir()):
            if fn.suffix.lower() == ".pk3":
                out.append(fn)
    return out


def _file_rec(vfs_path: str, *, pak="", pak_path="", disk_path="", size=0, source="pk3", zip_name="") -> dict:
    key = norm(vfs_path)
    return {
        "path": vfs_path.replace("\\", "/"),
        "pak": pak,
        "pak_path": pak_path,
        "disk_path": disk_path,
        "zip_name": zip_name,
        "size": size,
        "ext": Path(key).suffix,
        "source": source,
    }


def add_loose_files(index: dict, folder: Path) -> None:
    if not folder.is_dir():
        return
    for p in folder.rglob("*"):
        if not p.is_file() or p.suffix.lower() == ".pk3":
            continue
        rel = p.relative_to(folder).as_posix()
        rec = _file_rec(rel, disk_path=str(p), size=p.stat().st_size, source="loose", pak="(loose)")
        index[norm(rel)] = rec


_zips: dict[str, ZipFile] = {}


def _pak(pak_path: str) -> ZipFile:
    z = _zips.get(pak_path)
    if z is None or getattr(z, "fp", None) is None:
        if z is not None:
            try:
                z.close()
            except Exception:
                pass
        z = ZipFile(pak_path)
        _zips[pak_path] = z
    return z


def close_paks() -> None:
    for z in _zips.values():
        z.close()
    _zips.clear()


_SCAN_LOCK = threading.Lock()


def scan_game(game_dir: str) -> dict:
    with _SCAN_LOCK:
        return _scan_game_locked(game_dir)


def _scan_game_locked(game_dir: str) -> dict:
    game = Path(game_dir)
    if not game.is_dir():
        raise FileNotFoundError(game_dir)
    close_paks()
    index = {}
    paks = find_pk3s(game)
    for pak in paks:
        with ZipFile(pak) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                rec = _file_rec(
                    info.filename.replace("\\", "/"),
                    pak=pak.name,
                    pak_path=str(pak),
                    size=info.file_size,
                    source="pk3",
                    zip_name=info.filename,
                )
                index[norm(info.filename)] = rec
    for sub in ("main", "mainta", "maintt"):
        add_loose_files(index, game / sub)

    global _SHARED_HUMAN_ANIMS
    _SHARED_HUMAN_ANIMS = None
    try:
        for pak in paks:
            _pak(str(pak))
        shaders = load_shaders(index)
        tik_by_skd = {}
        skel_surfaces_map = {}
        assets = []
        for rec in index.values():
            if rec["ext"] not in (".tik", ".skd", ".bsp") and rec["ext"] not in IMAGE_EXTS:
                continue
            item = {
                "id": rec["path"],
                "name": Path(rec["path"]).stem.replace("_", " ").title(),
                "path": rec["path"],
                "pak": rec["pak"],
                "size": rec["size"],
                "ext": rec["ext"],
                "category": categorize(rec["path"]),
                "display_name": "",
                "skelmodel": "",
                "skelmodels": [],
                "shaders": [],
                "surfaces": [],
                "tik_path": "",
                "tiki_path": "",
                "kind": "model",
                "list_path": rec["path"],
            }
            if rec["ext"] in IMAGE_EXTS:
                item["kind"] = "texture"
                item["category"] = "textures"
                item["display_name"] = Path(rec["path"]).stem.replace("_", " ")
                item["name"] = item["display_name"]
            elif rec["ext"] == ".bsp":
                item["skelmodel"] = rec["path"]
                item["kind"] = "map"
                list_path, title = map_listing(rec["path"])
                item["list_path"] = list_path
                item["name"] = title
                item["display_name"] = title
            elif rec["ext"] == ".tik":
                tik = parse_tiki(
                    read_indexed(index, rec["path"]), filename=rec["path"], loader=tiki_loader(index)
                )
                item["display_name"] = tik["display_name"]
                item["name"] = tik["display_name"] or item["name"]
                item["shaders"] = tik["shaders"]
                item["surfaces"] = tik["surfaces"]
                item["tik_path"] = rec["path"]
                item["tiki_path"] = tik["path"]
                folder = tik["path"].rstrip("/") or posixpath.dirname(rec["path"])
                if tik["skelmodels"]:
                    resolved = [resolve_skelmodel(index, folder, sk) for sk in tik["skelmodels"]]
                    resolved = [p for p in resolved if p]
                    item["skelmodels"] = resolved
                    item["skelmodel"] = resolved[0] if resolved else ""
                    for p in resolved:
                        tik_by_skd.setdefault(norm(p), rec["path"])
                # Later TIKI cases (other heads) stay out of the idle merge, but
                # still need a shader map so clicking that SKD is textured.
                for sk in tik.get("all_skelmodels") or tik.get("skelmodels") or []:
                    p = resolve_skelmodel(index, folder, sk)
                    if p:
                        tik_by_skd.setdefault(norm(p), rec["path"])
                for sk, surfs in (tik.get("skel_surfaces") or {}).items():
                    p = resolve_skelmodel(index, folder, sk)
                    if p and surfs:
                        skel_surfaces_map.setdefault(norm(p), surfs)
            else:
                item["skelmodel"] = rec["path"]
            assets.append(item)
        folder_tik = {}
        tik_by_base = {}
        for item in assets:
            if item["ext"] != ".tik":
                continue
            if item.get("skelmodels"):
                for p in item["skelmodels"]:
                    tik_by_base.setdefault(posixpath.basename(p).lower(), item["tik_path"])
            elif item.get("skelmodel"):
                base = posixpath.basename(item["skelmodel"]).lower()
                tik_by_base.setdefault(base, item["tik_path"])
            has_all = any(
                (s.get("name") or "").lower() == "all" and s.get("shader") for s in item.get("surfaces") or []
            )
            if not has_all:
                continue
            if item.get("tiki_path"):
                folder_tik[norm(item["tiki_path"].rstrip("/"))] = item["tik_path"]
            if item.get("skelmodel"):
                folder_tik.setdefault(norm(posixpath.dirname(item["skelmodel"])), item["tik_path"])
        for item in assets:
            if item.get("kind") == "texture":
                continue
            if not item["tik_path"]:
                item["tik_path"] = tik_by_skd.get(norm(item["skelmodel"]), "")
            if not item["tik_path"] and item.get("skelmodel"):
                item["tik_path"] = folder_tik.get(norm(posixpath.dirname(item["skelmodel"])), "")
            if not item["tik_path"] and item.get("skelmodel"):
                item["tik_path"] = tik_by_base.get(posixpath.basename(item["skelmodel"]).lower(), "")
            if not item["tik_path"] and item.get("skelmodel"):
                folder = norm(posixpath.dirname(item["skelmodel"]))
                for other in assets:
                    if other["ext"] == ".tik" and other.get("skelmodel") and norm(posixpath.dirname(other["skelmodel"])) == folder:
                        item["tik_path"] = other["tik_path"]
                        break
        assets.sort(key=lambda a: (a["category"], a["name"].lower()))
        STATE["game"] = str(game)
        STATE["index"] = index
        STATE["shaders"] = shaders
        STATE["tik_by_skd"] = tik_by_skd
        STATE["skel_surfaces"] = skel_surfaces_map
        save_paths()
        print(
            "scan: %d pk3s, %d files, %d shader names, %d assets" % (len(paks), len(index), len(shaders), len(assets)),
            flush=True,
        )
        return {
            "game": str(game),
            "paks": len(paks),
            "assets": assets,
            "files": len(index),
            "shaders": len(shaders),
        }
    finally:
        close_paks()


def load_shaders(index: dict) -> dict:
    shaders = {}
    files = sorted((k, rec) for k, rec in index.items() if rec["ext"] == ".shader")
    for _key, rec in files:
        try:
            text = read_indexed(index, rec["path"]).decode("latin1", "replace")
        except Exception as exc:
            print("shader read fail %s: %s" % (rec["path"], exc), flush=True)
            continue
        parsed = parse_shader_file(text, rec["path"])
        for name, defn in parsed.items():
            key = name.lower()
            if key not in shaders:
                shaders[key] = defn
    return shaders


def read_indexed(index: dict, virtual_path: str) -> bytes:
    rec = index.get(norm(virtual_path))
    if not rec:
        raise FileNotFoundError(virtual_path)
    if rec.get("disk_path"):
        return Path(rec["disk_path"]).read_bytes()
    z = _zips.get(rec["pak_path"])
    owned = False
    if z is None:
        z = ZipFile(rec["pak_path"])
        owned = True
    try:
        name = rec.get("zip_name") or rec["path"]
        try:
            return z.read(name)
        except KeyError:
            return z.read(_zip_name(z, rec["path"]))
    finally:
        if owned:
            z.close()


def _zip_name(z: ZipFile, path: str) -> str:
    want = norm(path)
    for n in z.namelist():
        if norm(n) == want:
            return n
    raise FileNotFoundError(path)


def lookup_image(index: dict, path: str) -> dict | None:
    """Find an image in the VFS. JPG is tried before TGA, matching MOHAA."""
    raw = path.replace("\\", "/").strip()
    if not raw or raw.lower() in SKIP_MAPS:
        return None
    builtin = BUILTIN_MAPS.get(raw.lower())
    if builtin:
        return {
            "path": builtin,
            "pak": "builtin",
            "source": "builtin",
            "ext": ".png",
        }
    key = norm(raw)
    rec = index.get(key)
    if rec and rec["ext"] in IMAGE_EXTS:
        return rec
    stem, _ext = posixpath.splitext(key)
    if not stem:
        return None
    for ext in (".jpg", ".tga", ".png", ".jpeg", ".dds"):
        rec = index.get(stem + ext)
        if rec:
            return rec
    return None


def resolve_sky_cubemap(index: dict, env_base: str) -> dict[str, dict]:
    """Load Q3 skyParms cubemap faces (ft/bk/up/dn/rt/lf) from the VFS."""
    faces = {}
    if is_null_sky_box(env_base):
        return faces
    for side in SKY_FACE_SIDES:
        rec = None
        for cand in sky_face_candidates(env_base, side):
            rec = lookup_image(index, cand)
            if rec:
                break
        if rec:
            faces[side] = rec
    return faces


def tiki_shader_for_surface(tik_surfaces: list[dict], surf_name: str) -> tuple[str, str]:
    """Match TIKI surface lines to an SKD surface (all / prefix* / exact). Last match wins."""
    chosen = ""
    how = "skd-surface-name"
    low = surf_name.lower()
    for spec in tik_surfaces or []:
        spec_name = spec.get("name") or ""
        shader = spec.get("shader") or ""
        sl = spec_name.lower()
        matched = False
        if sl == "all":
            matched = True
        elif "*" in spec_name:
            prefix = sl.split("*", 1)[0]
            matched = low.startswith(prefix)
        elif sl == low:
            matched = True
        if matched and shader:
            chosen = shader
            how = "tiki:" + spec_name
    if chosen:
        return chosen, how
    if re.fullmatch(r"material\d+", surf_name.lower()):
        for spec in tik_surfaces or []:
            if spec.get("shader"):
                return spec["shader"], "tiki-unnamed-fallback"
        return "", "unnamed-material"
    return surf_name, "skd-surface-name"


FACE_STEM_ALIAS = {
    "sarge": "srg",
    "nobody": "us_north",
    "manon": "manon_head",
}

SURFACE_SHADER_ALIAS = {
    "mg": ("tankmg", "static_tankmg", "turretbase"),
    "opelhubstill": ("opelhub_norotate", "opelhubgreen_norotate", "opelhub"),
    "opeltreadstill": ("opeltread_norotate", "opeltread"),
    "breadbag": ("german_gear", "static_german_gear"),
    "shells": ("grenadier_shells", "static_grenadier_shells"),
    "ammobox": ("grenadier_ammobox", "static_grenadier_ammobox", "mg_box"),
    "compassbase": ("static_drawing_compass_1",),
    "compassneedle": ("static_drawing_compass_2",),
}


def shader_guesses_from_skd(skd_path: str, surf_name: str) -> list[str]:
    """Standalone heads with a generic SKD surface name (head/helmet)."""
    surf = (surf_name or "").lower()
    stem = posixpath.splitext(posixpath.basename(skd_path or ""))[0].lower()
    stem = re.sub(r"^(usarmyhead_|ushead|us_)", "", stem)
    stem = re.sub(r"\d+$", "", stem).strip("_")
    out: list[str] = []

    def add(name: str) -> None:
        if name and name not in out:
            out.append(name)

    if surf in ("head", "head1", "face", "manon"):
        add(FACE_STEM_ALIAS.get(stem, ""))
        add(stem)
        if stem:
            add(stem + "_head")
        if stem.startswith("head") or stem == "nobody":
            add("us_north")
    if surf in ("helmet", "us_helmet", "hat"):
        add("ranger_helmet")
        add("us_soldier_helmet")
        add(surf)
    for name in SURFACE_SHADER_ALIAS.get(surf, ()):
        add(name)
    stripped = re.sub(r"\d+$", "", surf)
    if stripped and stripped != surf:
        add(stripped)
        add("static_" + stripped)
    return out


def resolve_surface_material(
    index: dict, shaders: dict, surf_name: str, tik_surfaces: list[dict], skd_path: str = ""
) -> dict:
    shader_name, shader_from = tiki_shader_for_surface(tik_surfaces, surf_name)
    result = {
        "surface": surf_name,
        "skd_name": surf_name,
        "shader": shader_name,
        "shader_from": shader_from,
        "shader_def": None,
        "shader_file": None,
        "shader_body": None,
        "texture": None,
        "texture_url": None,
        "source": None,
        "status": "MISSING",
        "missing": "",
        "notes": [],
        "cull_none": False,
        "blend": False,
        "alpha_test": False,
        "autosprite": False,
        "env": False,
        "is_sky": False,
        "sky_env": "",
        "sky_faces": {},
    }
    if not shader_name:
        result["missing"] = "surface '%s' has no shader (unnamed material slot)" % surf_name
        return result

    is_map = (skd_path or "").lower().endswith(".bsp")
    stripped = posixpath.splitext(shader_name.replace("\\", "/"))[0]
    defn = shaders.get(shader_name.lower()) or shaders.get(stripped.lower())
    alias_note = ""
    if not defn and not is_map:
        base = posixpath.basename(stripped)
        candidates = [base + "_head", "static_" + base, "textures/models/human/faces/" + base]
        candidates.extend(shader_guesses_from_skd(skd_path, surf_name))
        digitless = re.sub(r"\d+$", "", base)
        if digitless and digitless != base:
            candidates.append(digitless)
            candidates.append("static_" + digitless)
        if surf_name:
            sl = surf_name.lower()
            candidates.append("static_" + sl)
            candidates.append(sl)
        for cand in candidates:
            alt = shaders.get(cand.lower())
            if alt:
                defn = alt
                alias_note = "shader alias %s -> %s" % (shader_name, alt["name"])
                result["shader"] = alt["name"]
                result["shader_from"] = "skd-filename" if cand in shader_guesses_from_skd(skd_path, surf_name) else result["shader_from"]
                break
    map_token = None
    if defn:
        result["shader_def"] = defn["name"]
        result["shader_file"] = defn["file"]
        result["shader_body"] = defn["body"][:400]
        result["notes"] = list(defn["notes"])
        if alias_note:
            result["notes"].append(alias_note)
        result["env"] = defn["env"]
        result["blend"] = defn["blend"]
        result["alpha_test"] = defn["alpha_test"]
        result["cull_none"] = defn["cull_none"]
        result["autosprite"] = bool(defn.get("autosprite"))
        if defn.get("is_sky"):
            result["is_sky"] = True
            parms = defn.get("sky_parms") or {}
            env_base = str(parms.get("farbox") or "")
            result["sky_env"] = env_base
            faces = resolve_sky_cubemap(index, env_base)
            result["sky_faces"] = {side: rec["path"] for side, rec in faces.items()}
            if faces:
                up = faces.get("up") or next(iter(faces.values()))
                result["texture"] = up["path"]
                result["source"] = up["pak"] if up["source"] == "pk3" else up["source"]
                result["texture_url"] = "/api/tex?path=" + quote(up["path"], safe="/") + "&w=1024"
                result["status"] = "SKY"
                result["missing"] = ""
                result["notes"].append(
                    "sky cubemap %s (%d/6 faces)" % (env_base, len(faces))
                )
                return result
            sh_low = (defn.get("name") or shader_name or "").lower()
            dummy = is_null_sky_box(env_base) or "idontexist" in env_base.lower()
            if dummy or "caulk" in sh_low:
                result["status"] = "NODRAW"
                result["nodraw"] = True
                result["missing"] = ""
                result["notes"].append("sky hull without cubemap (%s)" % (env_base or sh_low))
                return result
            result["missing"] = (
                "skyParms '%s' cubemap faces not found in loose files or pk3s" % env_base
            )
            result["texture"] = env_base
            return result
        albedo = []
        env_maps = []
        for m in defn.get("env_maps") or []:
            if m.lower() in SKIP_MAPS:
                result["notes"].append("skipped " + m)
                continue
            env_maps.append(m)
            result["notes"].append("skipped env-stage " + m)
        for m in defn["maps"]:
            if m.lower() in SKIP_MAPS:
                result["notes"].append("skipped " + m)
                continue
            base = posixpath.basename(m.replace("\\", "/")).lower()
            if "reflection" in base or base.startswith("env"):
                env_maps.append(m)
                result["notes"].append("skipped env " + m)
                continue
            albedo.append(m)
        if albedo:
            map_token = albedo[0]
        elif defn.get("qer_editorimage"):
            map_token = defn["qer_editorimage"]
            result["notes"].append("albedo from qer_editorimage")
        elif env_maps:
            map_token = env_maps[0]
        if not map_token:
            result["missing"] = "shader '%s' in %s has no map/clampmap image" % (defn["name"], defn["file"])
            return result
    else:
        guesses = []
        if not is_map and shader_from == "skd-surface-name":
            guesses = shader_guesses_from_skd(skd_path, surf_name)
        if guesses:
            result["notes"].append("no .shader definition; implicit image lookup")
            map_token = guesses[0]
            result["shader"] = guesses[0]
            result["shader_from"] = "skd-filename"
        else:
            result["notes"].append("no .shader definition; implicit image lookup")
            map_token = shader_name

    rec = lookup_image(index, map_token)
    if not rec:
        base = posixpath.basename(posixpath.splitext(map_token.replace("\\", "/"))[0])
        extras = []
        if not is_map:
            extras = [
                "textures/models/human/faces/" + base,
                "textures/models/human/faces/" + base + "_head",
                "textures/models/human/frenchmaps/" + base + "/" + base,
                "textures/models/human/frenchmaps/" + base + "/" + base + "_head",
            ]
            if shader_from in ("skd-surface-name", "skd-filename"):
                extras.extend(shader_guesses_from_skd(skd_path, surf_name))
        for cand in extras:
            rec = lookup_image(index, cand)
            if rec:
                result["notes"].append("image alias %s -> %s" % (map_token, rec["path"]))
                break
    if not rec:
        where = "shader map" if defn else "implicit shader name"
        result["missing"] = "%s '%s' not found in loose files or pk3s" % (where, map_token)
        result["texture"] = map_token
        return result

    result["texture"] = rec["path"]
    result["source"] = rec["pak"] if rec["source"] == "pk3" else rec["source"]
    if rec["source"] == "builtin":
        result["texture_url"] = "/api/tex?path=" + quote(rec["path"], safe="") + "&w=1024"
        result["status"] = "FOUND"
        result["missing"] = ""
        return result
    result["texture_url"] = "/api/tex?path=" + quote(rec["path"], safe="/") + "&w=1024"
    result["status"] = "FOUND"
    result["missing"] = ""
    return result


def tiki_loader(index: dict):
    def load(path: str):
        rec = index.get(norm(path))
        if not rec:
            return None
        return read_indexed(index, rec["path"])

    return load


def resolve_skelmodel(index: dict, folder: str, sk: str) -> str:
    sk = (sk or "").replace("\\", "/").strip().strip('"')
    if not sk:
        return ""
    folder = (folder or "").replace("\\", "/").rstrip("/")
    candidates = []
    if "/" in sk:
        candidates.append(sk)
    if folder:
        candidates.append(posixpath.join(folder, posixpath.basename(sk)))
    seen = []
    for c in candidates:
        if c in seen:
            continue
        seen.append(c)
        rec = index.get(norm(c))
        if rec:
            if rec["ext"] == ".skb":
                alt = index.get(norm(c[:-4] + ".skd"))
                if alt:
                    return alt["path"]
            return rec["path"]
        if c.lower().endswith(".skb"):
            rec = index.get(norm(c[:-4] + ".skd"))
            if rec:
                return rec["path"]
    names = {posixpath.basename(sk).lower()}
    if sk.lower().endswith(".skb"):
        names.add(posixpath.splitext(posixpath.basename(sk))[0].lower() + ".skd")
    hits = [
        rec["path"]
        for rec in index.values()
        if rec["ext"] == ".skd" and posixpath.basename(rec["path"]).lower() in names
    ]
    if len(hits) == 1:
        return hits[0]
    return seen[0] if seen else sk


def load_tik(skel_path: str, tik_query: str) -> tuple[dict | None, str]:
    index = STATE["index"]
    tik_path = tik_query or STATE["tik_by_skd"].get(norm(skel_path), "")
    if not tik_path:
        return None, ""
    rec = index.get(norm(tik_path))
    if not rec:
        return None, ""
    return (
        parse_tiki(read_indexed(index, rec["path"]), filename=rec["path"], loader=tiki_loader(index)),
        rec["path"],
    )


def resolve_skc_path(tik: dict, tik_file_path: str, anim: dict | None) -> str:
    if not anim:
        return ""
    folder = (anim.get("folder") or tik.get("path") or "").rstrip("/") or posixpath.dirname(tik_file_path)
    f = str(anim.get("file") or "").replace("\\", "/")
    if not f:
        return ""
    candidates = []
    if "/" in f and not f.lower().startswith("models/"):
        candidates.append(posixpath.join("models/human/animation", f))
        candidates.append(posixpath.join(folder, f))
    elif "/" in f:
        candidates.append(f)
    else:
        candidates.append(posixpath.join(folder, f))
        candidates.append(posixpath.join("models/human/animation", f))
        candidates.append(posixpath.join("models/human/protoanimations", posixpath.basename(f)))
    for path in candidates:
        if STATE["index"] and norm(path) in STATE["index"]:
            return STATE["index"][norm(path)]["path"]
    if STATE["index"]:
        base = posixpath.basename(f).lower()
        hits = [
            rec["path"]
            for rec in STATE["index"].values()
            if rec["ext"] == ".skc" and posixpath.basename(rec["path"]).lower() == base
        ]
        if len(hits) == 1:
            return hits[0]
    return candidates[0] if candidates else f


def idle_skc_path(tik: dict, tik_file_path: str) -> str:
    anims = tik.get("anims") or []
    idle = None
    for name in ("idle", "unarmed_stand_alert", "idle_stand", "stand"):
        idle = next((a for a in anims if str(a.get("alias", "")).lower() == name), None)
        if idle:
            break
    if idle is None:
        idle = next(
            (
                a
                for a in anims
                if str(a.get("alias", "")).lower() == "idle"
                or str(a.get("alias", "")).lower().startswith("idle_")
            ),
            None,
        )
    # Never use anims[0]: character includes start with scripted death, same
    # class of bug as attaching a weapon clip in idle.
    return resolve_skc_path(tik, tik_file_path, idle)


SKC_EXPORT_ALIASES = (
    "idle",
    "unarmed_walk_alert_forward",
    "unarmed_run_forward",
    "walk",
    "run",
    "unarmed_fire",
    "rifle_shoot",
    "unarmed_reload",
    "m1garand_reload",
    "rifle_crouch_alert",
    "unarmed_crouch_alert",
    "unarmed_jump_takeoff",
    "death_chest",
    "rifle_stand_hit_uppertorso",
    "rifle_butt",
    "rifle_raise",
    "rifle_lower",
    "rifle_prone_legs",
)

# Extra Unreal names so existing Persona assets get the composed clips.
_UE_ALIAS_EXTRAS = {
    "rifle_shoot": ("unarmed_fire",),
    "m1garand_reload": ("unarmed_reload",),
    "unarmed_fire": ("rifle_shoot",),
    "unarmed_reload": ("m1garand_reload",),
}

_SHARED_HUMAN_ANIMS = None
_SHARED_HUMAN_TIK = "models/player/base/include.txt"


def _anim_lookup(anims) -> dict:
    by_alias = {}
    for anim in anims or []:
        alias = str(anim.get("alias") or "").lower()
        if alias and alias not in by_alias:
            by_alias[alias] = anim
    return by_alias


def shared_human_anims() -> dict:
    """Player 3rd-person TIKI aliases (jump lives here, not on NPC human TIKs)."""
    global _SHARED_HUMAN_ANIMS
    if _SHARED_HUMAN_ANIMS is not None:
        return _SHARED_HUMAN_ANIMS
    rec = STATE["index"].get(norm(_SHARED_HUMAN_TIK)) if STATE.get("index") else None
    if not rec:
        _SHARED_HUMAN_ANIMS = {}
        return _SHARED_HUMAN_ANIMS
    try:
        tik = parse_tiki(
            read_indexed(STATE["index"], rec["path"]),
            filename=rec["path"],
            loader=tiki_loader(STATE["index"]),
        )
        _SHARED_HUMAN_ANIMS = _anim_lookup(tik.get("anims") or [])
    except Exception as exc:
        print("[anim] shared human tik fail %s: %s" % (_SHARED_HUMAN_TIK, exc), flush=True)
        _SHARED_HUMAN_ANIMS = {}
    return _SHARED_HUMAN_ANIMS


def pick_skc_clips(tik: dict) -> list[dict]:
    """Idle/locomotion/actions plus crouch/jump/death/pain; unique SKC files only.

    Alias names pick *which* clips to export. Composition is classified from
    SKC channels + TIKI flags (bHasDelta), never from the alias string.
    Missing character aliases (e.g. jump) fall back to player 3rd-person TIKI.
    """
    by_alias = _anim_lookup(tik.get("anims") or [])
    shared = shared_human_anims()
    picks = []
    seen = set()
    for name in SKC_EXPORT_ALIASES:
        anim = by_alias.get(name) or shared.get(name)
        if not anim:
            continue
        key = str(anim.get("file") or "").replace("\\", "/").lower()
        folder = str(anim.get("folder") or "").replace("\\", "/").lower()
        if folder:
            key = folder.rstrip("/") + "/" + key
        if not key or key in seen:
            continue
        seen.add(key)
        picks.append(anim)
    return picks


def build_anim_bundle(tik: dict | None, tik_file: str, skel_paths: list[str], skeleton: list[dict]) -> dict:
    clips = []
    if not tik or not skeleton:
        return {"clips": clips}
    picks = pick_skc_clips(tik)
    bone_groups = []
    for sp in skel_paths or []:
        if not sp.lower().endswith(".skd"):
            continue
        try:
            bone_groups.append(parse_skd_bones(read_indexed(STATE["index"], sp)))
        except Exception as exc:
            print("[anim] skd bones fail %s: %s" % (sp, exc), flush=True)
    if not bone_groups:
        return {"clips": clips}
    names = [str(b.get("name") or "") for b in skeleton]
    idle_path = idle_skc_path(tik, tik_file)
    idle_skc = None
    idle_ch0 = None
    if idle_path and norm(idle_path) in STATE["index"]:
        try:
            idle_skc = parse_skc(read_indexed(STATE["index"], idle_path))
            idle_ch0 = (idle_skc.get("frames") or [idle_skc.get("channels")])[0]
        except Exception as exc:
            print("[anim] idle base fail %s: %s" % (idle_path, exc), flush=True)
            idle_skc = None
            idle_ch0 = None
    for anim in picks:
        path = resolve_skc_path(tik, tik_file, anim)
        if not path or norm(path) not in STATE["index"]:
            print("[anim] missing %s (%s)" % (anim.get("alias"), path), flush=True)
            continue
        try:
            skc = parse_skc(read_indexed(STATE["index"], path))
            cls = classify_skc_clip(skc, anim.get("flags") or [], names)
            has_delta = bool(cls["has_delta"])
            # OpenMOHAA: motion if bHasDelta, else action over idle. Unchanged.
            overlay = bool(idle_ch0) and (not has_delta) and norm(path) != norm(idle_path)
            base = idle_ch0 if overlay else None
            frames = evaluate_animation_frames(bone_groups, skc, names, base_channels=base)
        except Exception as exc:
            print("[anim] eval fail %s: %s" % (anim.get("alias"), exc), flush=True)
            continue
        alias = str(anim.get("alias") or "anim")
        fps = 1.0 / float(skc.get("frameTime") or 0.05)
        flags = cls.get("tiki_flags") or []
        compose = "overlay_idle" if overlay else "clip_only"
        print(
            "[anim] %s frames=%d fps=%.3f channels=%d file=%s bones/frame=%d compose=%s type=%s bHasDelta=%s bHasUpper=%s tiki_flags=%s"
            % (
                alias,
                len(frames),
                fps,
                skc.get("numChannels") or 0,
                path,
                len(frames[0]) if frames else 0,
                compose,
                cls.get("type"),
                has_delta,
                cls.get("has_upper"),
                " ".join(str(f) for f in flags) or "(none)",
            ),
            flush=True,
        )
        log_skc_classification(alias, path, cls, frames)
        log_animation_focus(
            alias,
            bone_groups,
            skc,
            frames,
            base_channels=base,
            compose=compose,
        )
        log_tiki_anim_events(alias, path, str(anim.get("commands") or ""), float(skc.get("frameTime") or 0.05))
        extras = []
        for extra in _UE_ALIAS_EXTRAS.get(alias.lower()) or ():
            if extra.lower() != alias.lower():
                extras.append(extra)
        clips.append(
            {
                "alias": alias,
                "name": alias,
                "file": path,
                "fps": fps,
                "frame_time": float(skc.get("frameTime") or 0.05),
                "frame_count": len(frames),
                "channel_count": int(skc.get("numChannels") or 0),
                "compose": compose,
                "has_delta": has_delta,
                "clip_type": cls.get("type"),
                "tiki_flags": list(flags),
                "ue_aliases": extras,
                "frames": frames,
            }
        )
    return {"clips": clips}


def scan_character_animation_types() -> dict:
    """Classify unique SKCs referenced by human character TIKI files."""
    if not STATE.get("index"):
        scan_game(STATE["game"])
    index = STATE["index"]
    tiks = []
    for rec in index.values():
        if rec.get("ext") != ".tik":
            continue
        p = rec["path"].replace("\\", "/").lower()
        if p.startswith("models/human/") and p.count("/") == 2:
            tiks.append(rec["path"])
        elif p.startswith("models/player/") and p.count("/") == 2 and not p.endswith("_fps.tik"):
            tiks.append(rec["path"])
    by_skc = {}
    tik_count = 0
    for tik_path in tiks:
        rec = index.get(norm(tik_path))
        if not rec:
            continue
        try:
            tik = parse_tiki(
                read_indexed(index, rec["path"]),
                filename=rec["path"],
                loader=tiki_loader(index),
            )
        except Exception as exc:
            print("[scan] tik fail %s: %s" % (tik_path, exc), flush=True)
            continue
        tik_count += 1
        for anim in tik.get("anims") or []:
            path = resolve_skc_path(tik, rec["path"], anim)
            key = norm(path)
            if not key or key in by_skc:
                continue
            if key not in index:
                by_skc[key] = {
                    "file": path,
                    "type": "missing-skc",
                    "aliases": [anim.get("alias")],
                }
                continue
            try:
                skc = parse_skc(read_indexed(index, path))
                cls = classify_skc_clip(skc, anim.get("flags") or [])
            except Exception as exc:
                by_skc[key] = {
                    "file": path,
                    "type": "parse-fail",
                    "error": str(exc),
                    "aliases": [anim.get("alias")],
                }
                continue
            by_skc[key] = {
                "file": path,
                "type": cls["type"],
                "compose": cls["compose"],
                "has_delta": cls["has_delta"],
                "has_upper": cls["has_upper"],
                "delta_driven": cls["delta_driven"],
                "additive": cls["additive"],
                "aliases": [anim.get("alias")],
            }
        print("[scan] %s anims=%d unique=%d" % (tik_path, len(tik.get("anims") or []), len(by_skc)), flush=True)
    counts = {}
    examples = {}
    for rec in by_skc.values():
        t = rec.get("type") or "unknown"
        counts[t] = counts.get(t, 0) + 1
        examples.setdefault(t, [])
        if len(examples[t]) < 8:
            examples[t].append("%s (%s)" % (rec.get("aliases", [""])[0], rec.get("file")))
    print("[scan] character_tiks=%d unique_skc=%d" % (tik_count, len(by_skc)), flush=True)
    for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print("[scan]   %s: %d" % (t, n), flush=True)
        for ex in examples.get(t) or []:
            print("[scan]     e.g. %s" % ex, flush=True)
    return {"tik_count": tik_count, "unique_skc": len(by_skc), "counts": counts, "examples": examples}


def find_tik_surfaces(skel_path: str, tik_query: str) -> list[dict]:
    tik, _ = load_tik(skel_path, tik_query)
    return (tik or {}).get("surfaces") or []


def load_mesh_payload(
    vp: str,
    tik_path: str = "",
    *,
    use_idle: bool = True,
    full_geometry: bool = False,
    include_inline: bool = True,
) -> dict:
    if not STATE["index"]:
        scan_game(STATE["game"])
    if vp.lower().endswith(".bsp"):
        mesh = parse_bsp(
            read_indexed(STATE["index"], vp),
            max_indices=None if full_geometry else BSP_PREVIEW_MAX_INDICES,
            include_inline=include_inline,
        )
        mesh.pose = "bsp " + vp
        payload = mesh_to_json(mesh)
        rec = STATE["index"].get(norm(vp), {})
        materials = []
        sky_info = None
        seen_sky = set()
        for g in payload["groups"]:
            mat = resolve_surface_material(
                STATE["index"], STATE["shaders"], g["name"], [], skd_path=vp
            )
            mat["start"] = g["start"]
            mat["count"] = g["count"]
            mat["nodraw"] = False
            mat["hide_reason"] = ""
            g["shader"] = mat["shader"]
            g["texture"] = mat["texture_url"] if mat["status"] in ("FOUND", "SKY") else None
            g["status"] = mat["status"]
            if mat.get("is_sky") or mat.get("status") == "SKY":
                mat["nodraw"] = True
                mat["hide_reason"] = "skyParms cubemap hull"
                g["nodraw"] = True
                g["status"] = mat["status"]
                seen_sky.add((mat.get("shader") or g["name"] or "").lower())
                if sky_info is None and mat.get("sky_faces"):
                    sky_info = {
                        "shader": mat.get("shader"),
                        "env": mat.get("sky_env"),
                        "faces": dict(mat.get("sky_faces") or {}),
                    }
            materials.append(mat)
        for sh in payload.get("skyShaders") or []:
            key = (sh or "").lower()
            if not key or key in seen_sky:
                continue
            seen_sky.add(key)
            mat = resolve_surface_material(
                STATE["index"], STATE["shaders"], sh, [], skd_path=vp
            )
            mat["start"] = 0
            mat["count"] = 0
            mat["nodraw"] = True
            mat["hide_reason"] = "skyParms cubemap hull"
            mat["is_sky"] = True
            if mat.get("status") != "MISSING":
                mat["status"] = "SKY"
            materials.append(mat)
            if sky_info is None and mat.get("sky_faces"):
                sky_info = {
                    "shader": mat.get("shader") or sh,
                    "env": mat.get("sky_env"),
                    "faces": dict(mat.get("sky_faces") or {}),
                }
        payload["materials"] = materials
        payload["sky"] = sky_info
        payload["source"] = rec.get("path", vp)
        payload["tik"] = ""
        payload["kind"] = "map"
        return payload
    tik, tik_file = load_tik(vp, tik_path)
    channels = None
    pose_label = "skd-bind (no skc)"
    skc_path = idle_skc_path(tik, tik_file) if tik and use_idle else ""
    if tik and not use_idle:
        pose_label = "skd-bind (weapon export)"
    if skc_path and norm(skc_path) in STATE["index"]:
        try:
            skc = parse_skc(read_indexed(STATE["index"], skc_path))
            channels = skc["channels"]
            pose_label = "idle %s frame 0" % skc_path
        except Exception as exc:
            print("skc load fail %s: %s" % (skc_path, exc), flush=True)
            pose_label = "skd-bind (skc failed: %s)" % skc_path
    elif skc_path:
        pose_label = "skd-bind (missing %s)" % skc_path
    skel_paths = [vp]
    if tik and tik.get("skelmodels"):
        folder = (tik.get("path") or "").rstrip("/") or posixpath.dirname(tik_file)
        resolved = [resolve_skelmodel(STATE["index"], folder, sk) for sk in tik["skelmodels"]]
        resolved = [p for p in resolved if p and norm(p) in STATE["index"]]
        if resolved and norm(vp) == norm(resolved[0]):
            skel_paths = resolved
            print("[mesh] setup models: %s" % ", ".join(skel_paths), flush=True)
    parts = []
    for sp in skel_paths:
        if not sp.lower().endswith(".skd"):
            print("skip non-skd %s" % sp, flush=True)
            continue
        try:
            parts.append(
                parse_skd(
                    read_indexed(STATE["index"], sp),
                    channels,
                    pose_label,
                    tik,
                    reveal_if_all_hidden=norm(sp) == norm(vp),
                )
            )
        except Exception as exc:
            print("skd load fail %s: %s" % (sp, exc), flush=True)
    if not parts:
        raise ValueError("no skelmodels loaded for %s" % vp)
    mesh = merge_meshes(parts, pose_label)
    payload = mesh_to_json(mesh)
    rec = STATE["index"].get(norm(vp), {})
    tik_surfaces = (tik or {}).get("surfaces") or []
    if not tik_surfaces and len(skel_paths) == 1:
        overlay = STATE.get("skel_surfaces", {}).get(norm(vp))
        if overlay:
            tik_surfaces = overlay
        else:
            guesses = shader_guesses_from_skd(vp, "head")
            if any(g.lower() in STATE.get("shaders", {}) for g in guesses):
                tik_surfaces = []
    for cached in (tik or {}).get("cache") or []:
        print("[cache] not attached in idle: %s" % cached, flush=True)
    materials = []
    skd_hint = vp if len(skel_paths) == 1 else ""
    for g in payload["groups"]:
        mat = resolve_surface_material(
            STATE["index"], STATE["shaders"], g["name"], tik_surfaces, skd_path=skd_hint
        )
        mat["start"] = g["start"]
        mat["count"] = g["count"]
        mat["nodraw"] = bool(g.get("nodraw"))
        mat["hide_reason"] = g.get("hide_reason") or ""
        g["shader"] = mat["shader"]
        g["texture"] = mat["texture_url"] if mat["status"] == "FOUND" else None
        g["status"] = mat["status"]
        if mat["nodraw"]:
            mat["status"] = "NODRAW"
            mat["notes"] = list(mat.get("notes") or [])
            mat["notes"].append("hidden in idle: " + mat["hide_reason"])
            g["status"] = "NODRAW"
        elif mat.get("autosprite") or any("autosprite" in str(n).lower() for n in (mat.get("notes") or [])):
            mat["nodraw"] = True
            mat["hide_reason"] = "shader deformVertexes autoSprite"
            mat["status"] = "NODRAW"
            g["nodraw"] = True
            g["status"] = "NODRAW"
        materials.append(mat)
    payload["materials"] = materials
    payload["source"] = rec.get("path", vp)
    payload["tik"] = tik_path or STATE["tik_by_skd"].get(norm(vp), "")
    payload["kind"] = "model"
    payload["skel_paths"] = skel_paths
    return payload


def collect_lod_bundle(skel_paths: list[str]) -> dict:
    """Keep SKD collapse tables + same-basename .lod sidecars for export."""
    files = []
    surfaces = {}
    lod_index = []
    lod_control = None
    for i, sp in enumerate(skel_paths or []):
        if not sp.lower().endswith(".skd"):
            continue
        try:
            raw = read_indexed(STATE["index"], sp)
        except Exception as exc:
            print("[lod] skip skd %s: %s" % (sp, exc), flush=True)
            continue
        info = extract_skd_lod(raw)
        if i == 0:
            lod_index = info.get("lod_index") or []
        for rec in info.get("surfaces") or []:
            if rec.get("name") and rec["name"] not in surfaces:
                surfaces[rec["name"]] = rec
        lod_vp = sp.rsplit(".", 1)[0] + ".lod"
        if norm(lod_vp) not in STATE["index"]:
            continue
        try:
            data = read_indexed(STATE["index"], lod_vp)
        except Exception as exc:
            print("[lod] skip sidecar %s: %s" % (lod_vp, exc), flush=True)
            continue
        rec_idx = STATE["index"].get(norm(lod_vp), {})
        files.append(
            {
                "path": rec_idx.get("path", lod_vp),
                "bytes": data,
                "stem": Path(sp.replace("\\", "/")).stem,
            }
        )
        if lod_control is None:
            lod_control = parse_lod_control(data)
        print("[lod] sidecar %s (%d bytes)" % (lod_vp, len(data)), flush=True)
    return {
        "files": files,
        "surfaces": surfaces,
        "lod_index": lod_index,
        "lod_control": lod_control,
    }


_TEX_CACHE = OrderedDict()
_TEX_LOCK = threading.Lock()
_TEX_CACHE_MAX = 512
_TEX_CACHE_BYTES = 0
_TEX_CACHE_BYTES_MAX = 96 * 1024 * 1024


def tex_png(path: str) -> bytes:
    return image_to_png(read_indexed(STATE["index"], path), path, max_size=2048)


def resolve_entity_tik(model: str) -> str:
    """Map a BSP model key (statweapons//mg42_gun.tik) to a VFS .tik path."""
    if not STATE.get("index"):
        return ""
    raw = (model or "").replace("\\", "/").replace("//", "/").strip().lstrip("/")
    if not raw or raw.startswith("*"):
        return ""
    cands = [raw]
    if not raw.lower().endswith((".tik", ".tiki")):
        cands.append(raw + ".tik")
    more = []
    for c in cands:
        more.append(c)
        if not c.lower().startswith("models/"):
            more.append("models/" + c)
    seen = set()
    for c in more:
        key = norm(c)
        if key in seen:
            continue
        seen.add(key)
        rec = STATE["index"].get(key)
        if rec and rec.get("ext") in (".tik", ".tiki"):
            return rec["path"]
    stem = posixpath.splitext(posixpath.basename(raw))[0].lower()
    hits = [
        rec["path"]
        for rec in STATE["index"].values()
        if rec.get("ext") == ".tik" and posixpath.splitext(posixpath.basename(rec["path"]))[0].lower() == stem
    ]
    return hits[0] if len(hits) == 1 else ""


def collect_map_furniture(vp: str) -> list[dict]:
    """TIKI props at BSP entity origins and LUMP_STATICMODELDEF placements."""
    # Reload so a long-lived HTTP server cannot keep loc=(-Y,+X) / yaw+90 after
    # formats.py changes. Campaign/briefing/DM/obj all share these helpers.
    import importlib
    import formats as _formats

    importlib.reload(_formats)
    point_to_ue = _formats.mohaa_point_to_ue_cm
    angles_to_ue = _formats.mohaa_angles_to_ue
    model_scale_to_ue = _formats.mohaa_model_scale_to_ue
    data = read_indexed(STATE["index"], vp)
    grouped: dict[str, dict] = {}
    seen_spawn: set[tuple] = set()
    skipped = 0
    n_ent = 0
    n_static = 0
    cands: list[dict] = []
    for ent in parse_bsp_entities(data):
        cls = (ent.get("classname") or "").lower()
        if cls.startswith("ai_") or cls.startswith("info_") or cls.startswith("trigger"):
            continue
        cands.append(ent)
    cands.extend(parse_bsp_static_models(data))
    for ent in cands:
        tik = resolve_entity_tik(ent.get("model") or ent.get("modelname") or "")
        if not tik or not is_furniture_tik(tik):
            continue
        try:
            tik_obj, tik_file = load_tik("", tik)
        except Exception as exc:
            print("[furniture] tik fail %s: %s" % (tik, exc), flush=True)
            skipped += 1
            continue
        if not tik_obj:
            skipped += 1
            continue
        folder = (tik_obj.get("path") or "").rstrip("/") or posixpath.dirname(tik_file)
        skels = [resolve_skelmodel(STATE["index"], folder, sk) for sk in (tik_obj.get("skelmodels") or [])]
        skels = [p for p in skels if p and norm(p) in STATE["index"] and p.lower().endswith(".skd")]
        if not skels:
            print("[furniture] no skd for %s" % tik, flush=True)
            skipped += 1
            continue
        ox, oy, oz = entity_origin(ent)
        pitch, yaw, roll = entity_angles(ent)
        spawn_key = (norm(tik), round(ox, 2), round(oy, 2), round(oz, 2))
        if spawn_key in seen_spawn:
            continue
        seen_spawn.add(spawn_key)
        ue_loc = point_to_ue(ox, oy, oz)
        ue_rot = angles_to_ue(pitch, yaw, roll)
        scale = model_scale_to_ue(tik_obj.get("scale") or 1.0, entity_scale(ent))
        skeletal = bool(tik_obj.get("anims"))
        key = norm(tik)
        slot = grouped.get(key)
        if slot is None:
            slot = {
                "tik": tik_file or tik,
                "skd": skels[0],
                "name": Path(tik).stem,
                "skeletal": skeletal,
                "spawns": [],
            }
            grouped[key] = slot
        if skeletal:
            slot["skeletal"] = True
        cls = ent.get("classname") or ""
        slot["spawns"].append(
            {
                "location": [round(ue_loc[0], 3), round(ue_loc[1], 3), round(ue_loc[2], 3)],
                "rotation": [round(ue_rot[0], 3), round(ue_rot[1], 3), round(ue_rot[2], 3)],
                "scale": scale,
                "classname": cls,
                "origin": [ox, oy, oz],
            }
        )
        if cls == "static_model":
            n_static += 1
        else:
            n_ent += 1
    out = list(grouped.values())
    print(
        "[furniture] %s unique=%d instances=%d entity=%d static=%d skipped=%d"
        % (vp, len(out), sum(len(g["spawns"]) for g in out), n_ent, n_static, skipped),
        flush=True,
    )
    return out


def _tex_cache_get(key):
    with _TEX_LOCK:
        hit = _TEX_CACHE.get(key)
        if hit is not None:
            _TEX_CACHE.move_to_end(key)
        return hit


def _tex_cache_put(key, blob, ctype):
    global _TEX_CACHE_BYTES
    with _TEX_LOCK:
        if key in _TEX_CACHE:
            old, _ = _TEX_CACHE.pop(key)
            _TEX_CACHE_BYTES -= len(old)
        _TEX_CACHE[key] = (blob, ctype)
        _TEX_CACHE_BYTES += len(blob)
        while _TEX_CACHE and (
            len(_TEX_CACHE) > _TEX_CACHE_MAX or _TEX_CACHE_BYTES > _TEX_CACHE_BYTES_MAX
        ):
            _, oldv = _TEX_CACHE.popitem(last=False)
            _TEX_CACHE_BYTES -= len(oldv[0])
        if _TEX_CACHE_BYTES < 0:
            _TEX_CACHE_BYTES = 0


def preview_tex(path: str, max_size: int, fmt: str) -> tuple[bytes, str]:
    key = (norm(path), int(max_size), fmt)
    hit = _tex_cache_get(key)
    if hit is not None:
        return hit
    raw = read_indexed(STATE["index"], path)
    blob, ctype = encode_preview_image(raw, path, max_size=max_size, fmt=fmt)
    _tex_cache_put(key, blob, ctype)
    return blob, ctype


EXPORT_LOCK = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def end_headers(self):
        if not getattr(self, "_skip_no_cache", False):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, obj, code=200):
        data = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _bytes(self, data: bytes, content_type: str, cache_sec: int = 0):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if cache_sec:
            self._skip_no_cache = True
            self.send_header("Cache-Control", "public, max-age=%d" % cache_sec)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        endpoint = urlparse(self.path).path
        if endpoint not in ("/api/project/pick", "/api/project/open", "/api/game/pick"):
            self._json({"error": "Unknown endpoint"}, 404)
            return
        # Native Windows pickers return a local path; a file upload cannot.
        if self.headers.get("X-MOHAA-Local") != "1":
            self._json({"error": "Local path picker only"}, 403)
            return
        if endpoint == "/api/project/open":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError("Missing or oversized project request")
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(body, dict) or not isinstance(body.get("project"), str) or not body["project"].strip():
                    raise ValueError("Choose an Unreal project first")
                project = remember_project(body["project"])
                launched = launch_unreal_editor(project)
                self._json(launched)
            except Exception as exc:
                self._json({"error": "Could not open project: " + str(exc)}, 400)
            return
        if endpoint == "/api/game/pick":
            try:
                value = pick_game_folder(STATE.get("game") or "")
                if not value:
                    self._json({"cancelled": True})
                    return
                game = Path(value)
                if not game.is_dir():
                    raise ValueError("Choose an existing assets folder")
                STATE["game"] = str(game)
                save_paths()
                self._json({"game": str(game), "cancelled": False})
            except Exception as exc:
                self._json({"error": str(exc)}, 400)
            return
        try:
            value = pick_unreal_project(STATE.get("project") or "")
            if not value:
                self._json({"cancelled": True})
                return
            self._json(project_payload(remember_project(value)))
        except Exception as exc:
            self._json({"error": str(exc)}, 400)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/paths":
            active = get_active_project()
            project = None
            try:
                project = active or resolve_project(STATE.get("project") or None)
            except ValueError:
                project = None
            payload = {
                "game": STATE.get("game") or "",
                "project": str(project) if project else "",
                "folder": str(project.parent) if project else "",
                "name": project.stem if project else "",
                "editor": str(UE_EDITOR_UI) if UE_EDITOR_UI.is_file() else "",
            }
            self._json(payload)
            return
        if u.path == "/api/project":
            try:
                raw = (q.get("path", [""])[0] or "").strip()
                project = remember_project(raw or None)
                self._json(project_payload(project))
            except Exception as exc:
                self._json({"error": str(exc)}, 400)
            return
        if u.path == "/api/scan":
            path = q.get("path", [STATE["game"]])[0]
            try:
                self._json(scan_game(path))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._json({"error": str(e)}, 400)
            return
        if u.path == "/api/mesh":
            vp = unquote(q.get("path", [""])[0])
            tik_path = unquote(q.get("tik", [""])[0])
            try:
                self._json(load_mesh_payload(vp, tik_path))
            except Exception as e:
                self._json({"error": str(e)}, 400)
            return
        if u.path == "/api/export/progress":
            self._json(PROGRESS)
            return
        if u.path == "/api/export":
            if not EXPORT_LOCK.acquire(blocking=False):
                self._json({"error": "An export is already running. Try again when it finishes."}, 409)
                return
            vp = unquote(q.get("path", [""])[0])
            tik_path = unquote(q.get("tik", [""])[0])
            kind = (q.get("kind", ["unreal"])[0] or "unreal").lower()
            category = q.get("category", [""])[0]
            name = q.get("name", [""])[0]
            def _flag(key: str) -> bool:
                raw = (q.get(key, ["0"])[0] or "0").strip().lower()
                return raw in ("1", "true", "yes", "on")
            with_textures = _flag("textures")
            with_furniture = _flag("furniture")
            try:
                into_ue = kind in ("unreal", "ue", "batch", "unreal-skel", "skeletal")
                raw_project = (q.get("project", [""])[0] or "").strip()
                project = remember_project(raw_project or None) if into_ue else None
                payload = load_mesh_payload(
                    vp,
                    tik_path,
                    full_geometry=True,
                    include_inline=with_furniture,
                )
                skeletal = kind in ("unreal-skel", "skeletal", "fbx-skel", "skel")
                into_ue = kind in ("unreal", "ue", "batch", "unreal-skel", "skeletal")
                is_map = payload.get("kind") == "map" or (category or "").lower() == "maps"
                if is_map:
                    skeletal = False
                    if not with_textures:
                        with_textures = False
                    print(
                        "[export] map textures=%s furniture=%s"
                        % (int(with_textures), int(with_furniture)),
                        flush=True,
                    )
                else:
                    with_textures = True
                    with_furniture = False
                furniture_jobs = []
                if is_map and with_furniture:
                    for item in collect_map_furniture(vp):
                        try:
                            prop = load_mesh_payload(
                                item["skd"], item["tik"], full_geometry=True, use_idle=True
                            )
                            furniture_jobs.append({**item, "payload": prop})
                        except Exception as exc:
                            print("[furniture] skip %s: %s" % (item.get("tik"), exc), flush=True)
                lod_bundle = None
                anim_bundle = None
                if not is_map:
                    lod_bundle = collect_lod_bundle(payload.get("skel_paths") or [vp])
                if skeletal:
                    tik, tik_file = load_tik(vp, tik_path)
                    anim_bundle = build_anim_bundle(
                        tik,
                        tik_file,
                        payload.get("skel_paths") or [vp],
                        payload.get("skeleton") or [],
                    )
                result = export_asset(
                    payload,
                    name or Path(payload.get("source") or vp).stem,
                    category,
                    tex_png,
                    into_unreal=into_ue,
                    lod_bundle=lod_bundle,
                    skeletal=skeletal,
                    anim_bundle=anim_bundle,
                    project=project,
                    with_textures=with_textures,
                    furniture_jobs=furniture_jobs,
                )
                PROGRESS["active"] = False
                PROGRESS["pct"] = 100
                self._json(result)
            except Exception as e:
                print("[export] fail %s" % e, flush=True)
                PROGRESS["status"] = "Failed"
                PROGRESS["active"] = False
                PROGRESS["pct"] = 100
                self._json({"error": str(e), "ok": False}, 400)
            finally:
                EXPORT_LOCK.release()
            return
        if u.path == "/api/tex":
            vp = unquote(q.get("path", [""])[0])
            try:
                if vp.startswith("builtin:"):
                    img = Image.new("RGBA", (4, 4), (255, 255, 255, 255))
                    out = BytesIO()
                    img.save(out, format="PNG")
                    self._bytes(out.getvalue(), "image/png", cache_sec=86400)
                    return
                try:
                    max_size = int(q.get("w", ["1024"])[0] or 1024)
                except ValueError:
                    max_size = 1024
                max_size = max(32, min(max_size, 2048))
                fmt = (q.get("fmt", ["jpeg"])[0] or "jpeg").lower()
                blob, ctype = preview_tex(vp, max_size, fmt)
                self._bytes(blob, ctype, cache_sec=86400)
            except Exception as e:
                self._json({"error": str(e)}, 400)
            return
        if u.path == "/" or u.path == "/index.html":
            self.path = "/index.html"
        return super().do_GET()


def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Open http://127.0.0.1:%d" % PORT, flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
