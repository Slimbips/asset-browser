"""Dump SM_flowerplate vs SM_simplechair vertex normals and actor basis."""
from __future__ import annotations

import unreal


def _mesh_nz(path: str) -> None:
    mesh = unreal.EditorAssetLibrary.load_asset(path)
    if mesh is None:
        print("NO", path)
        return
    b = mesh.get_bounds()
    desc = mesh.get_num_triangles(0) if hasattr(mesh, "get_num_triangles") else "?"
    print(
        "MESH",
        mesh.get_name(),
        "tris",
        desc,
        "minz",
        round(float(b.origin.z) - float(b.box_extent.z), 3),
        "maxz",
        round(float(b.origin.z) + float(b.box_extent.z), 3),
    )
    try:
        sml = unreal.EditorStaticMeshLibrary
        verts = sml.get_number_verts(mesh, 0)
        print("  nverts", verts)
    except Exception as exc:
        print("  nverts skip", exc)
        verts = 0
    nzs = []
    try:
        # LOD0 raw vertices via mesh description if available.
        md = unreal.StaticMeshEditorSubsystem
    except Exception:
        md = None
    try:
        sms = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
        dat = sms.get_lod_screen_sizes(mesh)
        print("  lod_screens", dat)
    except Exception as exc:
        print("  lod skip", exc)
    # Sample section tangents via Nanite/render data is not exposed; use
    # a temp actor and component bounds + a few transformed axes.
    print("  bounds origin", [round(float(v), 3) for v in (b.origin.x, b.origin.y, b.origin.z)])


def _actor_basis(label_sub: str) -> None:
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in list(sub.get_all_level_actors() or []):
        label = actor.get_actor_label() or ""
        if label_sub not in label.lower():
            continue
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        q = rot.quaternion()
        # Unreal quaternion rotates local axes to world.
        x = q.rotate_vector(unreal.Vector(1, 0, 0))
        y = q.rotate_vector(unreal.Vector(0, 1, 0))
        z = q.rotate_vector(unreal.Vector(0, 0, 1))
        origin, extent = actor.get_actor_bounds(False)
        print(
            "ACTOR",
            label,
            "locZ",
            round(float(loc.z), 3),
            "P",
            round(float(rot.pitch), 2),
            "Y",
            round(float(rot.yaw), 2),
            "R",
            round(float(rot.roll), 2),
            "axis+Z",
            round(float(z.x), 3),
            round(float(z.y), 3),
            round(float(z.z), 3),
            "visZ",
            round(float(origin.z) - float(extent.z), 2),
            round(float(origin.z) + float(extent.z), 2),
        )
        try:
            mesh = actor.static_mesh_component.static_mesh
            mat = actor.static_mesh_component.get_material(0)
            two = None
            if mat is not None:
                try:
                    two = mat.get_editor_property("two_sided")
                except Exception:
                    try:
                        two = mat.get_editor_property("is_two_sided")
                    except Exception:
                        two = "noprop"
            print("  mesh", mesh.get_name() if mesh else None, "mat", mat.get_name() if mat else None, "two_sided", two)
        except Exception as exc:
            print("  mat skip", exc)
        return


def main() -> None:
    print("LEVEL", unreal.EditorLevelLibrary.get_editor_world().get_name())
    for p in (
        "/Game/MOHAA/props/SM_flowerplate",
        "/Game/MOHAA/props/SM_servingplate",
        "/Game/MOHAA/props/SM_dish",
        "/Game/MOHAA/props/SM_simplechair",
        "/Game/MOHAA/props/SM_banquet_table",
    ):
        _mesh_nz(p)
    _actor_basis("flowerplate_0")
    _actor_basis("simplechair_0")
    _actor_basis("banquet_table_0")
    # Extract a few vertex positions from the static mesh LOD via mesh description.
    try:
        mesh = unreal.EditorAssetLibrary.load_asset("/Game/MOHAA/props/SM_flowerplate")
        sms = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
        # get_lod0 vertices through python MeshDescription if present
        desc = None
        for name in ("get_mesh_description", "get_lod_mesh_description"):
            fn = getattr(sms, name, None) or getattr(mesh, name, None)
            if fn:
                try:
                    desc = fn(mesh, 0) if fn is getattr(sms, name, None) else fn(0)
                    print("DESC via", name, type(desc))
                    break
                except Exception as exc:
                    print("DESC", name, exc)
        if desc is None:
            try:
                desc = mesh.get_mesh_description(0)
                print("DESC mesh.get_mesh_description", type(desc))
            except Exception as exc:
                print("DESC mesh method", exc)
    except Exception as exc:
        print("DESC fail", exc)


main()
