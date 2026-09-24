"""Dump Diverting chair/table live loc vs current/old formula. No LoadLevel."""
from __future__ import annotations

import json

import unreal

WANT = ("simplechair", "square_table", "cardtable", "simpledesk", "rolltop")


def _xyz(v):
    return [round(float(v.x), 3), round(float(v.y), 3), round(float(v.z), 3)]


def _pyr(rot):
    return [round(float(rot.pitch), 2), round(float(rot.yaw), 2), round(float(rot.roll), 2)]


def main() -> None:
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    print("WORLD", world.get_name() if world else "")
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    n = 0
    for actor in list(sub.get_all_level_actors() or []):
        label = (actor.get_actor_label() or "").lower()
        if not any(k in label for k in WANT):
            continue
        n += 1
        if n > 12:
            break
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        scl = actor.get_actor_scale3d()
        print(
            "LIVE",
            json.dumps(
                {
                    "label": actor.get_actor_label(),
                    "loc": _xyz(loc),
                    "rot": _pyr(rot),
                    "scale": _xyz(scl),
                    "y_sign": "+" if float(loc.y) >= 0 else "-",
                }
            ),
        )


main()
