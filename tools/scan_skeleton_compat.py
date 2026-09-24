#!/usr/bin/env python3
"""Scan human character TIKIs and group merged body/head/hand skeletons.

Read-only analysis. Does not modify exporters, create Unreal assets, or export FBX.

Merge logic matches server.load_mesh_payload / formats.merge_meshes:
first TIKI setup/case SKD is the body; extra SKDs map by lowercase bone NAME;
extra-only bones are appended; first-SKD-wins for shared names.

Bind-pose thresholds (documented):
  translation: 0.1 game units (MOHAA inches)
  rotation:    1.0 degree (local quaternion angle)
Tiny float noise below those is ignored.
"""
from __future__ import annotations

import json
import math
import posixpath
import sys
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from formats import merge_meshes, parse_skd, parse_tiki  # noqa: E402
from server import (  # noqa: E402
    DEFAULT_GAME,
    _file_rec,
    _pak,
    add_loose_files,
    find_pk3s,
    norm,
    read_indexed,
    resolve_skelmodel,
    tiki_loader,
)

TRANS_THRESH = 0.1  # inches / game units
ROT_THRESH_DEG = 1.0
ENGINEER_TIK = "models/human/1st-ranger_engineer.tik"
ENGINEER_BODY = "models/human/allied_army_soldier/usarmy.skd"


def build_index(game_dir: str) -> dict:
    game = Path(game_dir)
    if not game.is_dir():
        raise FileNotFoundError(game_dir)
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
    for pak in paks:
        _pak(str(pak))
    print("index: %d pk3s, %d files" % (len(paks), len(index)), flush=True)
    return index


def is_human_character_tik(path: str) -> bool:
    """Same roster as server.scan_character_animation_types.

    Top-level models/human/*.tik plus models/player/*.tik except _fps.
    Posed display meshes, weapons, and nested head packs are excluded.
    """
    p = path.replace("\\", "/").lower()
    if not p.endswith(".tik"):
        return False
    if "/weapons/" in p or p.startswith("models/ammo/") or "/fx/" in p:
        return False
    if "/vehicle" in p or "/jeep/" in p or "/tank/" in p or "/plane/" in p:
        return False
    if p.startswith("models/posed/"):
        return False
    if p.startswith("models/human/") and p.count("/") == 2:
        return True
    if p.startswith("models/player/") and p.count("/") == 2 and not p.endswith("_fps.tik"):
        return True
    return False


def classify_skd(path: str, index_in_setup: int) -> str:
    p = path.replace("\\", "/").lower()
    base = posixpath.basename(p)
    stem = posixpath.splitext(base)[0]
    if index_in_setup == 0:
        return "body"
    if "helmet" in stem or "helmet" in p:
        return "helmet"
    if any(k in stem or k in p for k in ("hand", "fist", "glove", "finger", "arms")):
        return "hand"
    if any(k in stem or k in p for k in ("head", "face", "skull")):
        return "head"
    if any(k in stem for k in ("hat", "cap", "helm")):
        return "helmet"
    return "other"


def quat_angle_deg(q0, q1) -> float:
    dot = abs(
        float(q0[0]) * float(q1[0])
        + float(q0[1]) * float(q1[1])
        + float(q0[2]) * float(q1[2])
        + float(q0[3]) * float(q1[3])
    )
    dot = min(1.0, max(0.0, dot))
    return math.degrees(2.0 * math.acos(dot))


def trans_delta(a, b) -> float:
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def parent_key(parent: str) -> str:
    p = (parent or "").strip()
    if p.lower() in ("", "worldbone", "world"):
        return ""
    return p.lower()


def is_root_parent(parent: str, parent_index: int) -> bool:
    return parent_index < 0 or parent_key(parent) == ""


def merge_skeleton(index: dict, skel_paths: list[str]):
    parts = []
    collisions = []
    seen_names: set[str] = set()
    for i, sp in enumerate(skel_paths):
        data = read_indexed(index, sp)
        mesh = parse_skd(data, None, "skd-bind", None, reveal_if_all_hidden=False)
        extra_names = []
        for b in mesh.bone_list:
            key = (b.get("name") or "").lower()
            if i > 0 and key in seen_names:
                collisions.append({"skd": sp, "bone": b.get("name")})
            elif key not in seen_names:
                extra_names.append(b.get("name"))
                seen_names.add(key)
        parts.append(mesh)
    if not parts:
        raise ValueError("no skelmodels")
    merged = merge_meshes(parts, "skd-bind")
    return merged, collisions


def skeleton_record(merged) -> dict:
    bones = []
    names = []
    names_lower = []
    parents = {}
    types = {}
    local = {}
    world = {}
    order = []
    roots = []
    for i, b in enumerate(merged.bone_list or []):
        name = b.get("name") or ("bone_%d" % i)
        parent = b.get("parent") or ""
        pi = int(b.get("parent_index", -1))
        lt = [float(x) for x in (b.get("local_t") or [0, 0, 0])]
        lq = [float(x) for x in (b.get("local_quat") or [0, 0, 0, 1])]
        wt = [float(x) for x in (b.get("world_t") or b.get("pos") or [0, 0, 0])]
        key = name.lower()
        rec = {
            "index": i,
            "name": name,
            "parent": parent,
            "parent_index": pi,
            "type": b.get("type") or "",
            "local_t": lt,
            "local_quat": lq,
            "world_t": wt,
        }
        bones.append(rec)
        names.append(name)
        names_lower.append(key)
        parents[key] = parent_key(parent)
        types[key] = str(b.get("type") or "")
        local[key] = (tuple(lt), tuple(lq))
        world[key] = tuple(wt)
        order.append(key)
        if is_root_parent(parent, pi):
            roots.append(name)
    root = roots[0] if roots else (names[0] if names else "")
    hier = tuple(sorted((n, parents[n]) for n in names_lower))
    return {
        "bones": bones,
        "names": names,
        "names_lower": names_lower,
        "name_set": frozenset(names_lower),
        "parents": parents,
        "types": types,
        "local": local,
        "world": world,
        "order": tuple(order),
        "root": root,
        "roots": roots,
        "count": len(names),
        "hierarchy": hier,
    }


def pose_diffs(a: dict, b: dict, trans_thresh=TRANS_THRESH, rot_thresh=ROT_THRESH_DEG) -> list[dict]:
    diffs = []
    shared = a["name_set"] & b["name_set"]
    for key in sorted(shared):
        ta, qa = a["local"][key]
        tb, qb = b["local"][key]
        dt = trans_delta(ta, tb)
        dr = quat_angle_deg(qa, qb)
        dw = trans_delta(a["world"][key], b["world"][key])
        if dt > trans_thresh or dr > rot_thresh:
            diffs.append(
                {
                    "bone": key,
                    "local_t": round(dt, 4),
                    "local_deg": round(dr, 4),
                    "world_t": round(dw, 4),
                    "parent_a": a["parents"].get(key, ""),
                    "parent_b": b["parents"].get(key, ""),
                }
            )
    return diffs


def parent_mismatches(a: dict, b: dict) -> list[dict]:
    out = []
    shared = a["name_set"] & b["name_set"]
    for key in sorted(shared):
        pa = a["parents"].get(key, "")
        pb = b["parents"].get(key, "")
        if pa != pb:
            out.append({"bone": key, "parent_a": pa or "(root)", "parent_b": pb or "(root)"})
    return out


def group_letter(i: int) -> str:
    # A, B, ... Z, AA, AB, ...
    n = i + 1
    letters = []
    while n:
        n, r = divmod(n - 1, 26)
        letters.append(chr(65 + r))
    return "".join(reversed(letters))


def format_hierarchy(skel: dict) -> list[str]:
    by_parent = defaultdict(list)
    name_of = {n.lower(): n for n in skel["names"]}
    for b in skel["bones"]:
        key = b["name"].lower()
        pk = parent_key(b["parent"]) if b["parent_index"] >= 0 else ""
        by_parent[pk].append(key)
    lines = []

    def walk(pk: str, depth: int) -> None:
        kids = by_parent.get(pk, [])
        for k in kids:
            nm = name_of.get(k, k)
            par = name_of.get(pk, pk) if pk else "(root)"
            lines.append("%s%s  →  %s" % ("  " * depth, nm, par))
            walk(k, depth + 1)

    walk("", 0)
    # bones whose parent is missing from the merged list
    listed = {ln.split("  →  ", 1)[0].strip().lower() for ln in lines}
    for n in skel["names_lower"]:
        if n not in listed:
            lines.append("%s  →  %s  (parent missing from merge)" % (name_of.get(n, n), skel["parents"].get(n) or "(root)"))
    return lines


def analyze(game_dir: str) -> dict:
    index = build_index(game_dir)
    loader = tiki_loader(index)
    tik_paths = sorted(
        rec["path"]
        for rec in index.values()
        if rec.get("ext") == ".tik" and is_human_character_tik(rec["path"])
    )
    skipped = sorted(
        rec["path"]
        for rec in index.values()
        if rec.get("ext") == ".tik"
        and rec["path"].replace("\\", "/").lower().startswith("models/human/")
        and rec["path"].replace("\\", "/").count("/") != 2
    )
    print("character tiks: %d  nested human tiks skipped: %d" % (len(tik_paths), len(skipped)), flush=True)

    characters = []
    errors = []
    for tik_path in tik_paths:
        rec = index.get(norm(tik_path))
        try:
            tik = parse_tiki(read_indexed(index, rec["path"]), filename=rec["path"], loader=loader)
        except Exception as exc:
            errors.append({"tik": tik_path, "error": "parse_tiki: %s" % exc})
            print("FAIL tik %s: %s" % (tik_path, exc), flush=True)
            continue
        folder = (tik.get("path") or "").rstrip("/") or posixpath.dirname(tik_path)
        raw_skels = tik.get("skelmodels") or []
        resolved = []
        missing_skels = []
        for sk in raw_skels:
            p = resolve_skelmodel(index, folder, sk)
            if p and norm(p) in index:
                resolved.append(p)
            else:
                missing_skels.append(sk)
        if not resolved:
            errors.append({"tik": tik_path, "error": "no skelmodels", "raw": raw_skels})
            print("SKIP no skel %s" % tik_path, flush=True)
            continue
        roles = []
        body = head = ""
        hands = []
        helmet = []
        other = []
        for i, p in enumerate(resolved):
            role = classify_skd(p, i)
            roles.append({"path": p, "role": role})
            if role == "body" and not body:
                body = p
            elif role == "head" and not head:
                head = p
            elif role == "hand":
                hands.append(p)
            elif role == "helmet":
                helmet.append(p)
            else:
                other.append(p)
        try:
            merged, collisions = merge_skeleton(index, resolved)
        except Exception as exc:
            errors.append({"tik": tik_path, "error": "merge: %s" % exc, "skels": resolved})
            print("FAIL merge %s: %s" % (tik_path, exc), flush=True)
            continue
        skel = skeleton_record(merged)
        name = tik.get("display_name") or Path(tik_path).stem.replace("_", " ").title()
        characters.append(
            {
                "name": name,
                "tik": tik_path,
                "body": body or resolved[0],
                "head": head,
                "hands": hands,
                "helmet": helmet,
                "other_skds": other,
                "skelmodels": resolved,
                "roles": roles,
                "missing_skels": missing_skels,
                "collisions": collisions,
                "skel": skel,
            }
        )
        print(
            "ok %s bones=%d body=%s skels=%d"
            % (name, skel["count"], posixpath.basename(body or resolved[0]), len(resolved)),
            flush=True,
        )

    engineer = None
    for c in characters:
        if norm(c["tik"]) == norm(ENGINEER_TIK):
            engineer = c
            break
    if engineer is None:
        for c in characters:
            if "1st-ranger engineer" in c["name"].lower() or "1st ranger engineer" in c["name"].lower():
                engineer = c
                break
    if engineer is None:
        raise RuntimeError("1St Ranger Engineer TIKI not found among %d characters" % len(characters))

    eng = engineer["skel"]
    print(
        "engineer: %s bones=%d root=%s body=%s"
        % (engineer["name"], eng["count"], eng["root"], engineer["body"]),
        flush=True,
    )

    # Per-character relation vs Engineer
    for c in characters:
        sk = c["skel"]
        extra = sorted(sk["name_set"] - eng["name_set"])
        missing = sorted(eng["name_set"] - sk["name_set"])
        pm = parent_mismatches(eng, sk)
        pd = pose_diffs(eng, sk)
        # Unreal mesh→Skeleton: all mesh bones must exist on the Skeleton with
        # the same parent. Extra mesh bones block reuse. Missing skeleton bones
        # do not (one-way: this mesh can use Engineer; Engineer cannot use this
        # smaller skeleton without dummy bones). Bind pose does not change the
        # Unreal name/parent test; it is reported separately and splits groups.
        if pm:
            relation = "hierarchy-mismatch"
            reuse = False
            reason = "parent mismatch on %d shared bone(s): %s" % (
                len(pm),
                ", ".join(
                    "%s (Eng %s vs this %s)"
                    % (x["bone"], x["parent_a"] or "root", x["parent_b"] or "root")
                    for x in pm[:8]
                ),
            )
        elif extra:
            relation = "superset" if not missing else "overlap"
            reuse = False
            reason = "extra bones Engineer lacks: " + ", ".join(extra[:12])
            if len(extra) > 12:
                reason += " … (+%d)" % (len(extra) - 12)
        elif missing:
            relation = "subset"
            reuse = True
            reason = (
                "subset of Engineer (%d missing: %s); can use SK_1St_Ranger_Engineer_Skeleton; "
                "Engineer cannot use this smaller skeleton without dummy bones"
                % (len(missing), ", ".join(missing))
            )
            if pd:
                reason += "; bind pose differs on %d bone(s) (rest pose not interchangeable)" % len(pd)
        elif pd:
            relation = "exact-names-bind-diff"
            reuse = True
            reason = "same names+parents so Unreal reuse is allowed, but bind pose differs on %d bone(s)" % len(pd)
        else:
            relation = "exact"
            reuse = True
            reason = "exact names+parents+bind pose match"
        if c is engineer:
            relation = "exact"
            reuse = True
            reason = "reference skeleton (SK_1St_Ranger_Engineer_Skeleton)"
        c["vs_engineer"] = {
            "relation": relation,
            "reuse_engineer": reuse,
            "bind_compatible": not pm and not extra and not pd,
            "extra": extra,
            "missing": missing,
            "parent_mismatches": pm,
            "pose_diffs": pd,
            "pose_diff_count": len(pd),
            "reason": reason,
        }

    # Cluster by identical hierarchy, then split incompatible bind poses.
    buckets = defaultdict(list)
    for i, c in enumerate(characters):
        buckets[c["skel"]["hierarchy"]].append(i)

    clusters: list[list[int]] = []
    for _hier, idxs in buckets.items():
        remaining = list(idxs)
        while remaining:
            seed = remaining.pop(0)
            cluster = [seed]
            still = []
            for j in remaining:
                diffs = pose_diffs(characters[seed]["skel"], characters[j]["skel"])
                if diffs:
                    still.append(j)
                else:
                    cluster.append(j)
            remaining = still
            clusters.append(cluster)

    # Group A = cluster containing Engineer
    eng_idx = characters.index(engineer)
    clusters.sort(key=lambda cl: (0 if eng_idx in cl else 1, -len(cl), characters[cl[0]]["name"].lower()))
    groups = []
    for gi, cl in enumerate(clusters):
        letter = group_letter(gi)
        members = [characters[i] for i in cl]
        members.sort(key=lambda c: (0 if c is engineer else 1, c["name"].lower(), c["tik"].lower()))
        rep = members[0]
        extra_vs_eng = sorted(rep["skel"]["name_set"] - eng["name_set"])
        missing_vs_eng = sorted(eng["name_set"] - rep["skel"]["name_set"])
        reuse_all = all(m["vs_engineer"]["reuse_engineer"] for m in members)
        bind = "compatible"
        if rep["vs_engineer"]["parent_mismatches"]:
            bind = "n/a (hierarchy differs)"
        elif rep["vs_engineer"]["pose_diff_count"]:
            bind = "differences listed"
        if letter == "A":
            compatible = "YES"
        elif reuse_all and bind == "compatible":
            compatible = "YES (subset of Engineer — can reuse SK_1St_Ranger_Engineer_Skeleton)"
        elif reuse_all:
            compatible = "YES for Unreal names/parents (subset); NO for bind pose"
        else:
            compatible = "NO"
        reasons = []
        if letter != "A":
            if extra_vs_eng:
                reasons.append("extra bones: " + ", ".join(extra_vs_eng))
            if missing_vs_eng:
                reasons.append("missing Engineer bones: " + ", ".join(missing_vs_eng))
            if rep["vs_engineer"]["parent_mismatches"]:
                reasons.append(
                    "different hierarchy: "
                    + "; ".join(
                        "%s parent Eng=%s this=%s" % (x["bone"], x["parent_a"] or "root", x["parent_b"] or "root")
                        for x in rep["vs_engineer"]["parent_mismatches"][:12]
                    )
                )
            if rep["vs_engineer"]["pose_diff_count"]:
                reasons.append("incompatible bind pose (%d bones)" % rep["vs_engineer"]["pose_diff_count"])
            if not reasons:
                reasons.append(rep["vs_engineer"]["reason"])
        groups.append(
            {
                "letter": letter,
                "compatible_with_engineer": compatible,
                "reuse_engineer_skeleton": reuse_all,
                "count": len(members),
                "root": rep["skel"]["root"],
                "bone_count": rep["skel"]["count"],
                "extra_vs_engineer": extra_vs_eng,
                "missing_vs_engineer": missing_vs_eng,
                "bind_pose": bind,
                "pose_diffs": rep["vs_engineer"]["pose_diffs"],
                "parent_mismatches": rep["vs_engineer"]["parent_mismatches"],
                "reason_separate": reasons,
                "characters": [{"name": m["name"], "tik": m["tik"]} for m in members],
                "representative": {"name": rep["name"], "tik": rep["tik"]},
                "bone_names": rep["skel"]["names"],
                "hierarchy_lines": format_hierarchy(rep["skel"]),
                "parents": [{"name": b["name"], "parent": b["parent"] or "(root)"} for b in rep["skel"]["bones"]],
            }
        )
        for m in members:
            m["group"] = letter

    reuse = [c for c in characters if c["vs_engineer"]["reuse_engineer"]]
    own = [c for c in characters if not c["vs_engineer"]["reuse_engineer"]]
    return {
        "thresholds": {
            "translation_units": TRANS_THRESH,
            "translation_note": "MOHAA game units (inches); >0.1 is a meaningful bind-pose translation difference",
            "rotation_degrees": ROT_THRESH_DEG,
            "rotation_note": "local quaternion angle; >1 degree is a meaningful bind-pose rotation difference",
            "pose_space": "SKD bind (no idle SKC); local parent-relative transforms after merge_meshes",
        },
        "engineer": {
            "name": engineer["name"],
            "tik": engineer["tik"],
            "body": engineer["body"],
            "head": engineer["head"],
            "hands": engineer["hands"],
            "helmet": engineer["helmet"],
            "skelmodels": engineer["skelmodels"],
            "bone_count": eng["count"],
            "root": eng["root"],
            "group": engineer.get("group", "A"),
            "collisions": engineer["collisions"],
        },
        "summary": {
            "character_count": len(characters),
            "group_count": len(groups),
            "reuse_engineer_count": len(reuse),
            "own_skeleton_count": len(own),
            "nested_human_tiks_skipped": skipped,
            "errors": errors,
        },
        "groups": groups,
        "characters": characters,
        "reuse_engineer": [{"name": c["name"], "tik": c["tik"], "group": c["group"], "relation": c["vs_engineer"]["relation"]} for c in reuse],
        "require_own": [{"name": c["name"], "tik": c["tik"], "group": c["group"], "relation": c["vs_engineer"]["relation"], "reason": c["vs_engineer"]["reason"]} for c in own],
    }


def bone_table_md(skel: dict) -> str:
    lines = ["| # | bone | parent | type | local T (x y z) |", "|---|------|--------|------|-----------------|"]
    for b in skel["bones"]:
        lt = b["local_t"]
        lines.append(
            "| %d | %s | %s | %s | %.4f %.4f %.4f |"
            % (
                b["index"],
                b["name"],
                b["parent"] or "(root)",
                b["type"],
                lt[0],
                lt[1],
                lt[2],
            )
        )
    return "\n".join(lines)


def render_markdown(data: dict, characters: list) -> str:
    eng = data["engineer"]
    lines = []
    a = lines.append
    a("# MOHAA human skeleton compatibility")
    a("")
    a("Analysis only. Merged TIKI setup SKDs with the same first-SKD-wins name merge as the viewer/export path. No Unreal assets, FBX, or exporter changes.")
    a("")
    a("## Method")
    a("")
    a("- Roster: `models/human/*.tik` (exactly one subfolder) plus `models/player/*.tik` except `_fps` — same as `scan_character_animation_types`. Nested head packs and `models/posed/` display meshes are not the character roster.")
    a("- Merge: first TIKI setup/case `skelmodel` is the body; extra SKDs map onto it by **lowercase bone name**; extra-only bones appended; shared names keep the first SKD (helmets that reuse `Bip01 R …` arm names do not add those bones).")
    a("- Bind pose: SKD rest pose (`parse_skd` with no SKC / idle overlay). Compared in **local / parent-relative** space.")
    a("- Thresholds: translation **> %.2f** game units (inches); rotation **> %.1f°**. Differences at or below that are treated as float noise." % (TRANS_THRESH, ROT_THRESH_DEG))
    a("- Unreal Skeleton sharing: identical **names + parents**. Order may differ (name-remap). Extra bones on a mesh cannot use a smaller Skeleton. A mesh that is a **subset** of Engineer **can** use `SK_1St_Ranger_Engineer_Skeleton`; Engineer cannot use that smaller skeleton without dummy bones.")
    a("")
    a("## Summary")
    a("")
    a("- Unique skeleton groups: **%d**" % data["summary"]["group_count"])
    a("- Characters scanned: **%d**" % data["summary"]["character_count"])
    a("- Group containing 1St Ranger Engineer: **%s** (%d bones, root `%s`)" % (eng["group"], eng["bone_count"], eng["root"]))
    a("- Can reuse `SK_1St_Ranger_Engineer_Skeleton`: **%d**" % data["summary"]["reuse_engineer_count"])
    a("- Require their own Unreal Skeleton (or a larger shared one): **%d**" % data["summary"]["own_skeleton_count"])
    a("")
    a("Characters per group:")
    a("")
    for g in data["groups"]:
        a("- Group %s: %d characters, %d bones, root `%s`" % (g["letter"], g["count"], g["bone_count"], g["root"]))
    a("")
    if eng["collisions"]:
        a("Engineer first-SKD-wins collisions (extra SKD bones whose names already existed on the body — not appended):")
        a("")
        by = defaultdict(list)
        for hit in eng["collisions"]:
            by[hit["skd"]].append(hit["bone"])
        for skd, bones in by.items():
            a("- `%s`: %s" % (skd, ", ".join(bones)))
        a("")
    a("Engineer setup SKDs:")
    a("")
    a("- TIKI: `%s`" % eng["tik"])
    a("- body: `%s`" % eng["body"])
    a("- head: `%s`" % (eng["head"] or "(none)"))
    a("- hands: %s" % (", ".join("`%s`" % p for p in eng["hands"]) or "(none)"))
    a("- helmet: %s" % (", ".join("`%s`" % p for p in eng["helmet"]) or "(none)"))
    a("- all setup: %s" % ", ".join("`%s`" % p for p in eng["skelmodels"]))
    a("")
    a("## Characters that can reuse SK_1St_Ranger_Engineer_Skeleton")
    a("")
    a("These have no extra bones vs Engineer and matching parents on every shared name. A **subset** mesh can use the larger Engineer Skeleton; Engineer cannot use the smaller skeleton without dummy bones. Bind-pose mismatches are called out — Unreal will still accept the Skeleton, but rest pose / retarget will not match.")
    a("")
    for c in data["reuse_engineer"]:
        a("- %s (`%s`) — group %s, %s" % (c["name"], c["tik"], c["group"], c["relation"]))
    a("")
    a("## Characters that require their own Unreal Skeleton")
    a("")
    a("Cannot reuse `SK_1St_Ranger_Engineer_Skeleton`: extra bones Engineer lacks, or parent mismatches. They may still share a group skeleton with each other. Bind-pose-only differences stay in the reuse list with a caveat.")
    a("")
    for c in data["require_own"]:
        a("- %s (`%s`) — group %s — %s" % (c["name"], c["tik"], c["group"], c["reason"]))
    a("")

    for g in data["groups"]:
        a("## Skeleton Group %s" % g["letter"])
        a("")
        if g["letter"] == "A":
            a("Shared skeleton:")
        else:
            a("Characters:")
        a("")
        for m in g["characters"]:
            a("- %s (`%s`)" % (m["name"], m["tik"]))
        a("")
        a("- Bone count: **%d**" % g["bone_count"])
        a("- Compatible with Engineer skeleton: **%s**" % g["compatible_with_engineer"])
        a("- Root: `%s`" % g["root"])
        extras = g["extra_vs_engineer"]
        missing = g["missing_vs_engineer"]
        a("- Extras vs Engineer: %s" % (", ".join("`%s`" % x for x in extras) if extras else "(none)"))
        a("- Missing vs Engineer: %s" % (", ".join("`%s`" % x for x in missing) if missing else "(none)"))
        a("- Bind-pose: %s" % g["bind_pose"])
        if g["reason_separate"]:
            a("- Reason separate:")
            for r in g["reason_separate"]:
                a("  - %s" % r)
        if g["parent_mismatches"]:
            a("")
            a("Parent mismatches vs Engineer:")
            a("")
            for x in g["parent_mismatches"]:
                a("- `%s`: Engineer `%s` vs this `%s`" % (x["bone"], x["parent_a"] or "(root)", x["parent_b"] or "(root)"))
        if g["pose_diffs"]:
            a("")
            a("Bind-pose differences vs Engineer (local ΔT inches, local ΔR degrees; first %d of %d):" % (len(g["pose_diffs"]), len(g["pose_diffs"])))
            a("")
            for d in g["pose_diffs"]:
                a("- `%s`: ΔT=%.3f  ΔR=%.2f°  (world ΔT=%.3f)" % (d["bone"], d["local_t"], d["local_deg"], d["world_t"]))
        a("")
        a("<details><summary>Canonical bone list (%d)</summary>" % len(g["bone_names"]))
        a("")
        a("")
        for i, n in enumerate(g["bone_names"]):
            a("%d. %s" % (i, n))
        a("")
        a("</details>")
        a("")
        a("<details><summary>Parent hierarchy</summary>")
        a("")
        a("```")
        for ln in g["hierarchy_lines"]:
            a(ln)
        a("```")
        a("")
        a("</details>")
        a("")

    a("## Compact table")
    a("")
    a("| character | body SKD | merged bones | group | reuse Engineer skeleton? | reason if no |")
    a("|---|---|---:|---|---|---|")
    rows = sorted(characters, key=lambda c: (c.get("group") or "Z", c["name"].lower(), c["tik"].lower()))
    for c in rows:
        reuse = "YES" if c["vs_engineer"]["reuse_engineer"] else "NO"
        reason = ""
        if not c["vs_engineer"]["reuse_engineer"]:
            reason = c["vs_engineer"]["reason"].replace("|", "/")
        elif c["vs_engineer"]["pose_diff_count"]:
            reason = "bind pose differs (%d bones)" % c["vs_engineer"]["pose_diff_count"]
        elif c["vs_engineer"]["relation"] == "subset":
            reason = "subset: " + ", ".join(c["vs_engineer"]["missing"])
        a(
            "| %s | `%s` | %d | %s | %s | %s |"
            % (c["name"], c["body"], c["skel"]["count"], c.get("group"), reuse, reason)
        )
    a("")
    if data["summary"]["errors"]:
        a("## Errors / skipped TIKIs")
        a("")
        for e in data["summary"]["errors"]:
            a("- `%s`: %s" % (e.get("tik"), e.get("error")))
        a("")
    if data["summary"]["nested_human_tiks_skipped"]:
        a("## Nested human TIKIs not treated as characters")
        a("")
        a("These match `models/human/**` but are not the top-level roster (`path.count('/') != 2`), typically head packs / includes.")
        a("")
        for p in data["summary"]["nested_human_tiks_skipped"][:80]:
            a("- `%s`" % p)
        extra_n = len(data["summary"]["nested_human_tiks_skipped"]) - 80
        if extra_n > 0:
            a("- … +%d more" % extra_n)
        a("")
    a("## Appendix: Group A (Engineer) bind-pose bone table")
    a("")
    eng_char = next(c for c in characters if norm(c["tik"]) == norm(eng["tik"]))
    a(bone_table_md(eng_char["skel"]))
    a("")
    return "\n".join(lines)


def jsonable(obj):
    if isinstance(obj, frozenset):
        return sorted(obj)
    if isinstance(obj, tuple):
        return [jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [jsonable(x) for x in obj]
    return obj


def main() -> int:
    game = str(DEFAULT_GAME)
    if len(sys.argv) > 1:
        game = sys.argv[1]
    data = analyze(game)
    characters = data["characters"]
    out_md = ROOT / "tools" / "skeleton_compat_report.md"
    out_json = ROOT / "tools" / "skeleton_compat_report.json"
    md = render_markdown(data, characters)
    out_md.write_text(md, encoding="utf-8")
    dump = {
        "thresholds": data["thresholds"],
        "engineer": data["engineer"],
        "summary": data["summary"],
        "groups": [],
        "characters": [],
        "reuse_engineer": data["reuse_engineer"],
        "require_own": data["require_own"],
    }
    for g in data["groups"]:
        dump["groups"].append(
            {
                "letter": g["letter"],
                "compatible_with_engineer": g["compatible_with_engineer"],
                "reuse_engineer_skeleton": g.get("reuse_engineer_skeleton"),
                "count": g["count"],
                "root": g["root"],
                "bone_count": g["bone_count"],
                "extra_vs_engineer": g["extra_vs_engineer"],
                "missing_vs_engineer": g["missing_vs_engineer"],
                "bind_pose": g["bind_pose"],
                "pose_diffs": g["pose_diffs"],
                "parent_mismatches": g["parent_mismatches"],
                "reason_separate": g["reason_separate"],
                "characters": g["characters"],
                "representative": g["representative"],
                "bone_names": g["bone_names"],
                "parents": g["parents"],
                "hierarchy_lines": g["hierarchy_lines"],
            }
        )
    for c in characters:
        dump["characters"].append(
            {
                "name": c["name"],
                "tik": c["tik"],
                "body": c["body"],
                "head": c["head"],
                "hands": c["hands"],
                "helmet": c["helmet"],
                "other_skds": c["other_skds"],
                "skelmodels": c["skelmodels"],
                "root": c["skel"]["root"],
                "merged_bones": c["skel"]["count"],
                "group": c.get("group"),
                "vs_engineer": {
                    "relation": c["vs_engineer"]["relation"],
                    "reuse_engineer": c["vs_engineer"]["reuse_engineer"],
                    "bind_compatible": c["vs_engineer"].get("bind_compatible"),
                    "extra": c["vs_engineer"]["extra"],
                    "missing": c["vs_engineer"]["missing"],
                    "parent_mismatches": c["vs_engineer"]["parent_mismatches"],
                    "pose_diff_count": c["vs_engineer"]["pose_diff_count"],
                    "pose_diffs": c["vs_engineer"]["pose_diffs"],
                    "reason": c["vs_engineer"]["reason"],
                },
                "collisions": c["collisions"],
            }
        )
    out_json.write_text(json.dumps(jsonable(dump), indent=2), encoding="utf-8")
    print("wrote %s" % out_md, flush=True)
    print("wrote %s" % out_json, flush=True)
    print(
        "groups=%d characters=%d engineer_bones=%d reuse=%d own=%d"
        % (
            data["summary"]["group_count"],
            data["summary"]["character_count"],
            data["engineer"]["bone_count"],
            data["summary"]["reuse_engineer_count"],
            data["summary"]["own_skeleton_count"],
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
