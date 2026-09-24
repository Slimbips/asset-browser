"""Closest-point floor proof + collision + tree material slots. No LoadLevel."""
from __future__ import annotations

import json

import unreal

SAMPLES = (
    "MOHAA_prop_SM_tree_winter_smallpine_0",
    "MOHAA_prop_SM_rock_winter_medium_0",
    "MOHAA_prop_SM_lightpost_globe_winter_0",
)


def _xyz(v):
    return [round(float(v.x), 2), round(float(v.y), 2), round(float(v.z), 2)]


def main() -> None:
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    print("WORLD", world.get_name() if world else "")
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    by_label = {}
    map_actor = None
    for actor in list(sub.get_all_level_actors() or []):
        label = actor.get_actor_label() or ""
        by_label[label] = actor
        if label == "SM_Snowy_Park":
            map_actor = actor
    if map_actor is None:
        print("NO MAP")
        return
    smc = map_actor.static_mesh_component
    mesh = smc.static_mesh
    for prop in (
        "collision_enabled",
        "generate_overlap_events",
        "can_character_step_up_on",
        "notify_rigid_body_collision",
        "use_default_collision",
    ):
        try:
            print("SMC", prop, smc.get_editor_property(prop))
        except Exception as visc:
            print("SMC skip", prop, visc)
    try:
        print("actor_enable_collision", map_actor.get_editor_property("actor_enable_collision"))
    except Exception as visc:
        print("actor_enable_collision skip", visc)
    try:
        print("mesh nanite", mesh.nanite_settings)
    except Exception:
        pass
    try:
        slots = list(mesh.static_materials or [])
        print("MAP slots", len(slots))
    except Exception as visc:
        print("slots skip", visc)

    tree = by_label.get("MOHAA_prop_SM_tree_winter_smallpine_0")
    if tree is not None:
        tmesh = tree.static_mesh_component.static_mesh
        print("TREE mesh", tmesh.get_path_name() if tmesh else None)
        try:
            names = []
            for i, slot in enumerate(list(tmesh.static_materials or [])):
                mat = tmesh.get_material(i)
                names.append(mat.get_name() if mat else str(slot))
            print("TREE slots", names)
            print("TREE has_sprite", any("sprite" in (n or "").lower() for n in names))
        except Exception as visc:
            print("TREE slots skip", visc)

    origin, extent = map_actor.get_actor_bounds(False)
    print("MAP origin", _xyz(origin), "extent", _xyz(extent))

    for label in SAMPLES:
        actor = by_label.get(label)
        if actor is None:
            print("MISSING", label)
            continue
        loc = actor.get_actor_location()
        closest = unreal.Vector()
        dist = None
        try:
            dist = smc.get_closest_point_on_collision(loc, "None")
            if isinstance(dist, (tuple, list)):
                if len(dist) >= 2:
                    closest = dist[1]
                    dist = dist[0]
            elif isinstance(dist, unreal.Vector):
                closest = dist
                dist = 0.0
        except Exception as visc:
            print("CLOSEST try1", label, visc)
            try:
                dist = smc.get_closest_point_on_collision(loc)
            except Exception as visc2:
                print("CLOSEST fail", label, visc2)
                continue
        rec = {
            "label": label,
            "loc": _xyz(loc),
            "closest": _xyz(closest),
            "dist": round(float(dist), 2),
            "dz": round(float(loc.z) - float(closest.z), 2),
            "dxy": round(((float(loc.x) - float(closest.x)) ** 2 + (float(loc.y) - float(closest.y)) ** 2) ** 0.5, 2),
        }
        print("CLOSEST", json.dumps(rec))

    print("CLOSEST_DONE")


main()
