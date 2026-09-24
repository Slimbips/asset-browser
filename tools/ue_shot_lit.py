"""Set an outside Lit camera with explicit pitch/yaw, then HighResShot."""
import json
import unreal

SHOT = r"D:/Games/test/Stalingrad/Saved/Screenshots/WindowsEditor/L_Stalingrad_lit_proof.png"


def _comp(actor, *names):
    for name in names:
        try:
            val = getattr(actor, name, None)
            if val is not None:
                return val
        except Exception:
            pass
    return None


sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = ues.get_editor_world()
print("WORLD", world.get_name() if world else None)

actor = None
for a in list(sub.get_all_level_actors() or []):
    print("ACTOR", a.get_actor_label(), a.get_class().get_name())
    if a.get_actor_label() == "SM_Stalingrad":
        actor = a

if actor is None:
    print("NO MESH ACTOR")
else:
    origin, extent = actor.get_actor_bounds(False)
    ox, oy, oz = float(origin.x), float(origin.y), float(origin.z)
    ex = max(abs(float(extent.x)), 100.0)
    ey = max(abs(float(extent.y)), 100.0)
    ez = max(abs(float(extent.z)), 100.0)
    dist = max(ex, ey, ez) * 2.4
    loc = unreal.Vector(ox + dist, oy + dist, oz + ez + max(ez * 0.35, 600.0))
    rot = unreal.Rotator(pitch=-28.0, yaw=-135.0, roll=0.0)
    ues.set_level_viewport_camera_info(loc, rot)
    got_loc, got_rot = ues.get_level_viewport_camera_info()
    print(
        "CAM set",
        round(float(loc.x), 1),
        round(float(loc.y), 1),
        round(float(loc.z), 1),
        "rot P",
        -28,
        "Y",
        -135,
        "got",
        round(float(got_loc.x), 1),
        round(float(got_loc.y), 1),
        round(float(got_loc.z), 1),
        "P",
        round(float(got_rot.pitch), 1),
        "Y",
        round(float(got_rot.yaw), 1),
        "R",
        round(float(got_rot.roll), 1),
    )

for a in list(sub.get_all_level_actors() or []):
    cls = a.get_class().get_name()
    if "Light" not in cls and "Atmosphere" not in cls and "Fog" not in cls and "PostProcess" not in cls:
        continue
    lc = _comp(a, "light_component", "component")
    extra = {}
    if lc is not None:
        for key in ("intensity", "real_time_capture", "affects_world", "cast_shadows", "intensity_units"):
            try:
                extra[key] = str(lc.get_editor_property(key))
            except Exception:
                pass
    print("LIGHT", a.get_actor_label(), cls, extra)

for line in (
    "viewmode lit",
    "r.Unlit 0",
    "ShowFlag.Lighting 1",
    "ShowFlag.StaticMeshes 1",
    "ShowFlag.Atmosphere 1",
    "r.SkyAtmosphere 1",
    "r.DefaultFeature.AutoExposure 0",
    "r.EyeAdaptationQuality 0",
    "r.Shadow.Virtual.Enable 0",
):
    unreal.SystemLibrary.execute_console_command(world, line)

ok = False
try:
    ok = bool(unreal.AutomationLibrary.take_high_res_screenshot(1600, 900, "L_Stalingrad_lit_proof"))
    print("AUTOMATION SHOT", ok)
except Exception as visc:
    print("automation fail", visc)

unreal.SystemLibrary.execute_console_command(world, "HighResShot 1600x900")
print("HIGHRESSHOT queued")
print("DONE", json.dumps({"world": world.get_name() if world else None, "automation": ok}))
