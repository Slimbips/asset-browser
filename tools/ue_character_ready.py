"""After a skeletal Convert, retarget onto SK_Mannequin using the pack chains and mesh-specific retarget poses.

Installs:
  /Game/Characters/Mohaa/IK_Mohaa
  /Game/Characters/UE5_Mannequins/Rigs/IK_UE5_Mannequin_Retarget
  /Game/Characters/Mohaa/RTG_Mohaa_to_Manny

Pack meshes retain the supplied pose. Exported skeletons are aligned separately.
"""
from __future__ import annotations

import re
from pathlib import Path

import unreal

PACK_IK_MOHAA = "/Game/Characters/Mohaa/IK_Mohaa"
PACK_IK_MANNY = "/Game/Characters/UE5_Mannequins/Rigs/IK_UE5_Mannequin_Retarget"
PACK_RTG = "/Game/Characters/Mohaa/RTG_Mohaa_to_Manny"
PACK_AIRBORNE = "/Game/MOH/Characters/AlliedAssault/SkeletalMeshes/Players/allied_Airborne"
IK_MANNY_SRC = "/Game/Characters/Mannequins/Rigs/IK_Mannequin"
MANNY_MESH_CANDIDATES = (
    "/Game/Characters/UE5_Mannequins/Meshes/SKM_Manny",
    "/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple",
    "/Game/Characters/Mannequins/Meshes/SKM_Manny",
)
MANNY_ROOT = "/Game/MOHAA/Manny"
CHAR_RTG_FOLDER = "/Game/MOHAA/Retarget"

CHAIN_RE = re.compile(
    r'ChainName="([^"]+)",StartBone=\(BoneName="([^"]+)"\),EndBone=\(BoneName="([^"]+)"\)'
    r'(?:,IKGoalName="([^"]+)")?'
)
POSE_RE = re.compile(
    r'\("([^"]+)", \(X=([-\d.]+),Y=([-\d.]+),Z=([-\d.]+),W=([-\d.]+)\)\)'
)
ROOT_OFF_RE = re.compile(
    r"RootTranslationOffset=\(X=([-\d.]+),Y=([-\d.]+),Z=([-\d.]+)\)"
)
ROOT_BONE_RE = re.compile(r'RootBone="([^"]+)"')
PELVIS_BONE_RE = re.compile(r'PelvisBone="([^"]+)"')


def pack_t3d_dir():
    here = Path(__file__).resolve().parent
    for cand in (
        here / "pack_retarget",
        Path(r"C:\Users\paulh\Desktop\conv\asset-browser\tools\pack_retarget"),
        Path(r"C:\Users\paulh\Downloads"),
    ):
        if (cand / "RTG_Mohaa_to_Manny.T3D").is_file():
            return cand
    return here / "pack_retarget"


def pack_t3d(name):
    return pack_t3d_dir() / name


def load(path):
    if not path or not unreal.EditorAssetLibrary.does_asset_exist(path):
        return None
    return unreal.EditorAssetLibrary.load_asset(path)


def save(asset):
    if asset:
        unreal.EditorAssetLibrary.save_asset(asset.get_path_name(), False)


def first_existing(paths):
    for path in paths:
        asset = load(path)
        if asset is not None:
            return path, asset
    return None, None


def create_or_load(path, uclass, factory):
    folder, name = path.rsplit("/", 1)
    existing = load(path)
    if existing is not None:
        return existing
    unreal.EditorAssetLibrary.make_directory(folder)
    return unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, folder, uclass, factory
    )


def duplicate_to(src_path, dest_path):
    if load(dest_path) is not None:
        return load(dest_path)
    if load(src_path) is None:
        return None
    folder, name = dest_path.rsplit("/", 1)
    unreal.EditorAssetLibrary.make_directory(folder)
    return unreal.EditorAssetLibrary.duplicate_asset(src_path, dest_path)


def parse_chains(t3d_name):
    text = pack_t3d(t3d_name).read_text(encoding="utf-8", errors="ignore")
    start = text.find("BoneChains=")
    block = text[start:] if start >= 0 else text
    chains = []
    for m in CHAIN_RE.finditer(block):
        chains.append((m.group(1), m.group(2), m.group(3), m.group(4) or ""))
    definition = text[text.index("RetargetDefinition="):]
    root = ROOT_BONE_RE.search(definition)
    pelvis = PELVIS_BONE_RE.search(definition)
    return (
        chains,
        root.group(1) if root else "",
        pelvis.group(1) if pelvis else "",
    )


def parse_pack_poses():
    text = pack_t3d("RTG_Mohaa_to_Manny.T3D").read_text(encoding="utf-8", errors="ignore")
    poses = []
    start = text.find("BoneRotationOffsets=")
    block = text[start : text.find("TargetRetargetPoses=", start)] if start >= 0 else ""
    for m in POSE_RE.finditer(block):
        poses.append(
            (
                m.group(1),
                float(m.group(2)),
                float(m.group(3)),
                float(m.group(4)),
                float(m.group(5)),
            )
        )
    root = (0.0, 0.0, 0.0)
    m = ROOT_OFF_RE.search(text)
    if m:
        root = (float(m.group(1)), float(m.group(2)), float(m.group(3)))
    return root, poses


def list_bones(mesh):
    names = []
    actor = None
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    try:
        actor = sub.spawn_actor_from_class(
            unreal.SkeletalMeshActor, unreal.Vector(0, 0, -26000)
        )
        comp = actor.skeletal_mesh_component
        try:
            comp.set_skeletal_mesh_asset(mesh)
        except Exception:
            try:
                comp.set_editor_property("skeletal_mesh", mesh)
            except Exception:
                pass
        for i in range(int(comp.get_num_bones())):
            names.append(str(comp.get_bone_name(i)))
    finally:
        if actor is not None:
            try:
                actor.destroy_actor()
            except Exception:
                pass
    return names


def bone_on_mesh(bones, name):
    lower = {b.lower(): b for b in bones}
    for cand in (name, name.replace(" ", "-"), name.replace("-", " ")):
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def set_bone_ref(settings, property_name, bone_name):
    ref = settings.get_editor_property(property_name)
    ref.set_editor_property("bone_name", bone_name)
    settings.set_editor_property(property_name, ref)


def apply_t3d_chains(ik, mesh, t3d_name, add_goals=False):
    ctrl = unreal.IKRigController.get_controller(ik)
    # Clear old chains before changing mesh: otherwise a stale delta requirement
    # can make SetSkeletalMesh reject an exported Bip01-rooted skeleton.
    for chain in list(ctrl.get_retarget_chains()):
        ctrl.remove_retarget_chain(chain.chain_name)
    if not ctrl.set_skeletal_mesh(mesh):
        raise RuntimeError("Cannot assign mesh to IK rig: " + mesh.get_path_name())
    chains, root, pelvis = parse_chains(t3d_name)
    bones = list_bones(mesh)
    # The pack's target RetargetDefinition.RootBone still says pelvis, but
    # its root chain and Root Motion operation explicitly use root.
    motion_root = next((start for name, start, end, goal in chains if name == "root"), root)
    root_b = bone_on_mesh(bones, motion_root)
    if not root_b and root == "delta":
        root_b = bone_on_mesh(bones, "Bip01")
    pelvis_b = bone_on_mesh(bones, pelvis)
    if not root_b or not pelvis_b:
        raise RuntimeError("Missing retarget root/pelvis on " + mesh.get_path_name())
    missing = []
    for name, start, end, goal in chains:
        start_b = root_b if name == "root" else bone_on_mesh(bones, start)
        end_b = root_b if name == "root" else bone_on_mesh(bones, end)
        if not start_b or not end_b:
            missing.append(name)
            continue
        if add_goals and goal:
            if ctrl.get_goal(goal) is None:
                ctrl.add_new_goal(goal, end_b)
            else:
                ctrl.set_goal_bone(goal, end_b)
        added = ctrl.add_retarget_chain(name, start_b, end_b, goal if add_goals and goal else "None")
        if str(added) == "None":
            raise RuntimeError("Could not add retarget chain: " + name)
    if not ctrl.set_retarget_root(pelvis_b):
        raise RuntimeError("Could not set retarget pelvis: " + pelvis_b)
    if not ctrl.set_root_motion_bone(root_b):
        raise RuntimeError("Could not set root motion bone: " + root_b)
    save(ik)
    print("PACK chains", ik.get_name(), len(chains) - len(missing), "/", len(chains),
          "root", root_b, "pelvis", pelvis_b, "missing", missing)
    return ctrl


def configure_manny_solver(ctrl):
    # Rebuild the solver on this generated rig, preserving the supplied pack's
    # limits and preferred bend directions rather than template defaults.
    for i in reversed(range(ctrl.get_num_solvers())):
        ctrl.remove_solver(i)
    index = ctrl.add_solver("/Script/IKRig.IKRigFullBodyIKSolver")
    if index < 0:
        raise RuntimeError("Cannot create Manny Full Body IK solver")
    ctrl.set_start_bone("pelvis", index)
    solver = ctrl.get_solver_controller(index)
    st = solver.get_solver_settings()
    st.iterations = 10
    st.sub_iterations = 20
    st.mass_multiplier = 0.5
    st.allow_stretch = False
    st.root_behavior = unreal.PBIKRootBehavior.PIN_TO_INPUT
    st.global_pull_chain_alpha = 0.0
    solver.set_solver_settings(st)
    for goal in ("LeftFootIK", "RightFootIK", "LeftHandIK", "RightHandIK"):
        if not ctrl.connect_goal_to_solver(goal, index):
            raise RuntimeError("Cannot connect IK goal: " + goal)
        settings = solver.get_goal_settings(goal)
        settings.chain_depth = 2
        solver.set_goal_settings(goal, settings)
    for bone in ("pelvis", "clavicle_l", "clavicle_r", "foot_l", "foot_r",
                 "calf_l", "calf_r", "lowerarm_l", "lowerarm_r"):
        ctrl.add_bone_setting(bone, index)
        st = solver.get_bone_settings(bone)
        if bone in ("pelvis", "clavicle_l", "clavicle_r"):
            st.rotation_stiffness = 0.95
        else:
            st.use_preferred_angles = True
            st.preferred_angles = unreal.Vector(0, 0, 45 if bone.startswith("foot") else 90)
            if bone.startswith("foot"):
                st.rotation_stiffness = 0.5
            else:
                st.x = unreal.PBIKLimitType.LOCKED
                st.y = unreal.PBIKLimitType.LOCKED
        solver.set_bone_settings(bone, st)


def apply_t3d_ops(rctrl):
    SRC = unreal.RetargetSourceOrTarget.SOURCE
    TGT = unreal.RetargetSourceOrTarget.TARGET
    source_mesh = rctrl.get_preview_mesh(SRC)
    target_mesh = rctrl.get_preview_mesh(TGT)
    source_bones = list_bones(source_mesh)
    target_bones = list_bones(target_mesh)
    source_root = bone_on_mesh(source_bones, "delta") or bone_on_mesh(source_bones, "Bip01")
    source_pelvis = bone_on_mesh(source_bones, "Bip01 Pelvis")
    target_root = bone_on_mesh(target_bones, "root")
    target_pelvis = bone_on_mesh(target_bones, "pelvis")
    if not all((source_root, source_pelvis, target_root, target_pelvis)):
        raise RuntimeError("Retarget mesh is missing a required root or pelvis")
    has_delta = bone_on_mesh(source_bones, "delta") is not None
    rctrl.remove_all_ops()
    for op in ("PelvisMotion", "FKChains", "RunIKRig", "RootMotion", "CurveRemap"):
        index = rctrl.add_retarget_op("/Script/IKRig.IKRetarget" + op + "Op")
        if index < 0:
            raise RuntimeError("Cannot create retarget operation: " + op)
    rctrl.assign_ik_rig_to_all_ops(SRC, rctrl.get_ik_rig(SRC))
    rctrl.assign_ik_rig_to_all_ops(TGT, rctrl.get_ik_rig(TGT))
    rctrl.auto_map_chains(unreal.AutoMapChainType.EXACT, True)
    if not has_delta:
        # Bip01 is at hip height; it is not the ground-level delta root.
        rctrl.set_source_chain("None", "root")
    for i in range(rctrl.get_num_retarget_ops()):
        name = str(rctrl.get_op_name(i)).lower()
        oc = rctrl.get_op_controller(i)
        st = oc.get_settings()
        if "pelvis" in name:
            set_bone_ref(st, "source_pelvis_bone", source_pelvis)
            set_bone_ref(st, "target_pelvis_bone", target_pelvis)
            st.scale_horizontal = st.scale_vertical = 1.0
            st.translation_alpha = st.rotation_alpha = 1.0
            st.blend_to_source_translation = 0.0
        elif "root" in name:
            set_bone_ref(st, "source_root", source_root)
            set_bone_ref(st, "target_root", target_root)
            set_bone_ref(st, "target_pelvis", target_pelvis)
            st.root_motion_source = (unreal.RootMotionSource.COPY_FROM_SOURCE_ROOT if has_delta
                                    else unreal.RootMotionSource.GENERATE_FROM_TARGET_PELVIS)
            st.root_height_source = (unreal.RootMotionHeightSource.COPY_HEIGHT_FROM_SOURCE if has_delta
                                    else unreal.RootMotionHeightSource.SNAP_TO_GROUND)
            st.rotate_with_pelvis = False
            st.maintain_offset_from_pelvis = has_delta
        oc.set_settings(st)


def apply_export_pose(rctrl):
    SRC = unreal.RetargetSourceOrTarget.SOURCE
    # Pack offsets are relative to allied_Airborne's axes/reference pose, not
    # Blender's exported reference pose. Align this actual source mesh instead.
    name = "Export Pose"
    if name not in [str(n) for n in rctrl.get_retarget_poses(SRC)]:
        rctrl.create_retarget_pose(name, SRC)
    rctrl.set_current_retarget_pose(name, SRC)
    rctrl.reset_retarget_pose(name, [], SRC)
    rctrl.auto_align_all_bones(SRC, unreal.RetargetAutoAlignMethod.CHAIN_TO_CHAIN)
    print("PACK aligned exported reference pose")


def apply_pack_poses(rctrl, bones):
    SRC = unreal.RetargetSourceOrTarget.SOURCE
    root, poses = parse_pack_poses()
    try:
        rctrl.create_retarget_pose("Default Pose", SRC)
    except Exception:
        pass
    try:
        rctrl.set_current_retarget_pose("Default Pose", SRC)
    except Exception:
        pass
    applied = 0
    for bone, x, y, z, w in poses:
        actual = bone_on_mesh(bones, bone)
        if not actual:
            continue
        try:
            rctrl.set_rotation_offset_for_retarget_pose_bone(
                actual, unreal.Quat(x, y, z, w), SRC
            )
            applied += 1
        except Exception as exc:
            print("PACK pose skip", actual, exc)
    try:
        rctrl.set_root_offset_in_retarget_pose(unreal.Vector(*root), SRC)
    except Exception:
        pass
    print("PACK poses applied", applied, "/", len(poses))
    return applied


def install_pack(source_mesh=None):
    airborne = load(PACK_AIRBORNE)
    if airborne is None:
        airborne = source_mesh
    manny_path, manny_mesh = first_existing(MANNY_MESH_CANDIDATES)
    if airborne is None:
        raise RuntimeError(
            "pack preview mesh missing: %s (and no converted mesh to use)" % PACK_AIRBORNE
        )
    if manny_mesh is None:
        raise RuntimeError("Manny mesh missing")

    needed = ("IK_Mohaa.T3D", "IK_UE5_Mannequin_Retarget.T3D", "RTG_Mohaa_to_Manny.T3D")
    missing = [n for n in needed if not pack_t3d(n).is_file()]
    if missing:
        raise RuntimeError("pack T3D missing: %s" % missing)
    print("PACK T3D dir", pack_t3d_dir())

    ik_mohaa = create_or_load(
        PACK_IK_MOHAA, unreal.IKRigDefinition, unreal.IKRigDefinitionFactory()
    )
    apply_t3d_chains(ik_mohaa, airborne, "IK_Mohaa.T3D", add_goals=False)

    ik_manny = create_or_load(PACK_IK_MANNY, unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())
    mctrl = apply_t3d_chains(ik_manny, manny_mesh, "IK_UE5_Mannequin_Retarget.T3D", add_goals=True)
    configure_manny_solver(mctrl)
    save(ik_manny)
    print("PACK manny ik", ik_manny.get_path_name(), "mesh", manny_path)

    rtg = create_or_load(PACK_RTG, unreal.IKRetargeter, unreal.IKRetargetFactory())
    rctrl = unreal.IKRetargeterController.get_controller(rtg)
    SRC = unreal.RetargetSourceOrTarget.SOURCE
    TGT = unreal.RetargetSourceOrTarget.TARGET
    rctrl.set_ik_rig(SRC, ik_mohaa)
    rctrl.set_ik_rig(TGT, ik_manny)
    rctrl.set_preview_mesh(SRC, airborne)
    rctrl.set_preview_mesh(TGT, manny_mesh)
    if int(rctrl.get_num_retarget_ops() or 0) == 0:
        rctrl.add_default_ops()
    try:
        rctrl.auto_map_chains(unreal.AutoMapChainType.EXACT, True)
    except Exception as exc:
        print("PACK auto map", exc)
    apply_t3d_ops(rctrl)
    apply_pack_poses(rctrl, list_bones(airborne))
    save(rtg)
    print("PACK rtg", PACK_RTG)
    return ik_mohaa, ik_manny, rtg, manny_mesh


def stem_from_mesh_name(asset_name):
    name = str(asset_name or "").strip()
    if name.startswith("SK_"):
        name = name[3:]
    return name or "Character"


def alias_from_anim(anim_name, stem):
    alias = str(anim_name or "")
    for prefix in ("AS_" + stem + "_", "AS_"):
        if alias.startswith(prefix):
            return alias[len(prefix) :]
    return alias


def asset_data(path):
    asset = load(path)
    if asset is None:
        return None
    obj_path = asset.get_path_name()
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        return registry.get_asset_by_object_path(unreal.SoftObjectPath(obj_path))
    except Exception:
        try:
            return registry.get_asset_by_object_path(obj_path)
        except Exception:
            return None


def pick_walk_idle(created):
    walk = idle = None
    for rec in created:
        if not rec.get("ok"):
            continue
        name = str(rec.get("alias") or "").lower()
        if "run" in name or "sprint" in name:
            continue
        if idle is None and "idle" in name:
            idle = rec
        if walk is None and "walk" in name:
            walk = rec
    return idle, walk


def is_idle_or_walk(alias):
    name = str(alias or "").lower()
    if "run" in name or "sprint" in name:
        return False
    return "idle" in name or "walk" in name


def pose_actor(label, mesh, seq, loc):
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    found = None
    for actor in list(actors.get_all_level_actors() or []):
        if str(actor.get_actor_label()) == label:
            found = actor
            break
    if found is None:
        found = actors.spawn_actor_from_class(
            unreal.SkeletalMeshActor,
            unreal.Vector(float(loc[0]), float(loc[1]), float(loc[2])),
        )
        found.set_actor_label(label)
    found.set_actor_location(unreal.Vector(*[float(v) for v in loc]), False, False)
    found.set_actor_rotation(unreal.Rotator(pitch=0, yaw=0, roll=0), False)
    try:
        found.set_is_temporarily_hidden_in_editor(False)
    except Exception:
        pass
    comp = found.skeletal_mesh_component
    try:
        comp.set_skeletal_mesh_asset(mesh)
    except Exception:
        try:
            comp.set_editor_property("skeletal_mesh", mesh)
        except Exception:
            pass
    comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
    try:
        comp.set_update_animation_in_editor(True)
        comp.set_visibility(True, True)
        comp.set_editor_property(
            "visibility_based_anim_tick_option",
            unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES,
        )
    except Exception:
        pass
    data = unreal.SingleAnimationPlayData()
    data.anim_to_play = seq
    data.saved_looping = True
    data.saved_playing = True
    data.saved_position = 0.0
    data.saved_play_rate = 1.0
    comp.set_editor_property("animation_data", data)
    try:
        comp.override_animation_data(seq, True, True, 0.0, 1.0)
    except Exception:
        pass
    return found


def source_ik_for_mesh(mesh, pack_ik):
    if mesh.get_path_name().split(".")[0] == PACK_AIRBORNE:
        return pack_ik
    dest = CHAR_RTG_FOLDER + "/IK_" + str(mesh.get_name()).replace("SK_", "")
    ik = create_or_load(dest, unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())
    apply_t3d_chains(ik, mesh, "IK_Mohaa.T3D", add_goals=False)
    return ik


def make_ready(mesh_path, dest, asset_name, anim_names, spawn_previews=True):
    report = {
        "ok": False,
        "mesh": mesh_path,
        "errors": [],
        "created": [],
        "ik": PACK_IK_MOHAA,
        "rtg": PACK_RTG,
        "manny_folder": "",
        "ok_count": 0,
        "fail_count": 0,
    }

    def err(msg):
        print("CHARACTER READY ERROR", msg)
        report["errors"].append(str(msg))

    mesh = load(mesh_path)
    if mesh is None or not isinstance(mesh, unreal.SkeletalMesh):
        err("no skeletal mesh at %s" % mesh_path)
        return _finish(report)

    try:
        pack_ik, _ik_manny, pack_rtg, manny_mesh = install_pack(mesh)
    except Exception as exc:
        err(exc)
        return _finish(report)

    bones = list_bones(mesh)
    if not bone_on_mesh(bones, "Bip01 Pelvis") and not bone_on_mesh(bones, "Bip01-Pelvis"):
        print("CHARACTER READY skip: not a humanoid")
        return _finish(report)

    src_ik = source_ik_for_mesh(mesh, pack_ik)
    stem = stem_from_mesh_name(asset_name)
    manny_folder = MANNY_ROOT + "/" + stem
    rtg_path = CHAR_RTG_FOLDER + "/RTG_" + stem + "_To_Manny"
    report["ik"] = src_ik.get_path_name().split(".")[0]
    report["rtg"] = rtg_path
    report["manny_folder"] = manny_folder

    unreal.EditorAssetLibrary.make_directory(CHAR_RTG_FOLDER)
    rtg = create_or_load(rtg_path, unreal.IKRetargeter, unreal.IKRetargetFactory())
    rctrl = unreal.IKRetargeterController.get_controller(rtg)
    SRC = unreal.RetargetSourceOrTarget.SOURCE
    TGT = unreal.RetargetSourceOrTarget.TARGET
    rctrl.set_ik_rig(SRC, src_ik)
    rctrl.set_ik_rig(TGT, _ik_manny)
    rctrl.set_preview_mesh(TGT, manny_mesh)
    rctrl.set_preview_mesh(SRC, mesh)
    apply_t3d_ops(rctrl)
    if mesh.get_path_name().split(".")[0] == PACK_AIRBORNE:
        apply_pack_poses(rctrl, bones)
    else:
        apply_export_pose(rctrl)
    save(rtg)

    unreal.EditorAssetLibrary.make_directory(manny_folder)
    dest = str(dest or "").rstrip("/")
    src_search = "AS_" + stem + "_"
    dst_replace = "AS_Manny_" + stem + "_"
    datas = []
    native_idle = native_walk = None
    for anim_name in list(anim_names or []):
        src_path = dest + "/" + anim_name
        alias = alias_from_anim(anim_name, stem)
        rec = {
            "src": src_path,
            "dst": manny_folder + "/" + dst_replace + alias,
            "alias": alias,
            "ok": False,
        }
        data = asset_data(src_path)
        if data is None:
            rec["error"] = "missing source anim"
            report["created"].append(rec)
            continue
        seq = load(src_path)
        if native_idle is None and is_idle_or_walk(alias) and "idle" in alias.lower() and seq:
            native_idle = seq
        if native_walk is None and is_idle_or_walk(alias) and "walk" in alias.lower() and seq:
            native_walk = seq
        if not is_idle_or_walk(alias):
            rec["skipped"] = "idle+walk only"
            report["created"].append(rec)
            continue
        datas.append((rec, data))
    created = None
    if datas:
        inputs = unreal.IKRetargetBatchOperationInputs()
        inputs.assets_to_retarget = [item[1] for item in datas]
        inputs.source_mesh = mesh
        inputs.target_mesh = manny_mesh
        inputs.ik_retarget_asset = rtg
        inputs.search = src_search
        inputs.replace = dst_replace
        inputs.prefix = ""
        inputs.suffix = ""
        inputs.target_path = manny_folder
        inputs.use_source_path = False
        inputs.include_referenced_assets = False
        try:
            inputs.set_editor_property("overwrite_existing_files", True)
        except Exception:
            pass
        try:
            created = unreal.IKRetargetBatchOperation.run_batch_retarget(inputs)
        except Exception as exc:
            err("batch retarget %s" % exc)
    got_paths = []
    if created:
        for item in created:
            try:
                got_paths.append(str(item.package_name))
            except Exception:
                pass
    for rec, _data in datas:
        got = rec["dst"]
        leaf = rec["dst"].rsplit("/", 1)[-1]
        for path in got_paths:
            if path.rsplit("/", 1)[-1] == leaf or path.endswith("/" + leaf):
                got = path.split(".")[0]
                break
        rec["dst"] = got
        rec["ok"] = load(got) is not None
        report["created"].append(rec)

    idle, walk = pick_walk_idle(report["created"])
    spawned = []
    if spawn_previews and native_walk:
        pose_actor("MOHAA_" + stem + "_Walk", mesh, native_walk, (0.0, 180.0, 0.0))
        spawned.append("native_walk")
    if spawn_previews and native_idle:
        pose_actor("MOHAA_" + stem + "_Idle", mesh, native_idle, (0.0, 0.0, 0.0))
        spawned.append("native_idle")
    if walk and spawn_previews:
        seq = load(walk["dst"])
        if seq:
            actor = pose_actor("PIEManny_" + stem + "_Walk", manny_mesh, seq, (180.0, 0.0, 0.0))
            spawned.append("walk")
            try:
                t = actor.skeletal_mesh_component.get_socket_transform(
                    "pelvis", unreal.RelativeTransformSpace.RTS_WORLD
                )
                print("PACK CHECK walk pelvis_z", round(float(t.translation.z), 2))
            except Exception as exc:
                print("PACK CHECK walk pelvis fail", exc)
    if idle and spawn_previews:
        seq = load(idle["dst"])
        if seq:
            actor = pose_actor("PIEManny_" + stem + "_Idle", manny_mesh, seq, (360.0, 0.0, 0.0))
            spawned.append("idle")
            try:
                t = actor.skeletal_mesh_component.get_socket_transform(
                    "pelvis", unreal.RelativeTransformSpace.RTS_WORLD
                )
                print("PACK CHECK idle pelvis_z", round(float(t.translation.z), 2))
            except Exception as exc:
                print("PACK CHECK idle pelvis fail", exc)
    report["spawned"] = spawned
    report["ok_count"] = sum(1 for c in report["created"] if c.get("ok"))
    report["fail_count"] = sum(
        1 for c in report["created"] if not c.get("ok") and not c.get("skipped")
    )
    report["ok"] = not report["errors"]
    return _finish(report)


def _finish(report):
    print(
        "CHARACTER READY ok=%s fail=%s ik=%s rtg=%s folder=%s"
        % (
            report.get("ok_count", 0),
            report.get("fail_count", 0),
            report.get("ik") or "",
            report.get("rtg") or "",
            report.get("manny_folder") or "",
        )
    )
    return report


def check_pack():
    print("PACK CHECK begin", pack_t3d_dir())
    return make_ready(
        "/Game/MOHAA/characters/SK_1St_Ranger_Engineer",
        "/Game/MOHAA/characters",
        "SK_1St_Ranger_Engineer",
        [
            "AS_1St_Ranger_Engineer_idle",
            "AS_1St_Ranger_Engineer_unarmed_walk_alert_forward",
        ],
    )
