"""Export live SM verts and actor world AABB for plates vs chair."""
from __future__ import annotations

import os

import unreal

OUT = r"C:\Users\paulh\Desktop\conv\asset-browser\export\Remagen\props\_ue_dump"
STEMS = (
    "/Game/MOHAA/props/SM_flowerplate",
    "/Game/MOHAA/props/SM_servingplate",
    "/Game/MOHAA/props/SM_dish",
    "/Game/MOHAA/props/SM_simplechair",
    "/Game/MOHAA/props/SM_woodchair",
)


def _aabb(tag, xs, ys, zs):
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    dz = max(zs) - min(zs)
    thin = "XYZ"[min(range(3), key=lambda i: (dx, dy, dz)[i])]
    print(
        tag,
        "n",
        len(xs),
        "x",
        round(min(xs), 3),
        round(max(xs), 3),
        "dx",
        round(dx, 3),
        "y",
        round(min(ys), 3),
        round(max(ys), 3),
        "dy",
        round(dy, 3),
        "z",
        round(min(zs), 3),
        round(max(zs), 3),
        "dz",
        round(dz, 3),
        "thin",
        thin,
        "standing" if dz > 0.7 * max(dx, dy) and min(dx, dy) < 0.45 * max(dx, dy, dz) else "flat_or_chunky",
    )


def _mesh_desc_verts(mesh):
    xs, ys, zs = [], [], []
    try:
        desc = mesh.get_mesh_description(0)
    except Exception as exc:
        print("  get_mesh_description", exc)
        desc = None
    if desc is None:
        return xs, ys, zs
    for attr in ("vertex_positions", "get_vertex_positions"):
        fn = getattr(desc, attr, None)
        if fn is None:
            continue
        try:
            pos = fn() if callable(fn) else fn
            print("  desc", attr, type(pos), (len(pos) if hasattr(pos, "__len__") else pos))
        except Exception as exc:
            print("  desc", attr, exc)
    # Iterate VertexArray if present
    for getter in ("get_vertices", "vertices"):
        fn = getattr(desc, getter, None)
        if fn is None:
            continue
        try:
            verts = fn() if callable(fn) else fn
            print("  desc", getter, type(verts), len(verts) if hasattr(verts, "__len__") else "?")
        except Exception as exc:
            print("  desc", getter, exc)
    try:
        n = int(desc.get_num_vertices())
        print("  num_vertices", n)
    except Exception as exc:
        print("  num_vertices", exc)
        n = 0
    # VertexID 0..n-1
    get_pos = getattr(desc, "get_vertex_position", None)
    if get_pos and n:
        for i in range(n):
            try:
                p = get_pos(unreal.VertexID(i))
            except Exception:
                try:
                    p = get_pos(i)
                except Exception:
                    break
            xs.append(float(p.x))
            ys.append(float(p.y))
            zs.append(float(p.z))
        return xs, ys, zs
    return xs, ys, zs


def _export_obj(mesh, dest):
    os.makedirs(OUT, exist_ok=True)
    task = unreal.AssetExportTask()
    task.object = mesh
    task.filename = dest
    task.automated = True
    task.prompt = False
    task.replace_identical = True
    task.use_file_archive = False
    exporters = []
    for name in ("StaticMeshExporterOBJ", "ExporterOBJ", "ObjExporter"):
        cls = getattr(unreal, name, None)
        if cls is not None:
            try:
                exporters.append(cls())
            except Exception:
                pass
    ok = False
    if exporters:
        task.exporter = exporters[0]
        try:
            ok = bool(unreal.Exporter.run_asset_export_task(task))
        except Exception as exc:
            print("  export task", exc)
    if not ok:
        try:
            ok = bool(unreal.Exporter.run_asset_export_tasks([task]))
        except Exception as exc:
            print("  export tasks", exc)
    print("  OBJ export", dest, "ok", ok, "exists", os.path.isfile(dest))
    return dest if os.path.isfile(dest) else ""


def _read_obj(path):
    xs, ys, zs = [], [], []
    if not path or not os.path.isfile(path):
        return xs, ys, zs
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("v "):
                p = line.split()
                xs.append(float(p[1]))
                ys.append(float(p[2]))
                zs.append(float(p[3]))
    return xs, ys, zs


def _world_aabb(actor):
    loc = actor.get_actor_location()
    rot = actor.get_actor_rotation()
    scl = actor.get_actor_scale3d()
    origin, extent = actor.get_actor_bounds(False)
    comp = actor.static_mesh_component
    rel = comp.get_relative_rotation() if comp else None
    mesh = comp.static_mesh if comp else None
    print(
        "ACTOR",
        actor.get_actor_label(),
        "loc",
        round(float(loc.x), 2),
        round(float(loc.y), 2),
        round(float(loc.z), 2),
        "P",
        round(float(rot.pitch), 3),
        "Y",
        round(float(rot.yaw), 3),
        "R",
        round(float(rot.roll), 3),
        "scale",
        round(float(scl.x), 4),
        round(float(scl.y), 4),
        round(float(scl.z), 4),
        "relP",
        None if rel is None else round(float(rel.pitch), 3),
        "relY",
        None if rel is None else round(float(rel.yaw), 3),
        "relR",
        None if rel is None else round(float(rel.roll), 3),
        "worldAABB",
        [
            round(float(origin.x) - float(extent.x), 2),
            round(float(origin.y) - float(extent.y), 2),
            round(float(origin.z) - float(extent.z), 2),
        ],
        [
            round(float(origin.x) + float(extent.x), 2),
            round(float(origin.y) + float(extent.y), 2),
            round(float(origin.z) + float(extent.z), 2),
        ],
        "span",
        round(2 * float(extent.x), 2),
        round(2 * float(extent.y), 2),
        round(2 * float(extent.z), 2),
        "mesh",
        mesh.get_name() if mesh else None,
    )


def main():
    print("LEVEL", unreal.EditorLevelLibrary.get_editor_world().get_name())
    for path in STEMS:
        mesh = unreal.EditorAssetLibrary.load_asset(path)
        print("MESH", path, mesh)
        if mesh is None:
            continue
        b = mesh.get_bounds()
        print(
            "  bounds origin",
            [round(float(v), 3) for v in (b.origin.x, b.origin.y, b.origin.z)],
            "extent",
            [round(float(v), 3) for v in (b.box_extent.x, b.box_extent.y, b.box_extent.z)],
        )
        xs, ys, zs = _mesh_desc_verts(mesh)
        if xs:
            _aabb("  DESC", xs, ys, zs)
        dest = os.path.join(OUT, path.rsplit("/", 1)[-1] + ".obj")
        exported = _export_obj(mesh, dest)
        xs, ys, zs = _read_obj(exported)
        if xs:
            _aabb("  EXPORTED", xs, ys, zs)

    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    want = ("flowerplate_0", "servingplate_0", "dish_0", "simplechair_0", "woodchair_1", "banquet_table_0")
    for actor in list(sub.get_all_level_actors() or []):
        label = (actor.get_actor_label() or "").lower()
        if any(w in label for w in want):
            _world_aabb(actor)


main()
