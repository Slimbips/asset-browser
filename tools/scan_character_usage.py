#!/usr/bin/env python3
"""Scan MOHAA game data for actual human/player character instantiation.

Read-only analysis. Does not modify exporters, Unreal assets, or FBX.
"""
from __future__ import annotations

import json
import posixpath
import re
import sys
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import (  # noqa: E402
    DEFAULT_GAME,
    _file_rec,
    _pak,
    add_loose_files,
    find_pk3s,
    norm,
    read_indexed,
)

REPORT_JSON = ROOT / "tools" / "skeleton_compat_report.json"
OUT_JSON = ROOT / "tools" / "character_usage_report.json"
OUT_MD = ROOT / "tools" / "character_usage_report.md"

TEXT_EXTS = {
    ".tik",
    ".tiki",
    ".scr",
    ".txt",
    ".menu",
    ".cfg",
    ".con",
    ".dat",
    ".def",
    ".inc",
    ".map",
    ".arena",
    ".hud",
    ".mnu",
    ".skin",
    ".anim",
    ".state",
    ".ai",
    ".npc",
    ".sp",
    ".script",
    ".csv",
    ".lst",
    ".list",
    ".res",
    ".ini",
    ".json",
    ".xml",
    ".h",
    ".c",
    ".precache",
    ".rumble",
    ".st",
    ".os",
    ".game",
    ".ddef",
    ".mus",
    ".shader",
    ".mtr",
    ".min",
}

# DMprecache / .min names that do not match the roster filename.
# allied_oss is intentionally omitted: there is no models/player/allied_oss.tik
# (allied_SAS.tik is French resistance, not OSS).
PLAYER_ALIASES = {
    "german_winter1": "german_winter_1",
    "german_winter2": "german_winter_2",
    "german_elite_gestapo": "german_elite_officer",
}
QUAKED_RE = re.compile(r"/\*\s*QUAKED\s+(\S+)", re.I)
LOC_PAIR_RE = re.compile(r'\{\s*"([^"]+)"\s+"([^"]*)"\s*\}')
CLASSNAME_TOKEN_RE = re.compile(r"\bai_[a-z0-9_\-]+\b", re.I)
SKIP_EXTS = {
    ".tga",
    ".jpg",
    ".jpeg",
    ".png",
    ".dds",
    ".gif",
    ".bmp",
    ".skd",
    ".skc",
    ".wav",
    ".mp3",
    ".ogg",
    ".mp2",
    ".md3",
    ".obj",
    ".fbx",
    ".bin",
    ".dll",
    ".exe",
    ".pk3",
    ".zip",
    ".pak",
}
ARCHIVE_EXTS = {".pk3", ".zip", ".pak", ".pk4"}
MAX_TEXT_BYTES = 40 * 1024 * 1024
SNIPPET = 120
REPR_LIMIT = 20

ENTITY_KEYS_DIRECT = {
    "model",
    "model2",
    "model3",
    "skin",
    "classname",
    "spawnname",
    "npc",
    "actor",
    "ai",
    "aitype",
    "type",
    "character",
    "playermodel",
    "body",
    "ai_model",
}
ENTITY_KEYS_WEAK = {"targetname", "target", "name", "anim", "idle"}
CMD_DIRECT = (
    "spawn",
    "waitspawn",
    "setmodel",
    "model",
    "precache",
    "precachemodel",
    "include",
    "$include",
    "exec",
)
PATH_RE = re.compile(
    r'(?:models[/\\])?(human|player)[/\\]([a-z0-9_\-]+)\.tik\b',
    re.I,
)
PATH_NOEXT_RE = re.compile(
    r'(?:models[/\\])?(human|player)[/\\]([a-z0-9_\-]+)(?!\.tik)(?![a-z0-9_\-/\\])',
    re.I,
)
TIK_FILE_RE = re.compile(r'(?<![a-z0-9_\-/\\])([a-z0-9_\-]+\.tik)\b', re.I)
QUOTED_RE = re.compile(r'"([^"\n]{3,120})"')
KV_RE = re.compile(r'"([^"]+)"\s+"([^"]*)"')
CONCAT_RE = re.compile(
    r'''(?x)
    (?:["']models[/\\](human|player)[/\\]["']\s*\+)
    | (?:\+\s*["']\.tik["'])
    | (?:["'](?:models[/\\])?(human|player)[/\\]["'])
    | (?:models[/\\](human|player)[/\\]\*)
    | (?:sprintf\s*\([^)]*(?:human|player)[/\\])
    ''',
    re.I,
)
WILDCARD_RE = re.compile(
    r'(?:models[/\\])?(human|player)[/\\][a-z0-9_\-]*\*|\*\.tik',
    re.I,
)
PREFIX_CONCAT_RE = re.compile(
    r'''(?x)
    ["'](
        1st-ranger_|2nd-ranger_|dday_ranger_|dday_29th_|
        german_afrika_|german_elite_|german_panzer_|
        german_waffenss_|german_wehrmact_|german_winter_|
        allied_|american_|german_
    )["']\s*\+
    ''',
    re.I,
)


def build_index(game_dir: str) -> tuple[dict, list[Path]]:
    game = Path(game_dir)
    if not game.is_dir():
        raise FileNotFoundError(game_dir)
    index: dict = {}
    paks = find_pk3s(game)
    extra_archives = []
    for sub in ("", "main", "mainta", "maintt"):
        d = game / sub if sub else game
        if not d.is_dir():
            continue
        for fn in sorted(d.iterdir()):
            if fn.is_file() and fn.suffix.lower() in ARCHIVE_EXTS and fn not in paks:
                extra_archives.append(fn)
    all_archives = list(paks) + extra_archives
    for pak in all_archives:
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
    for pak in all_archives:
        _pak(str(pak))
    print("index: %d archives, %d files" % (len(all_archives), len(index)), flush=True)
    return index, all_archives


def load_roster(report: dict) -> list[dict]:
    chars = []
    for g in report["groups"]:
        for c in g["characters"]:
            tik = c["tik"].replace("\\", "/")
            folder = "player" if tik.lower().startswith("models/player/") else "human"
            stem = posixpath.splitext(posixpath.basename(tik))[0]
            chars.append(
                {
                    "name": c["name"],
                    "tik": tik,
                    "tik_n": norm(tik),
                    "group": g["letter"],
                    "folder": folder,
                    "stem": stem,
                    "stem_n": stem.lower(),
                }
            )
    seen = {c["tik_n"] for c in chars}
    for err in report.get("summary", {}).get("errors", []):
        tik = (err.get("tik") or "").replace("\\", "/")
        if not tik or norm(tik) in seen:
            continue
        stem = posixpath.splitext(posixpath.basename(tik))[0]
        folder = "player" if tik.lower().startswith("models/player/") else "human"
        chars.append(
            {
                "name": stem.replace("_", " ").replace("-", " ").title(),
                "tik": tik,
                "tik_n": norm(tik),
                "group": None,
                "folder": folder,
                "stem": stem,
                "stem_n": stem.lower(),
                "no_skel": True,
            }
        )
    return chars


def is_self(src_n: str, char: dict) -> bool:
    return src_n == char["tik_n"]


def file_kind(path: str) -> str:
    p = path.replace("\\", "/").lower()
    ext = posixpath.splitext(p)[1]
    if ext == ".bsp" or p.startswith("maps/") or ext == ".map":
        return "map"
    if ext in {".scr", ".script", ".sp", ".ai", ".npc", ".state"}:
        return "script"
    if ext in {".tik", ".tiki"}:
        return "tik"
    if ext in {".menu", ".mnu", ".hud", ".txt"} and ("ui/" in p or "menu" in p):
        return "menu"
    if ext in {".cfg", ".con", ".menu", ".mnu", ".hud"}:
        return "config"
    return "other"


def should_scan(rec: dict) -> bool:
    ext = (rec.get("ext") or posixpath.splitext(rec["path"])[1]).lower()
    if ext in SKIP_EXTS:
        return False
    if ext in TEXT_EXTS or ext == ".bsp":
        return True
    if ext == "":
        return rec.get("size", 0) < 512 * 1024
    if rec.get("size", 0) <= 256 * 1024 and ext not in {".skd", ".skc"}:
        return True
    return False


def looks_text(data: bytes) -> bool:
    if not data:
        return False
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13))
    return printable / max(1, len(sample)) > 0.75


def bsp_search_text(data: bytes) -> str:
    """Prefer the entity lump; fall back to the whole file as latin-1."""
    if len(data) >= 20 and data[:4] == b"2015":
        try:
            for i in range(28):
                ofs, ln = __import__("struct").unpack_from("<ii", data, 12 + i * 8)
                if ln <= 0 or ofs < 0 or ofs + ln > len(data):
                    continue
                lump = data[ofs : ofs + ln]
                if b'"classname"' in lump or b"classname" in lump:
                    return lump.decode("latin-1", "replace")
        except Exception:
            pass
    text = data.decode("latin-1", "replace")
    if '"classname"' in text or "models/human/" in text.lower() or "models/player/" in text.lower():
        return text
    return ""


def load_text(index: dict, rec: dict) -> str | None:
    ext = (rec.get("ext") or "").lower()
    size = rec.get("size") or 0
    if size > MAX_TEXT_BYTES:
        return None
    try:
        data = read_indexed(index, rec["path"])
    except Exception:
        return None
    if ext == ".bsp":
        return bsp_search_text(data)
    if ext in TEXT_EXTS:
        return data.decode("latin-1", "replace")
    if looks_text(data):
        return data.decode("latin-1", "replace")
    # Still scan BSP-like / leftover archives for .tik ASCII even if mixed binary
    if b".tik" in data.lower() or b"models/human" in data.lower() or b"models/player" in data.lower():
        return data.decode("latin-1", "replace")
    return None


def nearby_line(text: str, idx: int) -> str:
    start = text.rfind("\n", 0, idx)
    end = text.find("\n", idx)
    if start < 0:
        start = 0
    else:
        start += 1
    if end < 0:
        end = min(len(text), idx + SNIPPET)
    line = text[start:end].strip()
    if len(line) > SNIPPET:
        off = max(0, idx - start - 40)
        line = line[off : off + SNIPPET]
    return " ".join(line.split())


def classify_hit_kind(src_kind: str, line: str, has_path: bool, key: str | None) -> tuple[str, bool]:
    """Return (kind, direct)."""
    low = line.lower()
    if key:
        k = key.lower()
        if k in ENTITY_KEYS_DIRECT:
            return ("entity_" + k, True)
        if k in ENTITY_KEYS_WEAK:
            return ("entity_" + k, False)
    if "$include" in low or low.lstrip().startswith("include"):
        return ("tik_include", True)
    if "waitspawn" in low:
        return ("script_waitspawn", True)
    if re.search(r"\bspawn\b", low):
        return ("script_spawn", True)
    if "setmodel" in low or "set model" in low:
        return ("script_setmodel", True)
    if "precache" in low:
        return ("script_precache", True)
    if has_path and src_kind == "map":
        return ("map_model_path", True)
    if has_path and src_kind == "script":
        return ("script_model_path", True)
    if has_path and src_kind == "tik":
        return ("tik_path", True)
    if has_path and src_kind == "menu":
        return ("menu_model", True)
    if has_path:
        return ("path", True)
    if src_kind == "menu":
        return ("menu_name", False)
    return ("bare_name", False)


def add_ref(bucket: dict, char_tik_n: str, rec: dict, kind: str, direct: bool, snippet: str) -> None:
    file_n = rec["path"].replace("\\", "/")
    key = (char_tik_n, file_n, kind, direct)
    slot = bucket.get(key)
    if slot is None:
        bucket[key] = {
            "tik_n": char_tik_n,
            "file": file_n,
            "file_n": norm(file_n),
            "pak": rec.get("pak") or "",
            "source": rec.get("source") or "",
            "kind": kind,
            "direct": direct,
            "count": 1,
            "snippet": snippet,
        }
    else:
        slot["count"] += 1
        if len(slot["snippet"]) < 20 and snippet:
            slot["snippet"] = snippet


def compact_stem(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def resolve_chars(
    by_folder_stem: dict,
    by_stem: dict,
    by_compact: dict,
    folder: str | None,
    stem_n: str,
) -> list[dict]:
    stem_n = (stem_n or "").lower()
    folder_n = folder.lower() if folder else None
    if folder_n == "player" and stem_n in PLAYER_ALIASES:
        stem_n = PLAYER_ALIASES[stem_n]
    if folder_n:
        hit = by_folder_stem.get((folder_n, stem_n))
        if hit:
            return [hit]
        compact_hits = by_compact.get((folder_n, compact_stem(stem_n))) or []
        if len(compact_hits) == 1:
            return list(compact_hits)
        return []
    hits = list(by_stem.get(stem_n) or [])
    if hits:
        return hits
    compact_hits = by_compact.get((None, compact_stem(stem_n))) or []
    return list(compact_hits)


def scan_text(
    rec: dict,
    text: str,
    chars: list[dict],
    by_folder_stem: dict,
    by_stem: dict,
    by_compact: dict,
    by_classname: dict,
    bucket: dict,
    dynamic: dict,
) -> None:
    src = rec["path"].replace("\\", "/")
    src_n = norm(src)
    src_kind = file_kind(src)
    low = text.lower()

    for m in CONCAT_RE.finditer(text):
        folder = (m.group(1) or m.group(2) or m.group(3) or "").lower()
        dynamic["concat"].append({"file": src, "folder": folder or "any", "snippet": nearby_line(text, m.start())})
    for m in WILDCARD_RE.finditer(text):
        folder = (m.group(1) or "").lower()
        dynamic["wildcard"].append({"file": src, "folder": folder or "any", "snippet": nearby_line(text, m.start())})
    for m in PREFIX_CONCAT_RE.finditer(text):
        dynamic["prefix"].append({"file": src, "prefix": m.group(1).lower(), "snippet": nearby_line(text, m.start())})

    # Quoted key/value pairs (map entities, some scripts)
    for m in KV_RE.finditer(text):
        key = m.group(1).strip()
        val = m.group(2).strip().replace("\\", "/")
        val_n = val.lower()
        folder = None
        stem = None
        has_path = False
        pm = PATH_RE.search(val)
        if pm:
            folder, stem = pm.group(1).lower(), pm.group(2).lower()
            has_path = True
        else:
            pm = PATH_NOEXT_RE.search(val)
            if pm:
                folder, stem = pm.group(1).lower(), pm.group(2).lower()
                has_path = True
            elif val_n.endswith(".tik"):
                stem = posixpath.splitext(posixpath.basename(val_n))[0]
                if "/human/" in val_n or val_n.startswith("human/"):
                    folder, has_path = "human", True
                elif "/player/" in val_n or val_n.startswith("player/"):
                    folder, has_path = "player", True
            elif key.lower() in ENTITY_KEYS_DIRECT | ENTITY_KEYS_WEAK:
                base = posixpath.splitext(posixpath.basename(val_n))[0]
                if base in by_stem:
                    stem = base
        if not stem:
            continue
        targets = resolve_chars(by_folder_stem, by_stem, by_compact, folder, stem)
        if not targets:
            continue
        line = nearby_line(text, m.start())
        kind, direct = classify_hit_kind(src_kind, line, has_path or bool(folder), key)
        if len(targets) > 1 and not folder:
            direct = False
            kind = "ambiguous_name"
        for ch in targets:
            if is_self(src_n, ch):
                continue
            add_ref(bucket, ch["tik_n"], rec, kind, direct, line)

    # Localization / UI identity pairs { "allied_SAS" "allied_SAS" }
    if "localization" in src_n or src_kind in {"menu", "config"}:
        for m in LOC_PAIR_RE.finditer(text):
            a, b = m.group(1), m.group(2)
            if a.lower() != b.lower():
                continue
            targets = resolve_chars(by_folder_stem, by_stem, by_compact, "player", a.lower())
            if not targets:
                continue
            line = nearby_line(text, m.start())
            for ch in targets:
                if is_self(src_n, ch):
                    continue
                add_ref(bucket, ch["tik_n"], rec, "menu_class_name", False, line)

    # QUAKED spawn classnames (ai_allied_2nd-ranger_sergeant, …)
    # Skip roster TIK files: those only *define* the classname.
    roster_src = src_n.startswith("models/human/") or src_n.startswith("models/player/")
    if by_classname and not (src_kind == "tik" and roster_src and src_n.count("/") == 2):
        for m in CLASSNAME_TOKEN_RE.finditer(text):
            cls = m.group(0).lower()
            targets = by_classname.get(cls) or []
            if not targets:
                continue
            line = nearby_line(text, m.start())
            window = text[max(0, m.start() - 250) : m.end() + 400]
            model_override = False
            pm = PATH_RE.search(window) or PATH_NOEXT_RE.search(window)
            if pm:
                folder, stem = pm.group(1).lower(), pm.group(2).lower()
                other = resolve_chars(by_folder_stem, by_stem, by_compact, folder, stem)
                if other and not any(o["tik_n"] == t["tik_n"] for t in targets for o in other):
                    model_override = True
            kind = "classname_model_override" if model_override else "classname_quaked"
            direct = not model_override
            for ch in targets:
                if is_self(src_n, ch):
                    continue
                add_ref(bucket, ch["tik_n"], rec, kind, direct, line)

    # Path mentions not already captured as KV
    for rx, with_ext in ((PATH_RE, True), (PATH_NOEXT_RE, False)):
        for m in rx.finditer(text):
            folder, stem = m.group(1).lower(), m.group(2).lower()
            targets = resolve_chars(by_folder_stem, by_stem, by_compact, folder, stem)
            if not targets:
                continue
            # skip models/human/animation etc — stem not in roster
            line = nearby_line(text, m.start())
            # avoid counting the same KV again by still counting; unique key includes kind
            kind, direct = classify_hit_kind(src_kind, line, True, None)
            if not with_ext and "tik" not in line.lower() and not any(c in line.lower() for c in CMD_DIRECT):
                # path without extension and no spawn-ish context: still a model path
                if src_kind in {"map", "tik"}:
                    pass
                else:
                    direct = True
            for ch in targets:
                if is_self(src_n, ch):
                    continue
                add_ref(bucket, ch["tik_n"], rec, kind, direct, line)

    # Bare filename.tik
    for m in TIK_FILE_RE.finditer(text):
        fname = m.group(1).lower()
        stem = posixpath.splitext(fname)[0]
        # If this match is part of a human/player path, PATH_RE already handled it
        start = m.start()
        prefix = low[max(0, start - 18) : start]
        if prefix.endswith("human/") or prefix.endswith("human\\") or prefix.endswith("player/") or prefix.endswith("player\\"):
            continue
        targets = resolve_chars(by_folder_stem, by_stem, by_compact, None, stem)
        if not targets:
            continue
        line = nearby_line(text, start)
        kind, direct = classify_hit_kind(src_kind, line, False, None)
        if len(targets) > 1:
            # try to disambiguate from the same line
            if "models/player/" in line.lower() or "/player/" in line.lower():
                targets = [t for t in targets if t["folder"] == "player"] or targets
            elif "models/human/" in line.lower() or "/human/" in line.lower():
                targets = [t for t in targets if t["folder"] == "human"] or targets
            if len(targets) > 1:
                kind, direct = "ambiguous_name", False
        for ch in targets:
            if is_self(src_n, ch):
                continue
            add_ref(bucket, ch["tik_n"], rec, kind, direct, line)

    # Command tokens: spawn <stem> / waitspawn <stem> without .tik
    cmd_re = re.compile(
        r'(?im)^\s*(?:\$)?(?:spawn|waitspawn|setmodel|precachemodel|precache)\s+([a-z0-9_/\.\-\\]+)'
    )
    for m in cmd_re.finditer(text):
        tok = m.group(1).replace("\\", "/").lower()
        if tok.startswith("ai_") or tok in {"origin", "at", "actor", "info_player_start"}:
            # still try stem after last slash
            pass
        base = posixpath.splitext(posixpath.basename(tok))[0]
        folder = None
        if "/human/" in tok or tok.startswith("human/"):
            folder = "human"
        elif "/player/" in tok or tok.startswith("player/"):
            folder = "player"
        targets = resolve_chars(by_folder_stem, by_stem, by_compact, folder, base)
        if not targets:
            continue
        line = nearby_line(text, m.start())
        kind, direct = classify_hit_kind(src_kind, line, bool(folder), None)
        if len(targets) > 1 and not folder:
            kind, direct = "ambiguous_name", False
        for ch in targets:
            if is_self(src_n, ch):
                continue
            add_ref(bucket, ch["tik_n"], rec, kind, direct, line)


def collapse_character(char: dict, refs: list[dict], possibly_reasons: list[str]) -> dict:
    files = {}
    direct_n = 0
    indirect_n = 0
    for r in refs:
        files.setdefault(r["file"], []).append(r)
        if r["direct"]:
            direct_n += r["count"]
        else:
            indirect_n += r["count"]
    total = sum(r["count"] for r in refs)
    file_list = []
    for fn, items in sorted(files.items(), key=lambda kv: -sum(i["count"] for i in kv[1])):
        kinds = sorted({i["kind"] for i in items})
        file_list.append(
            {
                "file": fn,
                "pak": items[0]["pak"],
                "source": items[0]["source"],
                "count": sum(i["count"] for i in items),
                "kinds": kinds,
                "direct": any(i["direct"] for i in items),
                "snippet": items[0]["snippet"],
            }
        )
    if total and direct_n:
        classification = "USED"
        rel = "direct" if indirect_n == 0 or direct_n >= indirect_n else "direct+indirect"
    elif total:
        classification = "USED"
        rel = "indirect"
        # targetname-only / ambiguous-only stays POSSIBLY if no spawn-ish kind
        weak_only = all(
            r["kind"].startswith("entity_target")
            or r["kind"] in {"ambiguous_name", "bare_name", "menu_name", "entity_name", "classname_model_override"}
            for r in refs
        )
        if weak_only:
            classification = "POSSIBLY_USED"
            rel = "indirect"
            if any(r["kind"] == "classname_model_override" for r in refs):
                possibly_reasons.append("classname used in maps but model spawnarg points at a different TIK")
    else:
        classification = "UNUSED"
        rel = None
        if possibly_reasons:
            classification = "POSSIBLY_USED"
            rel = "indirect"

    return {
        "name": char["name"],
        "tik": char["tik"],
        "group": char["group"],
        "folder": char["folder"],
        "stem": char["stem"],
        "no_skel": bool(char.get("no_skel")),
        "classification": classification,
        "direct_or_indirect": rel,
        "reference_count": total,
        "file_count": len(file_list),
        "direct_count": direct_n,
        "indirect_count": indirect_n,
        "possibly_reasons": possibly_reasons,
        "quaked": list(char.get("quaked") or []),
        "references": file_list,
    }


def md_escape(s: str) -> str:
    return (s or "").replace("|", "\\|")


def representative(files: list[dict], limit: int = REPR_LIMIT) -> list[dict]:
    return files[:limit]


def render_md(data: dict) -> str:
    lines = []
    a = lines.append
    a("# MOHAA character usage")
    a("")
    a("Analysis only. No exporter, Unreal, or FBX changes. Instantiation scan of game data (pk3/zip + loose `main` / `mainta` / `maintt`).")
    a("")
    a("## Method")
    a("")
    a("- Roster: skeleton groups A–G from `tools/skeleton_compat_report.json` (%d characters), plus no-skel roster TIKIs listed in that report’s errors (`deaths.tik`, `new_generic_human.tik`)." % data["summary"]["skeleton_report_characters"])
    a("- Game root: `%s`" % data["game"])
    a("- Archives scanned: **%d** (%s)" % (len(data["archives"]), ", ".join("`%s`" % x for x in data["archives"][:12]) + ("…" if len(data["archives"]) > 12 else "")))
    a("- Indexed files: **%d**; text/map/script files searched: **%d**" % (data["index_files"], data["files_searched"]))
    a("- Search: `.tik`/`.tiki`, `.map`/`.bsp` entity defs, `.min` precache manifests, scripts (`.scr` `.txt` `.menu` `.cfg` …), `$include`, `spawn`/`waitspawn`/`setmodel`/`precache`, classname/model keys, QUAKED `ai_*` classnames, short TIKI stems, `models/human/<name>` and `models/player/<name>`.")
    a("- Player aliases: `german_winter1` → `german_Winter_1`, `german_winter2` → `german_Winter_2`, `german_elite_gestapo` → `german_Elite_Officer` (player TIK uses the gestapo mesh).")
    a("- MP UI: `global/localization.txt` class-name keys match `models/player/<stem>.tik` by naming convention.")
    a("- Self-references (a character TIK naming itself) are ignored.")
    a("- **USED**: explicit path, include, spawn/setmodel/precache, entity model/classname, DMprecache/min, or MP class-name list.")
    a("- **POSSIBLY_USED**: string concat / wildcards / prefix tables / classname with a different model override / shared QUAKED classname. Dynamic `models/human/` + `ai_model` concat bumps unmatched human actors to POSSIBLY_USED rather than UNUSED.")
    a("- **UNUSED**: no references and no dynamic loader that could instantiate it.")
    a("")
    a("## Summary")
    a("")
    s = data["summary"]
    a("- Total discovered human characters: **%d**" % s["total"])
    a("- Actually referenced (USED): **%d**" % s["used"])
    a("- Possibly referenced (POSSIBLY_USED): **%d**" % s["possibly_used"])
    a("- No references found (UNUSED): **%d**" % s["unused"])
    a("- Of those, skeleton-report characters (groups A–G): **%d** (USED %d / POSSIBLY %d / UNUSED %d)" % (
        s["skeleton_report_characters"],
        s["skel_used"],
        s["skel_possibly"],
        s["skel_unused"],
    ))
    a("")
    if data.get("dynamic_notes"):
        a("### Dynamic / alias patterns")
        a("")
        for n in data["dynamic_notes"]:
            a("- %s" % n)
        a("")
    a("## Usage per skeleton group")
    a("")
    a("| group | used | possibly | unused | used names | possibly names | unused names |")
    a("|---|---:|---:|---:|---|---|---|")
    for g in data["groups"]:
        def names(key):
            xs = g[key]
            return ", ".join(xs) if xs else "—"
        a(
            "| %s | %d | %d | %d | %s | %s | %s |"
            % (
                g["letter"],
                g["used_count"],
                g["possibly_count"],
                g["unused_count"],
                md_escape(names("used_names")),
                md_escape(names("possibly_names")),
                md_escape(names("unused_names")),
            )
        )
    a("")
    for g in data["groups"]:
        a("### Group %s" % g["letter"])
        a("")
        a("- USED (%d): %s" % (g["used_count"], ", ".join(g["used_names"]) or "—"))
        a("- POSSIBLY_USED (%d): %s" % (g["possibly_count"], ", ".join(g["possibly_names"]) or "—"))
        a("- UNUSED (%d): %s" % (g["unused_count"], ", ".join(g["unused_names"]) or "—"))
        a("")

    def emit_char_section(title: str, items: list[dict]) -> None:
        a("## %s" % title)
        a("")
        if not items:
            a("_None._")
            a("")
            return
        for c in items:
            a("### %s (`%s`)" % (c["name"], c["tik"]))
            a("")
            a("- Skeleton group: **%s**" % (c["group"] or "(no skel)"))
            a("- Classification: **%s**" % c["classification"])
            a("- Direct or indirect: %s" % (c["direct_or_indirect"] or "—"))
            a("- References: **%d** in **%d** files" % (c["reference_count"], c["file_count"]))
            if c.get("possibly_reasons"):
                a("- Why possibly: %s" % "; ".join(c["possibly_reasons"]))
            if c["references"]:
                a("- Files (representative%s):" % (" of %d" % c["file_count"] if c["file_count"] > REPR_LIMIT else ""))
                for f in representative(c["references"]):
                    pak = " in `%s`" % f["pak"] if f["pak"] and f["pak"] != "(loose)" else ""
                    a(
                        "  - `%s`%s — %d hit(s), %s%s"
                        % (
                            f["file"],
                            pak,
                            f["count"],
                            ", ".join(f["kinds"]),
                            (" — `" + f["snippet"][:80] + "`") if f.get("snippet") else "",
                        )
                    )
                extra = c["file_count"] - min(REPR_LIMIT, c["file_count"])
                if extra > 0:
                    a("  - … +%d more files" % extra)
            a("")

    emit_char_section("USED characters", [c for c in data["characters"] if c["classification"] == "USED" and not c.get("no_skel")])
    emit_char_section("POSSIBLY_USED characters", [c for c in data["characters"] if c["classification"] == "POSSIBLY_USED" and not c.get("no_skel")])
    emit_char_section("UNUSED characters", [c for c in data["characters"] if c["classification"] == "UNUSED" and not c.get("no_skel")])
    extras = [c for c in data["characters"] if c.get("no_skel")]
    if extras:
        emit_char_section("Roster TIKIs with no skeleton", extras)
    return "\n".join(lines) + "\n"


def main() -> int:
    game = str(DEFAULT_GAME)
    if len(sys.argv) > 1:
        game = sys.argv[1]
    report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    chars = load_roster(report)
    by_folder_stem = {}
    by_stem = defaultdict(list)
    by_compact = defaultdict(list)
    for c in chars:
        by_folder_stem[(c["folder"], c["stem_n"])] = c
        by_stem[c["stem_n"]].append(c)
        by_compact[(c["folder"], compact_stem(c["stem_n"]))].append(c)
        by_compact[(None, compact_stem(c["stem_n"]))].append(c)

    index, archives = build_index(game)
    by_classname = defaultdict(list)
    for c in chars:
        c["quaked"] = []
        try:
            raw = read_indexed(index, c["tik"]).decode("latin-1", "replace")
        except Exception:
            continue
        for m in QUAKED_RE.finditer(raw):
            cls = m.group(1).lower()
            c["quaked"].append(cls)
            by_classname[cls].append(c)

    bucket: dict = {}
    dynamic = {"concat": [], "wildcard": [], "prefix": []}
    searched = 0
    skipped = 0
    for rec in index.values():
        if not should_scan(rec):
            skipped += 1
            continue
        text = load_text(index, rec)
        if not text:
            skipped += 1
            continue
        searched += 1
        if searched % 500 == 0:
            print("scanned %d files…" % searched, flush=True)
        scan_text(
            rec,
            text,
            chars,
            by_folder_stem,
            by_stem,
            by_compact,
            by_classname,
            bucket,
            dynamic,
        )

    refs_by_char = defaultdict(list)
    for hit in bucket.values():
        refs_by_char[hit["tik_n"]].append(hit)

    concat_folders = set()
    for hit in dynamic["concat"]:
        concat_folders.add(hit["folder"] or "any")
    wild_folders = set()
    for hit in dynamic["wildcard"]:
        wild_folders.add(hit["folder"] or "any")
    prefixes = sorted({h["prefix"] for h in dynamic["prefix"]})

    dynamic_notes = []
    if dynamic["concat"]:
        files = sorted({h["file"] for h in dynamic["concat"]})
        dynamic_notes.append(
            "Path concatenation involving `models/human/` or `models/player/` in %d file(s): %s"
            % (len(files), ", ".join("`%s`" % f for f in files[:8]) + ("…" if len(files) > 8 else ""))
        )
    if dynamic["wildcard"]:
        files = sorted({h["file"] for h in dynamic["wildcard"]})
        dynamic_notes.append(
            "Wildcard TIKI/model glob in %d file(s): %s"
            % (len(files), ", ".join("`%s`" % f for f in files[:8]) + ("…" if len(files) > 8 else ""))
        )
    if prefixes:
        dynamic_notes.append("Prefix string-concat tables: " + ", ".join("`" + p + "`" for p in prefixes))
    dynamic_notes.append(
        "Player TIK aliases: DMprecache/min use `german_winter1`/`german_winter2` for `german_Winter_1`/`german_Winter_2`, and `german_elite_gestapo` for `german_Elite_Officer`. `models/player/allied_oss.tik` is cached but that file does not exist (not treated as allied_SAS)."
    )
    dynamic_notes.append(
        "MP class names in `global/localization.txt` match `models/player/<name>.tik` stems (UI naming convention)."
    )
    dup_cls = {k: v for k, v in by_classname.items() if len(v) > 1}
    if dup_cls:
        bits = []
        for k, vs in sorted(dup_cls.items()):
            bits.append("`%s` → %s" % (k, ", ".join(c["tik"] for c in vs)))
        dynamic_notes.append("Shared QUAKED classnames: " + "; ".join(bits))

    results = []
    for c in chars:
        reasons = []
        folder = c["folder"]
        if not refs_by_char.get(c["tik_n"]):
            # Generic models/human/ + ai_model concat can spawn any human actor stem.
            # Do not apply to no-skel animation packs (deaths.tik) or player models.
            if folder == "human" and not c.get("no_skel") and ("human" in concat_folders or "any" in concat_folders):
                reasons.append("dynamic `models/human/` + `ai_model` concat (global/mg42_active.scr)")
            if folder == "player" and ("player" in concat_folders or "any" in concat_folders):
                reasons.append("dynamic path concat for models/player/")
            if "any" in wild_folders or folder in wild_folders:
                reasons.append("wildcard glob for models/%s/" % folder)
            for pfx in prefixes:
                if c["stem_n"].startswith(pfx):
                    reasons.append("prefix concat `%s`" % pfx)
            if len(c.get("quaked") or []) > 0:
                for cls in c["quaked"]:
                    if cls in dup_cls:
                        reasons.append("shared QUAKED classname `%s`" % cls)
        results.append(collapse_character(c, refs_by_char.get(c["tik_n"], []), reasons))

    results.sort(key=lambda c: ((c["group"] or "Z"), c["name"].lower(), c["tik"].lower()))

    def counts(items):
        used = [c for c in items if c["classification"] == "USED"]
        poss = [c for c in items if c["classification"] == "POSSIBLY_USED"]
        unused = [c for c in items if c["classification"] == "UNUSED"]
        return used, poss, unused

    skel = [c for c in results if not c.get("no_skel")]
    used, poss, unused = counts(results)
    su, sp, sn = counts(skel)

    def disp(c):
        same = sum(1 for x in results if x["name"] == c["name"])
        if same > 1:
            return "%s [%s]" % (c["name"], c["folder"])
        return c["name"]

    groups_out = []
    for g in report["groups"]:
        members = [c for c in results if c["group"] == g["letter"]]
        u, p, n = counts(members)
        groups_out.append(
            {
                "letter": g["letter"],
                "bone_count": g.get("bone_count"),
                "used_count": len(u),
                "possibly_count": len(p),
                "unused_count": len(n),
                "used_names": [disp(c) for c in u],
                "possibly_names": [disp(c) for c in p],
                "unused_names": [disp(c) for c in n],
                "used_tiks": [c["tik"] for c in u],
                "possibly_tiks": [c["tik"] for c in p],
                "unused_tiks": [c["tik"] for c in n],
            }
        )

    out = {
        "game": game,
        "archives": [p.name for p in archives],
        "index_files": len(index),
        "files_searched": searched,
        "files_skipped": skipped,
        "dynamic_notes": dynamic_notes,
        "dynamic_raw": {
            "concat_files": sorted({h["file"] for h in dynamic["concat"]}),
            "wildcard_files": sorted({h["file"] for h in dynamic["wildcard"]}),
            "prefixes": prefixes,
            "player_aliases": PLAYER_ALIASES,
        },
        "summary": {
            "total": len(results),
            "used": len(used),
            "possibly_used": len(poss),
            "unused": len(unused),
            "skeleton_report_characters": len(skel),
            "skel_used": len(su),
            "skel_possibly": len(sp),
            "skel_unused": len(sn),
            "no_skel_roster": len(results) - len(skel),
        },
        "groups": groups_out,
        "characters": results,
    }
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_md(out), encoding="utf-8")
    print("wrote %s" % OUT_MD, flush=True)
    print("wrote %s" % OUT_JSON, flush=True)
    print(
        "total=%d used=%d possibly=%d unused=%d searched=%d"
        % (out["summary"]["total"], out["summary"]["used"], out["summary"]["possibly_used"], out["summary"]["unused"], searched),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
