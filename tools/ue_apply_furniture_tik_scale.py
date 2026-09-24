"""Apply TIKI cm→world scale to existing L_Remagen furniture. No LoadLevel.

SKD meshes are centimeters. TIKI scale (usually 0.52) converts cm to BSP
world units; origins already use *2.54. Actor scale becomes
instance * tik_scale * 2.54. Loc/rot unchanged. Textures kept.
"""
from __future__ import annotations

import unreal

CM_PER_WORLD = 2.54
TAG = "MOHAA_TIKSCALE"

# Stem → TIKI setup scale (resolved from BSP model path, not basename).
TIK_SCALE = {
    "armchairposh": 0.52,
    "banquet_table": 0.52,
    "barbwire_long_two_post": 0.52,
    "barbwire_two_post": 0.52,
    "bathroomsink": 0.52,
    "bathtubwithshowerhead": 0.52,
    "bigbed": 0.52,
    "bookcase": 0.52,
    "bottle_wine": 0.52,
    "bshelf_tall_thin": 0.52,
    "bush_buckthorn": 0.52,
    "bush_regularbush": 0.52,
    "bush_sappling": 0.52,
    "cabinet_dark": 0.52,
    "cabinet_tall": 0.52,
    "chandalier": 0.52,
    "coatrack": 0.52,
    "dish": 0.52,
    "dresser": 0.52,
    "flowerplate": 0.52,
    "grillchair": 0.52,
    "halfcouch": 0.52,
    "hang3lamp": 0.52,
    "hang5lamp": 0.52,
    "hanglamp": 0.52,
    "large_desk": 0.52,
    "lightbulb_covered_nowire": 0.0429,
    "lightpost_sidemounted": 0.52,
    "lightpost_triple": 0.52,
    "loveseat": 0.52,
    "metalbench": 0.52,
    "oldladypainting": 0.52,
    "ornaterectable": 0.52,
    "produce_cart": 0.52,
    "rolltop_desk": 0.52,
    "round_table": 0.52,
    "servingplate": 0.52,
    "simplechair": 0.52,
    "smallhutch": 0.52,
    "square_table": 0.52,
    "stoolposh": 0.52,
    "table": 0.52,
    "tablelamp": 0.52,
    "toilet": 0.52,
    "tree_commontree": 0.52,
    "tree_oak": 1.0,
    "vanity": 0.52,
    "wallsconce_frosted": 0.52,
    "wallsconce_single": 0.52,
    "wardrobe": 0.52,
    "woodchair": 0.52,
}


def _stem(label: str) -> str:
    rest = label[len("MOHAA_prop_") :] if label.startswith("MOHAA_prop_") else label
    if rest.startswith("SM_"):
        rest = rest[3:]
    stem, sep, _idx = rest.rpartition("_")
    return (stem or rest).lower()


def _has_tag(actor, name: str) -> bool:
    try:
        tags = [str(t) for t in (actor.tags or [])]
    except Exception:
        return False
    return name in tags


def _add_tag(actor, name: str) -> None:
    try:
        tags = list(actor.tags or [])
        tags.append(name)
        actor.tags = tags
    except Exception as exc:
        print("tag skip", exc)


def _print_actor(tag: str, actor) -> None:
    loc = actor.get_actor_location()
    rot = actor.get_actor_rotation()
    scl = actor.get_actor_scale3d()
    origin, extent = actor.get_actor_bounds(False)
    print(
        tag,
        actor.get_actor_label(),
        "loc",
        round(float(loc.x), 3),
        round(float(loc.y), 3),
        round(float(loc.z), 3),
        "rot P",
        round(float(rot.pitch), 2),
        "Y",
        round(float(rot.yaw), 2),
        "R",
        round(float(rot.roll), 2),
        "scale",
        round(float(scl.x), 4),
        "visZ",
        round(float(origin.z) - float(extent.z), 2),
        round(float(origin.z) + float(extent.z), 2),
    )


def _aabb(map_actor):
    origin, extent = map_actor.get_actor_bounds(False)
    mn = (
        float(origin.x) - float(extent.x),
        float(origin.y) - float(extent.y),
        float(origin.z) - float(extent.z),
    )
    mx = (
        float(origin.x) + float(extent.x),
        float(origin.y) + float(extent.y),
        float(origin.z) + float(extent.z),
    )
    return mn, mx


def _inside(p, mn, mx) -> bool:
    return mn[0] <= p[0] <= mx[0] and mn[1] <= p[1] <= mx[1] and mn[2] <= p[2] <= mx[2]


def main() -> None:
    print("LEVEL", unreal.EditorLevelLibrary.get_editor_world().get_name())
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    map_actor = None
    n_prop = 0
    n_sun = 0
    props = []
    for actor in list(sub.get_all_level_actors() or []):
        label = actor.get_actor_label() or ""
        if label == "SM_Remagen":
            map_actor = actor
        if isinstance(actor, unreal.DirectionalLight):
            n_sun += 1
        if label.startswith("MOHAA_prop_"):
            n_prop += 1
            props.append(actor)
    print("props", n_prop, "dirlights", n_sun)
    if map_actor is None:
        print("NO SM_Remagen")
        return
    scl = map_actor.get_actor_scale3d()
    print(
        "MAP scale",
        round(float(scl.x), 4),
        round(float(scl.y), 4),
        round(float(scl.z), 4),
    )
    mn, mx = _aabb(map_actor)
    print("MAP aabb maxY", round(mx[1], 1), "minY", round(mn[1], 1))

    before_plate = None
    before_table = None
    for actor in props:
        label = actor.get_actor_label() or ""
        low = label.lower()
        if before_plate is None and "flowerplate" in low:
            _print_actor("BEFORE_PLATE", actor)
            before_plate = actor
        if before_table is None and "banquet_table" in low:
            _print_actor("BEFORE_TABLE", actor)
            before_table = actor

    n_set = 0
    n_skip = 0
    unknown = {}
    for actor in props:
        label = actor.get_actor_label() or ""
        stem = _stem(label)
        tik = TIK_SCALE.get(stem)
        if tik is None:
            unknown[stem] = unknown.get(stem, 0) + 1
            n_skip += 1
            continue
        if _has_tag(actor, TAG):
            n_skip += 1
            continue
        cur = actor.get_actor_scale3d()
        factor = float(tik) * CM_PER_WORLD
        actor.set_actor_scale3d(
            unreal.Vector(float(cur.x) * factor, float(cur.y) * factor, float(cur.z) * factor)
        )
        _add_tag(actor, TAG)
        n_set += 1
    print("SCALE applied", n_set, "skipped", n_skip, "unknown", unknown)

    plate = table = chair = oak = None
    for actor in props:
        label = (actor.get_actor_label() or "").lower()
        if plate is None and "flowerplate" in label:
            plate = actor
            _print_actor("AFTER_PLATE", actor)
        if table is None and "banquet_table" in label:
            table = actor
            _print_actor("AFTER_TABLE", actor)
        if chair is None and "simplechair" in label:
            chair = actor
        if oak is None and "tree_oak" in label:
            oak = actor

    if plate is not None and table is not None:
        pl = plate.get_actor_location()
        pr = plate.get_actor_rotation()
        po, pe = plate.get_actor_bounds(False)
        tl = table.get_actor_location()
        to, te = table.get_actor_bounds(False)
        table_top = float(to.z) + float(te.z)
        plate_min = float(po.z) - float(pe.z)
        print(
            "PROOF plate loc",
            round(float(pl.x), 3),
            round(float(pl.y), 3),
            round(float(pl.z), 3),
            "rot P",
            round(float(pr.pitch), 2),
            "Y",
            round(float(pr.yaw), 2),
            "R",
            round(float(pr.roll), 2),
            "scale",
            round(float(plate.get_actor_scale3d().x), 4),
        )
        print(
            "PROOF table loc Z",
            round(float(tl.z), 3),
            "table_top",
            round(table_top, 2),
            "plate_vis_min",
            round(plate_min, 2),
            "dZ_cm",
            round(plate_min - table_top, 2),
            "plate_not_inverted",
            abs(float(pr.pitch)) < 1.0 and abs(float(pr.roll)) < 1.0,
        )

    for name, actor in (("table", table), ("chair", chair), ("tree_oak", oak)):
        if actor is None:
            print(name, "MISSING")
            continue
        p = actor.get_actor_location()
        p = (float(p.x), float(p.y), float(p.z))
        print(name, "loc", [round(v, 1) for v in p], "inside_town_aabb", _inside(p, mn, mx))

    if table is not None:
        loc = table.get_actor_location()
        cam = unreal.Vector(float(loc.x) + 400.0, float(loc.y) + 200.0, float(loc.z) + 120.0)
        rot = unreal.Rotator(pitch=-12.0, yaw=-160.0, roll=0.0)
        try:
            ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
            ues.set_level_viewport_camera_info(cam, rot)
            print("FOCUS banquet table")
        except Exception as exc:
            print("focus skip", exc)

    try:
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
        print("SAVED L_Remagen")
    except Exception as exc:
        print("save skip", exc)


main()
