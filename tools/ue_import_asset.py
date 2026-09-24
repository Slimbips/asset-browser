"""Import one Convert job into the open Unreal editor.

export_ue.py copies this file to Content/Python/import_mohaa_asset.py and writes
import_mohaa_job.json next to it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import unreal

_PY = str((Path(unreal.Paths.project_content_dir()) / "Python").resolve())
if _PY not in sys.path:
    sys.path.insert(0, _PY)

JOB_PATH = Path(unreal.Paths.project_content_dir()) / "Python" / "import_mohaa_job.json"


def _set(obj, prop, value) -> bool:
    try:
        obj.set_editor_property(prop, value)
        return True
    except Exception:
        return False


def _load_job() -> dict:
    job = json.loads(JOB_PATH.read_text(encoding="utf-8"))
    actual = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.get_project_file_path())).resolve()
    if not job.get("project") or actual != Path(job["project"]).resolve():
        raise RuntimeError("Export destination does not match the running Unreal project")
    return job


def _asset_class_name(path: str) -> str:
    pkg = (path or "").split(".")[0]
    try:
        data = unreal.EditorAssetLibrary.find_asset_data(pkg)
    except Exception:
        data = None
    if data is None:
        return ""
    try:
        return str(data.asset_class_path.asset_name)
    except Exception:
        pass
    try:
        return str(data.asset_class)
    except Exception:
        return ""


def _is_world_asset(path: str) -> bool:
    """True for umaps. Must not load_asset them: a resident UWorld fails map GC."""
    cls = _asset_class_name(path)
    if cls == "World":
        return True
    if cls:
        return False
    return (path or "").split(".")[0].rsplit("/", 1)[-1].startswith("L_")


def _delete_existing(dest: str, name: str, skeletal: bool, anim_files: list, wipe_folder_mats: bool = False) -> None:
    if skeletal:
        extras = [name, name + "_Skeleton", name + "_PhysicsAsset"]
        extras.extend(item["name"] for item in anim_files)
        for extra in extras:
            path = dest + "/" + extra
            if not unreal.EditorAssetLibrary.does_asset_exist(path):
                continue
            try:
                unreal.EditorAssetLibrary.delete_asset(path)
            except Exception as extra_exc:
                print("delete skip", path, extra_exc)
        return
    if not wipe_folder_mats:
        return
    # Reimport of THIS mesh only. Never list_assets the whole /maps folder:
    # that deleted Remagen/Stalingrad MICs when another map imported.
    dest = dest.rstrip("/")
    mesh_path = dest + "/" + name
    to_delete = []
    seen = set()

    def add(path: str) -> None:
        path = (path or "").split(".")[0]
        if not path or path in seen or _is_world_asset(path):
            return
        seen.add(path)
        to_delete.append(path)

    if unreal.EditorAssetLibrary.does_asset_exist(mesh_path):
        mesh = None
        try:
            mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
        except Exception:
            mesh = None
        if isinstance(mesh, unreal.StaticMesh):
            slots = list(mesh.static_materials or [])
            for i, slot in enumerate(slots):
                mat = None
                try:
                    mat = mesh.get_material(i)
                except Exception:
                    mat = None
                if mat is None:
                    try:
                        mat = slot.get_editor_property("material_interface")
                    except Exception:
                        mat = getattr(slot, "material_interface", None)
                if mat is None:
                    continue
                try:
                    add(mat.get_path_name())
                except Exception:
                    pass
        add(mesh_path)
    n = 0
    for path in to_delete:
        try:
            if not unreal.EditorAssetLibrary.does_asset_exist(path):
                continue
            unreal.EditorAssetLibrary.delete_asset(path)
            n += 1
            print("deleted leftover", path)
        except Exception as exc:
            print("delete leftover skip", path, exc)
    print("deleted leftovers", n, "for", mesh_path)


def _import_mesh(job: dict):
    task = unreal.AssetImportTask()
    task.filename = job["fbx"]
    task.destination_path = job["dest"]
    task.destination_name = job["name"]
    task.automated = True
    task.save = True
    task.replace_existing = True

    options = unreal.FbxImportUI()
    options.import_mesh = True
    options.import_materials = True
    options.import_textures = bool(job.get("with_textures", True)) if _is_map(job) else True
    options.automated_import_should_detect_type = False
    options.import_animations = False
    if job["skeletal"]:
        options.import_as_skeletal = True
        options.mesh_type_to_import = unreal.FBXImportType.FBXIT_SKELETAL_MESH
        _set(options, "create_physics_asset", False)
        skd = options.skeletal_mesh_import_data
        skd.import_uniform_scale = 1.0
        # Blender already baked pack space (Y-mirror +90° Z, cm). convert_scene
        # would yaw/scale again and explode Bip01 to ~100.
        skd.convert_scene = False
        _set(skd, "convert_scene_unit", False)
        skd.force_front_x_axis = False
        _set(skd, "import_morph_targets", False)
        _set(skd, "update_skeleton_reference_pose", False)
        _set(skd, "use_t0_as_ref_pose", True)
    else:
        options.import_as_skeletal = False
        options.mesh_type_to_import = unreal.FBXImportType.FBXIT_STATIC_MESH
        smd = options.static_mesh_import_data
        smd.combine_meshes = True
        smd.auto_generate_collision = True
        smd.import_uniform_scale = 1.0
        smd.convert_scene = True
        _set(smd, "convert_scene_unit", False)
        smd.force_front_x_axis = False
        _set(smd, "transform_vertex_to_absolute", True)
    task.options = options
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    return list(task.imported_object_paths or [])


def _resolve_mesh(job: dict, imported: list):
    dest = job["dest"]
    name = job["name"]
    skeletal = job["skeletal"]
    mesh_path = dest + "/" + name
    mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
    if mesh is not None:
        return mesh, mesh_path
    for path in imported:
        asset = unreal.EditorAssetLibrary.load_asset(path)
        if skeletal and isinstance(asset, unreal.SkeletalMesh):
            return asset, path
        if (not skeletal) and isinstance(asset, unreal.StaticMesh):
            return asset, path
    if imported:
        return unreal.EditorAssetLibrary.load_asset(imported[0]), imported[0]
    return None, mesh_path


def _attach_lods(mesh, mesh_path: str, lod_files: list, screens: list) -> None:
    if not lod_files:
        return
    sms = None
    lib = getattr(unreal, "EditorStaticMeshLibrary", None)
    try:
        sms = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    except Exception:
        sms = None
    ok_count = 0
    for i, path in enumerate(lod_files, start=1):
        ok = False
        if sms is not None and hasattr(sms, "import_lod"):
            try:
                sms.import_lod(mesh, i, path)
                ok = True
            except Exception as exc:
                print("LOD", i, "fail", exc)
        if (not ok) and lib is not None and hasattr(lib, "import_lod"):
            try:
                lib.import_lod(mesh, i, path)
                ok = True
            except Exception as exc:
                print("LOD", i, "fail", exc)
        if ok:
            ok_count += 1
    _set(mesh, "auto_compute_lod_screen_size", False)
    if sms is not None and hasattr(sms, "set_lod_screen_sizes") and screens:
        try:
            sms.set_lod_screen_sizes(mesh, screens)
        except Exception as exc:
            print("LOD screens fail", exc)
    unreal.EditorAssetLibrary.save_asset(mesh_path)
    print("LODS", ok_count, "/", len(lod_files))


def _is_map(job: dict) -> bool:
    kind = str(job.get("kind") or "").lower()
    dest = str(job.get("dest") or "").rstrip("/").lower()
    return kind == "map" or dest.endswith("/maps")


def _world_path(job: dict) -> str:
    dest = str(job.get("dest") or "/Game/MOHAA/maps").rstrip("/")
    stem = str(job.get("name") or "Map")
    for prefix in ("SM_", "SK_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
            break
    return dest + "/L_" + stem


def _actor_named(sub, label: str):
    try:
        for old in list(sub.get_all_level_actors() or []):
            if old.get_actor_label() == label:
                return old
    except Exception:
        pass
    return None


def _world_name() -> str:
    try:
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        return world.get_name() if world else ""
    except Exception:
        return ""


def _save_dirty_packages() -> None:
    """Map switches fatal-assert if a dirty UWorld is still resident (EditorServer:2544)."""
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        les.save_current_level()
    except Exception:
        pass
    try:
        n = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
        print("SAVED DIRTY PACKAGES", n)
    except Exception as exc:
        print("SAVE DIRTY FAIL", exc)


def _open_map_level(job: dict) -> str:
    """Put BSP geometry in its own World so it is not dropped into the open map."""
    print("CURRENT WORLD BEFORE MAP", _world_name())
    level_path = _world_path(job)
    target_name = level_path.rsplit("/", 1)[-1]
    unreal.EditorAssetLibrary.make_directory(job["dest"])
    if _world_name() == target_name:
        print("LEVEL ALREADY OPEN", level_path, "WORLD", _world_name())
        return level_path
    _save_dirty_packages()
    les = None
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    except Exception:
        les = None
    # Leftover convert umaps crash LoadLevel (resident UWorld). Never load them.
    if unreal.EditorAssetLibrary.does_asset_exist(level_path):
        try:
            unreal.EditorAssetLibrary.delete_asset(level_path)
            print("LEVEL leftover deleted", level_path)
        except Exception as exc:
            print("LEVEL leftover delete skip", exc)
    template = "/Engine/Maps/Templates/Template_Default"
    try:
        if les is not None and hasattr(les, "new_level_from_template"):
            les.new_level_from_template(level_path, template)
        elif les is not None:
            les.new_level(level_path)
        else:
            unreal.EditorLevelLibrary.new_level(level_path)
        print("LEVEL NEW", level_path, "WORLD", _world_name())
        return level_path
    except Exception as visc:
        print("LEVEL NEW FAIL", visc)
        return ""


def _mobility(actor, mode) -> None:
    try:
        actor.set_editor_property("mobility", mode)
    except Exception:
        pass
    try:
        root = actor.root_component
        if root:
            root.set_editor_property("mobility", mode)
    except Exception:
        pass


def _light_comp(actor):
    for name in ("light_component", "component", "root_component"):
        try:
            comp = getattr(actor, name, None)
            if comp is not None:
                return comp
        except Exception:
            pass
        try:
            return actor.get_editor_property(name)
        except Exception:
            pass
    return None


def _import_file(filename: str, dest: str, name: str):
    if not filename or not Path(filename).is_file():
        return None
    task = unreal.AssetImportTask()
    task.filename = filename
    task.destination_path = dest
    task.destination_name = name
    task.automated = True
    task.save = True
    task.replace_existing = True
    try:
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    except Exception as exc:
        print("SKY IMPORT FAIL", name, exc)
        return None
    path = dest + "/" + name
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.EditorAssetLibrary.load_asset(path)
    for p in task.imported_object_paths or []:
        asset = unreal.EditorAssetLibrary.load_asset(p)
        if asset is not None:
            return asset
    return None


def _make_sky_material(dest: str, texture) -> object | None:
    """Unlit IsSky material: view-ray (-CameraVectorWS) → lat-long UV → cubemap equirect."""
    if texture is None:
        return None
    name = "M_MOHAA_Sky"
    path = dest + "/" + name
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            unreal.EditorAssetLibrary.delete_asset(path)
    except Exception:
        pass
    try:
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name, dest, unreal.Material, unreal.MaterialFactoryNew()
        )
    except Exception as exc:
        print("SKY MAT create fail", visc if False else exc)
        return None
    if mat is None:
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            mat = unreal.EditorAssetLibrary.load_asset(path)
            print("SKY MAT reused", path)
        else:
            print("SKY MAT create returned none", path)
            return None
    unlit = getattr(unreal.MaterialShadingModel, "MSM_UNLIT", None)
    if unlit is not None:
        _set(mat, "shading_model", unlit)
    _set(mat, "two_sided", True)
    _set(mat, "is_two_sided", True)
    _set(mat, "is_sky", True)
    try:
        unreal.MaterialEditingLibrary.delete_all_material_expressions(mat)
    except Exception:
        pass
    try:
        cam = unreal.MaterialEditingLibrary.create_material_expression(
            mat, unreal.MaterialExpressionCameraVectorWS, -840, 0
        )
        custom = unreal.MaterialEditingLibrary.create_material_expression(
            mat, unreal.MaterialExpressionCustom, -560, 0
        )
        _set(custom, "description", "viewDirToEquirect")
        cmot = getattr(unreal.CustomMaterialOutputType, "CMOT_FLOAT2", None)
        if cmot is not None:
            _set(custom, "output_type", cmot)
        _set(
            custom,
            "code",
            "float3 d = normalize(-Dir);\n"
            "float u = atan2(d.y, d.x) * 0.15915494309 + 0.5;\n"
            "float v = 0.5 - asin(clamp(d.z, -1.0, 1.0)) * 0.31830988618;\n"
            "return float2(u, v);",
        )
        inp = unreal.CustomInput()
        inp.set_editor_property("input_name", "Dir")
        custom.set_editor_property("inputs", [inp])
        unreal.MaterialEditingLibrary.connect_material_expressions(cam, "", custom, "Dir")
        tex_expr = unreal.MaterialEditingLibrary.create_material_expression(
            mat, unreal.MaterialExpressionTextureSample, -280, 0
        )
        _set(tex_expr, "texture", texture)
        try:
            tex_expr.set_editor_property("texture", texture)
        except Exception:
            pass
        unreal.MaterialEditingLibrary.connect_material_expressions(custom, "", tex_expr, "UVs")
        unreal.MaterialEditingLibrary.connect_material_property(
            tex_expr, "RGB", unreal.MaterialProperty.MP_EMISSIVE_COLOR
        )
        try:
            unreal.MaterialEditingLibrary.layout_material_expressions(mat)
        except Exception:
            pass
        unreal.MaterialEditingLibrary.recompile_material(mat)
    except Exception as exc:
        print("SKY MAT graph fail", exc)
    try:
        unreal.EditorAssetLibrary.save_asset(path)
    except Exception:
        pass
    print("SKY MAT", path)
    return mat


def _import_map_sky(job: dict):
    sky = job.get("sky") or {}
    dest = job.get("dest") or "/Game/MOHAA/maps"
    cube = None
    tex = None
    dds = sky.get("cubemap_dds") or ""
    if dds:
        cube = _import_file(dds, dest, "TC_MOHAA_Sky")
        if cube is not None:
            print("SKY CUBE", cube.get_path_name())
    eq = sky.get("equirect") or ""
    if eq:
        tex = _import_file(eq, dest, "T_MOHAA_SkyEquirect")
        if tex is not None:
            _set(tex, "srgb", True)
            try:
                unreal.EditorAssetLibrary.save_asset(tex.get_path_name().split(".")[0])
            except Exception:
                pass
            print("SKY EQUIRECT", tex.get_path_name())
    mat = _make_sky_material(dest, tex)
    return cube, mat


def _hide_sky_mesh_slots(mesh) -> None:
    """Drop leftover sky / magenta hull slots if they survived the OBJ skip."""
    try:
        slots = list(mesh.get_editor_property("static_materials") or [])
    except Exception:
        return
    n = 0
    for i, slot in enumerate(slots):
        name = ""
        try:
            mat = getattr(slot, "material_interface", None)
            slot_name = str(getattr(slot, "material_slot_name", "") or "")
            mat_name = mat.get_name() if mat is not None else ""
            name = (slot_name + " " + mat_name).lower()
        except Exception:
            continue
        if "sky" not in name and "mohday" not in name:
            continue
        try:
            mesh.set_material(i, None)
            n += 1
        except Exception:
            pass
    if n:
        print("HID sky slots", n)


def _spawn_sky_sphere(sub, map_actor, mat) -> None:
    old = _actor_named(sub, "MOHAA_SkySphere")
    if old is not None:
        try:
            sub.destroy_actor(old)
        except Exception:
            pass
    if mat is None:
        print("SKY SPHERE skipped (no material)")
        return
    sphere = None
    for path in ("/Engine/BasicShapes/Sphere", "/Engine/EngineMeshes/Sphere"):
        try:
            if unreal.EditorAssetLibrary.does_asset_exist(path):
                sphere = unreal.EditorAssetLibrary.load_asset(path)
                if sphere:
                    break
        except Exception:
            pass
    if sphere is None:
        print("SKY SPHERE skipped (no engine sphere)")
        return
    origin = unreal.Vector(0, 0, 0)
    scale = 250.0
    try:
        o, extent = map_actor.get_actor_bounds(False)
        origin = unreal.Vector(float(o.x), float(o.y), float(o.z))
        span = max(abs(float(extent.x)), abs(float(extent.y)), abs(float(extent.z)))
        scale = max(250.0, (span * 2.6) / 50.0)
    except Exception:
        pass
    actor = sub.spawn_actor_from_class(unreal.StaticMeshActor, origin, unreal.Rotator(0, 0, 0))
    if not actor:
        print("SKY SPHERE spawn fail")
        return
    actor.set_actor_label("MOHAA_SkySphere")
    try:
        actor.set_actor_scale3d(unreal.Vector(scale, scale, scale))
    except Exception:
        pass
    smc = actor.static_mesh_component
    smc.set_static_mesh(sphere)
    try:
        smc.set_material(0, mat)
    except Exception:
        pass
    none_col = getattr(unreal.CollisionEnabled, "NO_COLLISION", None) or getattr(
        unreal.CollisionEnabled, "NoCollision", None
    )
    _set(smc, "cast_shadow", False)
    _set(smc, "cast_static_shadow", False)
    _set(smc, "cast_dynamic_shadow", False)
    _set(smc, "affect_dynamic_indirect_lighting", False)
    if none_col is not None:
        _set(smc, "collision_enabled", none_col)
    try:
        actor.set_actor_enable_collision(False)
        actor.set_actor_hidden_in_game(False)
        actor.set_is_temporarily_hidden_in_editor(False)
    except Exception:
        pass
    movable = getattr(unreal.ComponentMobility, "MOVABLE", None)
    if movable is not None:
        _mobility(actor, movable)
    print("SPAWNED MOHAA_SkySphere scale", round(scale, 2))


def _ensure_basic_lighting(sub, cubemap=None) -> None:
    """Sun + SkyAtmosphere. SkyLight realtime capture without a valid sky is black in UE5.8."""
    movable = getattr(unreal.ComponentMobility, "MOVABLE", None)
    try:
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        ws = world.get_world_settings() if world else None
        _set(ws, "force_no_precomputed_lighting", True)
        _set(ws, "b_force_no_precomputed_lighting", True)
    except Exception:
        pass

    sun = _actor_named(sub, "MOHAA_Sun")
    if sun is None:
        sun = sub.spawn_actor_from_class(
            unreal.DirectionalLight, unreal.Vector(0, 0, 8000), unreal.Rotator(pitch=-46.0, yaw=35.0, roll=0.0)
        )
        if sun:
            sun.set_actor_label("MOHAA_Sun")
    extra_suns = 0
    try:
        for old in list(sub.get_all_level_actors() or []):
            if not isinstance(old, unreal.DirectionalLight):
                continue
            if old.get_actor_label() == "MOHAA_Sun":
                continue
            extra_suns += 1
            sub.destroy_actor(old)
        if extra_suns:
            print("REMOVED extra directional lights", extra_suns)
    except Exception as exc:
        print("sun dedupe skip", exc)
    if sun:
        try:
            sun.set_actor_hidden_in_game(False)
            sun.set_is_temporarily_hidden_in_editor(False)
        except Exception:
            pass
        if movable is not None:
            _mobility(sun, movable)
        try:
            lc = _light_comp(sun)
            unitless = getattr(unreal.LightUnits, "UNITLESS", None)
            lux = getattr(unreal.LightUnits, "LUX", None)
            # Classic unitless 10-15 is visible in Lit. Lux 10 is also valid but
            # auto-exposure + a black SkyLight cubemap still crushes the frame.
            if unitless is not None and _set(lc, "intensity_units", unitless):
                _set(lc, "intensity", 15.0)
            elif lux is not None and _set(lc, "intensity_units", lux):
                _set(lc, "intensity", 10.0)
            else:
                _set(lc, "intensity", 12.0)
            _set(lc, "atmosphere_sun_light", True)
            _set(lc, "cast_shadows", False)
            _set(lc, "affects_world", True)
            _set(lc, "visible", True)
            _set(lc, "hidden_in_game", False)
            try:
                lc.set_editor_property("light_color", unreal.Color(255, 244, 214, 255))
            except Exception:
                pass
        except Exception:
            pass
        try:
            sun.set_actor_rotation(unreal.Rotator(pitch=-46.0, yaw=35.0, roll=0.0), False)
        except Exception:
            pass

    atm_cls = getattr(unreal, "SkyAtmosphere", None)
    atm = _actor_named(sub, "MOHAA_SkyAtmosphere")
    if atm_cls is not None and atm is None:
        atm = sub.spawn_actor_from_class(atm_cls, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        if atm:
            atm.set_actor_label("MOHAA_SkyAtmosphere")
            print("SPAWNED MOHAA_SkyAtmosphere")
    if atm:
        try:
            atm.set_actor_hidden_in_game(False)
            atm.set_is_temporarily_hidden_in_editor(False)
        except Exception:
            pass

    fog_cls = getattr(unreal, "ExponentialHeightFog", None)
    if fog_cls is not None and _actor_named(sub, "MOHAA_Fog") is None:
        fog = sub.spawn_actor_from_class(fog_cls, unreal.Vector(0, 0, 200), unreal.Rotator(0, 0, 0))
        if fog:
            fog.set_actor_label("MOHAA_Fog")
            try:
                fc = fog.component if hasattr(fog, "component") else fog.root_component
                _set(fc, "fog_density", 0.012)
                _set(fc, "fog_height_falloff", 0.2)
            except Exception:
                pass

    # A leftover SkyLight with realtime capture / a black cubemap blacks Lit.
    sky = _actor_named(sub, "MOHAA_SkyLight")
    if sky is not None:
        try:
            sc = _light_comp(sky)
            _set(sc, "real_time_capture", False)
            _set(sc, "b_real_time_capture", False)
            sub.destroy_actor(sky)
            print("REMOVED stale MOHAA_SkyLight")
            sky = None
        except Exception as exc:
            print("skylight destroy skip", visc if False else exc)
    cube = cubemap
    if cube is None:
        for path in (
            "/Engine/EngineResources/DefaultTextureCube",
            "/Engine/EngineSky/T_Sky_Blue",
        ):
            try:
                if unreal.EditorAssetLibrary.does_asset_exist(path):
                    cube = unreal.EditorAssetLibrary.load_asset(path)
                    if cube:
                        break
            except Exception:
                pass
    specified = getattr(unreal.SkyLightSourceType, "SLS_SPECIFIED_CUBEMAP", None)
    if cube is not None and specified is not None:
        sky = sub.spawn_actor_from_class(
            unreal.SkyLight, unreal.Vector(0, 0, 12000), unreal.Rotator(0, 0, 0)
        )
        if sky:
            sky.set_actor_label("MOHAA_SkyLight")
            if movable is not None:
                _mobility(sky, movable)
            sc = _light_comp(sky)
            _set(sc, "real_time_capture", False)
            _set(sc, "source_type", specified)
            _set(sc, "cubemap", cube)
            _set(sc, "intensity", 1.0)
            _set(sc, "lower_hemisphere_is_black", False)
            _set(sc, "affects_world", True)
            _set(sc, "visible", True)
            try:
                sc.set_editor_property(
                    "lower_hemisphere_color", unreal.LinearColor(0.55, 0.58, 0.65, 1.0)
                )
            except Exception:
                pass
            print("SKYLIGHT cubemap realtime=off")
    else:
        print("SKYLIGHT skipped (no cubemap; Directional+Atmosphere only)")

    pp_cls = getattr(unreal, "PostProcessVolume", None)
    pp = _actor_named(sub, "MOHAA_PostProcess")
    if pp_cls is not None and pp is None:
        pp = sub.spawn_actor_from_class(pp_cls, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        if pp:
            pp.set_actor_label("MOHAA_PostProcess")
    if pp:
        _set(pp, "unbound", True)
        _set(pp, "b_unbound", True)
        _set(pp, "priority", 10.0)
        try:
            settings = pp.get_editor_property("settings")
            _set(settings, "override_auto_exposure_min_brightness", True)
            _set(settings, "auto_exposure_min_brightness", 1.0)
            _set(settings, "override_auto_exposure_max_brightness", True)
            _set(settings, "auto_exposure_max_brightness", 1.5)
            _set(settings, "override_auto_exposure_bias", True)
            _set(settings, "auto_exposure_bias", 0.5)
            _set(settings, "override_auto_exposure_enable", True)
            _set(settings, "auto_exposure_enable", False)
            pp.set_editor_property("settings", settings)
        except Exception:
            pass

    try:
        world = unreal.EditorLevelLibrary.get_editor_world()
        for line in (
            "viewmode lit",
            "r.Unlit 0",
            "ShowFlag.Lighting 1",
            "ShowFlag.StaticMeshes 1",
            "ShowFlag.Atmosphere 1",
            "r.SkyAtmosphere 1",
            "r.Shadow.Virtual.Enable 0",
        ):
            unreal.SystemLibrary.execute_console_command(world, line)
    except Exception:
        pass
    realtime = False
    if sky is not None:
        try:
            realtime = bool(_light_comp(sky).get_editor_property("real_time_capture"))
        except Exception:
            pass
    print(
        "LIGHTS sun",
        bool(sun),
        "sky",
        bool(sky),
        "atmosphere",
        bool(_actor_named(sub, "MOHAA_SkyAtmosphere")),
        "skylight_realtime",
        realtime,
        "world",
        _world_name(),
    )


def _default_map_material(dest: str):
    name = "M_MOHAA_Untextured"
    path = dest + "/" + name
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            return unreal.EditorAssetLibrary.load_asset(path)
    except Exception:
        pass
    try:
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name, dest, unreal.Material, unreal.MaterialFactoryNew()
        )
    except Exception:
        mat = None
    if mat is None:
        try:
            return unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/BasicShapeMaterial")
        except Exception:
            return None
    try:
        _set(mat, "two_sided", True)
        const = unreal.MaterialEditingLibrary.create_material_expression(
            mat, unreal.MaterialExpressionConstant3Vector, -300, 0
        )
        _set(const, "constant", unreal.LinearColor(0.45, 0.45, 0.48, 1.0))
        unreal.MaterialEditingLibrary.connect_material_property(
            const, "", unreal.MaterialProperty.MP_BASE_COLOR
        )
        unreal.MaterialEditingLibrary.recompile_material(mat)
        unreal.EditorAssetLibrary.save_asset(path)
    except Exception as exc:
        print("default mat skip", exc)
    return mat


def _apply_untextured_material(mesh, dest: str) -> None:
    mat = _default_map_material(dest)
    if mesh is None or mat is None:
        return
    try:
        slots = list(mesh.get_editor_property("static_materials") or [])
    except Exception:
        return
    n = 0
    for i, slot in enumerate(slots):
        try:
            slot.set_editor_property("material_interface", mat)
            slots[i] = slot
            n += 1
        except Exception:
            pass
    try:
        mesh.set_editor_property("static_materials", slots)
    except Exception:
        pass
    print("UNTEXTURED slots", n)


def _import_one_static(fbx: str, dest: str, name: str, with_textures: bool = True):
    if not fbx or not Path(fbx).is_file():
        print("FURNITURE FBX missing", fbx)
        return None
    unreal.EditorAssetLibrary.make_directory(dest)
    task = unreal.AssetImportTask()
    task.filename = fbx
    task.destination_path = dest
    task.destination_name = name
    task.automated = True
    task.save = True
    task.replace_existing = True
    options = unreal.FbxImportUI()
    options.import_mesh = True
    options.import_materials = True
    options.import_textures = bool(with_textures)
    options.automated_import_should_detect_type = False
    options.import_animations = False
    options.import_as_skeletal = False
    options.mesh_type_to_import = unreal.FBXImportType.FBXIT_STATIC_MESH
    smd = options.static_mesh_import_data
    smd.combine_meshes = True
    smd.auto_generate_collision = True
    smd.import_uniform_scale = 1.0
    smd.convert_scene = True
    _set(smd, "convert_scene_unit", False)
    smd.force_front_x_axis = False
    _set(smd, "transform_vertex_to_absolute", True)
    task.options = options
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    path = dest + "/" + name
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.EditorAssetLibrary.load_asset(path)
    for p in task.imported_object_paths or []:
        asset = unreal.EditorAssetLibrary.load_asset(p)
        if asset is not None:
            return asset
    print("FURNITURE IMPORT FAIL", name)
    return None


def _clear_furniture_actors(sub) -> None:
    try:
        for old in list(sub.get_all_level_actors() or []):
            label = old.get_actor_label() or ""
            if label.startswith("MOHAA_prop_"):
                sub.destroy_actor(old)
    except Exception as exc:
        print("furniture destroy skip", exc)


def _spawn_furniture(job: dict, sub) -> None:
    _clear_furniture_actors(sub)
    items = job.get("furniture") or []
    spawned = 0
    for item in items:
        mesh = _import_one_static(
            item.get("fbx") or "",
            item.get("dest") or "/Game/MOHAA/props",
            item.get("name") or "SM_prop",
            with_textures=True,
        )
        if mesh is None:
            continue
        stem = str(item.get("name") or "prop")
        for i, spawn in enumerate(item.get("spawns") or []):
            loc = spawn.get("location") or [0, 0, 0]
            rot = spawn.get("rotation") or [0, 0, 0]
            scale = float(spawn.get("scale") or 1.0)
            actor = sub.spawn_actor_from_class(
                unreal.StaticMeshActor,
                unreal.Vector(float(loc[0]), float(loc[1]), float(loc[2])),
                unreal.Rotator(pitch=float(rot[0]), yaw=float(rot[1]), roll=float(rot[2])),
            )
            if not actor:
                continue
            actor.set_actor_label("MOHAA_prop_%s_%d" % (stem, i))
            try:
                actor.set_folder_path("MOHAA/Furniture")
            except Exception:
                pass
            try:
                actor.static_mesh_component.set_static_mesh(mesh)
                if abs(scale - 1.0) > 0.001:
                    actor.set_actor_scale3d(unreal.Vector(scale, scale, scale))
            except Exception as exc:
                print("furniture assign skip", exc)
            spawned += 1
    print("FURNITURE spawned", spawned, "meshes", len(items))


def _prepare_map_materials(mesh) -> None:
    """Keep Default Lit (textures on BaseColor) but two-sided so interior BSP faces show."""
    try:
        slots = list(mesh.get_editor_property("static_materials") or [])
    except Exception:
        return
    n = 0
    for slot in slots:
        mat = getattr(slot, "material_interface", None)
        if mat is None:
            continue
        if _set(mat, "two_sided", True) or _set(mat, "is_two_sided", True):
            n += 1
        try:
            overrides = mat.get_editor_property("base_property_overrides")
            if overrides is None:
                overrides = unreal.MaterialInstanceBasePropertyOverrides()
            if _set(overrides, "override_two_sided", True) or _set(overrides, "b_override_two_sided", True):
                _set(overrides, "two_sided", True)
                mat.set_editor_property("base_property_overrides", overrides)
                n += 1
        except Exception:
            pass
        try:
            unreal.EditorAssetLibrary.save_asset(mat.get_path_name().split(".")[0])
        except Exception:
            pass
    print("MAP MATS two_sided", n)


def _focus_actor(actor) -> None:
    try:
        origin, extent = actor.get_actor_bounds(False)
        ox, oy, oz = float(origin.x), float(origin.y), float(origin.z)
        ex = max(abs(float(extent.x)), 100.0)
        ey = max(abs(float(extent.y)), 100.0)
        ez = max(abs(float(extent.z)), 100.0)
        dist = max(ex, ey, ez) * 1.35
        loc = unreal.Vector(ox + dist, oy + dist, oz + ez * 0.55)
        rot = unreal.Rotator(pitch=-22.0, yaw=-135.0, roll=0.0)
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        ues.set_level_viewport_camera_info(loc, rot)
        print(
            "FOCUS outside origin",
            round(ox, 1),
            round(oy, 1),
            round(oz, 1),
            "extent",
            round(ex, 1),
            round(ey, 1),
            round(ez, 1),
            "cam",
            round(float(loc.x), 1),
            round(float(loc.y), 1),
            round(float(loc.z), 1),
        )
    except Exception as exc:
        print("focus skip", exc)
        try:
            _focus_mesh(actor.static_mesh_component.static_mesh)
        except Exception:
            pass


def _focus_mesh(mesh) -> None:
    if mesh is None:
        return
    try:
        b = mesh.get_bounds()
        ox, oy, oz = float(b.origin.x), float(b.origin.y), float(b.origin.z)
        ex = max(float(b.box_extent.x), 100.0)
        ey = max(float(b.box_extent.y), 100.0)
        ez = max(float(b.box_extent.z), 100.0)
        dist = max(ex, ey, ez) * 1.35
        loc = unreal.Vector(ox + dist, oy + dist, oz + ez * 0.55)
        rot = unreal.Rotator(pitch=-22.0, yaw=-135.0, roll=0.0)
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        ues.set_level_viewport_camera_info(loc, rot)
    except Exception as visc:
        print("focus skip", visc)


def _spawn_map(job: dict, mesh, name: str) -> None:
    level_path = _open_map_level(job)
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    try:
        for old in list(sub.get_all_level_actors() or []):
            if old.get_actor_label() in (name, "MOHAA_SkySphere"):
                sub.destroy_actor(old)
    except Exception as exc:
        print("destroy skip", exc)
    actor = sub.spawn_actor_from_class(
        unreal.StaticMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0)
    )
    if not actor:
        print("SPAWN FAIL", name)
        return
    actor.set_actor_label(name)
    actor.set_actor_location(unreal.Vector(0, 0, 0), False, False)
    actor.set_actor_rotation(unreal.Rotator(0, 0, 0), False)
    actor.set_actor_scale3d(unreal.Vector(1.0, 1.0, 1.0))
    actor.static_mesh_component.set_static_mesh(mesh)
    try:
        _set(actor.static_mesh_component, "cast_shadow", False)
        actor.set_actor_hidden_in_game(False)
        actor.set_is_temporarily_hidden_in_editor(False)
    except Exception:
        pass
    print("SPAWNED", name, "WORLD", _world_name())
    with_textures = bool(job.get("with_textures", True))
    if with_textures:
        _prepare_map_materials(mesh)
        _hide_sky_mesh_slots(mesh)
        cube, sky_mat = _import_map_sky(job)
        _ensure_basic_lighting(sub, cubemap=cube)
        _spawn_sky_sphere(sub, actor, sky_mat)
    else:
        _apply_untextured_material(mesh, job["dest"])
        _hide_sky_mesh_slots(mesh)
        _ensure_basic_lighting(sub, cubemap=None)
    _spawn_furniture(job, sub)
    try:
        t = actor.get_actor_transform()
        loc = t.translation
        rot = actor.get_actor_rotation()
        scl = actor.get_actor_scale3d()
        print(
            "MAP actor loc",
            round(float(loc.x), 3),
            round(float(loc.y), 3),
            round(float(loc.z), 3),
            "rot",
            round(float(rot.pitch), 2),
            round(float(rot.yaw), 2),
            round(float(rot.roll), 2),
            "scale",
            round(float(scl.x), 4),
            round(float(scl.y), 4),
            round(float(scl.z), 4),
        )
    except Exception as exc:
        print("MAP actor xform skip", exc)
    try:
        origin, extent = actor.get_actor_bounds(False)
        print(
            "ACTOR bounds origin_cm",
            round(float(origin.x), 1),
            round(float(origin.y), 1),
            round(float(origin.z), 1),
            "extent_cm",
            round(float(extent.x), 1),
            round(float(extent.y), 1),
            round(float(extent.z), 1),
        )
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
        sample = None
        for item in job.get("furniture") or []:
            name = str(item.get("name") or "")
            if "table" in name.lower() or "chair" in name.lower():
                spawns = item.get("spawns") or []
                if spawns:
                    sample = (name, spawns[0].get("location") or [0, 0, 0])
                    break
        if sample:
            sl = sample[1]
            inside = mn[0] <= sl[0] <= mx[0] and mn[1] <= sl[1] <= mx[1] and mn[2] <= sl[2] <= mx[2]
            print(
                "FURNITURE sample",
                sample[0],
                "loc",
                round(float(sl[0]), 1),
                round(float(sl[1]), 1),
                round(float(sl[2]), 1),
                "inside_map_aabb",
                inside,
                "aabb",
                [round(v, 1) for v in mn],
                [round(v, 1) for v in mx],
            )
        start = unreal.Vector(float(origin.x), float(origin.y), float(origin.z - abs(extent.z)) + 120.0)
        ps = _actor_named(sub, name + "_PlayerStart")
        if ps is None:
            ps = sub.spawn_actor_from_class(unreal.PlayerStart, start, unreal.Rotator(0, 0, 0))
            if ps:
                ps.set_actor_label(name + "_PlayerStart")
        else:
            ps.set_actor_location(start, False, False)
    except Exception as exc:
        print("player start skip", exc)
        _focus_mesh(mesh)
    else:
        _focus_actor(actor)
    try:
        labels = []
        for a in list(sub.get_all_level_actors() or []):
            labels.append(a.get_actor_label() + ":" + a.get_class().get_name())
        print("ACTORS", labels)
        sun = _actor_named(sub, "MOHAA_Sun")
        sky = _actor_named(sub, "MOHAA_SkyLight")
        if sun is not None:
            lc = _light_comp(sun)
            print(
                "SUN intensity",
                None if lc is None else lc.get_editor_property("intensity"),
            )
        print("SKY", "present" if sky else "none")
    except Exception as visc:
        print("actor dump skip", visc)
    try:
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
    except Exception:
        pass
    print("LEVEL", level_path or _world_path(job), "WORLD", _world_name())


def _spawn(mesh, name: str, skeletal: bool) -> None:
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    try:
        for old in list(sub.get_all_level_actors() or []):
            if old.get_actor_label() == name:
                sub.destroy_actor(old)
    except Exception as exc:
        print("destroy skip", exc)
    actor_class = unreal.SkeletalMeshActor if skeletal else unreal.StaticMeshActor
    actor = sub.spawn_actor_from_class(
        actor_class, unreal.Vector(0, 0, 80), unreal.Rotator(0, 0, 0)
    )
    if not actor:
        return
    actor.set_actor_label(name)
    if skeletal:
        comp = actor.skeletal_mesh_component
        try:
            if hasattr(comp, "set_skinned_asset_and_update"):
                comp.set_skinned_asset_and_update(mesh)
            else:
                comp.set_skeletal_mesh_asset(mesh)
        except Exception:
            try:
                comp.set_editor_property("skeletal_mesh", mesh)
            except Exception:
                pass
        try:
            for i in range(min(3, int(comp.get_num_bones()))):
                bname = str(comp.get_bone_name(i))
                xf = comp.get_socket_transform(bname, unreal.RelativeTransformSpace.RTS_PARENT)
                print(
                    "bind",
                    bname,
                    "T",
                    round(float(xf.translation.x), 2),
                    round(float(xf.translation.y), 2),
                    round(float(xf.translation.z), 2),
                    "S",
                    round(float(xf.scale3d.x), 3),
                    round(float(xf.scale3d.y), 3),
                    round(float(xf.scale3d.z), 3),
                )
        except Exception as exc:
            print("bind print", exc)
    else:
        actor.static_mesh_component.set_static_mesh(mesh)
    print("SPAWNED", name)
    try:
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
    except Exception:
        pass


def _set_anim_rate(obj, fps) -> None:
    fps_i = max(1, int(round(float(fps or 30.0))))
    _set(obj, "use_default_sample_rate", False)
    _set(obj, "custom_sample_rate", fps_i)
    _set(obj, "snap_to_closest_frame_boundary", True)
    _set(obj, "b_snap_to_closest_frame_boundary", True)
    _set(obj, "custom_bone_animation_sample_rate", float(fps_i))


def _import_anims(job: dict, mesh) -> None:
    dest = job["dest"]
    name = job["name"]
    anim_files = job.get("anim_files") or []
    if not job["skeletal"] or not anim_files:
        return
    skel_asset = unreal.EditorAssetLibrary.load_asset(dest + "/" + name + "_Skeleton")
    if skel_asset is None and mesh:
        try:
            skel_asset = mesh.get_editor_property("skeleton")
        except Exception:
            skel_asset = None
    ok = 0
    for item in anim_files:
        atask = unreal.AssetImportTask()
        atask.filename = item["fbx"]
        atask.destination_path = dest
        atask.destination_name = item["name"]
        atask.automated = True
        atask.save = True
        atask.replace_existing = True
        aopts = unreal.FbxImportUI()
        aopts.import_mesh = False
        aopts.import_as_skeletal = True
        aopts.import_animations = True
        aopts.import_materials = False
        aopts.import_textures = False
        aopts.automated_import_should_detect_type = False
        _set(aopts, "create_physics_asset", False)
        try:
            aopts.mesh_type_to_import = unreal.FBXImportType.FBXIT_ANIMATION
        except Exception:
            aopts.mesh_type_to_import = unreal.FBXImportType.FBXIT_SKELETAL_MESH
        _set(aopts, "import_only_animations", True)
        if skel_asset is not None:
            try:
                aopts.skeleton = skel_asset
            except Exception:
                pass
        fps = item.get("fps") or 30.0
        try:
            adata = aopts.anim_sequence_import_data
            adata.convert_scene = False
            _set(adata, "convert_scene_unit", False)
            adata.force_front_x_axis = False
            adata.import_uniform_scale = 1.0
            _set_anim_rate(adata, fps)
            _set(adata, "use_t0_as_ref_pose", False)
            _set(adata, "update_skeleton_reference_pose", False)
            _set(adata, "preserve_local_transform", False)
        except Exception:
            try:
                adata = aopts.skeletal_mesh_import_data
                adata.convert_scene = False
                _set(adata, "convert_scene_unit", False)
                adata.force_front_x_axis = False
                adata.import_uniform_scale = 1.0
                _set_anim_rate(adata, fps)
            except Exception:
                pass
        _set_anim_rate(aopts, fps)
        atask.options = aopts
        try:
            unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([atask])
            ok += 1
        except Exception as exc:
            print("ANIM IMPORT FAIL", item["name"], exc)
    print("ANIMS", ok, "/", len(anim_files))


def _make_ready(job: dict, mesh_path: str) -> None:
    if not job["skeletal"]:
        return
    try:
        import importlib
        import ue_character_ready

        importlib.reload(ue_character_ready)
        ue_character_ready.make_ready(
            mesh_path,
            job["dest"],
            job["name"],
            [item["name"] for item in (job.get("anim_files") or [])],
        )
    except Exception as exc:
        print("CHARACTER READY FAILED", exc)


def main() -> None:
    job = _load_job()
    dest = job["dest"]
    name = job["name"]
    skeletal = bool(job["skeletal"])
    unreal.EditorAssetLibrary.make_directory(dest)
    _delete_existing(
        dest,
        name,
        skeletal,
        job.get("anim_files") or [],
        wipe_folder_mats=_is_map(job) and not skeletal,
    )
    imported = _import_mesh(job)
    print("IMPORTED", imported)

    import importlib
    import fix_mohaa_opaque

    importlib.reload(fix_mohaa_opaque)
    from fix_mohaa_opaque import flatten_folder_textures, make_mesh_opaque

    flatten_folder_textures(dest)
    mesh, mesh_path = _resolve_mesh(job, imported)
    if mesh is not None and not skeletal:
        _attach_lods(mesh, mesh_path, job.get("lod_files") or [], job.get("screens") or [])
    if mesh is not None:
        try:
            b = mesh.get_bounds()
            height = round(2.0 * float(b.box_extent.z), 2)
            print(
                "MESH height_cm",
                height,
                "extent",
                round(float(b.box_extent.x), 2),
                round(float(b.box_extent.y), 2),
                round(float(b.box_extent.z), 2),
            )
            if skeletal and height > 400.0:
                print("MESH SCALE WARNING height_cm", height, "expected ~180 (S=1, not 100)")
        except Exception:
            pass
        try:
            print(make_mesh_opaque(mesh, dest))
        except Exception as exc:
            print("OPAQUE FIX FAILED", exc)
        if _is_map(job) and not skeletal:
            _spawn_map(job, mesh, name)
        else:
            _spawn(mesh, name, skeletal)
    _import_anims(job, mesh)
    _make_ready(job, mesh_path)
    for folder in ("/Game/MOHAA", "/Game/Characters"):
        try:
            unreal.EditorAssetLibrary.save_directory(folder, only_if_is_dirty=False, recursive=True)
        except Exception:
            pass
    print("DONE")


main()
