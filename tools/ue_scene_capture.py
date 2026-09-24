"""Capture Lit scene to a PNG via SceneCapture2D (HighResShot is deferred and often never writes)."""
import os
import traceback

import unreal

OUT = r"D:\Games\test\Stalingrad\Saved\Screenshots\L_Stalingrad_lit_proof.png"


def _find(label):
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for a in list(sub.get_all_level_actors() or []):
        if a.get_actor_label() == label:
            return a
    return None


try:
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world = ues.get_editor_world()
    print("WORLD", world.get_name())
    actor = _find("SM_Stalingrad")
    if actor is None:
        raise RuntimeError("SM_Stalingrad missing")
    origin, extent = actor.get_actor_bounds(False)
    ox, oy, oz = float(origin.x), float(origin.y), float(origin.z)
    ex, ey, ez = abs(float(extent.x)), abs(float(extent.y)), abs(float(extent.z))
    dist = max(ex, ey, ez) * 1.35
    loc = unreal.Vector(ox + dist, oy + dist, oz + ez * 0.55)
    rot = unreal.Rotator(pitch=-22.0, yaw=-135.0, roll=0.0)
    ues.set_level_viewport_camera_info(loc, rot)
    print("CAM", round(float(loc.x), 1), round(float(loc.y), 1), round(float(loc.z), 1))

    sun = _find("MOHAA_Sun")
    if sun is not None:
        lc = getattr(sun, "light_component", None)
        unitless = getattr(unreal.LightUnits, "UNITLESS", None)
        if unitless is not None:
            try:
                lc.set_editor_property("intensity_units", unitless)
            except Exception:
                pass
        try:
            lc.set_editor_property("intensity", 15.0)
            lc.set_editor_property("cast_shadows", False)
            print("SUN", lc.get_editor_property("intensity"), lc.get_editor_property("intensity_units"))
        except Exception as visc:
            print("sun skip", visc)
    sky = _find("MOHAA_SkyLight")
    if sky is not None:
        sc = getattr(sky, "light_component", None)
        try:
            sc.set_editor_property("real_time_capture", False)
            print("SKY realtime", sc.get_editor_property("real_time_capture"))
        except Exception:
            pass

    for line in (
        "viewmode lit",
        "r.Unlit 0",
        "ShowFlag.Lighting 1",
        "ShowFlag.StaticMeshes 1",
        "ShowFlag.Atmosphere 1",
        "r.SkyAtmosphere 1",
        "r.DefaultFeature.AutoExposure 1",
        "r.EyeAdaptationQuality 2",
        "r.Shadow.Virtual.Enable 0",
    ):
        unreal.SystemLibrary.execute_console_command(world, line)

    rt = None
    for fn in ("create_render_target2d", "create_render_target_2d"):
        maker = getattr(unreal.RenderingLibrary, fn, None)
        if maker:
            try:
                rt = maker(world, 1280, 720, unreal.TextureRenderTargetFormat.RTF_RGBA8)
                print("RT via", fn, rt)
                break
            except Exception as visc:
                print("RT fail", fn, visc)
    if rt is None:
        raise RuntimeError("no render target")

    cap = sub.spawn_actor_from_class(unreal.SceneCapture2D, loc, rot)
    cap.set_actor_label("MOHAA_Capture")
    comp = getattr(cap, "capture_component2d", None) or cap.root_component
    try:
        comp.set_editor_property("texture_target", rt)
    except Exception:
        comp.texture_target = rt
    try:
        comp.set_editor_property("capture_every_frame", False)
        comp.set_editor_property("capture_on_movement", False)
    except Exception:
        pass
    src = getattr(unreal.SceneCaptureSource, "SCS_FINAL_COLOR_LDR", None) or getattr(
        unreal.SceneCaptureSource, "SCS_FINAL_COLOR_HDR", None
    )
    if src is not None:
        try:
            comp.set_editor_property("capture_source", src)
        except Exception:
            pass
    try:
        pp = comp.get_editor_property("post_process_settings")
        pp.set_editor_property("override_auto_exposure_bias", True)
        pp.set_editor_property("auto_exposure_bias", 8.0)
        pp.set_editor_property("override_auto_exposure_min_brightness", True)
        pp.set_editor_property("auto_exposure_min_brightness", 1.0)
        comp.set_editor_property("post_process_settings", pp)
        comp.set_editor_property("post_process_blend_weight", 1.0)
    except Exception as visc:
        print("capture pp skip", visc)
    if hasattr(comp, "capture_scene"):
        comp.capture_scene()
        print("capture_scene ok")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.isfile(OUT):
        os.remove(OUT)
    folder = os.path.dirname(OUT)
    name = os.path.basename(OUT)
    exported = False
    try:
        print("EXPORT DOC", unreal.RenderingLibrary.export_render_target.__doc__)
    except Exception:
        pass
    for args in (
        (world, rt, folder, name),
        (world, rt, OUT),
        (rt, OUT),
    ):
        try:
            unreal.RenderingLibrary.export_render_target(*args)
            exported = True
            print("exported args", len(args))
            break
        except Exception as visc:
            print("export fail", visc)
    size = os.path.getsize(OUT) if os.path.isfile(OUT) else 0
    print("CAPTURE", OUT, exported, size)
    try:
        sub.destroy_actor(cap)
    except Exception:
        pass
    try:
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
        print("SAVED", world.get_name())
    except Exception as visc:
        print("save skip", visc)
except Exception:
    traceback.print_exc()
    print("CAPTURE FAIL")
