"""Add the missing quarter-turn yaw to all L_Remagen furniture. No LoadLevel.

Meshes already bake blender +90 Z. Old actor rot was (pitch, -(BSP_yaw+90), -roll)
which double-counted that +90. New rot is (pitch, -BSP_yaw, -roll): loc, pitch,
and roll stay so plates remain flat. Map actor stays (1,1,1) unmirrored.
"""
from __future__ import annotations

import math

import unreal

TAG = "MOHAA_YAWFIX"
DELTA_YAW = 90.0

# BSP static-model angles for the banquet set (maps/DM/mohdm3.bsp).
BSP = {
    "banquet_table_0": (0.0, 0.0, 0.0),
    "flowerplate_0": (0.0, 0.0, 0.0),
    "servingplate_0": (0.0, 0.0, 0.0),
    "dish_0": (0.0, 0.0, 0.0),
    "woodchair_1": (0.0, 270.0, 0.0),
}


def _has_tag(actor, name: str) -> bool:
    try:
        return name in [str(t) for t in (actor.tags or [])]
    except Exception:
        return False


def _add_tag(actor, name: str) -> None:
    try:
        tags = list(actor.tags or [])
        tags.append(name)
        actor.tags = tags
    except Exception as exc:
        print("tag skip", exc)


def _pyr(rot) -> tuple[float, float, float]:
    return (float(rot.pitch), float(rot.yaw), float(rot.roll))


def _xy_extent(origin, extent) -> tuple[float, float, float]:
    dx = float(extent.x) * 2.0
    dy = float(extent.y) * 2.0
    dz = float(extent.z) * 2.0
    return (dx, dy, dz)


def _print_actor(tag: str, actor) -> None:
    loc = actor.get_actor_location()
    rot = actor.get_actor_rotation()
    rel = None
    try:
        rel = actor.root_component.get_relative_rotation()
    except Exception:
        rel = None
    origin, extent = actor.get_actor_bounds(False)
    dx, dy, dz = _xy_extent(origin, extent)
    q = rot.quaternion()
    lx = q.rotate_vector(unreal.Vector(1, 0, 0))
    ly = q.rotate_vector(unreal.Vector(0, 1, 0))
    lz = q.rotate_vector(unreal.Vector(0, 0, 1))
    print(
        tag,
        actor.get_actor_label(),
        "loc",
        round(float(loc.x), 3),
        round(float(loc.y), 3),
        round(float(loc.z), 3),
        "world P",
        round(float(rot.pitch), 2),
        "Y",
        round(float(rot.yaw), 2),
        "R",
        round(float(rot.roll), 2),
        "aabb XYZcm",
        round(dx, 1),
        round(dy, 1),
        round(dz, 1),
        "long",
        "X" if dx >= dy else "Y",
    )
    print(
        tag,
        "  local+X",
        round(float(lx.x), 3),
        round(float(lx.y), 3),
        round(float(lx.z), 3),
        "local+Y",
        round(float(ly.x), 3),
        round(float(ly.y), 3),
        round(float(ly.z), 3),
        "local+Z",
        round(float(lz.x), 3),
        round(float(lz.y), 3),
        round(float(lz.z), 3),
        "Z_up",
        abs(float(lz.z)) > 0.95,
    )
    if rel is not None:
        print(
            tag,
            "  rel P",
            round(float(rel.pitch), 2),
            "Y",
            round(float(rel.yaw), 2),
            "R",
            round(float(rel.roll), 2),
        )


def _find(props, key: str):
    for actor in props:
        if key in (actor.get_actor_label() or "").lower():
            return actor
    return None


def _nearest_chair(props, table):
    if table is None:
        return None
    tl = table.get_actor_location()
    best = None
    best_d = 1e12
    for actor in props:
        label = (actor.get_actor_label() or "").lower()
        if "woodchair" not in label and "simplechair" not in label:
            continue
        p = actor.get_actor_location()
        d = (float(p.x) - float(tl.x)) ** 2 + (float(p.y) - float(tl.y)) ** 2
        if d < best_d:
            best_d = d
            best = actor
    return best


def _proof(tag: str, table, plate, dish, chair, map_actor) -> None:
    print("----", tag, "PROOF ----")
    if map_actor is not None:
        mrot = map_actor.get_actor_rotation()
        ms = map_actor.get_actor_scale3d()
        print(
            tag,
            "MAP rot",
            round(float(mrot.pitch), 2),
            round(float(mrot.yaw), 2),
            round(float(mrot.roll), 2),
            "scale",
            round(float(ms.x), 4),
            round(float(ms.y), 4),
            round(float(ms.z), 4),
        )
    if table is not None:
        _print_actor(tag + " TABLE", table)
        to, te = table.get_actor_bounds(False)
        dx, dy, dz = _xy_extent(to, te)
        print(
            tag,
            "TABLE long_axis",
            "X" if dx >= dy else "Y",
            "dx",
            round(dx, 1),
            "dy",
            round(dy, 1),
            "floorboards_are_Y",
            "MATCH_Y" if dy > dx else "WRONG_X",
        )
    if plate is not None:
        _print_actor(tag + " PLATE", plate)
        po, pe = plate.get_actor_bounds(False)
        dx, dy, dz = _xy_extent(po, pe)
        span = max(dx, dy)
        print(
            tag,
            "PLATE thinZ",
            round(dz, 2),
            "xy",
            round(span, 2),
            "flat_circle",
            dz < 0.45 * max(span, 1.0),
        )
    if dish is not None:
        _print_actor(tag + " DISH", dish)
    if chair is not None and table is not None:
        _print_actor(tag + " CHAIR", chair)
        cl = chair.get_actor_location()
        tl = table.get_actor_location()
        q = chair.get_actor_rotation().quaternion()
        # Idle +X forward bakes to mesh -Y after +90 Z and Unreal Y-mirror.
        fwd = q.rotate_vector(unreal.Vector(0, -1, 0))
        to_t = unreal.Vector(float(tl.x) - float(cl.x), float(tl.y) - float(cl.y), 0.0)
        tlen = math.hypot(float(to_t.x), float(to_t.y)) or 1.0
        flen = math.hypot(float(fwd.x), float(fwd.y)) or 1.0
        dot = (float(fwd.x) * float(to_t.x) + float(fwd.y) * float(to_t.y)) / (tlen * flen)
        print(
            tag,
            "CHAIR forward-Y",
            round(float(fwd.x), 3),
            round(float(fwd.y), 3),
            "to_table",
            round(float(to_t.x), 1),
            round(float(to_t.y), 1),
            "dot",
            round(dot, 3),
            "faces_table",
            dot > 0.35,
        )


def main() -> None:
    print("LEVEL", unreal.EditorLevelLibrary.get_editor_world().get_name())
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    map_actor = None
    props = []
    for actor in list(sub.get_all_level_actors() or []):
        label = actor.get_actor_label() or ""
        if label == "SM_Remagen":
            map_actor = actor
        if label.startswith("MOHAA_prop_"):
            props.append(actor)
    print("props", len(props))

    table = _find(props, "banquet_table_0")
    plate = _find(props, "flowerplate_0")
    dish = _find(props, "dish_0")
    serving = _find(props, "servingplate_0")
    chair = _nearest_chair(props, table)

    print("BSP banquet_table yaw 0 -> OLD ue -(0+90)=-90  NEW ue -0=0")
    print("BSP flowerplate yaw 0 pitch 0 roll 0 (stay flat)")
    for key, actor in (
        ("banquet_table_0", table),
        ("flowerplate_0", plate),
        ("servingplate_0", serving),
        ("dish_0", dish),
    ):
        if actor is None:
            print("MISSING", key)
            continue
        rot = actor.get_actor_rotation()
        bsp = BSP.get(key)
        print(
            "COMPARE",
            key,
            "BSP",
            bsp,
            "UE_now",
            [round(v, 2) for v in _pyr(rot)],
            "OLD_formula",
            [bsp[0], -(bsp[1] + 90.0), -bsp[2]],
            "NEW_formula",
            [bsp[0], -bsp[1], -bsp[2]],
        )
    if chair is not None:
        print("NEAREST_CHAIR", chair.get_actor_label(), "UE_now", [round(v, 2) for v in _pyr(chair.get_actor_rotation())])
    if table is not None:
        tl = table.get_actor_location()
        for actor in props:
            label = (actor.get_actor_label() or "").lower()
            if "woodchair" not in label:
                continue
            p = actor.get_actor_location()
            d = math.hypot(float(p.x) - float(tl.x), float(p.y) - float(tl.y))
            if d > 400.0:
                continue
            rot = actor.get_actor_rotation()
            print(
                "BANQUET_CHAIR",
                actor.get_actor_label(),
                "dXY",
                round(d, 1),
                "rot",
                [round(v, 2) for v in _pyr(rot)],
            )

    _proof("BEFORE", table, plate, dish, chair, map_actor)

    n_set = 0
    n_skip = 0
    for actor in props:
        if _has_tag(actor, TAG):
            n_skip += 1
            continue
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        actor.set_actor_location(loc, False, False)
        actor.set_actor_rotation(
            unreal.Rotator(
                pitch=float(rot.pitch),
                yaw=float(rot.yaw) + DELTA_YAW,
                roll=float(rot.roll),
            ),
            False,
        )
        _add_tag(actor, TAG)
        n_set += 1
    print("YAW +90 applied", n_set, "skipped", n_skip)

    _proof("AFTER", table, plate, dish, chair, map_actor)
    if serving is not None:
        _print_actor("AFTER SERVING", serving)
    if table is not None:
        tl = table.get_actor_location()
        for actor in props:
            label = (actor.get_actor_label() or "").lower()
            if "woodchair" not in label:
                continue
            p = actor.get_actor_location()
            d = math.hypot(float(p.x) - float(tl.x), float(p.y) - float(tl.y))
            if d > 400.0:
                continue
            rot = actor.get_actor_rotation()
            q = rot.quaternion()
            fwd = q.rotate_vector(unreal.Vector(0, -1, 0))
            to_t = (float(tl.x) - float(p.x), float(tl.y) - float(p.y))
            tlen = math.hypot(*to_t) or 1.0
            flen = math.hypot(float(fwd.x), float(fwd.y)) or 1.0
            dot = (float(fwd.x) * to_t[0] + float(fwd.y) * to_t[1]) / (tlen * flen)
            print(
                "AFTER_BANQUET_CHAIR",
                actor.get_actor_label(),
                "dXY",
                round(d, 1),
                "rot",
                [round(v, 2) for v in _pyr(rot)],
                "dot",
                round(dot, 3),
                "faces_table",
                dot > 0.35,
            )

    if table is not None:
        loc = table.get_actor_location()
        cam = unreal.Vector(float(loc.x), float(loc.y), float(loc.z) + 420.0)
        rot = unreal.Rotator(pitch=-89.0, yaw=-90.0, roll=0.0)
        try:
            ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
            ues.set_level_viewport_camera_info(cam, rot)
            print("FOCUS topdown banquet")
        except Exception as exc:
            print("focus skip", exc)

    try:
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
        print("SAVED L_Remagen")
    except Exception as exc:
        print("save skip", exc)


main()
