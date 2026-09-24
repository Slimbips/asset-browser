"""Keep Interchange FBX materials (the first-import look).

Only: flatten leftover TGA alpha, force Opaque blend, disable Nanite.
Do not replace slots with M_*_opaque graphs.
"""
from __future__ import annotations

import unreal


def _opaque_enum():
    return getattr(unreal.BlendMode, "OPAQUE", None) or getattr(unreal.BlendMode, "BLEND_OPAQUE", None)


def _save(path_or_asset):
    if isinstance(path_or_asset, str):
        unreal.EditorAssetLibrary.save_asset(path_or_asset)
        return
    path = path_or_asset.get_path_name().split(".")[0]
    unreal.EditorAssetLibrary.save_asset(path)


def flatten_texture(tex: unreal.Texture2D) -> None:
    for prop, value in (
        ("compression_no_alpha", True),
        ("compress_no_alpha", True),
        ("srgb", True),
        ("alpha_coverage_threshold", 0.0),
    ):
        try:
            tex.set_editor_property(prop, value)
        except Exception:
            pass
    try:
        tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_DEFAULT)
    except Exception:
        pass
    _save(tex)


def force_material_opaque(mat) -> None:
    """Opaque blend only — leave Interchange shading / DiffuseColorMap alone."""
    opaque = _opaque_enum()
    if opaque is None or mat is None:
        return
    if isinstance(mat, unreal.Material):
        try:
            mat.set_editor_property("blend_mode", opaque)
        except Exception:
            pass
        _save(mat)
        return
    mi_types = tuple(
        t
        for t in (
            getattr(unreal, "MaterialInstance", None),
            getattr(unreal, "MaterialInstanceConstant", None),
        )
        if t
    )
    if mi_types and isinstance(mat, mi_types):
        try:
            overrides = unreal.MaterialInstanceBasePropertyOverrides()
            for prop, value in (
                ("b_override_blend_mode", True),
                ("override_blend_mode", True),
                ("blend_mode", opaque),
            ):
                try:
                    overrides.set_editor_property(prop, value)
                except Exception:
                    pass
            mat.set_editor_property("base_property_overrides", overrides)
        except Exception as visc:
            print("MI override failed", visc)
        _save(mat)


def disable_nanite(mesh: unreal.StaticMesh) -> None:
    try:
        settings = mesh.get_editor_property("nanite_settings")
        if settings is not None:
            settings.enabled = False
            mesh.set_editor_property("nanite_settings", settings)
            print("Nanite off")
            return
    except Exception as visc:
        print("nanite_settings skip", visc)
    try:
        sms = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
        ns = unreal.MeshNaniteSettings()
        ns.enabled = False
        sms.set_nanite_settings(mesh, ns)
        print("Nanite off via subsystem")
    except Exception as visc:
        print("nanite subsystem skip", visc)


def _is_engine_tex(tex) -> bool:
    path = str(tex.get_path_name() if tex else "")
    return "/Engine/" in path or "EngineMaterials" in path or "EngineResources" in path


def _texture_from_mic(mat):
    try:
        for item in mat.get_editor_property("texture_parameter_values") or []:
            tex = getattr(item, "parameter_value", None)
            if isinstance(tex, unreal.Texture2D) and not _is_engine_tex(tex):
                return tex
    except Exception:
        pass
    getter = getattr(unreal.MaterialEditingLibrary, "get_material_used_textures", None) or getattr(
        unreal.MaterialEditingLibrary, "get_used_textures", None
    )
    if getter:
        try:
            for tex in getter(mat) or []:
                if isinstance(tex, unreal.Texture2D) and not _is_engine_tex(tex):
                    return tex
        except Exception:
            pass
    return None


def _is_material(asset) -> bool:
    if asset is None:
        return False
    kinds = tuple(
        t
        for t in (
            getattr(unreal, "MaterialInterface", None),
            getattr(unreal, "Material", None),
            getattr(unreal, "MaterialInstance", None),
            getattr(unreal, "MaterialInstanceConstant", None),
        )
        if t
    )
    return isinstance(asset, kinds) if kinds else False


def _original_slot_material(dest: str, slot_name: str):
    dest = dest.rstrip("/")
    names = [slot_name]
    if slot_name:
        names.append("MI_" + slot_name)
        names.append(slot_name + "_Mat")
    for name in names:
        path = dest + "/" + name
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            asset = unreal.EditorAssetLibrary.load_asset(path)
            if _is_material(asset) and "opaque" not in asset.get_name().lower():
                return asset
    return None


def _restore_fbx_material(mesh, index: int, current, slot_name: str, dest: str):
    if current is None:
        orig = _original_slot_material(dest, slot_name)
        if orig is not None:
            mesh.set_material(index, orig)
            return orig
        return None
    if "opaque" not in current.get_name().lower():
        return current
    orig = _original_slot_material(dest, slot_name)
    if orig is not None:
        mesh.set_material(index, orig)
        print("restored FBX mat", orig.get_name(), "slot", slot_name)
        return orig
    print("no FBX mat for slot", slot_name, "kept", current.get_name())
    return current


def _delete_opaque_replacements(dest: str) -> int:
    n = 0
    for p in unreal.EditorAssetLibrary.list_assets(dest, recursive=True, include_folder=False) or []:
        asset = unreal.EditorAssetLibrary.load_asset(p)
        if asset is None:
            continue
        name = asset.get_name()
        if name.startswith("M_") and name.lower().endswith("_opaque"):
            try:
                unreal.EditorAssetLibrary.delete_asset(p.split(".")[0])
                n += 1
                print("deleted", name)
            except Exception as visc:
                print("delete skip", name, visc)
    return n


def make_mesh_opaque(mesh, dest: str) -> dict:
    is_skel = isinstance(mesh, unreal.SkeletalMesh)
    if not is_skel:
        disable_nanite(mesh)
    n = 0
    try:
        prop = "materials" if is_skel else "static_materials"
        slots = list(mesh.get_editor_property(prop) or [])
    except Exception:
        slots = []
    for i, slot in enumerate(slots):
        old = getattr(slot, "material_interface", None)
        slot_name = str(getattr(slot, "material_slot_name", "") or "mat%d" % i)
        mat = _restore_fbx_material(mesh, i, old, slot_name, dest)
        if mat is None:
            continue
        force_material_opaque(mat)
        tex = _texture_from_mic(mat)
        if tex:
            flatten_texture(tex)
            n += 1
    mesh_path = mesh.get_path_name().split(".")[0]
    _save(mesh_path)
    print("FBX mats kept", mesh_path, "textures flattened", n)
    return {"mesh": mesh_path, "slots": n}


def flatten_folder_textures(dest: str) -> int:
    n = 0
    for p in unreal.EditorAssetLibrary.list_assets(dest, recursive=True, include_folder=False) or []:
        try:
            asset = unreal.EditorAssetLibrary.load_asset(p)
        except Exception as visc:
            print("flatten skip", p, visc)
            continue
        if isinstance(asset, unreal.Texture2D):
            flatten_texture(asset)
            n += 1
    print("flattened textures", n, "in", dest)
    return n


def fix_all_mohaa() -> dict:
    fixed = []
    root = "/Game/MOHAA"
    flatten_folder_textures(root)
    for p in unreal.EditorAssetLibrary.list_assets(root, recursive=True, include_folder=False) or []:
        asset = unreal.EditorAssetLibrary.load_asset(p)
        if isinstance(asset, unreal.StaticMesh):
            dest = "/".join(p.split("/")[:-1])
            fixed.append(make_mesh_opaque(asset, dest))
    _delete_opaque_replacements("/Game/MOHAA/weapons")
    _delete_opaque_replacements("/Game/MOHAA/characters")
    unreal.EditorAssetLibrary.save_directory(root, only_if_is_dirty=False, recursive=True)
    print("FIXED", len(fixed), "meshes")
    return {"ok": True, "meshes": fixed}
