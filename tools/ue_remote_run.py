"""Run a Python file in the open Unreal editor via remote execution."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UE_REMOTE_PY = Path(
    r"D:\epicgames\UE_5.8\Engine\Plugins\Experimental\PythonScriptPlugin\Content\Python"
)
PROJECT = Path(r"D:\Games\test\Stalingrad\Stalingrad.uproject")
SCRIPT = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "ue_verify_map_lights.py")

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
        for _ in range(8):
            time.sleep(0.25)
            nodes = session.remote_nodes or []
            node = matching_editor(nodes, PROJECT)
            if node:
                break
        if not node:
            print("NO EDITOR", session.remote_nodes)
            sys.exit(2)
        print("NODE", node.get("project_name"), node.get("project_root"))
        session.open_command_connection(node["node_id"])
        code = SCRIPT.read_text(encoding="utf-8")
        data = session.run_command(code, unattended=True, exec_mode=re.MODE_EXEC_FILE)
        chunks = []
        for item in data.get("output") or []:
            if isinstance(item, dict):
                chunks.append(str(item.get("output") or ""))
            else:
                chunks.append(str(item))
        log = "\n".join(chunks)
        if data.get("result"):
            log += "\n" + str(data.get("result"))
        print(log)
        print("SUCCESS", data.get("success"))
        if not data.get("success"):
            sys.exit(1)
    finally:
        session.stop()


if __name__ == "__main__":
    main()
