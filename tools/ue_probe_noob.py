from __future__ import annotations

import sys
import time
from pathlib import Path

UE_REMOTE_PY = Path(
    r"D:\epicgames\UE_5.8\Engine\Plugins\Experimental\PythonScriptPlugin\Content\Python"
)
PROJECT = Path(r"D:\Games\test\MohaaNoob\MohaaNoob.uproject")

sys.path.insert(0, str(UE_REMOTE_PY))
import remote_execution as re  # noqa: E402


def matching_editor(nodes, project):
    for node in nodes:
        root = node.get("project_root")
        if root and Path(root).resolve() == project.parent.resolve() and node.get("project_name") == project.stem:
            return node
    return None


def main() -> None:
    session = re.RemoteExecution()
    session.start()
    try:
        node = None
        for i in range(30):
            time.sleep(0.5)
            nodes = session.remote_nodes or []
            print("try", i, [(n.get("project_name"), n.get("project_root")) for n in nodes], flush=True)
            node = matching_editor(nodes, PROJECT)
            if node:
                break
        if not node:
            print("NO EDITOR", flush=True)
            sys.exit(2)
        print("MATCH", node.get("project_name"), node.get("project_root"), flush=True)
        session.open_command_connection(node["node_id"])
        code = (
            "import unreal\n"
            "w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()\n"
            "print('WORLD', w.get_name() if w else '')\n"
            "print('MANNY_SIMPLE', unreal.EditorAssetLibrary.does_asset_exist('/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple'))\n"
            "print('MANNY', unreal.EditorAssetLibrary.does_asset_exist('/Game/Characters/Mannequins/Meshes/SKM_Manny'))\n"
        )
        data = session.run_command(code, unattended=True, exec_mode=re.MODE_EXEC_FILE)
        chunks = []
        for item in data.get("output") or []:
            chunks.append(str(item.get("output") if isinstance(item, dict) else item))
        print("\n".join(chunks), flush=True)
        print("SUCCESS", data.get("success"), flush=True)
        if not data.get("success"):
            sys.exit(1)
    finally:
        session.stop()


if __name__ == "__main__":
    main()
