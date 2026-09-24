"""Numeric Manny/Engineer check after Convert. No screenshots."""
from __future__ import annotations

import json

import unreal

MESH = "/Game/MOHAA/characters/SK_1St_Ranger_Engineer"
IDLE = "/Game/MOHAA/characters/AS_1St_Ranger_Engineer_idle"
WALK = "/Game/MOHAA/characters/AS_1St_Ranger_Engineer_unarmed_walk_alert_forward"
MANNY_IDLE = "/Game/MOHAA/Manny/1St_Ranger_Engineer/AS_Manny_1St_Ranger_Engineer_idle"
MANNY_WALK = "/Game/MOHAA/Manny/1St_Ranger_Engineer/AS_Manny_1St_Ranger_Engineer_unarmed_walk_alert_forward"
IK = "/Game/Characters/Mohaa/IK_Mohaa"
RTG = "/Game/Characters/Mohaa/RTG_Mohaa_to_Manny"
IK_MANNY = "/Game/Characters/UE5_Mannequins/Rigs/IK_UE5_Mannequin_Retarget"
MANNY_SIMPLE = "/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple"


def exists(path):
    return bool(unreal.EditorAssetLibrary.does_asset_exist(path))


def load(path):
    if not exists(path):
        return None
    return unreal.EditorAssetLibrary.load_asset(path)


def bone_names(mesh):
    names = []
    actor = None
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    try:
        actor = sub.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(0, 0, -26000))
        comp = actor.skeletal_mesh_component
        try:
            comp.set_skeletal_mesh_asset(mesh)
        except Exception:
            comp.set_skeletal_mesh(mesh)
        n = int(comp.get_num_bones())
        for i in range(n):
            names.append(str(comp.get_bone_name(i)))
    finally:
        if actor:
            sub.destroy_actor(actor)
    return names


def pelvis_z(label):
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in list(sub.get_all_level_actors() or []):
        if str(actor.get_actor_label()) != label:
            continue
        try:
            t = actor.skeletal_mesh_component.get_socket_transform(
                "pelvis", unreal.RelativeTransformSpace.RTS_WORLD
            )
            return round(float(t.translation.z), 2)
        except Exception as visc:
            return str(visc)
    return None


def main():
    mesh = load(MESH)
    rec = {
        "mesh": exists(MESH),
        "idle": exists(IDLE),
        "walk": exists(WALK),
        "manny_idle": exists(MANNY_IDLE),
        "manny_walk": exists(MANNY_WALK),
        "ik": exists(IK),
        "ik_manny": exists(IK_MANNY),
        "rtg": exists(RTG),
        "manny_simple": exists(MANNY_SIMPLE),
        "height_cm": None,
        "root": None,
        "idle_pelvis_z": pelvis_z("PIEManny_1St_Ranger_Engineer_Idle"),
        "walk_pelvis_z": pelvis_z("PIEManny_1St_Ranger_Engineer_Walk"),
    }
    if mesh is not None:
        b = mesh.get_bounds()
        rec["height_cm"] = round(2.0 * float(b.box_extent.z), 2)
        rec["extent"] = [
            round(float(b.box_extent.x), 2),
            round(float(b.box_extent.y), 2),
            round(float(b.box_extent.z), 2),
        ]
        names = bone_names(mesh)
        rec["root"] = names[0] if names else None
        rec["has_delta"] = "delta" in names
        rec["bone_count"] = len(names)
    print("CHAR PROOF", json.dumps(rec))
    print("HEIGHT", rec["height_cm"], "ROOT", rec["root"], "DELTA", rec.get("has_delta"))
    print("MANNY IDLE", rec["manny_idle"], "WALK", rec["manny_walk"], "pelvis", rec["idle_pelvis_z"], rec["walk_pelvis_z"])
    print("PACK IK", rec["ik"], "RTG", rec["rtg"], "IK_MANNY", rec["ik_manny"])


main()
