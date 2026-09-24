"""Capture banquet table from a grazing camera matching the user screenshot."""
from __future__ import annotations

import os

import unreal

OUT_DIR = r"D:\Games\test\Stalingrad\Saved\Screenshots"


def _find(sub, key):
    for actor in list(sub.get_all_level_actors() or []):
        if key in (actor.get_actor_label() or "").lower():
            return actor
    return None


def _capture(name, loc, rot):
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    ues.set_level_viewport_camera_info(loc, rot)
    rt = unreal.EditorAssetLibrary.load_asset("/Game/MOHAA/tmp/RT_PlateProof")
    if rt is None:
        rt = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "RT_PlateProof",
            "/Game/MOHAA/tmp",
            unreal.TextureRenderTarget2D,
            unreal.TextureRenderTargetFactoryNew(),
        )
    rt.set_editor_property("size_x", 1920)
    rt.set_editor_property("size_y", 1080)
    cap = sub.spawn_actor_from_class(unreal.SceneCapture2D, loc, rot)
    comp = cap.capture_component2d
    comp.set_editor_property("texture_target", rt)
    comp.set_editor_property("capture_every_frame", False)
    comp.set_editor_property("capture_on_movement", False)
    try:
        comp.capture_scene()
    except Exception as exc:
        print("capture", exc)
    out = os.path.join(OUT_DIR, name)
    unreal.RenderingLibrary.export_render_target(ues.get_editor_world(), rt, OUT_DIR, name)
    print("WROTE", out, os.path.isfile(out))
    sub.destroy_actor(cap)


def main():
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    plate = _find(sub, "flowerplate_0")
    table = _find(sub, "banquet_table_0")
    loc = plate.get_actor_location()
    print("plate", loc)
    # User-like: slightly above table, looking along it (grazing).
    _capture(
        "L_Remagen_plates_grazing.png",
        unreal.Vector(float(loc.x) + 40.0, float(loc.y) + 280.0, float(loc.z) + 55.0),
        unreal.Rotator(pitch=-18.0, yaw=-110.0, roll=0.0),
    )
    # High top-down so a lying plate is a circle and a standing one is a line.
    to = table.get_actor_location()
    _capture(
        "L_Remagen_plates_topdown.png",
        unreal.Vector(float(to.x), float(to.y), float(to.z) + 420.0),
        unreal.Rotator(pitch=-89.0, yaw=-90.0, roll=0.0),
    )


main()
