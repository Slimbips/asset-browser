"""Check map static meshes still have materials after folder-wipe reimports. No LoadLevel."""
from __future__ import annotations

import unreal

MESHES = (
    "/Game/MOHAA/maps/SM_Remagen",
    "/Game/MOHAA/maps/SM_Stalingrad",
    "/Game/MOHAA/maps/SM_Southern_France",
    "/Game/MOHAA/maps/SM_Algiers",
)


def main() -> None:
    for path in MESHES:
        exists = unreal.EditorAssetLibrary.does_asset_exist(path)
        if not exists:
            print("MISSING", path)
            continue
        mesh = unreal.EditorAssetLibrary.load_asset(path)
        if mesh is None:
            print("LOAD FAIL", path)
            continue
        n = mesh.get_num_sections(0) if hasattr(mesh, "get_num_sections") else -1
        slots = list(mesh.static_materials or [])
        ok = 0
        none = 0
        names = []
        for slot in slots[:8]:
            mat = None
            try:
                mat = slot.get_editor_property("material_interface")
            except Exception:
                mat = getattr(slot, "material_interface", None)
            if mat is None:
                none += 1
                names.append("NONE")
            else:
                ok += 1
                names.append(mat.get_name())
        print(
            "MESH",
            mesh.get_name(),
            "sections",
            n,
            "slots",
            len(slots),
            "ok",
            ok,
            "none",
            none,
            "sample",
            names,
        )


main()
