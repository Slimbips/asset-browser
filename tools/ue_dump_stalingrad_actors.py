"""Dump L_Stalingrad actors: map AABB, dumpster/MG42/crate loc, sun count. No LoadLevel."""
from __future__ import annotations

import json

import unreal

KEYS = ("dumpster", "trash", "bin", "garbage", "crate", "mg42", "barrel", "desk", "box", "boiler", "prop")


def _world_name() -> str:
    try:
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        return world.get_name() if world else ""
    except Exception:
        return ""


def main() -> None:
    print("WORLD", _world_name())
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = list(sub.get_all_level_actors() or [])
    print("NACTORS", len(actors))
    map_actor = None
    n_sun = 0
    n_prop = 0
    hits = []
    for actor in actors:
        label = actor.get_actor_label() or ""
        cls = actor.get_class().get_name() if actor.get_class() else ""
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        scl = actor.get_actor_scale3d()
        rec = {
            "label": label,
            "class": cls,
            "loc": [round(float(loc.x), 2), round(float(loc.y), 2), round(float(loc.z), 2)],
            "rot": [round(float(rot.pitch), 2), round(float(rot.yaw), 2), round(float(rot.roll), 2)],
            "scale": [round(float(scl.x), 4), round(float(scl.y), 4), round(float(scl.z), 4)],
        }
        if label == "SM_Stalingrad":
            map_actor = actor
            print("MAP", json.dumps(rec))
        if isinstance(actor, unreal.DirectionalLight) or "DirectionalLight" in cls:
            n_sun += 1
            print("SUN", json.dumps(rec))
        if label.startswith("MOHAA_prop_"):
            n_prop += 1
        low = (label + " " + cls).lower()
        if any(k in low for k in KEYS) or label.startswith("MOHAA_"):
            hits.append(rec)
        if "Volume" in cls or "Brush" in cls or "PlayerStart" in cls:
            print("MISC", json.dumps(rec))
    print("NSUN", n_sun, "NPROP", n_prop, "NHIT", len(hits))
    if map_actor is not None:
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
        print(
            "MAP AABB",
            [round(v, 1) for v in mn],
            [round(v, 1) for v in mx],
            "origin",
            [round(float(origin.x), 1), round(float(origin.y), 1), round(float(origin.z), 1)],
            "extent",
            [round(float(extent.x), 1), round(float(extent.y), 1), round(float(extent.z), 1)],
        )
        try:
            mesh = map_actor.static_mesh_component.static_mesh
            b = mesh.get_bounds()
            print(
                "MESH bounds origin",
                [round(float(b.origin.x), 1), round(float(b.origin.y), 1), round(float(b.origin.z), 1)],
                "extent",
                [round(float(b.box_extent.x), 1), round(float(b.box_extent.y), 1), round(float(b.box_extent.z), 1)],
            )
        except Exception as exc:
            print("MESH bounds skip", exc)
    for rec in hits:
        loc = rec["loc"]
        inside = False
        if map_actor is not None:
            inside = mn[0] <= loc[0] <= mx[0] and mn[1] <= loc[1] <= mx[1] and mn[2] <= loc[2] <= mx[2]
        rec["inside_map"] = inside
        print("HIT", json.dumps(rec))
    try:
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        cam_loc, cam_rot = ues.get_level_viewport_camera_info()
        print(
            "CAM",
            [round(float(cam_loc.x), 1), round(float(cam_loc.y), 1), round(float(cam_loc.z), 1)],
            [round(float(cam_rot.pitch), 1), round(float(cam_rot.yaw), 1), round(float(cam_rot.roll), 1)],
        )
    except Exception as exc:
        print("CAM skip", exc)


main()
